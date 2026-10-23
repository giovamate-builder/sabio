"""API de SABIO."""
from __future__ import annotations

import asyncio
import os
import secrets
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from . import engine, store
from .ingest import ingest_local, ingest_site

ROOT = Path(__file__).resolve().parent.parent
RECRAWL_HOURS = float(os.environ.get("SABIO_RECRAWL_HOURS", "24"))
DEMO = os.environ.get("SABIO_DEMO", "0") == "1"
ADMIN_TOKEN = os.environ.get("SABIO_ADMIN_TOKEN", "")


def _check_admin(token: str | None):
    if ADMIN_TOKEN and token != ADMIN_TOKEN:
        raise HTTPException(401, "Falta la clave de administración")
_rw = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
PUBLIC_URL = (os.environ.get("SABIO_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
              or (f"https://{_rw}" if _rw else None)
              or f"http://localhost:{os.environ.get('PORT', '8000')}").rstrip("/")
DEMO_SITES = {"tecnosur": "TecnoSur", "dulcepilar": "Dulce Pilar"}

app = FastAPI(title="SABIO", version="0.1.0",
              description="Asistente conversacional que aprende solo del sitio web donde se instala.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def _startup():
    store.init()
    if DEMO:
        _setup_demo()
    asyncio.create_task(_recrawl_loop())


def _setup_demo():
    """Modo demo: la misma app sirve los dos sitios de ejemplo con el widget ya instalado."""
    import subprocess
    import sys
    if not (ROOT / "demo_sites" / "tecnosur" / "index.html").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_data.py")], check=True)
    for key, name in DEMO_SITES.items():
        sid = f"demo-{key}"
        store.create_site(sid, f"{PUBLIC_URL}/demo/{key}")
        ingest_local(sid, ROOT / "demo_sites" / key, f"/demo/{key}/", name)


async def _recrawl_loop():
    while True:
        await asyncio.sleep(3600)
        for s in store.list_sites():
            if s["status"] == "listo" and time.time() - (s["crawled_at"] or 0) > RECRAWL_HOURS * 3600:
                try:
                    await ingest_site(s["id"])
                except Exception:
                    pass


class SiteIn(BaseModel):
    url: str
    platform: str | None = Field(None, description="shopify | woocommerce | tiendanube (opcional, se detecta)")
    creds: dict | None = None
    allow_general: bool = False
    max_pages: int = 300


class ChatIn(BaseModel):
    site_id: str
    message: str
    session: str | None = None
    history: list[dict] | None = None


@app.post("/api/sites")
async def create_site(body: SiteIn, bg: BackgroundTasks, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    from .crawler import is_public_url
    if not is_public_url(body.url):
        raise HTTPException(400, "La dirección no es un sitio público")
    site_id = "s_" + secrets.token_hex(5)
    store.create_site(site_id, body.url.rstrip("/"), body.platform, body.creds, body.allow_general)
    bg.add_task(ingest_site, site_id, body.max_pages)
    return {"id": site_id, "estado": "en cola",
            "snippet": f'<script src="{{SABIO_URL}}/widget.js" data-site="{site_id}" defer></script>'}


@app.get("/api/sites")
def sites():
    return store.list_sites()


@app.get("/api/sites/{site_id}")
def site(site_id: str):
    s = store.get_site(site_id)
    if not s:
        raise HTTPException(404, "Sitio no encontrado")
    s.pop("creds", None)
    return s


@app.post("/api/sites/{site_id}/recrawl")
async def recrawl(site_id: str, bg: BackgroundTasks, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    if not store.get_site(site_id):
        raise HTTPException(404, "Sitio no encontrado")
    bg.add_task(ingest_site, site_id)
    return {"estado": "en cola"}


@app.get("/api/sites/{site_id}/stats")
def stats(site_id: str):
    return store.stats(site_id)


@app.post("/api/chat")
async def chat(body: ChatIn):
    s = store.get_site(body.site_id)
    if not s:
        raise HTTPException(404, "Sitio no encontrado")
    if s["status"] != "listo":
        return {"respuesta": "Estoy terminando de leer el sitio, probá en unos minutos.",
                "estado": "preparando", "fuentes": []}
    ans = await engine.answer(body.site_id, body.message, body.history)
    store.log_message(body.site_id, body.session or "", body.message, ans.text, ans.status,
                      [x["url"] for x in ans.sources])
    return ans.to_dict()


@app.get("/api/health")
def health():
    return {"ok": True, "modo": "llm" if engine.use_llm() else "extractivo", "modelo": engine.MODEL}


@app.get("/widget.js")
def widget():
    return FileResponse(ROOT / "widget" / "widget.js", media_type="application/javascript")


@app.get("/admin")
def admin():
    return FileResponse(ROOT / "admin" / "index.html")


@app.get("/demo/{site}/{path:path}")
def demo_page(site: str, path: str = ""):
    """Sirve los sitios de ejemplo inyectando la línea de instalación del widget."""
    if not DEMO or site not in DEMO_SITES:
        raise HTTPException(404)
    folder = (ROOT / "demo_sites" / site).resolve()
    f = (folder / (path or "index.html")).resolve()
    if folder not in f.parents and f != folder or not f.is_file():
        raise HTTPException(404)
    if f.suffix != ".html":
        return FileResponse(f)
    html = f.read_text(encoding="utf-8").replace("{{BASE}}", f"/demo/{site}/").replace(
        "<!--SABIO-->", f'<script src="/widget.js" data-site="demo-{site}" defer></script>')
    return HTMLResponse(html)


@app.get("/demo/{site}")
def demo_root(site: str):
    return RedirectResponse(f"/demo/{site}/")


@app.get("/")
def root():
    if DEMO:
        return FileResponse(ROOT / "admin" / "inicio.html")
    return RedirectResponse("/admin")
