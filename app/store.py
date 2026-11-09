"""Persistencia en SQLite: sitios, fragmentos de conocimiento y conversaciones."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("SABIO_DB", os.path.join(os.path.dirname(__file__), "..", "data", "sabio.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
  id TEXT PRIMARY KEY, url TEXT NOT NULL, name TEXT, platform TEXT, creds TEXT,
  status TEXT DEFAULT 'nuevo', progress INTEGER DEFAULT 0, pages INTEGER DEFAULT 0,
  products INTEGER DEFAULT 0, profile TEXT, created REAL, crawled_at REAL, error TEXT,
  allow_general INTEGER DEFAULT 0, contact TEXT, crawl_info TEXT, emb_model TEXT,
  plan TEXT DEFAULT 'emprendedor'
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT, url TEXT, title TEXT, kind TEXT,
  text TEXT, product TEXT, vec BLOB
);
CREATE INDEX IF NOT EXISTS ix_chunks_site ON chunks(site_id);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT, session TEXT, question TEXT,
  answer TEXT, status TEXT, sources TEXT, ts REAL
);
CREATE INDEX IF NOT EXISTS ix_messages_site_ts ON messages(site_id, ts);
-- Bloque 6: un voto por mensaje (la clave primaria lo garantiza)
CREATE TABLE IF NOT EXISTS feedback (
  message_id INTEGER PRIMARY KEY, site_id TEXT, valor INTEGER, ts REAL
);
"""


@contextmanager
def conn():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        # Bases creadas con versiones anteriores
        for table, col, typ in (("sites", "crawl_info", "TEXT"), ("sites", "emb_model", "TEXT"),
                                ("chunks", "vec", "BLOB"),
                                # Bloque 5: los sitios que ya existían quedan en el plan por defecto
                                ("sites", "plan", "TEXT DEFAULT 'emprendedor'")):
            if col not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def create_site(site_id: str, url: str, platform: str | None = None, creds: dict | None = None,
                allow_general: bool = False, plan: str = "emprendedor"):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO sites (id,url,platform,creds,status,created,allow_general,plan) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (site_id, url, platform, json.dumps(creds or {}), "en cola", time.time(), int(allow_general), plan))


def update_site(site_id: str, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in fields.values()]
    with conn() as c:
        c.execute(f"UPDATE sites SET {cols} WHERE id=?", (*vals, site_id))


