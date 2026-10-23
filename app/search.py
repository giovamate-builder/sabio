"""Índice híbrido por sitio y perfil automático del sitio (rubro, vocabulario, contacto).

La búsqueda combina:
- BM25 por palabras, con sinónimos/lunfardo (textutil.SYNONYMS), variantes por prefijo
  (envio ~ envios) y corrección de errores de tipeo por distancia de edición (notbook ~ notebook).
- Búsqueda semántica con embeddings, si está activada (ver semantic.py).
Las dos listas se combinan con reciprocal rank fusion (RRF). La "cobertura" de cada resultado
(qué parte de la pregunta aparece escrita en el fragmento) se calcula siempre por palabras:
es la evidencia que el motor exige antes de responder.
"""
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

from .textutil import edit_distance, expansions, query_tokens, tokens

K1, B = 1.4, 0.72
RRF_K = 60


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


class Index:
    def __init__(self, chunks: list[dict], vectors: np.ndarray | None = None):
        self.chunks = chunks
        self.docs = []
        for ch in chunks:
            # El título pesa doble: suele ser el nombre del producto o de la sección
            toks = tokens(ch["title"]) * 2 + tokens(ch["text"])
            self.docs.append(Counter(toks))
        self.N = len(self.docs) or 1
        self.avgdl = sum(sum(d.values()) for d in self.docs) / self.N if self.docs else 1
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        self.df = df
        self.vocab = set(df)
        self._prefix: dict[str, set[str]] = {}
        self._by_first: dict[str, list[str]] = {}
        for t in self.vocab:
            if len(t) >= 5:
                self._prefix.setdefault(t[:5], set()).add(t)
            if len(t) >= 3 and not t[0].isdigit():
                self._by_first.setdefault(t[0], []).append(t)
        self._fuzzy: dict[str, set[str]] = {}
        self.vectors = vectors if vectors is not None and len(vectors) == len(chunks) else None

    def fuzzy(self, t: str) -> set[str]:
        """Palabras del sitio a 1 error de tipeo (2 si la palabra es larga), con la misma primera y última
        letra: en castellano la terminación cambia el significado ("libro" no es "libre"), y los errores
        de tipeo suelen estar en el medio ("mause", "notbook", "maizena")."""
        if t in self._fuzzy:
            return self._fuzzy[t]
        out: set[str] = set()
        if len(t) >= 4 and not t[0].isdigit():
            lim = 1 if len(t) <= 6 else 2
            best = lim + 1
            for v in self._by_first.get(t[0], ()):
                if abs(len(v) - len(t)) > lim or v[-1] != t[-1]:
                    continue
                d = edit_distance(t, v, lim)
                if d > lim:
                    continue
                if d < best:
                    best, out = d, {v}
                elif d == best:
                    out.add(v)
        self._fuzzy[t] = out
        return out

    def expand(self, t: str) -> set[str]:
        """Variantes del término presentes en el sitio (devolver ~ devoluciones, envio ~ envios, mause ~ mouse)."""
        if t in self.vocab:
            return {t}
        if len(t) >= 5 and self._prefix.get(t[:5]):
            return self._prefix[t[:5]]
        return self.fuzzy(t)

    def known(self, t: str) -> bool:
        return bool(self.expand(t))

    def strong(self, t: str) -> bool:
        """El término está en el sitio tal cual, con un error de tipeo, o como derivado cercano
        (disponible ~ disponibilidad). Un prefijo corto compartido ("helado" ~ "heladera") sirve para
        buscar, pero no alcanza como evidencia para responder."""
        if t in self.vocab or self.fuzzy(t):
            return True
        need = max(6, len(t) - 2)
        return any(_common_prefix(t, v) >= need for v in self._prefix.get(t[:5], ()))

    def idf(self, t: str) -> float:
        n = max((self.df.get(x, 0) for x in self.expand(t)), default=0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def _groups(self, query: str):
        """Palabras de la pregunta que el sitio conoce, cada una con sus sinónimos y su peso (idf)."""
        q = self._terms(query)
        exp = {t: self.expand(t) for t in q}
        qidf = {t: self.idf(t) for t in q}
        groups = []
        for base, alts in expansions(query):
            members = [t for t in [base] + alts if exp.get(t)]
            if members:
                groups.append((members, max(qidf[t] for t in members)))
        return q, exp, qidf, groups

    def coverage(self, query: str, text: str) -> float:
        """Qué parte de la pregunta aparece en un texto cualquiera (por ejemplo, el nombre de un producto)."""
        _, exp, _, groups = self._groups(query)
        toks = set(tokens(text))
        total = sum(w for _, w in groups) or 1
        return sum(w for members, w in groups if any(exp[t] & toks for t in members)) / total

    def _bm25(self, query: str) -> list[tuple[float, int, float]]:
        """(puntaje, posición del fragmento, cobertura) de cada fragmento que contiene algún término.

        La cobertura se mide por palabra de la pregunta, contando sus sinónimos: "escuchar música sin
        cables" queda cubierta por un fragmento que dice "auriculares inalámbricos". Solo cuentan las
        palabras que el sitio conoce: las desconocidas las maneja el motor (alcance y bloqueo).
        """
        q, exp, qidf, groups = self._groups(query)
        if not q:
            return []
        total = sum(w for _, w in groups) or 1
        out = []
        for i, d in enumerate(self.docs):
            dl = sum(d.values()) or 1
            freq = {t: sum(d.get(x, 0) for x in exp[t]) for t in q}
            s = sum(qidf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / self.avgdl)) for t, f in freq.items() if f)
            if s > 0:
                cov = sum(w for members, w in groups if any(freq[t] for t in members))
                out.append((s, i, cov / total))
        out.sort(key=lambda x: -x[0])
        return out

    def _terms(self, query: str) -> list[str]:
        base = tokens(query)
        return [t for t in query_tokens(query) if t in base or self.known(t)]

    def search(self, query: str, k: int = 6, qvec: np.ndarray | None = None,
               alternatives: tuple[str, ...] = ()) -> tuple[list[tuple[float, dict, float]], list[str]]:
        """Devuelve [(puntaje, fragmento, cobertura)] y los términos de la pregunta.

        `qvec` es el embedding de la pregunta; `alternatives`, reformulaciones (por ejemplo, las que
        propone Claude). Ambas solo cambian el orden: la cobertura se mide contra la pregunta original.
        """
        q = self._terms(query)
        lexical = self._bm25(query)
        cov = {i: c for _, i, c in lexical}
        rankings = [[i for _, i, _ in lexical[:50]]]
        for alt in alternatives:
            rankings.append([i for _, i, _ in self._bm25(alt)[:50]])
        sims = None
        if qvec is not None and self.vectors is not None:
            sims = self.vectors @ qvec
            rankings.append(list(np.argsort(-sims)[:50]))
        if len(rankings) == 1:
            return [(s, self.chunks[i], c) for s, i, c in lexical[:k]], q
        fused: dict[int, float] = {}
        for ranking in rankings:
            for r, i in enumerate(ranking):
                fused[int(i)] = fused.get(int(i), 0.0) + 1 / (RRF_K + r + 1)
        order = sorted(fused, key=lambda i: -fused[i])[:k]
        hits = []
        for i in order:
            ch = self.chunks[i] if sims is None else dict(self.chunks[i], sem=float(sims[i]))
            hits.append((fused[i], ch, cov.get(i, 0.0)))
        return hits, q

    def semantic_focus(self, qvec: np.ndarray | None) -> float | None:
        """Cuánto se destaca el fragmento más parecido sobre el resto (puntaje z). Sirve con cualquier modelo:
        una pregunta del rubro tiene un fragmento que sobresale; una de otro tema se parece poco a todos por igual."""
        if qvec is None or self.vectors is None or len(self.vectors) < 3:
            return None
        sims = self.vectors @ qvec
        sd = float(sims.std()) or 1e-6
        return (float(sims.max()) - float(sims.mean())) / sd


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?:\+?54\s?9?\s?)?(?:\(?\d{2,4}\)?[\s-]?)\d{3,4}[\s-]?\d{4}")
WA = re.compile(r"(?:wa\.me/|whatsapp\.com/send\?phone=)(\d+)")
TEL_LINK = re.compile(r"tel:\s*(\+?[\d\s().-]{8,20})")
TEL_LABEL = re.compile(r"(?:tel[eé]fono|tel\.|\btel\b|llamanos|llam[aá]|atenci[oó]n al cliente)[:\s]*"
                       r"(\+?[\d\s().-]{8,20}\d)", re.I)
