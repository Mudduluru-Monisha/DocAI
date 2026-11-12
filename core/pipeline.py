"""Ingest (extract → chunk → embed → store) and analyse (summaries, entities, overview) with checkpoints."""
from __future__ import annotations

import hashlib
import time
from collections import Counter
from pathlib import Path
from typing import Callable

from . import analyze, config, embeddings, extract, store
from .sections import build_sections, chunk_units, section_text

Progress = Callable[[float, str], None]


class AnalysisPaused(Exception):
    pass


def doc_id_for(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


def ingest(data: bytes, filename: str, progress: Progress | None = None, force: bool = False) -> str:
    p = progress or (lambda f, m: None)
    ext = Path(filename).suffix.lower()
    if ext not in extract.SUPPORTED:
        raise ValueError(f"Unsupported format '{ext}'. Supported: {', '.join(sorted(extract.SUPPORTED))}")
    doc_id = doc_id_for(data)
    if store.get_document(doc_id) and not force:
        p(1.0, "Already in your library")
        return doc_id

    p(0.03, "Reading file…")
    (config.UPLOAD_DIR / f"{doc_id}{ext}").write_bytes(data)
    ex = extract.extract(data, filename)
    if not any(u.kind == "text" and u.text.strip() for u in ex.units):
        raise ValueError("No readable text found in this file.")

    p(0.12, "Finding structure…")
    sections = build_sections(ex.units)
    chunks = chunk_units(doc_id, ex.units, sections)

    store.delete_chunks(doc_id)
    store.clear_kv(doc_id)
    batch = 64
    for s in range(0, len(chunks), batch):
        part = chunks[s : s + batch]
        store.add_chunks(doc_id, part, embeddings.embed([c.embed_text for c in part]))
        p(0.15 + 0.8 * min(s + batch, len(chunks)) / len(chunks), f"Indexing passages {min(s + batch, len(chunks))}/{len(chunks)}")

    store.add_document(
        doc_id, name=filename, fmt=ex.fmt, ext=ext, n_pages=ex.n_pages,
        n_chars=sum(len(u.text) for u in ex.units if u.kind == "text"), n_chunks=len(chunks),
        n_sections=len(sections), status="indexed", warnings=ex.warnings)
    store.save_sections(doc_id, sections)
    p(1.0, "Indexed")
    return doc_id


def analyze_document(doc_id: str, llm, progress: Progress | None = None) -> None:
    """Study the whole document. Per-section results are checkpointed, so a failure resumes where it stopped."""
    p = progress or (lambda f, m: None)
    doc = store.get_document(doc_id)
    if not doc:
        raise ValueError("Document not found.")
    ex = extract.extract((config.UPLOAD_DIR / f"{doc_id}{doc['ext']}").read_bytes(), doc["name"])
    sections = build_sections(ex.units)
    total = len(sections)
    store.update_document(doc_id, status="analysing", error="")

    results: dict[int, dict] = {}
    known: Counter = Counter()
    for n, sec in enumerate(sections):
        res = store.get_kv(doc_id, f"sec:{sec.idx}")
        if res is None:
            p(0.02 + 0.8 * n / total, f"Reading section {n + 1} of {total}: {sec.title[:48]}")
            try:
                res = analyze.analyze_section(llm, doc["name"], sec, section_text(ex.units, sec),
                                              [k for k, _ in known.most_common(40)])
            except Exception as e:  # noqa: BLE001
                store.update_document(doc_id, status="partial", error=str(e))
                raise AnalysisPaused(f"Paused at section {n + 1} of {total}. {e} "
                                     "Progress is saved; resume when ready.") from e
            store.put_kv(doc_id, f"sec:{sec.idx}", res)
        results[sec.idx] = res
        known.update(e["name"] for e in res["entities"])

    p(0.85, "Merging entities and relationships…")
    entities, relations = analyze.merge_entities(results)
    store.save_sections(doc_id, sections, results)
    store.save_knowledge(doc_id, entities, relations)

    p(0.92, "Writing the document overview…")
    try:
        overview = analyze.build_overview(llm, doc["name"], store.get_sections(doc_id))
    except Exception as e:  # noqa: BLE001
        store.update_document(doc_id, status="partial", error=str(e))
        raise AnalysisPaused(f"Paused while writing the overview. {e} Section results are saved; resume to finish.") from e
    store.update_document(doc_id, status="ready", error="", overview=overview)
    p(1.0, "Analysis complete")