def get_site(site_id: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("profile", "creds", "contact", "crawl_info"):
        d[k] = json.loads(d[k]) if d.get(k) else {}
    return d


def list_sites() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT id,url,name,platform,status,pages,products,crawled_at,crawl_info,plan FROM sites "
                         "ORDER BY created DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["crawl_info"] = json.loads(d["crawl_info"]) if d["crawl_info"] else {}
        out.append(d)
    return out


def replace_chunks(site_id: str, chunks: list[dict]):
    with conn() as c:
        c.execute("DELETE FROM chunks WHERE site_id=?", (site_id,))
        c.executemany("INSERT INTO chunks (site_id,url,title,kind,text,product,vec) VALUES (?,?,?,?,?,?,?)",
                      [(site_id, ch["url"], ch["title"], ch["kind"], ch["text"],
                        json.dumps(ch.get("product"), ensure_ascii=False) if ch.get("product") else None,
                        ch.get("vec")) for ch in chunks])


def get_chunks(site_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT id,url,title,kind,text,product,vec FROM chunks WHERE site_id=?",
                         (site_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["product"] = json.loads(d["product"]) if d["product"] else None
        out.append(d)
    return out


def log_message(site_id: str, session: str, q: str, a: str, status: str, sources: list[str]) -> int:
    """Guarda la pregunta y la respuesta. Devuelve el id del mensaje (lo usa el voto 👍/👎)."""
    with conn() as c:
        return c.execute("INSERT INTO messages (site_id,session,question,answer,status,sources,ts) VALUES (?,?,?,?,?,?,?)",
                         (site_id, session, q, a, status, json.dumps(sources), time.time())).lastrowid


# Sesiones internas: la página /presentacion, la evaluación automática y las verificaciones manuales.
# Se guardan igual (trazabilidad), pero no cuentan en las métricas del dueño del sitio.
INTERNAL_SESSIONS = ("presentacion", "eval", "verificacion")


def stats(site_id: str) -> dict:
    real = f"site_id=? AND session NOT IN ({','.join('?' * len(INTERNAL_SESSIONS))})"
    args = (site_id, *INTERNAL_SESSIONS)
    with conn() as c:
        rows = c.execute(f"SELECT status, COUNT(*) n FROM messages WHERE {real} GROUP BY status", args).fetchall()
        unanswered = c.execute(f"SELECT question, COUNT(*) n FROM messages WHERE {real} AND status='sin_info' "
                               "GROUP BY question ORDER BY n DESC LIMIT 20", args).fetchall()
        off_topic = c.execute(f"SELECT question, COUNT(*) n FROM messages WHERE {real} AND status='fuera_de_alcance' "
                              "GROUP BY question ORDER BY n DESC LIMIT 20", args).fetchall()
        recent = c.execute(f"SELECT question, answer, status, ts FROM messages WHERE {real} "
                           "ORDER BY ts DESC LIMIT 30", args).fetchall()
        votes = c.execute("SELECT f.valor, COUNT(*) n FROM feedback f JOIN messages m ON m.id=f.message_id "
                          f"WHERE m.site_id=? AND m.session NOT IN ({','.join('?' * len(INTERNAL_SESSIONS))}) "
                          "GROUP BY f.valor", args).fetchall()
    by = {r["status"]: r["n"] for r in rows}
    total = sum(by.values())
    return {"total": total, "por_estado": by,
            "tasa_resolucion": round(by.get("respondida", 0) / total, 3) if total else None,
            "sin_respuesta": [dict(r) for r in unanswered], "fuera_de_tema": [dict(r) for r in off_topic],
            "recientes": [dict(r) for r in recent], "utiles": _useful({r["valor"]: r["n"] for r in votes})}


def _useful(by_value: dict) -> dict:
    up, down = by_value.get(1, 0), by_value.get(-1, 0)
    return {"votos": up + down, "positivos": up,
            "porcentaje": round(100 * up / (up + down), 1) if up + down else None}


INTERRUPTED = "El rastreo se interrumpió, volvé a rastrear"


def mark_interrupted() -> int:
    """Al arrancar no hay ningún rastreo corriendo: los que figuran en curso quedaron cortados por un reinicio."""
    with conn() as c:
        return c.execute("UPDATE sites SET status='error', error=? WHERE status IN ('rastreando', 'en cola')",
                         (INTERRUPTED,)).rowcount


def delete_site(site_id: str) -> bool:
    """Borra el sitio, sus fragmentos y sus conversaciones."""
    with conn() as c:
        c.execute("DELETE FROM feedback WHERE site_id=?", (site_id,))
        c.execute("DELETE FROM messages WHERE site_id=?", (site_id,))
        c.execute("DELETE FROM chunks WHERE site_id=?", (site_id,))
        return c.execute("DELETE FROM sites WHERE id=?", (site_id,)).rowcount > 0



# ---------------------------------------------------------------- Planes y uso (Bloque 5)

PLANS = {"emprendedor": 500, "pyme": 2000, "pro": 8000}  # conversaciones por mes
WARN_SHARE = 0.8
AR_OFFSET = -3 * 3600  # hora de Argentina: UTC-3 fijo (no hay horario de verano desde 2009)


def month_start(now: float | None = None) -> float:
    """Comienzo del mes calendario en hora de Argentina, como timestamp UTC."""
    import calendar
    local = time.gmtime((now if now is not None else time.time()) + AR_OFFSET)
    return calendar.timegm((local.tm_year, local.tm_mon, 1, 0, 0, 0)) - AR_OFFSET


def _counted(c, site_id: str, since: float) -> str:
    """Mensajes que cuentan para el uso: del mes, de visitantes reales y no rechazados por límite."""
    return (f"site_id=? AND ts>=? AND status!='limite' "
            f"AND session NOT IN ({','.join('?' * len(INTERNAL_SESSIONS))})")


def usage(site_id: str, now: float | None = None) -> int:
    """Conversaciones del mes: sesiones distintas. Un mensaje sin sesión cuenta como una conversación."""
    since = month_start(now)
    with conn() as c:
        return c.execute(f"SELECT COUNT(DISTINCT CASE WHEN session='' OR session IS NULL THEN 'm' || id ELSE session END) "
                         f"FROM messages WHERE {_counted(c, site_id, since)}",
                         (site_id, since, *INTERNAL_SESSIONS)).fetchone()[0]


def session_started(site_id: str, session: str, now: float | None = None) -> bool:
    """La conversación ya empezó este mes (si llega al límite a mitad de charla, puede terminarla)."""
    if not session:
        return False
    since = month_start(now)
    with conn() as c:
        return c.execute(f"SELECT 1 FROM messages WHERE {_counted(c, site_id, since)} AND session=? LIMIT 1",
                         (site_id, since, *INTERNAL_SESSIONS, session)).fetchone() is not None


def plan_status(site_id: str, plan: str | None, now: float | None = None) -> dict:
    plan = plan if plan in PLANS else "emprendedor"
    used, limit = usage(site_id, now), PLANS[plan]
    share = used / limit
    return {"plan": plan, "limite": limit, "conversaciones_mes": used, "porcentaje": round(share * 100, 1),
            "estado": "limite" if share >= 1 else "aviso" if share >= WARN_SHARE else "ok"}


def set_plan(site_id: str, plan: str):
    if plan not in PLANS:
        raise ValueError(plan)
    update_site(site_id, plan=plan)



# ---------------------------------------------------------------- Satisfacción y reporte (Bloque 6)

class FeedbackError(ValueError):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def add_feedback(site_id: str, message_id: int, valor: int, session: str | None = None):
    """Un voto por mensaje. El mensaje tiene que existir, ser de ese sitio y (si tiene sesión) de esa sesión."""
    with conn() as c:
        m = c.execute("SELECT site_id, session FROM messages WHERE id=?", (message_id,)).fetchone()
        if not m or m["site_id"] != site_id:
            raise FeedbackError(404, "El mensaje no existe en este sitio")
        if m["session"] and session != m["session"]:
            raise FeedbackError(403, "El mensaje es de otra conversación")
        try:
            c.execute("INSERT INTO feedback (message_id, site_id, valor, ts) VALUES (?,?,?,?)",
                      (message_id, site_id, valor, time.time()))
        except sqlite3.IntegrityError:
            raise FeedbackError(409, "Ese mensaje ya tiene un voto")


def month_range(mes: str | None = None) -> tuple[float, float, str]:
    """("AAAA-MM" o None = mes actual) -> (inicio, fin, "AAAA-MM") en hora de Argentina."""
    import calendar
    import re
    if mes is None:
        local = time.gmtime(time.time() + AR_OFFSET)
        y, m = local.tm_year, local.tm_mon
    else:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
            raise ValueError(mes)
        y, m = int(mes[:4]), int(mes[5:])
    start = calendar.timegm((y, m, 1, 0, 0, 0)) - AR_OFFSET
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, calendar.timegm((ny, nm, 1, 0, 0, 0)) - AR_OFFSET, f"{y:04d}-{m:02d}"


def month_report(site_id: str, mes: str | None = None) -> dict:
    """Datos del reporte mensual del dueño (sin las sesiones internas)."""
    start, end, label = month_range(mes)
    real = (f"m.site_id=? AND m.ts>=? AND m.ts<? "
            f"AND m.session NOT IN ({','.join('?' * len(INTERNAL_SESSIONS))})")
    args = (site_id, start, end, *INTERNAL_SESSIONS)
    with conn() as c:
        by = {r["status"]: r["n"] for r in c.execute(
            f"SELECT status, COUNT(*) n FROM messages m WHERE {real} GROUP BY status", args)}
        top = lambda st: [(r["question"], r["n"]) for r in c.execute(  # noqa: E731
            f"SELECT question, COUNT(*) n FROM messages m WHERE {real} AND status=? "
            "GROUP BY question ORDER BY n DESC, question LIMIT 10", (*args, st))]
        votes = {r["valor"]: r["n"] for r in c.execute(
            f"SELECT f.valor, COUNT(*) n FROM feedback f JOIN messages m ON m.id=f.message_id WHERE {real} "
            "GROUP BY f.valor", args)}
        unanswered, off_topic = top("sin_info"), top("fuera_de_alcance")
    total = sum(by.values())
    return {"mes": label, "total": total,
            "resueltas": round(100 * by.get("respondida", 0) / total, 1) if total else None,
            "utiles": _useful(votes), "sin_respuesta": unanswered, "fuera_de_tema": off_topic}
