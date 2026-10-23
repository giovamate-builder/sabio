"""Corre el set de evaluación contra una instancia de SABIO y calcula los indicadores del proyecto.

Indicadores (ver punto 10 y 19 del documento):
- Precisión: preguntas del sitio respondidas con la fuente correcta y el dato esperado.
- Respuestas inventadas: respuestas a preguntas fuera de tema (deberían ser 0).
- Rechazo correcto: preguntas fuera de tema que el asistente rechaza.
Uso:  python eval/run_eval.py [http://localhost:8000]
"""
import json
import sys
import time
import unicodedata
from pathlib import Path

import httpx

API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
SET = json.loads((Path(__file__).parent / "eval_set.json").read_text(encoding="utf-8"))
PORTS = {"tecnosur": 8101, "dulcepilar": 8102}


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def main():
    sites = {s["url"]: s["id"] for s in httpx.get(API + "/api/sites").json()}
    tot = {"dentro": 0, "ok": 0, "fuera": 0, "rechazo": 0, "inventadas": 0, "latencias": []}
    fails = []
    for name, data in SET.items():
        sid = sites[f"http://localhost:{PORTS[name]}"]
        for q, url_part, expected in data["dentro"]:
            t = time.time()
            r = httpx.post(API + "/api/chat", json={"site_id": sid, "message": q, "session": "eval"}).json()
            tot["latencias"].append(time.time() - t)
            tot["dentro"] += 1
            src_ok = any(url_part in f["url"] for f in r["fuentes"])
            ok = r["estado"] == "respondida" and src_ok and norm(expected) in norm(r["respuesta"])
            tot["ok"] += ok
            if not ok:
                fails.append((name, q, r["estado"], r["respuesta"][:120]))
        for q in data["fuera"]:
            r = httpx.post(API + "/api/chat", json={"site_id": sid, "message": q, "session": "eval"}).json()
            tot["fuera"] += 1
            if r["estado"] in ("fuera_de_alcance", "sin_info"):
                tot["rechazo"] += 1
            else:
                tot["inventadas"] += 1
                fails.append((name, q, r["estado"], r["respuesta"][:120]))
    lat = sorted(tot["latencias"])
    res = {
        "modo": httpx.get(API + "/api/health").json()["modo"],
        "preguntas_dentro_de_tema": tot["dentro"],
        "precision": round(tot["ok"] / tot["dentro"], 3),
        "preguntas_fuera_de_tema": tot["fuera"],
        "rechazo_correcto": round(tot["rechazo"] / tot["fuera"], 3),
        "respuestas_inventadas": tot["inventadas"],
        "latencia_p50_ms": round(lat[len(lat) // 2] * 1000),
        "latencia_max_ms": round(lat[-1] * 1000),
    }
    print(json.dumps(res, indent=2, ensure_ascii=False))
    for f in fails:
        print("FALLA:", f)
    (Path(__file__).parent / "resultados.json").write_text(json.dumps({"resumen": res, "fallas": fails},
                                                                      indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
