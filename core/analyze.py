"""Upload-time understanding: per-section analysis, entity merging, hierarchical overview."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from . import config

TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "lady", "lord", "mx", "the"}
GENERIC = {"he", "she", "they", "it", "him", "her", "them", "narrator", "author", "reader", "user", "company"}

SECTION_PROMPT = """TASK: SECTION_ANALYSIS
You are studying one part of a document, "<<NAME>>". Part: "<<TITLE>>"<<PAGES>>.
Learn what is actually in the text; do not assume the document's type.

Return ONLY JSON in this shape:
{
  "summary": "3-6 sentence summary of this part",
  "key_points": ["short point", "..."],
  "entities": [{"name": "fullest name used", "type": "free-form label such as person, character, organization, place, concept, method, dataset, skill, product, term", "description": "one sentence grounded in the text", "aliases": ["other names used"]}],
  "relations": [{"source": "entity name", "target": "entity name", "relation": "short verb phrase", "evidence": "brief phrase from the text"}],
  "events_or_facts": ["important event or fact, one line each"]
}
Rules: use only information in the text. Never invent. At most 25 entities and 25 relations; skip trivial ones.
<<KNOWN>>
TEXT:
<<TEXT>>"""

CONDENSE_PROMPT = """TASK: CONDENSE
Condense these section summaries of "<<NAME>>" into one faithful summary of about 200 words that preserves
the order of events/arguments, names, numbers and conclusions. Reply with plain text only.

<<TEXT>>"""

FINAL_PROMPT = """TASK: FINAL_OVERVIEW
Below are summaries of every part of the document "<<NAME>>", in order. Build the document-level understanding.

Return ONLY JSON:
{
  "title": "the document's title or best descriptive title",
  "document_type": "what kind of document this is, in your own words",
  "purpose": "1-2 sentences: what it is for / about",
  "overall_summary": "a complete summary (150-400 words) covering the whole document from beginning to end",
  "main_topics": ["5-10 important topics, themes or concepts"],
  "key_facts": ["5-12 important facts, events, findings or figures"],
  "conclusion": "how it ends / its conclusion / the main takeaway"
}
Use only the summaries below.

