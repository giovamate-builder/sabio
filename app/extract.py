"""Extracción de contenido de una página: texto principal y productos (schema.org)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from urllib.parse import urljoin

from bs4 import BeautifulSoup

AVAIL = {
    "instock": "en stock",
    "outofstock": "sin stock",
    "preorder": "en preventa",
    "backorder": "a pedido",
    "limitedavailability": "pocas unidades",
    "soldout": "agotado",
    "discontinued": "discontinuado",
}


@dataclass
class Product:
    name: str
    url: str
    description: str = ""
    price: str | None = None
    currency: str | None = None
    availability: str | None = None
    sku: str | None = None
    brand: str | None = None
    category: str | None = None
    extra: dict = field(default_factory=dict)

    def as_text(self) -> str:
        parts = [f"Producto: {self.name}."]
        if self.brand:
            parts.append(f"Marca: {self.brand}.")
        if self.category:
            parts.append(f"Categoría: {self.category}.")
        if self.price:
            parts.append(f"Precio: {self.currency or ''} {self.price}.".replace("  ", " "))
        if self.availability:
            parts.append(f"Disponibilidad: {self.availability}.")
        if self.sku:
            parts.append(f"SKU: {self.sku}.")
        if self.description:
            parts.append(f"Descripción: {self.description}")
        return " ".join(parts)


@dataclass
class Page:
    url: str
    title: str
    text: str
    products: list[Product]
    links: list[str]
    meta_description: str = ""


def _norm_avail(v) -> str | None:
    if not v:
        return None
    key = str(v).rstrip("/").split("/")[-1].lower()
    return AVAIL.get(key, str(v))


def _iter_jsonld(obj):
    if isinstance(obj, list):
        for o in obj:
            yield from _iter_jsonld(o)
    elif isinstance(obj, dict):
        if "@graph" in obj:
            yield from _iter_jsonld(obj["@graph"])
        yield obj


def _products_from_jsonld(soup: BeautifulSoup, url: str) -> list[Product]:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for o in _iter_jsonld(data):
            t = o.get("@type")
            types = t if isinstance(t, list) else [t]
            if "Product" not in types:
                continue
            offers = o.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if offers.get("@type") == "AggregateOffer":
                price = offers.get("lowPrice")
            else:
                price = offers.get("price")
            brand = o.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            out.append(
                Product(
                    name=str(o.get("name", "")).strip(),
                    url=urljoin(url, o.get("url") or offers.get("url") or url),
                    description=re.sub(r"\s+", " ", str(o.get("description", ""))).strip(),
                    price=str(price) if price is not None else None,
                    currency=offers.get("priceCurrency"),
                    availability=_norm_avail(offers.get("availability")),
                    sku=o.get("sku"),
                    brand=brand,
                    category=o.get("category"),
                )
            )
    return [p for p in out if p.name]


def parse_page(url: str, html: str) -> Page:
    soup = BeautifulSoup(html, "lxml")
    base = soup.find("base", href=True)
    if base and "{" not in base["href"]:
        url_base = urljoin(url, base["href"])
    else:
        url_base = url
    links = [urljoin(url_base, a["href"]) for a in soup.find_all("a", href=True)]
    products = _products_from_jsonld(soup, url_base)
    title = (soup.title.get_text(strip=True) if soup.title else "") or url
    md = soup.find("meta", attrs={"name": "description"})
    meta_description = md.get("content", "").strip() if md else ""
    for t in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        t.decompose()
    for t in soup.select("nav, footer, header, [aria-hidden=true], .cookie, #cookie-banner"):
        t.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    blocks = []
    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "dt", "dd"]):
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if len(txt) >= 3:
            blocks.append(txt)
    # Evita duplicados (li dentro de li, etc.) manteniendo el orden
    seen, uniq = set(), []
    for b in blocks:
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    return Page(url=url, title=title, text="\n".join(uniq), products=products, links=links,
                meta_description=meta_description)
