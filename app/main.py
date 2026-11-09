"""API de SABIO."""
from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from . import engine, store
from . import ingest
from .ingest import ingest_local, ingest_site

ROOT = Path(__file__).resolve().parent.parent
RECRAWL_HOURS = float(os.environ.get("SABIO_RECRAWL_HOURS", "24"))
DEMO = os.environ.get("SABIO_DEMO", "0") == "1"
ADMIN_TOKEN = os.environ.get("SABIO_ADMIN_TOKEN", "")


def dev_mode() -> bool:
    return os.environ.get("SABIO_ENV", "").strip().lower() == "dev"


NO_TOKEN = ("El panel está deshabilitado: falta configurar SABIO_ADMIN_TOKEN en el servidor "
            "(o SABIO_ENV=dev para desarrollo local).")


def _check_admin(token: str | None):
    """Endpoints del panel (cargar, rastrear, borrar, ver sitios y conversaciones).

    - Con SABIO_ADMIN_TOKEN definido, se exige el encabezado X-Admin-Token (comparación en tiempo constante).
    - Sin token, todo el panel queda deshabilitado salvo con SABIO_ENV=dev (desarrollo local).
    /api/chat, /widget.js y /api/health son públicos: los usa el widget en el sitio del cliente.
    """
    if ADMIN_TOKEN:
        if not hmac.compare_digest((token or "").encode(), ADMIN_TOKEN.encode()):
            raise HTTPException(401, "Falta la clave de administración o es incorrecta")
    elif not dev_mode():
        raise HTTPException(403, NO_TOKEN)
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
    if not ADMIN_TOKEN and not dev_mode():
        print("SABIO AVISO: SABIO_ADMIN_TOKEN no está definido. El panel y la carga de sitios quedan "
              "deshabilitados; el widget sigue funcionando. Definí la clave (o SABIO_ENV=dev en local).")
    n = store.mark_interrupted()
    if n:
        print(f"SABIO: {n} sitio(s) quedaron con el rastreo cortado por un reinicio; se marcaron como error.")
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
                if not ingest.reserve(s["id"]):
                    break  # hay un rastreo manual en curso: se reintenta en la próxima vuelta
                try:
                    await ingest_site(s["id"], reserved=True)
                except Exception:
                    pass


class SiteIn(BaseModel):
    url: str
    platform: str | None = Field(None, description="shopify | woocommerce | tiendanube (opcional, se detecta)")
    creds: dict | None = None
    allow_general: bool = False
    max_pages: int | None = Field(None, description="Se acota a SABIO_MAX_PAGES")


class ChatIn(BaseModel):
    site_id: str
    message: str
    session: str | None = None
    history: list[dict] | None = None


def _reserve_or_409(site_id: str):
    """Un solo rastreo a la vez: cada rastreo puede ocupar buena parte de los 512 MB del servidor."""
    if not ingest.reserve(site_id):
        current = store.get_site(ingest.busy()) or {}
        raise HTTPException(409, f"Ya hay un rastreo en curso ({current.get('name') or current.get('url') or ingest.busy()}). "
                                 "Esperá a que termine y volvé a intentar.")


@app.post("/api/sites")
async def create_site(body: SiteIn, bg: BackgroundTasks, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    from .crawler import is_public_url
    if not is_public_url(body.url):
        raise HTTPException(400, "La dirección no es un sitio público")
    site_id = "s_" + secrets.token_hex(5)
    _reserve_or_409(site_id)
    store.create_site(site_id, body.url.rstrip("/"), body.platform, body.creds, body.allow_general)
    bg.add_task(ingest_site, site_id, body.max_pages, True)
    return {"id": site_id, "estado": "en cola",
            "snippet": f'<script src="{{SABIO_URL}}/widget.js" data-site="{site_id}" defer></script>'}


@app.get("/api/sites")
def sites(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    return store.list_sites()


@app.get("/api/sites/{site_id}")
def site(site_id: str, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
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
    _reserve_or_409(site_id)
    bg.add_task(ingest_site, site_id, None, True)
    return {"estado": "en cola"}


@app.delete("/api/sites/{site_id}")
def delete_site(site_id: str, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    if site_id.startswith("demo-"):
        raise HTTPException(403, "Los sitios de ejemplo no se pueden eliminar")
    if not store.get_site(site_id):
        raise HTTPException(404, "Sitio no encontrado")
    if ingest.busy() == site_id:
        raise HTTPException(409, "El sitio se está rastreando: esperá a que termine para eliminarlo")
    store.delete_site(site_id)
    engine.forget(site_id)
    return {"eliminado": site_id}


@app.get("/api/sites/{site_id}/stats")
def stats(site_id: str, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    return store.stats(site_id)


@app.post("/api/chat")
async def chat(body: ChatIn):
    s = store.get_site(body.site_id)
    if not s:
        raise HTTPException(404, "Sitio no encontrado")
    # Un rastreo cortado por tiempo deja el sitio en "error", pero con lo leído se puede responder
    partial = s["status"] == "error" and (s.get("crawl_info") or {}).get("parcial")
    if s["status"] != "listo" and not partial:
        return {"respuesta": "Estoy terminando de leer el sitio, probá en unos minutos.",
                "estado": "preparando", "fuentes": []}
    ans = await engine.answer(body.site_id, body.message, body.history)
    store.log_message(body.site_id, body.session or "", body.message, ans.text, ans.status,
                      [x["url"] for x in ans.sources])
    return ans.to_dict()


@app.get("/api/eval")
def eval_summary():
    """Resumen de la última evaluación (eval/resultados.json), para las tarjetas de /presentacion."""
    import json
    f = ROOT / "eval" / "resultados.json"
    if not f.is_file():
        raise HTTPException(404, "Todavía no hay resultados de evaluación")
    return json.loads(f.read_text(encoding="utf-8")).get("resumen", {})


@app.get("/presentacion")
def presentacion():
    return FileResponse(ROOT / "admin" / "presentacion.html")


@app.get("/api/health")
def health():
    from . import semantic
    from .crawler import render_mode
    return {"ok": True, "modo": "llm" if engine.use_llm() else "extractivo", "modelo": engine.MODEL,
            "navegador": render_mode(), "embeddings": semantic.model_name() or "off"}


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
