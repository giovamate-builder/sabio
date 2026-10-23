"""Extracción de contenido de una página: texto principal y productos.

Fuentes de productos, en orden: schema.org (JSON-LD), etiquetas og:/product: y los JSON que muchas
tiendas hechas con JavaScript traen dentro de la página (__NEXT_DATA__, window.__INITIAL_STATE__,
<script type="application/json">). Los mismos lectores de JSON se usan con las respuestas de la API
del sitio que se capturan al renderizar con navegador (ver crawler.py).
"""
from __future__ import annotations

import html as html_lib
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
    scripts: int = 0          # cantidad de <script> con código: indica un sitio hecho con JavaScript
    rendered: bool = False    # True si se leyó con navegador (Playwright)
    site_name: str = ""       # og:site_name, el nombre que el sitio declara


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


def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return None


def _products_from_meta(soup: BeautifulSoup, url: str) -> list[Product]:
    """Etiquetas og:/product: (Facebook, Pinterest). Solo cuenta si la página declara un precio."""
    price = _meta(soup, "product:price:amount", "og:price:amount")
    name = _meta(soup, "og:title")
    if not price or not name:
        return []
    return [Product(name=name, url=urljoin(url, _meta(soup, "og:url") or url),
                    description=_meta(soup, "og:description") or "", price=price,
                    currency=_meta(soup, "product:price:currency", "og:price:currency"),
                    availability=_norm_avail(_meta(soup, "product:availability", "og:availability")),
                    brand=_meta(soup, "product:brand"))]


# Claves con las que las tiendas suelen nombrar los datos de un producto en sus JSON
NAME_KEYS = ("name", "nombre", "title", "titulo", "productName", "product_name")
PRICE_KEYS = ("price", "precio", "salePrice", "sale_price", "finalPrice", "precioFinal", "precio_final",
              "precioEspecial", "precio_especial", "precioLista", "precio_lista", "listPrice")
STOCK_KEYS = ("availability", "disponibilidad", "inStock", "in_stock", "is_in_stock", "available",
              "disponible", "stock", "quantity", "cantidad")
URL_KEYS = ("url", "link", "permalink", "href", "canonical_url")
DESC_KEYS = ("description", "descripcion", "short_description", "shortDescription")


def _price_of(v):
    if isinstance(v, dict):
        v = next((v[k] for k in ("amount", "value", "price", "precio") if k in v), None)
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v) if v > 0 else None
    s = str(v).strip()
    return s if re.search(r"\d", s) and len(s) < 30 else None


def _stock_of(o: dict) -> str | None:
    for k in STOCK_KEYS:
        if k not in o:
            continue
        v = o[k]
        if isinstance(v, bool):
            return "en stock" if v else "sin stock"
        if isinstance(v, (int, float)):
            return "en stock" if v > 0 else "sin stock"
        if isinstance(v, str) and v.strip():
            return _norm_avail(v)
    return None


def _first(o: dict, keys) -> object:
    return next((o[k] for k in keys if o.get(k) not in (None, "", [], {})), None)


def products_from_json(data, url: str, limit: int = 500) -> list[Product]:
    """Busca objetos con forma de producto (nombre + precio) en cualquier JSON."""
    out: list[Product] = []
    stack, steps = [data], 0
    while stack and len(out) < limit and steps < 200_000:
        o = stack.pop()
        steps += 1
        if isinstance(o, list):
            stack.extend(reversed(o))
            continue
        if not isinstance(o, dict):
            continue
        name, price = _first(o, NAME_KEYS), _price_of(_first(o, PRICE_KEYS))
        if isinstance(name, str) and 2 < len(name.strip()) < 200 and price:
            link = _first(o, URL_KEYS)
            brand = _first(o, ("brand", "marca", "vendor"))
            if isinstance(brand, dict):
                brand = brand.get("name") or brand.get("nombre")
            cat = _first(o, ("category", "categoria", "product_type"))
            if isinstance(cat, dict):
                cat = cat.get("name") or cat.get("nombre")
            desc = _first(o, DESC_KEYS)
            out.append(Product(
                name=re.sub(r"\s+", " ", name).strip(),
                url=urljoin(url, link) if isinstance(link, str) else url,
                description=re.sub(r"<[^>]+>|\s+", " ", desc).strip()[:1500] if isinstance(desc, str) else "",
                price=price,
                currency=o.get("currency") or o.get("priceCurrency") or o.get("moneda"),
                availability=_stock_of(o),
                sku=str(o["sku"]) if o.get("sku") else None,
                brand=brand if isinstance(brand, str) else None,
                category=cat if isinstance(cat, str) else None))
            continue
        stack.extend(reversed([v for v in o.values() if isinstance(v, (dict, list))]))
    return out


STATE_ASSIGN = re.compile(r"window\.(__[A-Z0-9_]+__|__[A-Za-z]+State|initialState)\s*=\s*", re.I)


def _embedded_json(soup: BeautifulSoup):
    """JSON que la página trae adentro: __NEXT_DATA__, application/json y window.__ESTADO__ = {...}."""
    for tag in soup.find_all("script"):
        body = tag.string or tag.get_text() or ""
        typ = (tag.get("type") or "").lower()
        if typ == "application/json" or tag.get("id") == "__NEXT_DATA__":
            try:
                yield json.loads(body)
            except (json.JSONDecodeError, TypeError):
                pass
            continue
        m = STATE_ASSIGN.search(body)
        if m:
            try:
                obj, _ = json.JSONDecoder().raw_decode(body[m.end():])
                yield obj
            except json.JSONDecodeError:
                pass


def parse_page(url: str, html: str, rendered: bool = False) -> Page:
    soup = BeautifulSoup(html, "lxml")
    base = soup.find("base", href=True)
    if base and "{" not in base["href"]:
        url_base = urljoin(url, base["href"])
    else:
        url_base = url
    links = [urljoin(url_base, a["href"]) for a in soup.find_all("a", href=True)]
    products = _products_from_jsonld(soup, url_base)
    if not products:
        products = _products_from_meta(soup, url_base)
    if not products:
        for data in _embedded_json(soup):
            products += products_from_json(data, url_base)
    scripts = sum(1 for s in soup.find_all("script")
                  if s.get("src") or (s.get("type") or "text/javascript").endswith("javascript"))
    title = (soup.title.get_text(strip=True) if soup.title else "") or url
    site_name = _meta(soup, "og:site_name", "application-name") or ""
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
                meta_description=meta_description, scripts=scripts, rendered=rendered,
                site_name=html_lib.unescape(site_name).strip())
