"""Turn units into analysis sections, and units into retrieval chunks."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from . import config
from .extract import Unit


@dataclass
class Section:
    idx: int
    title: str
    page_start: int | None
    page_end: int | None
    unit_ids: list[int]


@dataclass
class Chunk:
    id: str
    text: str
    page: int | None
    section_title: str
    section_idx: int
    kind: str

    @property
    def embed_text(self) -> str:
        return f"{self.section_title}\n{self.text}" if self.section_title else self.text


def _size(units, ids) -> int:
    return sum(len(units[i].text) for i in ids)


def _pages(units, ids):
    p = [units[i].page for i in ids if units[i].page is not None]
    return (min(p), max(p)) if p else (None, None)


def _join_title(titles: list[str]) -> str:
    names = [t for t in titles if t]
    if not names:
        return ""
    if len(names) == 1 or names[0] == names[-1]:
        return names[0]
    return f"{names[0]} → {names[-1]}"


def build_sections(units: list[Unit]) -> list[Section]:
    ids = [i for i, u in enumerate(units) if u.kind == "text" and u.text.strip()]
    if not ids:
        return []

    groups: list[list] = []  # [title, [unit ids]]
    for i in ids:
        t = (units[i].section or "").strip()
        if groups and groups[-1][0] == t:
            groups[-1][1].append(i)
        else:
            groups.append([t, [i]])
    titled = len({g[0] for g in groups if g[0]}) >= 2
    if not titled:
        groups = [["", ids]]

    # merge tiny headed groups so we don't spend one API call on a few lines
    merged: list[tuple[list[str], list[int]]] = []
    bt: list[str] = []
    bi: list[int] = []
    for t, g in groups:
        bt.append(t)
        bi += g
        if _size(units, bi) >= config.MIN_SECTION_CHARS:
            merged.append((bt, bi))
            bt, bi = [], []
    if bi:
        if merged:
            merged[-1] = (merged[-1][0] + bt, merged[-1][1] + bi)
        else:
            merged.append((bt, bi))

    limit = config.MAX_SECTION_CHARS if titled else config.WINDOW_CHARS
    parts: list[tuple[str, list[int]]] = []
    for ts, g in merged:
        title = _join_title(ts)
        pieces, cur, sz = [], [], 0
        for i in g:
            n = len(units[i].text)
            if cur and sz + n > limit:
                pieces.append(cur)
                cur, sz = [], 0
            cur.append(i)
            sz += n
        if cur:
            pieces.append(cur)
        for k, p in enumerate(pieces, 1):
            parts.append((f"{title} (part {k})" if title and len(pieces) > 1 else title, p))

    cap = config.MAX_ANALYSIS_CALLS
    if len(parts) > cap:
        k = math.ceil(len(parts) / cap)
        regrouped = []
        for s in range(0, len(parts), k):
            chunk = parts[s : s + k]
            regrouped.append((_join_title([c[0] for c in chunk]), [i for c in chunk for i in c[1]]))
        parts = regrouped

    sections = []
    for n, (title, p) in enumerate(parts):
        a, b = _pages(units, p)
        if not title:
            if a is not None:
                title = f"Page {a}" if a == b else f"Pages {a}–{b}"
            else:
                title = f"Part {n + 1}"
        sections.append(Section(n, title, a, b, p))
    return sections


def section_text(units: list[Unit], sec: Section) -> str:
    out = []
    for i in sec.unit_ids:
        u = units[i]
        out.append(f"[p.{u.page}] {u.text}" if u.page is not None else u.text)
    return "\n\n".join(out)


def split_text(text: str, size: int, overlap: int) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    floor = int(size * 0.6)
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start + floor : end]
            m = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if m > 0:
                end = start + floor + m + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def chunk_units(doc_id: str, units: list[Unit], sections: list[Section]) -> list[Chunk]:
    uid2sec = {i: s.idx for s in sections for i in s.unit_ids}
    titles = {s.idx: s.title for s in sections}
    chunks: list[Chunk] = []
    last = 0
    for i, u in enumerate(units):
        last = uid2sec.get(i, last)
        for piece in split_text(u.text, config.CHUNK_CHARS, config.CHUNK_OVERLAP):
            chunks.append(Chunk(f"{doc_id}:{len(chunks)}", piece, u.page, titles.get(last, ""), last, u.kind))
    return chunks
