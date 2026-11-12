"""Run the strategies a Route asks for and collect numbered evidence."""
from __future__ import annotations

import difflib
import re

from . import config, embeddings, store
from .analyze import norm
from .router import Route


def _pages(s: dict) -> str:
    if s.get("page_start") is None:
        return ""
    return f"p.{s['page_start']}" if s["page_start"] == s["page_end"] else f"pp.{s['page_start']}–{s['page_end']}"


def find_sections(sections: list[dict], refs: list[str]) -> list[dict]:
    found: list[dict] = []
    window_title = re.compile(r"^(pages?|part)\s+\d", re.I)
    for ref in refs:
        r = ref.lower().strip()
        hit = None
        m = re.search(r"(?:page|slide)\s*(\d+)", r)
        if m:
            pg = int(m.group(1))
            hit = next((s for s in sections if s["page_start"] is not None and s["page_start"] <= pg <= s["page_end"]), None)
        else:
            nums = re.findall(r"\d+", r)
            if nums:
                hit = next((s for s in sections if not window_title.match(s["title"])
                            and re.search(rf"(?<!\d){nums[0]}(?!\d)", s["title"])), None)
            if hit is None:
                hit = next((s for s in sections if r and (r in s["title"].lower()
                            or (len(s["title"]) > 3 and s["title"].lower() in r))), None)
            if hit is None and not nums:  # a numbered ref ("chapter 99") must never fuzzy-match another number
                titles = [s["title"].lower() for s in sections]
                close = difflib.get_close_matches(r, titles, n=1, cutoff=0.5)
                hit = sections[titles.index(close[0])] if close else None
        if hit and hit not in found:
            found.append(hit)
    return found[:3]


def find_entities(entities: list[dict], names: list[str]) -> list[dict]:
    keyed = [(e, {norm(e["name"])} | {norm(a) for a in e["aliases"]}) for e in entities]
    out: list[dict] = []
    for n in names:
        k = norm(n)
        hits = [e for e, ks in keyed if k in ks or any(k in kk.split() for kk in ks)]
        if not hits:
            allk = {kk: e for e, ks in keyed for kk in ks}
            close = difflib.get_close_matches(k, list(allk), n=1, cutoff=0.8)
            hits = [allk[close[0]]] if close else []
        for e in hits:
            if e not in out:
                out.append(e)
    return out[:8]


def _entity_text(e: dict) -> str:
    t = f"{e['name']} ({e['type']})"
    if e["description"]:
        t += f": {e['description']}"
    if e["aliases"]:
        t += f" Also called: {', '.join(e['aliases'])}."
    return t + f" Mentioned in {e['mentions']} section(s)."


def gather(doc_id: str, route: Route) -> tuple[list[dict], list[str]]:
    """Returns (evidence, notes). Evidence items: kind, title, text, page, section."""
    doc = store.get_document(doc_id)
    sections = store.get_sections(doc_id)
    entities = store.get_entities(doc_id)
    relations = store.get_relations(doc_id)
    ov = doc.get("overview") or {}
    ev: list[dict] = []
    notes: list[str] = []
    seen: set[str] = set()
    st = set(route.strategies)
    qvec = embeddings.embed([route.standalone])[0]

    def add_chunks(rows, label=None):
        for c in rows:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            ev.append({"kind": "passage", "title": label or (c["section"] or "Passage"), "text": c["text"],
                       "page": c["page"], "section": c["section"]})

    if "overall_summary" in st and ov.get("overall_summary"):
        body = ov["overall_summary"]
        for key, label in (("purpose", "Purpose"), ("conclusion", "Conclusion")):
            if ov.get(key):
                body += f"\n{label}: {ov[key]}"
        if ov.get("main_topics"):
            body += "\nMain topics: " + "; ".join(ov["main_topics"])
        if ov.get("key_facts"):
            body += "\nKey facts: " + "; ".join(ov["key_facts"])
        ev.append({"kind": "summary", "title": "Document summary", "text": body, "page": None, "section": ""})
        steps = [f"{s['idx'] + 1}. {s['title']} {_pages(s)}: {s['summary']}" for s in sections if s["summary"]]
        if steps and sum(len(x) for x in steps) <= 14000:
            ev.append({"kind": "summary", "title": "Section-by-section summary", "text": "\n".join(steps),
                       "page": None, "section": ""})

    if "section" in st:
        matched = find_sections(sections, route.section_refs)
        if not matched and route.section_refs:
            notes.append(f"No section matched {', '.join(route.section_refs)}; answer from the passages found instead.")
        for s in matched:
            body = s["summary"] or "(no summary available)"
            if s["key_points"]:
                body += "\nKey points: " + "; ".join(s["key_points"])
            ev.append({"kind": "section", "title": f"Section: {s['title']}", "text": body,
                       "page": s["page_start"], "section": s["title"]})
            add_chunks(store.query_chunks(doc_id, qvec, 4, section_idx=s["idx"]))

    matched_ents = find_entities(entities, route.entities) if ({"entity", "relationship"} & st) else []
    if "entity" in st:
        if route.list_all or not matched_ents:
            types = [t.lower() for t in route.entity_types]
            pool = [e for e in entities if not types or any(t in e["type"] or e["type"] in t for t in types)] or entities
            if pool:
                ev.append({"kind": "entity", "title": "Entities found in the document",
                           "text": "\n".join(_entity_text(e) for e in pool[:40]), "page": None, "section": ""})
        for e in matched_ents:
            ev.append({"kind": "entity", "title": f"Entity: {e['name']}", "text": _entity_text(e), "page": None, "section": ""})

    if "relationship" in st:
        names = {e["name"] for e in matched_ents}
        rels = [r for r in relations if r["source"] in names or r["target"] in names]
        both = [r for r in rels if r["source"] in names and r["target"] in names]
        rels = (both + [r for r in rels if r not in both])[:30]
        if rels:
            ev.append({"kind": "relation", "title": "Relationships",
                       "text": "\n".join(f"{r['source']} —{r['relation']}→ {r['target']}"
                                         + (f" ({r['evidence']})" if r["evidence"] else "") for r in rels),
                       "page": None, "section": ""})
        elif route.entities:
            notes.append("No stored relationship matched those entities; passages were searched instead.")

    if "multi_step" in st:
        for sq in (route.sub_questions or [route.standalone])[:4]:
            add_chunks(store.query_chunks(doc_id, embeddings.embed([sq])[0], 4), label=f"For: {sq[:60]}")

    k = config.TOP_K if ("semantic" in st or not (st - {"semantic"})) else 3
    add_chunks(store.query_chunks(doc_id, qvec, k))

    # respect the evidence budget, dropping the least important passages last-first
    total = 0
    kept = []
    for item in ev:
        total += len(item["text"])
        if total > config.EVIDENCE_BUDGET and item["kind"] == "passage":
            continue
        kept.append(item)
    return kept, notes
