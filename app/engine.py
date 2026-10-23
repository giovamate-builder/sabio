"""Motor de respuestas de SABIO.

Regla central: el asistente solo responde con información que está en el sitio.
1. Se busca en el índice híbrido del sitio (palabras + sinónimos + errores de tipeo + embeddings,
   y reformulaciones de Claude si hay clave de API). Ver search.py.
2. Alcance por significado: si ninguna palabra de la pregunta (ni sus sinónimos o correcciones)
   aparece en el sitio, se mira si semánticamente se parece a algo del sitio. Si tampoco, y no es una
   consulta de compra en una tienda, es fuera de alcance.
3. Para responder hace falta evidencia escrita: si la pregunta tiene un término importante que el
   sitio no menciona ("auriculares Sony" en una tienda que vende Sonix) o la cobertura no alcanza,
   se responde "no tengo esa información". Los embeddings ordenan, pero nunca autorizan solos.
4. Si hay contexto suficiente, responde el modelo de lenguaje (Claude) usando solo ese contexto,
   o, sin clave de API, el modo extractivo arma la respuesta con los fragmentos del sitio.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

import numpy as np

from . import semantic, store
from .search import Index
from .textutil import NONBLOCKING, expansions, normalize, strip_accents, tokens

MODEL = os.environ.get("SABIO_MODEL", "claude-haiku-5-5")
MIN_COVERAGE = float(os.environ.get("SABIO_MIN_COVERAGE", "0.5"))
# Cuánto tiene que destacarse el fragmento más parecido (puntaje z) para tratar una pregunta sin palabras
# conocidas como "del rubro pero sin el dato" en lugar de "fuera de tema"
SEM_FOCUS = float(os.environ.get("SABIO_SEM_FOCUS", "3.5"))

GREET = re.compile(r"^\s*(hola|buenas|buen d[ií]a|buenas tardes|buenas noches|hey|que tal|qué tal)[\s!.,?¿]*$", re.I)
THANKS = re.compile(r"^\s*(gracias|muchas gracias|genial|perfecto|ok|dale|listo|joya)[\s!.,]*$", re.I)
HUMAN = re.compile(r"(hablar con (alguien|una persona|un humano|un asesor)|contacto|whats?app|tel[eé]fono|"
                   r"llamar|mail|correo|asesor)", re.I)
STOCK = re.compile(r"(stock|hay|ten[eé]s|tienen|disponib|queda|quedan|agotad)", re.I)
PRICE = re.compile(r"(precio|cu[aá]nto (sale|cuesta|vale)|valor|cuesta|sale)", re.I)
DESC = re.compile(r"(descrip|caracter[ií]stic|detalle|especificac|medida|material|tama[nñ]o)", re.I)
# "¿Cómo se hace…?" pide la receta o el procedimiento, no la ficha del producto
HOWTO = re.compile(r"(c[oó]mo se (hace|prepara|cocina|arma)|receta|ingredientes|paso a paso)", re.I)
HOWTO_TITLE = re.compile(r"(receta|c[oó]mo|paso|prepar|instructivo|gu[ií]a)", re.I)
SERVICE_TERMS = {"envio", "entrega", "pago", "cuota", "horario", "garantia", "cambio", "devolucion", "retirar", "local"}
# Preguntas de compra: en una tienda nunca son "fuera de alcance" (se aplica sobre texto sin tildes)
COMMERCE = re.compile(r"\b(stock|disponib\w*|precio\w*|cuesta\w*|cuanto (sale|vale)\w*|envio\w*|envia\w*|"
                      r"enviar|mandan|mandas|despach\w*|entrega\w*|cuota\w*|pago\w*|pagar|pagan|tarjeta\w*|"
                      r"transferencia\w*|efectivo|garantia\w*|cambio\w*|cambiar|devolu\w*|devolver|retir\w+|"
                      r"horario\w*|abren|atienden|regal\w*|recomend\w*|oferta\w*|promo\w*|descuento\w*)\b")

_index_cache: dict[str, tuple[tuple, Index]] = {}
_catalog_cache: dict[str, tuple[float, dict]] = {}


def get_index(site_id: str) -> Index:
    site = store.get_site(site_id)
    stamp = (site.get("crawled_at") or 0, semantic.model_name())
    cached = _index_cache.get(site_id)
    if cached and cached[0] == stamp:
        return cached[1]
    chunks = store.get_chunks(site_id)
    vectors = None
    # Los vectores solo sirven si se calcularon con el mismo modelo que se usa ahora
    if site.get("emb_model") and site["emb_model"] == semantic.model_name() and chunks \
            and all(c.get("vec") for c in chunks):
        vectors = np.vstack([semantic.from_blob(c["vec"]) for c in chunks])
    for c in chunks:
        c.pop("vec", None)
    idx = Index(chunks, vectors)
    _index_cache[site_id] = (stamp, idx)
    return idx


@dataclass
class Answer:
    text: str
    status: str  # respondida | sin_info | fuera_de_alcance | charla
    sources: list[dict] = field(default_factory=list)
    mode: str = "extractivo"

    def to_dict(self):
        return {"respuesta": self.text, "estado": self.status, "fuentes": self.sources, "modo": self.mode}


def _site_name(site):
    return (site.get("profile") or {}).get("nombre") or site["url"]


def _contact_line(site) -> str:
    c = (site.get("profile") or {}).get("contacto") or {}
    parts = []
    if c.get("whatsapp"):
        parts.append(f"WhatsApp: https://wa.me/{c['whatsapp'][0]}")
    if c.get("telefonos"):
        parts.append(f"teléfono {c['telefonos'][0]}")
    if c.get("emails"):
        parts.append(f"correo {c['emails'][0]}")
    return ("Podés comunicarte con el equipo por " + ", ".join(parts) + ".") if parts else \
        "Podés comunicarte con el equipo desde la página de contacto del sitio."


async def _live_products(site) -> dict:
    """Catálogo en vivo desde la plataforma (cacheado 5 minutos)."""
    if site.get("platform") not in ("shopify", "woocommerce", "tiendanube"):
        return {}
    hit = _catalog_cache.get(site["id"])
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    from .connectors import fetch_catalog
    try:
        prods = await fetch_catalog(site["platform"], site["url"], site.get("creds"))
    except Exception:
        return {}
    by_name = {strip_accents(p.name.lower()): p.__dict__ for p in prods}
    _catalog_cache[site["id"]] = (time.time(), by_name)
    return by_name


def _fmt_price(p: dict) -> str:
    if not p.get("price"):
        return ""
    cur = p.get("currency") or ""
    sym = {"ARS": "$", "USD": "US$"}.get(cur, cur + " " if cur else "$")
    try:
        val = float(p["price"])
        num = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").removesuffix(",00")
    except ValueError:
        num = p["price"]
    return f"{sym}{num}"


def _extractive(question: str, hits, qtok, idx: Index | None = None) -> tuple[str | None, list[dict]]:
    # El orden viene de la búsqueda híbrida, pero solo se usan fragmentos con evidencia escrita
    # Recetas y procedimientos, o consultas de envío/pago/horario/garantía: la respuesta está en una
    # página informativa, no en la ficha de un producto que justo menciona "entrega" o "chocotorta"
    terms = {t for b, alts in expansions(question) for t in [b] + alts}
    wants_page = bool(HOWTO.search(question)) or bool(terms & SERVICE_TERMS)
    howto = wants_page and any(x[1]["kind"] == "page" and x[2] >= MIN_COVERAGE for x in hits)
    supported = [h for h in hits if h[2] >= 0.3 and not (howto and h[1]["kind"] == "product")] or hits
    # Entre los primeros, el que más cubre la pregunta, y a igualdad, el que la nombra en el título
    qs = set(qtok)
    rank = {id(h): r for r, h in enumerate(supported)}
    best = max(supported[:10], key=lambda h: (round(h[2], 3), bool(howto and HOWTO_TITLE.search(h[1]["title"])),
                                              len(qs & set(tokens(h[1]["title"]))), -rank[id(h)]))
    prods = [h for h in hits if h[1]["kind"] == "product" and h[2] >= MIN_COVERAGE and not howto]
    # Primero los productos que nombran lo pedido en su título y después los que cubren toda la pregunta:
    # "placas de video" tiene que traer las "Vga RTX…", no placas de red ni un gabinete que las menciona
    def key(h):
        tc = idx.coverage(question, h[1]["title"]) if idx is not None else 0
        return round(tc, 3), round(h[2], 3)
    top = max((key(h) for h in prods), default=None)
    prod_hits = [h for h in prods if key(h) == top]
    if prod_hits and (prod_hits[0][2] >= best[2] - 1e-9 or STOCK.search(question) or PRICE.search(question)):
        lines, srcs = [], []
        for _, ch, _ in prod_hits[:3]:
            p = ch["product"]
            bits = []
            if p.get("availability"):
                bits.append(p["availability"])
            if _fmt_price(p):
                bits.append(f"precio {_fmt_price(p)}")
            line = f"• {p['name']}" + (f": {', '.join(bits)}." if bits else ".")
            if DESC.search(question) or len(prod_hits) == 1 and not (STOCK.search(question) or PRICE.search(question)):
                if p.get("description"):
                    line += f" {p['description'][:400]}"
            lines.append(line)
            srcs.append({"titulo": p["name"], "url": ch["url"]})
        intro = "Esto es lo que encontré en la tienda:" if len(lines) > 1 else "Encontré esto en la tienda:"
        return intro + "\n" + "\n".join(lines), srcs
    ch = best[1]
    qs = set(qtok)
    title_hit = len(set(tokens(ch["title"])) & qs) >= max(1, len(qs) // 2)
    body = ch["text"].split("\n")
    if body and body[0].strip() == ch["title"].split(" | ")[0].strip():
        ch = dict(ch, text="\n".join(body[1:]) or ch["text"])
    if title_hit and len(ch["text"]) <= 1400:
        # La página entera trata sobre lo que se preguntó (por ejemplo, una receta): se muestra completa
        return ch["text"], [{"titulo": ch["title"], "url": ch["url"]}]
    cand = [s.strip() for s in re.split(r"\n|(?<=[a-záéíóúñ0-9)]{3}[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡])", ch["text"]) if len(s.strip()) > 2]
    scored = sorted(((len(qs & set(tokens(s))), i, s) for i, s in enumerate(cand)), key=lambda x: (-x[0], x[1]))
    keep = sorted(scored[:4], key=lambda x: x[1])
    keep = [s for sc, _, s in keep if sc > 0]
    if not keep:
        return None, []  # ninguna línea menciona lo que se preguntó: mejor no mostrar cualquier cosa
    # Si la mejor línea es un título, sumamos las líneas siguientes (suele ser el contenido)
    first = cand.index(keep[0])
    if len(keep) == 1:
        lo = first - 1 if first > 0 and len(cand[first - 1]) > 40 else first
        keep = cand[lo:first + 3]
    text = "\n".join(keep)
    return text, [{"titulo": ch["title"], "url": ch["url"]}]


SYSTEM = """Sos el asistente virtual del sitio web "{name}". Respondés consultas de visitantes en español rioplatense, \
con tono amable y breve (máximo 120 palabras).