# Palabras (ya normalizadas por tokens()) que delatan que el sitio vende algo
STORE_WORDS = ("carrito", "comprar", "compra", "precio", "cuota", "checkout", "envio", "stock", "oferta")


def _plausible_phone(digits: str) -> bool:
    """Descarta números que no son teléfonos: "00-1024-1024" (tamaños de imagen), "001715514", etc."""
    return len(digits) >= 8 and not digits.startswith("00") and len(set(digits)) > 3


def build_profile(pages, products, name_hint: str = "") -> dict:
    """Resume de qué trata el sitio. Se usa para decidir si una pregunta está dentro del rubro."""
    term_counts = Counter()
    for p in pages:
        term_counts.update(set(tokens(p.title + " " + p.meta_description + " " + p.text[:3000])))
    cats = Counter(p.category for p in products if p.category)
    home = pages[0] if pages else None
    segs = Counter()
    for p in pages:
        for seg in re.split(r"\s[|\-–·]\s", p.title):
            if seg.strip():
                segs[seg.strip()] += 1
    common = [s for s, n in segs.most_common() if n > 1 and s.lower() not in ("inicio", "home")]
    # og:site_name es el nombre que el propio sitio declara: es más confiable que adivinarlo del título
    declared = Counter(p.site_name for p in pages if getattr(p, "site_name", ""))
    name = name_hint or (declared.most_common(1)[0][0] if declared else
                         common[0] if common else (home.title if home else ""))
    all_text = "\n".join(p.text for p in pages) + "\n" + "\n".join(" ".join(p.links) for p in pages)
    contact = {
        "emails": sorted(set(EMAIL.findall(all_text)))[:3],
        "whatsapp": sorted(set(WA.findall(all_text)))[:2],
    }
    wa = set(WA.findall(all_text))
    # Solo números que el sitio presenta como teléfono (enlace tel: o precedidos por "tel.", "llamanos"…):
    # en una tienda hay muchos números largos que no lo son (códigos, ISBN, tamaños de imagen)
    candidates = TEL_LINK.findall(all_text) + [m.group(1) for m in TEL_LABEL.finditer(all_text)]
    contact["telefonos"] = sorted(set(m.strip() for m in candidates
                                      if _plausible_phone(re.sub(r"\D", "", m)) and re.sub(r"\D", "", m) not in wa
                                      and not any(re.sub(r"\D", "", m) in w or w.endswith(re.sub(r"\D", "", m)[-8:]) for w in wa)))[:3]
    store_words = sum(1 for w in STORE_WORDS if term_counts.get(w))
    return {
        "nombre": name,
        "tienda": bool(products) or store_words >= 2,
        "descripcion": home.meta_description if home else "",
        "categorias": [c for c, _ in cats.most_common(15)],
        "terminos": [t for t, _ in term_counts.most_common(60)],
        "productos": len(products),
        "contacto": contact,
    }


def chunk_pages(pages, products) -> list[dict]:
    out = []
    product_urls = set()
    for pr in products:
        product_urls.add(pr.url)
        out.append({"url": pr.url, "title": pr.name, "kind": "product", "text": pr.as_text(),
                    "product": pr.__dict__})
    for p in pages:
        lines = p.text.split("\n")
        # La meta descripción suele resumir lo importante ("Envíos a todo el país") y en los sitios
        # hechos con JavaScript a veces es lo único legible
        if p.meta_description and p.meta_description not in p.text:
            lines.insert(0, p.meta_description)
        buf, size = [], 0
        for ln in lines:
            if size + len(ln) > 900 and buf:
                out.append({"url": p.url, "title": p.title, "kind": "page", "text": "\n".join(buf)})
                buf, size = buf[-1:], len(buf[-1])  # solapamiento de una línea
            buf.append(ln)
            size += len(ln)
        if buf:
            out.append({"url": p.url, "title": p.title, "kind": "page", "text": "\n".join(buf)})
    return out