<<TEXT>>"""


def _clean(r) -> dict:
    if not isinstance(r, dict):
        r = {}
    ents = [e for e in (r.get("entities") or []) if isinstance(e, dict) and str(e.get("name", "")).strip()]
    rels = [x for x in (r.get("relations") or [])
            if isinstance(x, dict) and x.get("source") and x.get("target") and x.get("relation")]
    return {
        "summary": str(r.get("summary", "")).strip(),
        "key_points": [str(k) for k in (r.get("key_points") or []) if k][:10],
        "entities": ents[:30],
        "relations": rels[:30],
        "facts": [str(f) for f in (r.get("events_or_facts") or []) if f][:15],
    }


def analyze_section(llm, name: str, sec, text: str, known: list[str]) -> dict:
    pages = ""
    if sec.page_start is not None:
        pages = f" (pages {sec.page_start}–{sec.page_end})" if sec.page_end != sec.page_start else f" (page {sec.page_start})"
    known_line = ""
    if known:
        known_line = ("Entities already found earlier (reuse these exact names when the same entity appears): "
                      + "; ".join(known[:40]) + "\n")
    prompt = (SECTION_PROMPT.replace("<<NAME>>", name).replace("<<TITLE>>", sec.title)
              .replace("<<PAGES>>", pages).replace("<<KNOWN>>", known_line).replace("<<TEXT>>", text))
    return _clean(llm.generate_json(prompt, model=config.FAST_MODEL, max_tokens=8192))


# ------------------------------------------------------------ entity merging
def norm(name: str) -> str:
    s = re.sub(r"[^\w\s'-]", " ", str(name).lower())
    return " ".join(t for t in s.split() if t not in TITLES)


def _first_non_unknown(types: list[str]) -> str:
    c = Counter(t for t in types if t and t != "unknown")
    return c.most_common(1)[0][0] if c else "unknown"


def merge_entities(per_section: dict[int, dict]) -> tuple[list[dict], list[dict]]:
    """Dedupe entities across sections ("Mr. Smith" / "John Smith"), then remap relations onto them."""
    raw = []
    for sidx, res in sorted(per_section.items()):
        for e in res["entities"]:
            raw.append({"name": str(e["name"]).strip(), "type": str(e.get("type", "")).strip().lower() or "unknown",
                        "desc": str(e.get("description", "")).strip(),
                        "aliases": [str(a).strip() for a in (e.get("aliases") or []) if str(a).strip()],
                        "sec": sidx})

    parent = list(range(len(raw)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def keys_of(i):
        ks = {norm(raw[i]["name"])} | {norm(a) for a in raw[i]["aliases"]}
        return {k for k in ks if len(k) >= 3 and k not in GENERIC}

    owner: dict[str, int] = {}
    for i in range(len(raw)):
        for k in keys_of(i):
            if k in owner:
                union(i, owner[k])
            else:
                owner[k] = i

    def clusters():
        c = defaultdict(list)
        for i in range(len(raw)):
            c[find(i)].append(i)
        return c

    # a lone surname/first name joins the single longer name that contains it
    cl = clusters()
    for root, idxs in list(cl.items()):
        names = {norm(raw[i]["name"]) for i in idxs}
        if all(len(n.split()) == 1 for n in names):
            tok = next(iter(names))
            if len(tok) < 3 or tok in GENERIC:
                continue
            hits = {r2 for r2, i2 in cl.items() if r2 != root and any(
                len(k.split()) > 1 and tok in (k.split()[0], k.split()[-1]) for j in i2 for k in keys_of(j))}
            if len(hits) == 1:
                union(root, next(iter(hits)))

    entities, amap = [], {}
    for idxs in clusters().values():
        names = Counter(raw[i]["name"] for i in idxs)
        canon = max(names, key=lambda n: (min(len(norm(n).split()), 3), names[n], len(n)))
        descs = sorted({raw[i]["desc"] for i in idxs if raw[i]["desc"]}, key=len, reverse=True)[:2]
        als, seen = [], {canon.lower()}
        for i in idxs:
            for a in [raw[i]["name"], *raw[i]["aliases"]]:
                if a.lower() not in seen:
                    seen.add(a.lower())
                    als.append(a)
        ent = {"name": canon, "type": _first_non_unknown([raw[i]["type"] for i in idxs]),
               "description": " ".join(descs)[:400], "aliases": als[:8],
               "mentions": len({raw[i]["sec"] for i in idxs}), "sections": sorted({raw[i]["sec"] for i in idxs})}
        entities.append(ent)
        for i in idxs:
            for k in keys_of(i) | {norm(raw[i]["name"])}:
                if k:
                    amap.setdefault(k, canon)

    def resolve(name: str) -> str:
        k = norm(name)
        if k in amap:
            return amap[k]
        cands = {v for kk, v in amap.items() if k and k in kk.split()}
        if len(cands) == 1:
            return cands.pop()
        canon = str(name).strip()
        entities.append({"name": canon, "type": "unknown", "description": "", "aliases": [],
                         "mentions": 1, "sections": []})
        amap[k] = canon
        return canon

    rels: dict[tuple, dict] = {}
    for sidx, res in sorted(per_section.items()):
        for r in res["relations"]:
            s, t = resolve(r["source"]), resolve(r["target"])
            if s == t:
                continue
            key = (s.lower(), str(r["relation"]).strip().lower(), t.lower())
            if key in rels:
                rels[key]["weight"] += 1
            else:
                rels[key] = {"source": s, "target": t, "relation": str(r["relation"]).strip(),
                             "evidence": str(r.get("evidence", ""))[:200], "weight": 1}
    entities.sort(key=lambda e: (-e["mentions"], e["name"]))
    return entities, sorted(rels.values(), key=lambda r: -r["weight"])


# ------------------------------------------------------------ hierarchical overview
def _line(s: dict) -> str:
    pg = ""
    if s.get("page_start") is not None:
        pg = f" (p.{s['page_start']}–{s['page_end']})"
    return f"[{s['idx'] + 1}] {s['title']}{pg}: {s['summary']}"


def build_overview(llm, name: str, sections: list[dict]) -> dict:
    lines = [_line(s) for s in sections if s.get("summary")]
    for _ in range(4):  # collapse in layers until it fits one prompt
        if sum(len(x) for x in lines) <= 24000 or len(lines) <= 1:
            break
        batches, cur, size = [], [], 0
        for ln in lines:
            if cur and size + len(ln) > 12000:
                batches.append(cur)
                cur, size = [], 0
            cur.append(ln)
            size += len(ln)
        if cur:
            batches.append(cur)
        lines = [llm.generate(CONDENSE_PROMPT.replace("<<NAME>>", name).replace("<<TEXT>>", "\n".join(b)),
                              model=config.FAST_MODEL, max_tokens=1200) for b in batches]
    prompt = FINAL_PROMPT.replace("<<NAME>>", name).replace("<<TEXT>>", "\n".join(lines))
    r = llm.generate_json(prompt, model=config.SMART_MODEL, max_tokens=4096)
    if not isinstance(r, dict):
        r = {}
    as_list = lambda v: [str(x) for x in v if x] if isinstance(v, list) else []  # noqa: E731
    return {"title": str(r.get("title") or name), "document_type": str(r.get("document_type", "")),
            "purpose": str(r.get("purpose", "")), "overall_summary": str(r.get("overall_summary", "")),
            "main_topics": as_list(r.get("main_topics"))[:12], "key_facts": as_list(r.get("key_facts"))[:15],
            "conclusion": str(r.get("conclusion", ""))}
