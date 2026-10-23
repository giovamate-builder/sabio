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
  allow_general INTEGER DEFAULT 0, contact TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT, url TEXT, title TEXT, kind TEXT,
  text TEXT, product TEXT
);
CREATE INDEX IF NOT EXISTS ix_chunks_site ON chunks(site_id);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT, session TEXT, question TEXT,
  answer TEXT, status TEXT, sources TEXT, ts REAL
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


def create_site(site_id: str, url: str, platform: str | None = None, creds: dict | None = None,
                allow_general: bool = False):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO sites (id,url,platform,creds,status,created,allow_general) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (site_id, url, platform, json.dumps(creds or {}), "en cola", time.time(), int(allow_general)))


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
    for k in ("profile", "creds", "contact"):
        d[k] = json.loads(d[k]) if d.get(k) else {}
    return d


def list_sites() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT id,url,name,platform,status,pages,products,crawled_at FROM sites "
                         "ORDER BY created DESC").fetchall()
    return [dict(r) for r in rows]


def replace_chunks(site_id: str, chunks: list[dict]):
    with conn() as c:
        c.execute("DELETE FROM chunks WHERE site_id=?", (site_id,))
        c.executemany("INSERT INTO chunks (site_id,url,title,kind,text,product) VALUES (?,?,?,?,?,?)",
                      [(site_id, ch["url"], ch["title"], ch["kind"], ch["text"],
                        json.dumps(ch.get("product"), ensure_ascii=False) if ch.get("product") else None)
                       for ch in chunks])


def get_chunks(site_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT id,url,title,kind,text,product FROM chunks WHERE site_id=?", (site_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["product"] = json.loads(d["product"]) if d["product"] else None
        out.append(d)
    return out


def log_message(site_id: str, session: str, q: str, a: str, status: str, sources: list[str]):
    with conn() as c:
        c.execute("INSERT INTO messages (site_id,session,question,answer,status,sources,ts) VALUES (?,?,?,?,?,?,?)",
                  (site_id, session, q, a, status, json.dumps(sources), time.time()))


def stats(site_id: str) -> dict:
    with conn() as c:
        rows = c.execute("SELECT status, COUNT(*) n FROM messages WHERE site_id=? GROUP BY status",
                         (site_id,)).fetchall()
        unanswered = c.execute("SELECT question, COUNT(*) n FROM messages WHERE site_id=? AND status='sin_info' GROUP BY question ORDER BY n DESC LIMIT 20",
                               (site_id,)).fetchall()
        recent = c.execute("SELECT question, answer, status, ts FROM messages WHERE site_id=? "
                           "ORDER BY ts DESC LIMIT 30", (site_id,)).fetchall()
    by = {r["status"]: r["n"] for r in rows}
    total = sum(by.values())
    return {"total": total, "por_estado": by,
            "tasa_resolucion": round(by.get("respondida", 0) / total, 3) if total else None,
            "sin_respuesta": [dict(r) for r in unanswered], "recientes": [dict(r) for r in recent]}
