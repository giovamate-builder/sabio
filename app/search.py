"""Índice BM25 por sitio y perfil automático del sitio (rubro, vocabulario, contacto)."""
from __future__ import annotations

import math
import re
from collections import Counter

from .textutil import query_tokens, tokens

K1, B = 1.4, 0.72


class Index:
    def __init__(self, chunks: list[dict]):
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
        for t in self.vocab:
            if len(t) >= 5:
                self._prefix.setdefault(t[:5], set()).add(t)

    def expand(self, t: str) -> set[str]:
        """Variantes del término presentes en el sitio (devolver ~ devoluciones, envio ~ envios)."""
        if t in self.vocab:
            return {t}
        if len(t) >= 5:
            return self._prefix.get(t[:5], set())
        return set()

    def known(self, t: str) -> bool:
        return bool(self.expand(t))

    def idf(self, t: str) -> float:
        n = max((self.df.get(x, 0) for x in self.expand(t)), default=0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def search(self, query: str, k: int = 6) -> tuple[list[tuple[float, dict, float]], list[str]]:
        base = tokens(query)
        q = [t for t in query_tokens(query) if t in base or self.known(t)]
        if not q:
            return [], q
        results = []
        exp = {t: self.expand(t) for t in q}
        qidf = {t: self.idf(t) for t in q}
        total_idf = sum(qidf.values()) or 1
        for d, ch in zip(self.docs, self.chunks):
            dl = sum(d.values()) or 1
            s, cov = 0.0, 0.0
            for t in q:
                f = sum(d.get(x, 0) for x in exp[t])
                if f:
                    s += qidf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / self.avgdl))
                    cov += qidf[t]
            if s > 0:
                results.append((s, ch, cov / total_idf))
        results.sort(key=lambda x: -x[0])
        return results[:k], q


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?:\+?54\s?9?\s?)?(?:\(?\d{2,4}\)?[\s-]?)\d{3,4}[\s-]?\d{4}")
WA = re.compile(r"(?:wa\.me/|whatsapp\.com/send\?phone=)(\d+)")
# Palabras (ya normalizadas por tokens()) que delatan que el sitio vende algo
STORE_WORDS = ("carrito", "comprar", "compra", "precio", "cuota", "checkout", "envio", "stock", "oferta")


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
    name = name_hint or (common[0] if common else (home.title if home else ""))
    all_text = "\n".join(p.text for p in pages) + "\n" + "\n".join(" ".join(p.links) for p in pages)
    contact = {
        "emails": sorted(set(EMAIL.findall(all_text)))[:3],
        "whatsapp": sorted(set(WA.findall(all_text)))[:2],
    }
    wa = set(WA.findall(all_text))
    contact["telefonos"] = sorted(set(m.strip() for m in PHONE.findall(all_text)
                                      if len(re.sub(r"\D", "", m)) >= 8 and re.sub(r"\D", "", m) not in wa
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