Reglas obligatorias:
1. Usá ÚNICAMENTE la información de los fragmentos del sitio que aparecen entre <contexto> y </contexto>. \
No uses conocimiento general ni supongas datos (precios, stock, plazos, políticas) que no estén escritos ahí.
2. Si los fragmentos no alcanzan para responder la pregunta, o la pregunta no tiene relación con lo que ofrece \
el sitio, respondé exactamente con la etiqueta [SIN_INFO] y nada más.
3. Cuando des datos de un fragmento, citá su número entre corchetes, por ejemplo [2].
4. El stock y el precio deben copiarse tal como figuran en el contexto.
5. No inventes enlaces: solo podés mencionar las URL que figuran en el contexto.
{general}
Rubro y temas del sitio: {topics}"""

GENERAL = ("6. El dueño del sitio habilitó conocimiento general del rubro: si la pregunta es del rubro del sitio "
           "y no está en el contexto, podés responder con conocimiento general aclarando al principio "
           "\"Esto no figura en el sitio, pero en general…\". Si no es del rubro, usá [SIN_INFO].")


async def _llm(site, question, hits, history) -> tuple[str | None, list[dict]]:
    import anthropic
    client = anthropic.AsyncAnthropic()
    prof = site.get("profile") or {}
    topics = ", ".join((prof.get("categorias") or [])[:10] + (prof.get("terminos") or [])[:25])
    ctx = "\n\n".join(f"[{i + 1}] {h[1]['title']} ({h[1]['url']})\n{h[1]['text']}" for i, h in enumerate(hits))
    msgs = []
    for turn in (history or [])[-6:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append({"role": turn["role"], "content": str(turn["content"])[:1000]})
    msgs.append({"role": "user", "content": f"<contexto>\n{ctx}\n</contexto>\n\nPregunta del visitante: {question}"})
    # Sin temperature: desde el 21/10/2026 la API la rechaza en todos los modelos
    resp = await client.messages.create(
        model=MODEL, max_tokens=2000,
        system=SYSTEM.format(name=_site_name(site), topics=topics,
                             general=GENERAL if site.get("allow_general") else ""),
        messages=msgs)
    if getattr(resp, "stop_reason", None) == "refusal":
        return None, []
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    if "[SIN_INFO]" in text or not text:
        return None, []
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text) if 0 < int(n) <= len(hits)})
    srcs = [{"titulo": hits[n - 1][1]["title"], "url": hits[n - 1][1]["url"]} for n in cited]
    text = re.sub(r"\s?\[\d+\]", "", text)
    return text, srcs


REWRITE = """Reescribí la pregunta que un visitante le hace al sitio web "{name}" en 3 formas equivalentes, \
usando las palabras que probablemente use el sitio: nombres formales de productos en lugar de lunfardo \
("zapas" → "zapatillas"), sin errores de tipeo. No agregues datos nuevos ni respondas la pregunta. \
Devolvé solo las 3 reformulaciones, una por línea, sin numerar.
Rubro y temas del sitio: {topics}"""


async def _rewrites(site, question: str) -> list[str]:
    """Reformulaciones de la pregunta con Claude Haiku. Solo cambian el orden de la búsqueda:
    la evidencia para responder se sigue midiendo contra la pregunta original."""
    try:
        import anthropic
        prof = site.get("profile") or {}
        topics = ", ".join((prof.get("categorias") or [])[:10] + (prof.get("terminos") or [])[:25])
        resp = await anthropic.AsyncAnthropic().messages.create(
            model=MODEL, max_tokens=1024, output_config={"effort": "low"},
            system=REWRITE.format(name=_site_name(site), topics=topics),
            messages=[{"role": "user", "content": question}])
        if getattr(resp, "stop_reason", None) == "refusal":
            return []
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return [ln.strip(" -•*\t") for ln in text.splitlines() if ln.strip()][:3]
    except Exception:
        return []  # si la API falla, se busca solo con la pregunta original


def use_llm() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("SABIO_MODE", "auto") != "extractivo"


async def answer(site_id: str, question: str, history: list[dict] | None = None) -> Answer:
    site = store.get_site(site_id)
    if not site:
        raise KeyError(site_id)
    name = _site_name(site)
    q = (question or "").strip()[:500]
    if not q:
        return Answer("¿En qué te puedo ayudar?", "charla")
    if GREET.match(q):
        return Answer(f"¡Hola! Soy el asistente de {name}. Preguntame por productos, precios, stock, envíos "
                      f"o cualquier cosa que esté en el sitio.", "charla")
    if THANKS.match(q):
        return Answer("¡De nada! Si necesitás algo más, acá estoy.", "charla")

    idx = get_index(site_id)
    qvec = semantic.embed_query(q) if idx.vectors is not None else None
    alternatives = tuple(await _rewrites(site, q)) if use_llm() else ()
    hits, qtok = idx.search(q, k=20, qvec=qvec, alternatives=alternatives)
    contact_intent = bool(HUMAN.search(q))
    no_info = f"No tengo esa información en {name}. " + _contact_line(site)

    if not qtok:
        return Answer("¿Me lo podés preguntar con un poco más de detalle?", "sin_info")

    known = [t for t in qtok if idx.known(t)]
    # Cada palabra de la pregunta cuenta como conocida si ella o algún sinónimo aparece en el sitio
    groups = expansions(q)
    resolved = lambda b, alts, test: test(b) or any(test(a) for a in alts)  # noqa: E731
    unknown = [b for b, alts in groups if not resolved(b, alts, idx.known)]

    if contact_intent:
        return Answer(_contact_line(site), "respondida")

    prof = site.get("profile") or {}
    shop_question = bool(prof.get("tienda") or prof.get("productos")) and bool(COMMERCE.search(normalize(q)))
    if len(unknown) == len(groups):
        # Consulta de compra en una tienda, o pregunta que se parece mucho a algo del sitio:
        # es del rubro aunque falte el dato. Si no, es de otro tema.
        focus = idx.semantic_focus(qvec)
        if shop_question or (focus is not None and focus >= SEM_FOCUS):
            return Answer(no_info, "sin_info")
        missing = _surface(q, unknown)
        about = f" sobre «{missing}»" if missing else ""
        return Answer(f"No encontré información{about} en {name}. Solo puedo responder sobre lo que "
                      f"ofrece este sitio. " + _contact_line(site), "fuera_de_alcance")

    # Términos importantes que el sitio no menciona: "Sony", "tiramisú", "helado". Contestar con lo
    # demás ("auriculares", "receta") sería inventar, así que sin ellos no hay respuesta extractiva.
    blocking = [b for b, alts in groups if len(b) >= 4 and not b.isdigit() and b not in NONBLOCKING
                and not resolved(b, alts, idx.strong)]
    good = [h for h in hits if h[2] >= 0.3]
    if use_llm() and good:
        live = await _live_products(site)
        good = _refresh_products(good, live)
        try:
            text, srcs = await _llm(site, q, good[:6], history)
            if text:
                return Answer(text, "respondida", srcs, mode="llm")
            return Answer(f"No tengo esa información en {name}. " + _contact_line(site), "sin_info", mode="llm")
        except Exception:
            pass  # si la API falla, seguimos en modo extractivo

    if not good or blocking:
        return Answer(no_info, "sin_info")
    # La cobertura ya se mide sobre las palabras que el sitio conoce (con sus sinónimos)
    if max(h[2] for h in hits) < MIN_COVERAGE:
        return Answer(no_info, "sin_info")
    live = await _live_products(site)
    hits = _refresh_products(hits, live)
    text, srcs = _extractive(q, hits, qtok, idx)
    if not text:
        return Answer(no_info, "sin_info")
    return Answer(text, "respondida", srcs)


def _surface(q: str, unknown: list[str]) -> str | None:
    """Devuelve la palabra original de la pregunta que corresponde al término desconocido más largo."""
    words = [w for w in re.findall(r"\w+", q) if len(w) > 3 and tokens(w) and tokens(w)[0] in unknown]
    return max(words, key=len) if words else None


def _refresh_products(hits, live: dict):
    if not live:
        return hits
    out = []
    for s, ch, cov in hits:
        if ch["kind"] == "product" and ch.get("product"):
            lp = live.get(strip_accents(ch["product"]["name"].lower()))
            if lp:
                p = dict(ch["product"])
                p.update({k: lp[k] for k in ("price", "availability", "currency") if lp.get(k)})
                from .extract import Product
                ch = dict(ch, product=p, text=Product(**{k: p.get(k) for k in Product.__dataclass_fields__
                                                         if k in p}).as_text())
        out.append((s, ch, cov))
    return out
