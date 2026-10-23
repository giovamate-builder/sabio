"""Motor de respuestas de SABIO.

Regla central: el asistente solo responde con información que está en el sitio.
1. Se busca en el índice del sitio (BM25).
2. Si la pregunta usa términos que el sitio no contiene, se considera fuera de alcance.
3. Si lo encontrado no alcanza el umbral de cobertura, se responde "no tengo esa información".
4. Si hay contexto suficiente, responde el modelo de lenguaje (Claude) usando solo ese contexto,
   o, sin clave de API, el modo extractivo arma la respuesta con los fragmentos del sitio.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

from . import store
from .search import Index
from .textutil import strip_accents, tokens

MODEL = os.environ.get("SABIO_MODEL", "claude-haiku-5-5")
MIN_COVERAGE = float(os.environ.get("SABIO_MIN_COVERAGE", "0.5"))

GREET = re.compile(r"^\s*(hola|buenas|buen d[ií]a|buenas tardes|buenas noches|hey|que tal|qué tal)[\s!.,?¿]*$", re.I)
THANKS = re.compile(r"^\s*(gracias|muchas gracias|genial|perfecto|ok|dale|listo|joya)[\s!.,]*$", re.I)
HUMAN = re.compile(r"(hablar con (alguien|una persona|un humano|un asesor)|contacto|whats?app|tel[eé]fono|"
                   r"llamar|mail|correo|asesor)", re.I)
STOCK = re.compile(r"(stock|hay|ten[eé]s|tienen|disponib|queda|quedan|agotad)", re.I)
PRICE = re.compile(r"(precio|cu[aá]nto (sale|cuesta|vale)|valor|cuesta|sale)", re.I)
DESC = re.compile(r"(descrip|caracter[ií]stic|detalle|especificac|medida|material|tama[nñ]o)", re.I)

_index_cache: dict[str, tuple[float, Index]] = {}
_catalog_cache: dict[str, tuple[float, dict]] = {}


def get_index(site_id: str) -> Index:
    site = store.get_site(site_id)
    stamp = site.get("crawled_at") or 0
    cached = _index_cache.get(site_id)
    if cached and cached[0] == stamp:
        return cached[1]
    idx = Index(store.get_chunks(site_id))
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


def _extractive(question: str, hits, qtok) -> tuple[str, list[dict]]:
    best = hits[0]
    prods = [h for h in hits if h[1]["kind"] == "product" and h[2] >= MIN_COVERAGE]
    prod_hits = [h for h in prods if h[0] >= prods[0][0] * 0.7] if prods else []
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
    keep = [s for sc, _, s in keep if sc > 0] or [cand[0]]
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
    resp = await client.messages.create(
        model=MODEL, max_tokens=400, temperature=0,
        system=SYSTEM.format(name=_site_name(site), topics=topics,
                             general=GENERAL if site.get("allow_general") else ""),
        messages=msgs)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    if "[SIN_INFO]" in text or not text:
        return None, []
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text) if 0 < int(n) <= len(hits)})
    srcs = [{"titulo": hits[n - 1][1]["title"], "url": hits[n - 1][1]["url"]} for n in cited]
    text = re.sub(r"\s?\[\d+\]", "", text)
    return text, srcs


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
    hits, qtok = idx.search(q, k=6)
    contact_intent = bool(HUMAN.search(q))

    if not qtok:
        return Answer("¿Me lo podés preguntar con un poco más de detalle?", "sin_info")

    # Términos de la pregunta que el sitio no menciona en ninguna página
    unknown = [t for t in qtok if not idx.known(t)]
    known = [t for t in qtok if idx.known(t)]

    if contact_intent:
        return Answer(_contact_line(site), "respondida")

    if not known:
        missing = _surface(q, unknown)
        about = f" sobre «{missing}»" if missing else ""
        return Answer(f"No encontré información{about} en {name}. Solo puedo responder sobre lo que "
                      f"ofrece este sitio. " + _contact_line(site), "fuera_de_alcance")

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

    if not hits:
        return Answer(f"No tengo esa información en {name}. " + _contact_line(site), "sin_info")
    # Cobertura calculada solo sobre los términos que el sitio conoce
    known_idf = sum(idx.idf(t) for t in known)
    all_idf = sum(idx.idf(t) for t in qtok) or 1
    cov_known = hits[0][2] * all_idf / known_idf if known_idf else 0
    if cov_known < MIN_COVERAGE or hits[0][2] < 0.3:
        return Answer(f"No tengo esa información en {name}. " + _contact_line(site), "sin_info")
    live = await _live_products(site)
    hits = _refresh_products(hits, live)
    text, srcs = _extractive(q, hits, qtok)
    if unknown and hits[0][2] < MIN_COVERAGE:
        missing = _surface(q, unknown)
        if missing:
            text = f"No encontré nada específico sobre «{missing}», pero esto es lo que dice el sitio:\n" + text
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
