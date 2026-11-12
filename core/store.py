"""Storage: SQLite for documents/sections/entities/relations/checkpoints, ChromaDB for chunk vectors."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager

from . import config

DB_PATH = config.DATA_DIR / "documind.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  doc_id TEXT PRIMARY KEY, name TEXT, fmt TEXT, ext TEXT, n_pages INT, n_chars INT, n_chunks INT,
  n_sections INT, status TEXT, error TEXT, warnings TEXT, overview TEXT, created REAL);
CREATE TABLE IF NOT EXISTS sections(
  doc_id TEXT, idx INT, title TEXT, page_start INT, page_end INT, summary TEXT, key_points TEXT,
  PRIMARY KEY(doc_id, idx));
CREATE TABLE IF NOT EXISTS entities(
  doc_id TEXT, name TEXT, type TEXT, description TEXT, aliases TEXT, mentions INT, sections TEXT);
CREATE TABLE IF NOT EXISTS relations(
  doc_id TEXT, source TEXT, relation TEXT, target TEXT, evidence TEXT, weight INT);
CREATE TABLE IF NOT EXISTS kv(doc_id TEXT, k TEXT, v TEXT, PRIMARY KEY(doc_id, k));
"""

_ready = False
_col = None


@contextmanager
def _db():
    global _ready
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        if not _ready:
            con.executescript(SCHEMA)
            _ready = True
        yield con
        con.commit()
    finally:
        con.close()


def collection():
    global _col
    if _col is None:
        import chromadb

        client = chromadb.PersistentClient(path=str(config.DATA_DIR / "chroma"))
        _col = client.get_or_create_collection("chunks", metadata={"hnsw:space": "cosine"})
    return _col


# ------------------------------------------------------------ documents
def add_document(doc_id: str, **f) -> None:
    f["warnings"] = json.dumps(f.get("warnings") or [])
    f.setdefault("overview", "{}")
    cols = ["doc_id", "name", "fmt", "ext", "n_pages", "n_chars", "n_chunks", "n_sections",
            "status", "error", "warnings", "overview", "created"]
    f.setdefault("error", "")
    f.setdefault("created", time.time())
    vals = [doc_id] + [f.get(c) for c in cols[1:]]
    with _db() as con:
        con.execute(f"INSERT OR REPLACE INTO documents({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)


def update_document(doc_id: str, **f) -> None:
    if "overview" in f and not isinstance(f["overview"], str):
        f["overview"] = json.dumps(f["overview"])
    sets = ",".join(f"{k}=?" for k in f)
    with _db() as con:
        con.execute(f"UPDATE documents SET {sets} WHERE doc_id=?", [*f.values(), doc_id])


def _doc(row) -> dict:
    d = dict(row)
    d["warnings"] = json.loads(d.get("warnings") or "[]")
    d["overview"] = json.loads(d.get("overview") or "{}")
    return d


def get_document(doc_id: str) -> dict | None:
    with _db() as con:
        row = con.execute("SELECT * FROM documents WHERE doc_id=?", [doc_id]).fetchone()
    return _doc(row) if row else None


def list_documents() -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT * FROM documents ORDER BY created DESC").fetchall()
    return [_doc(r) for r in rows]


def delete_document(doc_id: str) -> None:
    doc = get_document(doc_id)
    with _db() as con:
        for t in ("documents", "sections", "entities", "relations", "kv"):
            con.execute(f"DELETE FROM {t} WHERE doc_id=?", [doc_id])
    delete_chunks(doc_id)
    if doc:
        (config.UPLOAD_DIR / f"{doc_id}{doc['ext']}").unlink(missing_ok=True)


# ------------------------------------------------------------ sections / knowledge
def save_sections(doc_id: str, sections, results: dict | None = None) -> None:
    results = results or {}
    with _db() as con:
        con.execute("DELETE FROM sections WHERE doc_id=?", [doc_id])
        for s in sections:
            r = results.get(s.idx, {})
            con.execute("INSERT INTO sections VALUES(?,?,?,?,?,?,?)",
                        [doc_id, s.idx, s.title, s.page_start, s.page_end,
                         r.get("summary", ""), json.dumps(r.get("key_points", []))])


def get_sections(doc_id: str) -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT * FROM sections WHERE doc_id=? ORDER BY idx", [doc_id]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["key_points"] = json.loads(d["key_points"] or "[]")
        out.append(d)
    return out


def save_knowledge(doc_id: str, entities: list[dict], relations: list[dict]) -> None:
    with _db() as con:
        con.execute("DELETE FROM entities WHERE doc_id=?", [doc_id])
        con.execute("DELETE FROM relations WHERE doc_id=?", [doc_id])
        for e in entities:
            con.execute("INSERT INTO entities VALUES(?,?,?,?,?,?,?)",
                        [doc_id, e["name"], e["type"], e["description"], json.dumps(e["aliases"]),
                         e["mentions"], json.dumps(e["sections"])])
        for r in relations:
            con.execute("INSERT INTO relations VALUES(?,?,?,?,?,?)",
                        [doc_id, r["source"], r["relation"], r["target"], r.get("evidence", ""), r.get("weight", 1)])


def get_entities(doc_id: str) -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT * FROM entities WHERE doc_id=? ORDER BY mentions DESC, name", [doc_id]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["aliases"] = json.loads(d["aliases"] or "[]")
        d["sections"] = json.loads(d["sections"] or "[]")
        out.append(d)
    return out


def get_relations(doc_id: str) -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT * FROM relations WHERE doc_id=? ORDER BY weight DESC", [doc_id]).fetchall()
    return [dict(r) for r in rows]


def put_kv(doc_id: str, key: str, value) -> None:
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO kv VALUES(?,?,?)", [doc_id, key, json.dumps(value)])


def get_kv(doc_id: str, key: str):
    with _db() as con:
        row = con.execute("SELECT v FROM kv WHERE doc_id=? AND k=?", [doc_id, key]).fetchone()
    return json.loads(row["v"]) if row else None


def clear_kv(doc_id: str) -> None:
    with _db() as con:
        con.execute("DELETE FROM kv WHERE doc_id=?", [doc_id])


# ------------------------------------------------------------ vectors
def add_chunks(doc_id: str, chunks, vectors) -> None:
    col = collection()
    for s in range(0, len(chunks), 500):
        cs, vs = chunks[s : s + 500], vectors[s : s + 500]
        col.upsert(
            ids=[c.id for c in cs],
            documents=[c.text for c in cs],
            embeddings=vs,
            metadatas=[{"doc_id": doc_id, "page": c.page if c.page is not None else -1,
                        "section": c.section_title, "section_idx": c.section_idx, "kind": c.kind} for c in cs],
        )


def delete_chunks(doc_id: str) -> None:
    try:
        collection().delete(where={"doc_id": doc_id})
    except Exception:  # noqa: BLE001
        pass


def query_chunks(doc_id: str, vec, k: int, section_idx: int | None = None) -> list[dict]:
    where = {"doc_id": doc_id} if section_idx is None else {"$and": [{"doc_id": doc_id}, {"section_idx": section_idx}]}
    res = collection().query(query_embeddings=[vec], n_results=k, where=where)
    out = []
    for i, cid in enumerate(res["ids"][0]):
        m = res["metadatas"][0][i]
        out.append({"id": cid, "text": res["documents"][0][i], "page": None if m["page"] < 0 else m["page"],
                    "section": m["section"], "section_idx": m["section_idx"], "distance": res["distances"][0][i]})
    return out
