"""Absorción de un sitio: rastreo + catálogo de la plataforma + índice + perfil."""
from __future__ import annotations

import time

from . import store
from .connectors import detect_platform, fetch_catalog
from .crawler import crawl
from .search import build_profile, chunk_pages
from .textutil import strip_accents


async def ingest_site(site_id: str, max_pages: int = 300) -> dict:
    site = store.get_site(site_id)
    store.update_site(site_id, status="rastreando", progress=0, error=None)
    t0 = time.time()
    try:
        pages = await crawl(site["url"], max_pages=max_pages,
                            on_progress=lambda n: store.update_site(site_id, progress=n))
        products = [p for pg in pages for p in pg.products]
        platform = site.get("platform") or await detect_platform(site["url"])
        if platform:
            api_products = await fetch_catalog(platform, site["url"], site.get("creds"))
            if api_products:
                # Los datos de la API mandan (stock y precio actualizados)
                by_name = {strip_accents(p.name.lower()): p for p in products}
                for ap in api_products:
                    by_name[strip_accents(ap.name.lower())] = ap
                products = list(by_name.values())
        # Un mismo producto puede aparecer en varias páginas: se deja uno por nombre
        uniq = {}
        for p in products:
            uniq.setdefault(strip_accents(p.name.lower()), p)
        products = list(uniq.values())
        if not pages and not products:
            raise RuntimeError("No se pudo leer ninguna página del sitio")
        chunks = chunk_pages(pages, products)
        profile = build_profile(pages, products)
        store.replace_chunks(site_id, chunks)
        store.update_site(site_id, status="listo", pages=len(pages), products=len(products),
                          profile=profile, name=profile["nombre"], platform=platform,
                          crawled_at=time.time())
        return {"paginas": len(pages), "productos": len(products), "fragmentos": len(chunks),
                "segundos": round(time.time() - t0, 1), "plataforma": platform}
    except Exception as e:  # noqa: BLE001
        store.update_site(site_id, status="error", error=str(e))
        raise


def ingest_local(site_id: str, folder, public_base: str, name: str | None = None) -> dict:
    """Indexa un sitio desde archivos locales (modo demo): no hace falta que el servidor se llame a sí mismo."""
    from pathlib import Path

    from .extract import parse_page

    folder = Path(folder)
    base = public_base.rstrip("/") + "/"
    pages = []
    for f in sorted(folder.rglob("*.html")):
        rel = f.relative_to(folder).as_posix()
        html = f.read_text(encoding="utf-8").replace("{{BASE}}", base)
        pages.append(parse_page(base + ("" if rel == "index.html" else rel), html))
    pages.sort(key=lambda p: 0 if p.url == base else 1)
    uniq = {}
    for p in [p for pg in pages for p in pg.products]:
        uniq.setdefault(strip_accents(p.name.lower()), p)
    products = list(uniq.values())
    chunks = chunk_pages(pages, products)
    profile = build_profile(pages, products)
    store.update_site(site_id, status="listo", pages=len(pages), products=len(products), profile=profile,
                      name=name or profile["nombre"], crawled_at=time.time())
    store.replace_chunks(site_id, chunks)
    return {"paginas": len(pages), "productos": len(products)}
