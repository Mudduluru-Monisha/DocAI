"""Format-aware extraction. Every format becomes a list of Units that keep page/section metadata."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Unit:
    text: str
    page: int | None = None      # page / slide number when the format has one
    section: str | None = None   # heading, slide title, sheet name...
    kind: str = "text"           # "text" is analysed; "table_extra" is only indexed for retrieval


@dataclass
class Extracted:
    units: list[Unit]
    n_pages: int | None
    fmt: str
    warnings: list[str] = field(default_factory=list)


SUPPORTED = {".pdf": "PDF", ".docx": "Word", ".txt": "Text", ".md": "Text",
             ".pptx": "PowerPoint", ".csv": "CSV", ".xlsx": "Excel"}

MAX_ROWS = 5000
UNIT_LIMIT = 4000

HEAD_RE = re.compile(
    r"^(?:(?i:(?:chapter|part|book|section|act)\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten"
    r"|eleven|twelve)\b.{0,60}|prologue|epilogue|preface|introduction|abstract|conclusions?|references"
    r"|acknowledg(?:e)?ments)"
    r"|\d{1,2}(?:\.\d{1,2})?\.?\s+[A-Z][A-Za-z0-9 ,:&'-]{2,55})$"
)


def is_heading(line: str) -> bool:
    line = line.strip()
    return 0 < len(line) <= 70 and bool(HEAD_RE.match(line))


def split_long(text: str, limit: int = UNIT_LIMIT) -> list[str]:
    """Split on paragraph boundaries so no unit is huge."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    out, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        while len(para) > limit:  # one giant paragraph
            cut = para.rfind(". ", 0, limit)
            cut = cut + 1 if cut > limit // 2 else limit
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if cur and len(cur) + len(para) + 2 > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
    if cur.strip():
        out.append(cur)
    return [o for o in out if o.strip()]


def extract(data: bytes, filename: str) -> Extracted:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _pdf(data)
    if ext == ".docx":
        return _docx(data)
    if ext in (".txt", ".md"):
        return _txt(data)
    if ext == ".pptx":
        return _pptx(data)
    if ext == ".csv":
        return _csv(data)
    if ext == ".xlsx":
        return _xlsx(data)
    raise ValueError(f"Unsupported format: {ext or filename}")


# ---------------------------------------------------------------- PDF
def _pdf(data: bytes) -> Extracted:
    try:
        import pymupdf as fitz  # PyMuPDF >= 1.24.3
    except ImportError:
        import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    n = len(doc)
    warnings: list[str] = []
    toc = [t for t in doc.get_toc() if str(t[1]).strip()]
    entries: list[tuple[int, str]] = []
    if toc:
        top = min(t[0] for t in toc)
        entries = sorted(((max(1, t[2]), t[1].strip()) for t in toc if t[0] == top), key=lambda x: x[0])
        if len(entries) < 2:
            entries = sorted(((max(1, t[2]), t[1].strip()) for t in toc if t[0] <= top + 1), key=lambda x: x[0])
    units: list[Unit] = []
    title: str | None = None
    ei = 0
    total = 0
    want_tables = n <= 150
    for i in range(n):
        pn = i + 1
        page = doc[i]
        text = page.get_text("text").strip()
        total += len(text)
        if entries:
            while ei < len(entries) and entries[ei][0] <= pn:
                title = entries[ei][1]
                ei += 1
        else:
            for line in text.splitlines()[:200]:
                if is_heading(line):
                    title = line.strip()
                    break
        if text:
            units.append(Unit(text, pn, title))
        if want_tables and text:
            try:
                for t in page.find_tables().tables:
                    md = t.to_markdown()
                    if md and len(md) > 40:
                        units.append(Unit(md, pn, title, "table_extra"))
            except Exception:  # noqa: BLE001
                pass
    doc.close()
    if n and total < 40 * n:
        warnings.append("This PDF looks scanned (almost no extractable text). OCR isn't supported yet, "
                        "so results will be poor.")
    return Extracted(units, n, "PDF", warnings)


