"""Rastreador: recorre el sitio (sitemap + enlaces internos) y devuelve las páginas parseadas.

Si una página trae muy poco contenido y muchos <script> (sitios hechos con Angular, React, Vue…),
se vuelve a cargar con un navegador sin ventana (Chromium vía Playwright) y se lee lo que quedó
armado. Mientras carga, también se capturan las respuestas JSON de la API del propio sitio para
sacar productos de ahí. Se controla con SABIO_RENDER_JS=auto|on|off (auto por defecto).
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .extract import Page, parse_page, products_from_json

USER_AGENT = "SabioBot/0.1 (+asistente del sitio; contacto: equipo SABIO)"
SKIP_EXT = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|mp3|css|js|ico|woff2?|ttf|xml)$", re.I)
SKIP_PATH = re.compile(r"/(cart|carrito|checkout|login|account|cuenta|admin|wp-admin|search|buscar)\b", re.I)
PRODUCT_PATH = re.compile(r"/(producto|productos|product|products|item|articulo|p)/", re.I)

RENDER_MIN_TEXT = 300        # menos texto útil que esto: la página probablemente se arma con JavaScript
RENDER_MIN_SCRIPTS = 3
RENDER_TIMEOUT_MS = 20_000
RENDER_CONCURRENCY = 2
RENDER_MAX = int(os.environ.get("SABIO_RENDER_MAX", "60"))


def render_mode() -> str:
    m = os.environ.get("SABIO_RENDER_JS", "auto").strip().lower()
    return m if m in ("auto", "on", "off") else "auto"


def needs_render(page: Page, mode: str) -> bool:
    if mode == "on":
        return True
    if mode == "off":
        return False
    return page.scripts >= RENDER_MIN_SCRIPTS and (len(page.text) < RENDER_MIN_TEXT or not page.products)


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


def _base_domain(url: str) -> str:
    """tienda.com.ar para api.tienda.com.ar: la API de un sitio suele estar en un subdominio."""
    labels = (urlparse(url).hostname or "").lower().split(".")
    n = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in ("com", "net", "org", "gob", "edu", "co") else 2
    return ".".join(labels[-n:])


class Renderer:
    """Chromium sin ventana, compartido por todo el rastreo y cerrado al terminar."""

    def __init__(self, mode: str):
        self.mode = mode
        self.sem = asyncio.Semaphore(RENDER_CONCURRENCY)
        self.lock = asyncio.Lock()
        self.enabled = True
        self.count = self.tries = self.useful = 0
        self._pw = self._browser = self._ctx = None
        self._hosts: dict[str, bool] = {}

    async def _start(self) -> bool:
        async with self.lock:
            if self._ctx or not self.enabled:
                return bool(self._ctx)
            try:
                from playwright.async_api import async_playwright
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    args=["--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions"])
                self._ctx = await self._browser.new_context(user_agent=USER_AGENT, service_workers="block")
                await self._ctx.route("**/*", self._filter)
                return True
            except Exception:  # Playwright o Chromium no instalados: se sigue sin navegador
                self.enabled = False
                await self.close()
                return False

    async def _filter(self, route):
        req = route.request
        if req.resource_type in ("image", "media", "font"):
            return await route.abort()
        if req.url.startswith(("http://", "https://")):
            host = urlparse(req.url).hostname or ""
            if host not in self._hosts:
                self._hosts[host] = await asyncio.to_thread(is_public_url, req.url)
            if not self._hosts[host]:  # la página no puede usar el navegador para llegar a la red interna
                return await route.abort()
        await route.continue_()

    def feedback(self, useful: bool):
        """En modo auto, si las primeras páginas renderizadas no suman nada, se deja de usar el navegador."""
        self.tries += 1
        self.useful += useful
        if self.mode == "auto" and self.tries >= 4 and not self.useful:
            self.enabled = False

    async def render(self, url: str) -> tuple[str, list] | None:
        if self.count >= RENDER_MAX or not await self._start():
            return None
        async with self.sem:
            if not self.enabled:
                return None
            self.count += 1
            page = await self._ctx.new_page()
            apis, pending = [], []

            async def grab(resp):
                try:
                    if (resp.request.resource_type in ("xhr", "fetch") and resp.ok
                            and "json" in resp.headers.get("content-type", "")
                            and _base_domain(resp.url) == _base_domain(url)):
                        body = await resp.body()
                        if len(body) < 5_000_000:
                            apis.append(json.loads(body))
                except Exception:
                    pass

            page.on("response", lambda r: pending.append(asyncio.ensure_future(grab(r))))
            try:
                try:
                    await page.goto(url, wait_until="networkidle", timeout=RENDER_TIMEOUT_MS)
                except Exception as e:
                    if "Timeout" not in type(e).__name__:
                        return None
                    # Hay sitios que nunca dejan de pedir cosas: se usa lo que llegó a cargar
                html = await page.content()
                if pending:
                    await asyncio.wait(pending, timeout=3)
                return html, apis
            except Exception:
                return None
            finally:
                await page.close()

    async def close(self):
        for obj in (self._ctx, self._browser):
            try:
                if obj:
                    await obj.close()
            except Exception:
                pass
        if self._pw:
            await self._pw.stop()
        self._pw = self._browser = self._ctx = None


def _clean(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    # Se ignoran parámetros de seguimiento; se conservan los de paginación
    q = "&".join(x for x in p.query.split("&") if x and not x.startswith(("utm_", "fbclid", "gclid")))
    path = re.sub(r"/index\.html?$", "/", p.path) or "/"
    return p._replace(query=q, path=path).geturl()


async def _sitemap_urls(client: httpx.AsyncClient, base: str, limit: int,
                        extra: list[str] | None = None) -> list[str]:
    """URLs del sitemap (y de los sitemaps que declara robots.txt), con las de productos primero."""
    urls: list[str] = []
    pending = [urljoin(base, "/sitemap.xml")] + (extra or [])
    seen = set()
    while pending and len(urls) < limit * 4 and len(seen) < 20:
        sm = pending.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = await client.get(sm)
        except httpx.HTTPError:
            continue
        # Muchos sitios hechos con JavaScript devuelven su página de inicio en cualquier dirección
        if r.status_code != 200 or not re.search(r"<(urlset|sitemapindex)\b", r.text[:2000]):
            continue
        locs = re.findall(r"<loc>\s*(?:<!\[CDATA\[)?([^<\s\]]+)", r.text)
        for loc in locs:
            (pending if loc.endswith(".xml") else urls).append(loc)
    urls.sort(key=lambda u: 0 if PRODUCT_PATH.search(urlparse(u).path) else 1)
    return urls[:limit]


BLOCK_CODES = (403, 429, 503)
MAX_BLOCKS = 3  # respuestas de rechazo seguidas antes de dejar de rastrear


async def crawl(start_url: str, max_pages: int = 300, concurrency: int = 6,
                on_progress=None, info: dict | None = None) -> list[Page]:
    """`info`, si se pasa, se completa con datos del rastreo (por ejemplo, si el sitio nos bloqueó)."""
    if not start_url.startswith(("http://", "https://")):
        start_url = "https://" + start_url
    info = info if info is not None else {}
    info.update(bloqueado=None)
    pages: list[Page] = []
    blocks = 0
    mode = render_mode()
    renderer = Renderer(mode) if mode != "off" else None
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True,
                                 timeout=15) as client:
        robots = RobotFileParser()
        sitemaps: list[str] = []
        try:
            rr = await client.get(urljoin(start_url, "/robots.txt"))
            ok = rr.status_code == 200 and "text/html" not in rr.headers.get("content-type", "")
            robots.parse(rr.text.splitlines() if ok else [])
            sitemaps = (robots.site_maps() or []) if ok else []
        except httpx.HTTPError:
            robots.parse([])

        queue: list[str] = [start_url] + await _sitemap_urls(client, start_url, max_pages, sitemaps)
        seen: set[str] = set()
        # Si robots.txt pide una pausa entre pedidos, se rastrea de a uno y respetándola
        delay = min(float(robots.crawl_delay(USER_AGENT) or 0), 10.0)
        sem = asyncio.Semaphore(1 if delay else concurrency)

        async def fetch(u: str):
            nonlocal blocks
            async with sem:
                if delay:
                    await asyncio.sleep(delay)
                try:
                    r = await client.get(u)
                except httpx.HTTPError:
                    return None
                if r.status_code in BLOCK_CODES:
                    blocks += 1
                    info["bloqueado"] = r.status_code
                    return None
                blocks = 0
                if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                    return None
                page = parse_page(str(r.url), r.text)
            if renderer and renderer.enabled and needs_render(page, mode):
                got = await renderer.render(page.url)
                if got:
                    html, apis = got
                    rp = parse_page(page.url, html, rendered=True)
                    if not rp.products:
                        for data in apis:
                            rp.products += products_from_json(data, page.url)
                    useful = len(rp.text) > len(page.text) + 200 or len(rp.products) > len(page.products)
                    renderer.feedback(useful)
                    if useful or mode == "on":
                        rp.links = list(dict.fromkeys(rp.links + page.links))
                        page = rp
            return page

        try:
            while queue and len(pages) < max_pages and blocks < MAX_BLOCKS:
                batch = []
                while queue and len(batch) < min(concurrency * 2, max_pages - len(pages)):
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
                            # Las páginas de productos se visitan antes que el resto
                            (queue.insert(0, nu) if PRODUCT_PATH.search(urlparse(nu).path) else queue.append(nu))
                    if on_progress:
                        on_progress(len(pages))
        finally:
            if renderer:
                await renderer.close()
    return pages[:max_pages]
