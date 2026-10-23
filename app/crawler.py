"""Rastreador: recorre el sitio (sitemap + enlaces internos) y devuelve las páginas parseadas."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .extract import Page, parse_page

USER_AGENT = "SabioBot/0.1 (+asistente del sitio; contacto: equipo SABIO)"
SKIP_EXT = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|mp3|css|js|ico|woff2?|ttf|xml)$", re.I)
SKIP_PATH = re.compile(r"/(cart|carrito|checkout|login|account|cuenta|admin|wp-admin|search|buscar)\b", re.I)


def is_public_url(url: str) -> bool:
    """Evita que el rastreador se use para leer direcciones internas (localhost, redes privadas)."""
    if os.environ.get("SABIO_ALLOW_PRIVATE") == "1":
        return True
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _same_site(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower().removeprefix("www.") == urlparse(b).netloc.lower().removeprefix("www.")


def _clean(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    # Se ignoran parámetros de seguimiento; se conservan los de paginación
    q = "&".join(x for x in p.query.split("&") if x and not x.startswith(("utm_", "fbclid", "gclid")))
    path = re.sub(r"/index\.html?$", "/", p.path) or "/"
    return p._replace(query=q, path=path).geturl()


async def _sitemap_urls(client: httpx.AsyncClient, base: str, limit: int) -> list[str]:
    urls: list[str] = []
    pending = [urljoin(base, "/sitemap.xml")]
    seen = set()
    while pending and len(urls) < limit:
        sm = pending.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = await client.get(sm)
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
        for loc in locs:
            (pending if loc.endswith(".xml") else urls).append(loc)
    return urls[:limit]


async def crawl(start_url: str, max_pages: int = 300, concurrency: int = 6,
                on_progress=None) -> list[Page]:
    if not start_url.startswith(("http://", "https://")):
        start_url = "https://" + start_url
    pages: list[Page] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                                 timeout=15) as client:
        robots = RobotFileParser()
        try:
            rr = await client.get(urljoin(start_url, "/robots.txt"))
            robots.parse(rr.text.splitlines() if rr.status_code == 200 else [])
        except httpx.HTTPError:
            robots.parse([])

        queue: list[str] = [start_url] + await _sitemap_urls(client, start_url, max_pages)
        seen: set[str] = set()
        sem = asyncio.Semaphore(concurrency)

        async def fetch(u: str):
            async with sem:
                try:
                    r = await client.get(u)
                except httpx.HTTPError:
                    return None
                if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                    return None
                return parse_page(str(r.url), r.text)

        while queue and len(pages) < max_pages:
            batch = []
            while queue and len(batch) < concurrency * 2:
                u = _clean(queue.pop(0))
                if (u in seen or not _same_site(u, start_url) or SKIP_EXT.search(urlparse(u).path)
                        or SKIP_PATH.search(urlparse(u).path) or not robots.can_fetch(USER_AGENT, u)):
                    seen.add(u)
                    continue
                seen.add(u)
                batch.append(u)
            for page in await asyncio.gather(*(fetch(u) for u in batch)):
                if page is None:
                    continue
                pages.append(page)
                for href in page.links:
                    nu = _clean(urljoin(page.url, href))
                    if nu not in seen and _same_site(nu, start_url):
                        queue.append(nu)
                if on_progress:
                    on_progress(len(pages))
    return pages[:max_pages]
