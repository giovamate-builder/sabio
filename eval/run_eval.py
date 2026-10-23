"""Corre el set de evaluación contra una instancia de SABIO y calcula los indicadores del proyecto.

Indicadores (ver punto 10 y 19 del documento):
- Precisión: preguntas del sitio respondidas con la fuente correcta y el dato esperado.
  Se informa para el set original ("dentro") y para el coloquial (sinónimos, lunfardo, errores
  de tipeo, signos repetidos: "dentro_coloquial").
- Respuestas inventadas: respuestas a preguntas fuera de tema (deberían ser 0). Incluye las
  fuera de tema parecidas al rubro ("fuera_parecidas"), que son las más fáciles de contestar mal.
- Rechazo correcto: preguntas fuera de tema que el asistente rechaza (fuera_de_alcance o sin_info).
- Vagas atendidas: consultas de compra vagas que no se descartan como fuera de tema.
Uso:  python eval/run_eval.py [http://127.0.0.1:8000] [archivo_resultados.json]
"""
import json
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import httpx

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "resultados.json"
SET = json.loads((Path(__file__).parent / "eval_set.json").read_text(encoding="utf-8"))
PORTS = {"tecnosur": 8101, "dulcepilar": 8102}


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def server_memory_mb():
    """Memoria del proceso que atiende la API (solo si corre en esta máquina)."""
    try:
        import psutil
        port = urlparse(API).port or 80
        for c in psutil.net_connections("tcp"):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid:
                p = psutil.Process(c.pid)
                return round(sum(x.memory_info().rss for x in [p] + p.children(recursive=True)) / 2**20)
    except Exception:
        return None


def ask(sid, q, lat):
    t = time.time()
    r = httpx.post(API + "/api/chat", json={"site_id": sid, "message": q, "session": "eval"}, timeout=60).json()
    lat.append(time.time() - t)
    return r


def main():
    # La base guarda los rastreos de corridas anteriores: se usa el más reciente de cada sitio
    # (la API los devuelve del más nuevo al más viejo)
    sites = {}
    for s in httpx.get(API + "/api/sites").json():
        sites.setdefault(s["url"], s["id"])
    lat, fails = [], []
    c = {k: [0, 0] for k in ("dentro", "dentro_coloquial", "fuera", "fuera_parecidas", "vagas")}
    inventadas = 0
    for name, data in SET.items():
        sid = sites[f"http://localhost:{PORTS[name]}"]
        for cat in ("dentro", "dentro_coloquial"):
            for q, url_part, expected in data.get(cat, []):
                r = ask(sid, q, lat)
                src_ok = any(url_part in f["url"] for f in r["fuentes"])
                ok = r["estado"] == "respondida" and src_ok and norm(expected) in norm(r["respuesta"])
                c[cat][0] += ok
                c[cat][1] += 1
                if not ok:
                    fails.append((cat, name, q, r["estado"], r["respuesta"][:120]))
        for cat in ("fuera", "fuera_parecidas"):
            for q in data.get(cat, []):
                r = ask(sid, q, lat)
                ok = r["estado"] in ("fuera_de_alcance", "sin_info")
                c[cat][0] += ok
                c[cat][1] += 1
                if not ok:
                    inventadas += 1
                    fails.append((cat, name, q, r["estado"], r["respuesta"][:120]))
        for q in data.get("vagas", []):
            r = ask(sid, q, lat)
            ok = r["estado"] != "fuera_de_alcance"
            c["vagas"][0] += ok
            c["vagas"][1] += 1
            if not ok:
                fails.append(("vagas", name, q, r["estado"], r["respuesta"][:120]))
    lat = sorted(lat)
    rate = lambda k: round(c[k][0] / c[k][1], 3) if c[k][1] else None  # noqa: E731
    fuera_total = c["fuera"][1] + c["fuera_parecidas"][1]
    res = {
        "modo": httpx.get(API + "/api/health").json()["modo"],
        "preguntas_dentro_de_tema": c["dentro"][1],
        "precision": rate("dentro"),
        "preguntas_coloquiales": c["dentro_coloquial"][1],
        "precision_coloquial": rate("dentro_coloquial"),
        "preguntas_fuera_de_tema": fuera_total,
        "rechazo_correcto": round((c["fuera"][0] + c["fuera_parecidas"][0]) / fuera_total, 3),
        "rechazo_correcto_parecidas": rate("fuera_parecidas"),
        "respuestas_inventadas": inventadas,
        "vagas_atendidas": rate("vagas"),
        "latencia_p50_ms": round(lat[len(lat) // 2] * 1000),
        "latencia_p95_ms": round(lat[int(len(lat) * 0.95)] * 1000),
        "latencia_max_ms": round(lat[-1] * 1000),
        "memoria_servidor_mb": server_memory_mb(),
    }
    print(json.dumps(res, indent=2, ensure_ascii=False))
    for f in fails:
        print("FALLA:", f)
    OUT.write_text(json.dumps({"resumen": res, "fallas": fails}, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
