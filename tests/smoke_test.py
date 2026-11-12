"""Offline end-to-end test: fake Gemini + fake embeddings. Run: python tests/smoke_test.py"""
import hashlib
import os
import re
import sys
import tempfile

os.environ["DOCUMIND_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import analyze, answer, config, embeddings, pipeline, retrieval, router, store  # noqa: E402


def fake_embed(texts, batch_size=64):
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in re.findall(r"\w+", t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        out.append([x / n for x in v])
    return out


embeddings.embed = fake_embed


class FakeLLM:
    def __init__(self, key=None):
        pass

    def generate_json(self, prompt, **kw):
        if "TASK: SECTION_ANALYSIS" in prompt:
            text = prompt.split("TEXT:\n", 1)[1]
            names = [n for n, c in __import__("collections").Counter(re.findall(r"\b[A-Z][a-z]{3,}\b", text)).items() if c >= 2][:4]
            ents = [{"name": n, "type": "character", "description": f"{n} appears here.", "aliases": []} for n in names]
            if "Smith" in text:
                ents.append({"name": "Mr. John Smith", "type": "person", "description": "A baker.", "aliases": ["Smith"]})
                ents.append({"name": "Smith", "type": "person", "description": "The baker.", "aliases": []})
            rels = [{"source": names[0], "target": names[1], "relation": "meets", "evidence": "x"}] if len(names) > 1 else []
            return {"summary": f"Summary of: {text[:60]}", "key_points": ["a point"], "entities": ents,
                    "relations": rels, "events_or_facts": []}
        if "TASK: ROUTE" in prompt:
            return {"strategies": ["overall_summary", "entity"], "standalone_question": "q", "section_refs": [],
                    "entities": [], "entity_types": ["character"], "list_all_entities": True,
                    "sub_questions": [], "style": "bullets"}
        if "TASK: FINAL_OVERVIEW" in prompt:
            return {"title": "Test Doc", "document_type": "story", "purpose": "testing", "overall_summary": "All of it.",
                    "main_topics": ["t1"], "key_facts": ["f1"], "conclusion": "It ends."}
        raise AssertionError(prompt[:80])

    def generate(self, prompt, **kw):
        return "condensed"

    def stream(self, prompt, **kw):
        yield "Answer using [1]."


def make_files():
    import docx
    import openpyxl
    from pptx import Presentation
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    story = "\n\n".join(
        f"Chapter {i}\n\n" + " ".join(f"Alice met Bobby near the old harbour. Mr. John Smith baked bread. " * 20 for _ in range(3))
        for i in range(1, 7))
    files = {"story.txt": story.encode()}

    d = docx.Document()
    for i in range(1, 4):
        d.add_heading(f"Heading {i}", 1)
        d.add_paragraph(("Paragraph about Python and SQL skills. " * 60))
    d.add_table(rows=2, cols=2).cell(0, 0).text = "cell"
    p = os.path.join(config.DATA_DIR, "t.docx")
    d.save(p)
    files["t.docx"] = open(p, "rb").read()

    pdf = fitz.open()
    for i in range(1, 7):
        page = pdf.new_page()
        page.insert_text((72, 72), f"{i} Section number {i}", fontsize=14)
        page.insert_text((72, 110), "Gradient descent updates parameters. " * 3, fontsize=10)
    files["t.pdf"] = pdf.tobytes()

    prs = Presentation()
    for i in range(1, 4):
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = f"Slide topic {i}"
        s.placeholders[1].text = "Body text " * 20
    p = os.path.join(config.DATA_DIR, "t.pptx")
    prs.save(p)
    files["t.pptx"] = open(p, "rb").read()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["region", "revenue"])
    for i in range(50):
        ws.append([f"R{i % 3}", i * 10])
    p = os.path.join(config.DATA_DIR, "t.xlsx")
    wb.save(p)
    files["t.xlsx"] = open(p, "rb").read()
    files["t.csv"] = b"a,b\n" + b"\n".join(f"{i},{i * 2}".encode() for i in range(100))
    return files


def main():
    files = make_files()
    llm = FakeLLM()
    for name, data in files.items():
        doc_id = pipeline.ingest(data, name)
        doc = store.get_document(doc_id)
        assert doc["status"] == "indexed" and doc["n_chunks"] > 0, (name, doc)
        print(f"{name:10} chunks={doc['n_chunks']:3} sections={doc['n_sections']} pages={doc['n_pages']}")
        pipeline.analyze_document(doc_id, llm)
        doc = store.get_document(doc_id)
        assert doc["status"] == "ready" and doc["overview"]["title"] == "Test Doc"
        secs = store.get_sections(doc_id)
        assert all(s["summary"] for s in secs)

    # story: headed sections, entity dedupe, routing, retrieval
    sid = pipeline.doc_id_for(files["story.txt"])
    secs = store.get_sections(sid)
    print("story sections:", [s["title"] for s in secs])
    ents = {e["name"]: e for e in store.get_entities(sid)}
    print("entities:", list(ents)[:8])
    smiths = [n for n in ents if "smith" in n.lower()]
    assert len(smiths) == 1, smiths
    assert store.get_relations(sid)

    doc = store.get_document(sid)
    r = router.route(llm, "Who are all the characters?", doc, secs, ["character"], [], True)
    ev, notes = retrieval.gather(sid, r)
    kinds = {e["kind"] for e in ev}
    assert {"summary", "entity", "passage"} <= kinds, kinds
    r2 = router.heuristic_route("Explain Chapter 5")
    ev2, _ = retrieval.gather(sid, r2)
    assert any(e["title"].startswith("Section:") for e in ev2), [e["title"] for e in ev2]
    r3 = router.heuristic_route("Summarise Chapter 99")
    _, notes3 = retrieval.gather(sid, r3)
    print("notes:", notes3)
    assert notes3 and "99" in notes3[0]

    prompt = answer.build_prompt("q", ev, notes, "bullets", [])
    assert "EVIDENCE" in prompt and "".join(answer.stream(llm, "q", ev, notes, "auto", [])).startswith("Answer")

    # checkpoint/resume: fail on 3rd section call, then resume and confirm earlier work isn't redone
    calls = {"n": 0}

    class Flaky(FakeLLM):
        def generate_json(self, prompt, **kw):
            if "TASK: SECTION_ANALYSIS" in prompt:
                calls["n"] += 1
                if calls["n"] == 3 and not calls.get("fixed"):
                    raise RuntimeError("rate limit")
            return super().generate_json(prompt, **kw)

    data = files["story.txt"] + b"\nExtra line."
    did = pipeline.ingest(data, "story2.txt")
    try:
        pipeline.analyze_document(did, Flaky())
        raise SystemExit("expected pause")
    except pipeline.AnalysisPaused as e:
        print("paused:", e)
    assert store.get_document(did)["status"] == "partial"
    calls["n"], calls["fixed"] = 0, True
    pipeline.analyze_document(did, Flaky())
    assert store.get_document(did)["status"] == "ready"
    print("resume section calls:", calls["n"])
    assert calls["n"] == 4, calls  # 6 sections, 2 were checkpointed
    print("ALL OK")


if __name__ == "__main__":
    main()
