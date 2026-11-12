# DocuMind AI

One app that reads any document (PDF, DOCX, TXT, PPTX, CSV, XLSX), understands it at upload time, then answers
questions with page references. Built on Streamlit, Gemini, Sentence Transformers and ChromaDB.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then paste your free key from aistudio.google.com/apikey
streamlit run app.py
```

The first upload downloads the embedding model (about 90 MB). You can also paste the API key in the sidebar instead of `.env`.

## How it works

| Stage | Module | What happens |
|---|---|---|
| Extract | `core/extract.py` | Each format becomes units with page / heading / sheet metadata. Headings come from the PDF outline, Word heading styles, slide titles, sheet names, or "Chapter N"-style lines. |
| Section | `core/sections.py` | Units are grouped into analysis sections (merged if tiny, split if huge, fixed windows when there are no headings) and into ~1000-character retrieval chunks. |
| Index | `core/pipeline.py`, `core/store.py` | Local embeddings go into ChromaDB. This step needs no API key. |
| Understand | `core/analyze.py` | One Gemini call per section returns a summary, entities, relations and facts. Results are checkpointed per section. Entities are then merged ("Mr. John Smith" and "Smith"), and a layered reduce builds the whole-document overview. |
| Route | `core/router.py` | An LLM classifier picks strategies (semantic, overall summary, section, entity, relationship, multi-step). A regex fallback is used if it fails. |
| Retrieve | `core/retrieval.py` | Runs the chosen strategies and always adds a few semantic passages as a safety net. |
| Answer | `core/answer.py` | Gemini answers from numbered evidence only, cites `[n]`, and says so when the document lacks the answer. |

If analysis stops (rate limit, network), your progress is saved. Press **Resume analysis** and it continues from the
last finished section.

## Free-tier tips

- Both models default to `gemini-3.5-flash-lite`, which has the most generous free quota (about 10 requests/minute and 500/day). Bigger Flash models are limited to roughly 20 requests/day on free keys. If Google retires a name you'll get a 404 error: edit `GEMINI_FAST_MODEL` / `GEMINI_SMART_MODEL` in `.env` or the sidebar's **Models** box.
- Without a key you can still index documents and search; chat then returns the closest passages instead of a written answer.
- Set `GEMINI_RPM` to the per-minute limit shown for your project in Google AI Studio. The app paces itself to it.
- A 300-page book is about 25-35 analysis calls. Expect a few minutes on the free tier.
- Free-tier requests may be used by Google to improve its products. Don't upload confidential documents on the free tier.
- Turn off **Deep analysis on upload** for a quick index; run it later from the document banner.

## Known limits

- No OCR: scanned PDFs warn you and give poor results.
- CSV/XLSX are searched as text. The AI does not compute exact sums or averages, and only the first 5,000 rows per sheet are indexed.
- Entity extraction depends on the model; expect occasional duplicates or misses on long, name-heavy books.
- "Explain Chapter N" works when the document has detectable headings. Without them, sections are named by page range.

## Tests (no API key needed)

```bash
python tests/smoke_test.py   # every format end to end, entity merging, routing, checkpoint/resume
python tests/ui_test.py      # headless run of the Streamlit app
```
