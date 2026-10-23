"""Conectores con plataformas de e-commerce para leer stock y precio en vivo.

- Shopify: endpoint público /products.json (sin credenciales).
- WooCommerce: Store API pública /wp-json/wc/store/v1/products (sin credenciales).
- Tiendanube: API oficial, requiere store_id y token de acceso de la app instalada.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import httpx

from .extract import Product


def _strip_html(s: str) -> str:
    # html.unescape: WooCommerce manda los nombres con entidades ("DE MAYOR QUIERO SER&#8230;")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


async def detect_platform(base_url: str) -> str | None:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        try:
            r = await c.get(urljoin(base_url, "/products.json?limit=1"))
            if r.status_code == 200 and "products" in r.json():
                return "shopify"
        except Exception:
            pass
        try:
            r = await c.get(urljoin(base_url, "/wp-json/wc/store/v1/products?per_page=1"))
            if r.status_code == 200 and isinstance(r.json(), list):
                return "woocommerce"
        except Exception:
            pass
    return None


async def fetch_catalog(platform: str, base_url: str, creds: dict | None = None,
                        limit: int = 1000) -> list[Product]:
    creds = creds or {}
    out: list[Product] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        if platform == "shopify":
            page = 1
            while len(out) < limit:
                r = await c.get(urljoin(base_url, f"/products.json?limit=250&page={page}"))
                items = r.json().get("products", []) if r.status_code == 200 else []
                if not items:
                    break
                for p in items:
                    v = (p.get("variants") or [{}])[0]
                    avail = any(x.get("available") for x in p.get("variants", []))
                    out.append(Product(name=p["title"], url=urljoin(base_url, f"/products/{p['handle']}"),
                                       description=_strip_html(p.get("body_html", ""))[:1500],
                                       price=v.get("price"), availability="en stock" if avail else "sin stock",
                                       sku=v.get("sku"), brand=p.get("vendor"), category=p.get("product_type")))
                page += 1
        elif platform == "woocommerce":
            page = 1
            while len(out) < limit:
                r = await c.get(urljoin(base_url, f"/wp-json/wc/store/v1/products?per_page=100&page={page}"))
                items = r.json() if r.status_code == 200 else []
                if not items:
                    break
                for p in items:
                    pr = p.get("prices", {})
                    minor = int(pr.get("currency_minor_unit", 2) or 0)
                    price = pr.get("price")
                    if price is not None and minor:
                        price = f"{int(price) / 10 ** minor:.2f}"
                    out.append(Product(name=_strip_html(p.get("name", "")), url=p.get("permalink", base_url),
                                       description=_strip_html(p.get("short_description") or p.get("description", ""))[:1500],
                                       price=price, currency=pr.get("currency_code"),
                                       availability="en stock" if p.get("is_in_stock") else "sin stock",
                                       sku=p.get("sku")))
                page += 1
        elif platform == "tiendanube" and creds.get("store_id") and creds.get("token"):
            headers = {"Authentication": f"bearer {creds['token']}", "User-Agent": "SABIO (equipo SABIO)"}
            page = 1
            while len(out) < limit:
                r = await c.get(f"https://api.tiendanube.com/v1/{creds['store_id']}/products",
                                params={"per_page": 200, "page": page}, headers=headers)
                items = r.json() if r.status_code == 200 else []
                if not items:
                    break
                for p in items:
                    name = (p.get("name") or {}).get("es") or next(iter((p.get("name") or {}).values()), "")
                    v = (p.get("variants") or [{}])[0]
                    stock = sum((x.get("stock") or 0) for x in p.get("variants", []) if x.get("stock") is not None)
                    unlimited = any(x.get("stock") is None for x in p.get("variants", []))
                    out.append(Product(name=name, url=p.get("canonical_url", base_url),
                                       description=_strip_html((p.get("description") or {}).get("es", ""))[:1500],
                                       price=v.get("price"),
                                       availability="en stock" if unlimited or stock > 0 else "sin stock",
                                       sku=v.get("sku")))
                page += 1
    return out[:limit]