# ---------------------------------------------------------------- DOCX
def _docx(data: bytes) -> Extracted:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = Document(io.BytesIO(data))
    units: list[Unit] = []
    title: str | None = None
    buf: list[str] = []

    def flush():
        if buf:
            for part in split_long("\n\n".join(buf)):
                units.append(Unit(part, None, title))
            buf.clear()

    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            txt = p.text.strip()
            if not txt:
                continue
            style = (p.style.name or "") if p.style is not None else ""
            if style.lower().startswith(("heading", "title")):
                flush()
                title = txt
                continue
            buf.append(txt)
        elif tag == "tbl":
            t = Table(child, d)
            rows = [" | ".join(c.text.strip().replace("\n", " ") for c in r.cells) for r in t.rows]
            buf.append("\n".join(rows))
    flush()
    return Extracted(units, None, "Word")


# ---------------------------------------------------------------- TXT
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _txt(data: bytes) -> Extracted:
    text = _decode(data).replace("\r\n", "\n")
    units: list[Unit] = []
    title: str | None = None
    buf: list[str] = []

    def flush():
        if buf:
            for part in split_long("\n".join(buf)):
                units.append(Unit(part, None, title))
            buf.clear()

    for line in text.split("\n"):
        if is_heading(line):
            flush()
            title = line.strip()
        buf.append(line)
    flush()
    return Extracted(units, None, "Text")


# ---------------------------------------------------------------- PPTX
def _pptx(data: bytes) -> Extracted:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    units: list[Unit] = []
    for i, slide in enumerate(prs.slides, 1):
        title = None
        title_shape = slide.shapes.title
        if title_shape is not None and title_shape.has_text_frame:
            title = title_shape.text_frame.text.strip() or None
        parts: list[str] = []
        for sh in slide.shapes:
            if title_shape is not None and sh.shape_id == title_shape.shape_id:
                continue
            if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
                parts.append(sh.text_frame.text.strip())
            elif getattr(sh, "has_table", False):
                for r in sh.table.rows:
                    parts.append(" | ".join(c.text.strip() for c in r.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"Speaker notes: {notes}")
        body = "\n".join(parts)
        if title or body:
            units.append(Unit(f"Slide {i}: {title or ''}\n{body}".strip(), i, title or f"Slide {i}"))
    return Extracted(units, len(prs.slides), "PowerPoint")


# ---------------------------------------------------------------- CSV / XLSX
def _df_units(df, label: str, warnings: list[str]) -> list[Unit]:
    if len(df) > MAX_ROWS:
        warnings.append(f"'{label}' has {len(df):,} rows; only the first {MAX_ROWS:,} were indexed.")
        df = df.head(MAX_ROWS)
    cols = ", ".join(f"{c} ({t})" for c, t in zip(df.columns, df.dtypes.astype(str)))
    head = f"Table '{label}': {len(df)} rows x {len(df.columns)} columns.\nColumns: {cols}"
    try:
        head += "\nSummary statistics:\n" + df.describe(include="all").T.head(30).to_csv()
    except Exception:  # noqa: BLE001
        pass
    units = [Unit(head, None, label)]
    step = 30
    for start in range(0, len(df), step):
        block = df.iloc[start : start + step]
        units.append(Unit(f"Rows {start + 1}-{start + len(block)} of '{label}':\n{block.to_csv(index=False)}",
                          None, label))
    return units


def _csv(data: bytes) -> Extracted:
    import pandas as pd

    df = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(data), encoding=enc, sep=None, engine="python")
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        raise ValueError("Could not read this CSV file.")
    warnings = ["Tables are searched as text. Exact maths (sums, averages) isn't computed by the AI."]
    return Extracted(_df_units(df, "Data", warnings), None, "CSV", warnings)


def _xlsx(data: bytes) -> Extracted:
    import pandas as pd

    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    warnings = ["Tables are searched as text. Exact maths (sums, averages) isn't computed by the AI."]
    units: list[Unit] = []
    for name, df in sheets.items():
        if len(df.columns):
            units += _df_units(df, str(name), warnings)
    return Extracted(units, None, "Excel", warnings)
