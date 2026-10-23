"""Levanta todo para la demo: la API de SABIO (8000) y los dos sitios de ejemplo (8101 y 8102).

Uso:  python scripts/run_demo.py
Luego abrir http://localhost:8101 (tienda) o http://localhost:8102 (pastelería) y usar el chat.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "http://localhost:8000"
SITES = {"tecnosur": 8101, "dulcepilar": 8102}


def main():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_data.py")], check=True)
    for f in (ROOT / "demo_sites").rglob("*.html"):
        f.write_text(f.read_text(encoding="utf-8").replace("{{BASE}}", "/"), encoding="utf-8")
    env = dict(os.environ, SABIO_ALLOW_PRIVATE="1")  # los sitios de ejemplo corren en localhost
    procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"], cwd=ROOT, env=env)]
    for name, port in SITES.items():
        procs.append(subprocess.Popen([sys.executable, "-m", "http.server", str(port)],
                                      cwd=ROOT / "demo_sites" / name, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
    try:
        for _ in range(50):
            try:
                httpx.get(API + "/api/health", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.3)
        for name, port in SITES.items():
            r = httpx.post(API + "/api/sites", json={"url": f"http://localhost:{port}"}).json()
            sid = r["id"]
            while httpx.get(f"{API}/api/sites/{sid}").json()["status"] not in ("listo", "error"):
                time.sleep(0.5)
            info = httpx.get(f"{API}/api/sites/{sid}").json()
            # Instalación del widget: una sola línea en cada página del sitio
            snippet = f'<script src="{API}/widget.js" data-site="{sid}" defer></script>'
            for f in (ROOT / "demo_sites" / name).rglob("*.html"):
                html = f.read_text(encoding="utf-8")
                f.write_text(html.replace("<!--SABIO-->", snippet), encoding="utf-8")
            print(f"{name}: {info['pages']} páginas, {info['products']} productos -> http://localhost:{port}  (id {sid})")
        print(f"Panel: {API}/admin   ·   Ctrl+C para cortar")
        procs[0].wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
