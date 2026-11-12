"""DocuMind AI — Streamlit interface."""
from __future__ import annotations

import inspect
import json
import os
import re

import streamlit as st
import streamlit.components.v1 as components

import ui
from core import answer, config, pipeline, retrieval, router, store
from core.extract import SUPPORTED
from core.llm import LLM, LLMError

st.set_page_config(page_title="DocuMind AI", page_icon="📖", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)

# model names can be edited live in the sidebar (Google retires names from time to time)
config.FAST_MODEL = (st.session_state.get("fast_model") or config.FAST_MODEL).strip()
config.SMART_MODEL = (st.session_state.get("smart_model") or config.SMART_MODEL).strip()


def _wide(fn) -> dict:
    return {"width": "stretch"} if "width" in inspect.signature(fn).parameters else {"use_container_width": True}


BTN, DL, DF = _wide(st.button), _wide(st.download_button), _wide(st.dataframe)

STYLE_CHOICES = {"Auto": "auto", "Short": "short", "Detailed": "detailed", "Bullets": "bullets",
                 "Summary": "summary", "Comparison": "comparison", "Step by step": "steps"}
STATUS_ICON = {"ready": ":material/check_circle:", "indexed": ":material/bolt:",
               "partial": ":material/pause_circle:", "analysing": ":material/hourglass_top:"}
AV_USER, AV_BOT = ":material/person:", ":material/auto_stories:"


# ------------------------------------------------------------------ helpers
def get_llm():
    key = st.session_state.get("api_key") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return None
    if st.session_state.get("_llm_key") != key:
        st.session_state["_llm"] = LLM(key)
        st.session_state["_llm_key"] = key
    return st.session_state["_llm"]


def queue(job: dict) -> None:
    st.session_state["job"] = job


def queue_upload(up, deep_key: str) -> None:
    if up is not None:
        queue({"kind": "ingest", "name": up.name, "data": up.getvalue(), "deep": st.session_state.get(deep_key, True)})


def ask(q: str) -> None:
    st.session_state["pending_q"] = q


def select_doc(doc_id: str) -> None:
    st.session_state["doc_id"] = doc_id


def upload_block(prefix: str) -> None:
    up = st.file_uploader("Document", type=[e.lstrip(".") for e in SUPPORTED], key=f"{prefix}_up",
                          label_visibility="collapsed")
    st.toggle("Deep analysis", value=True, key=f"{prefix}_deep",
              help="Builds summaries, entities and relationships so whole-document questions work. "
                   "Uses Gemini calls, so big files take a few minutes on the free tier.")
    st.button("Process document", type="primary", disabled=up is None, key=f"{prefix}_go",
              on_click=queue_upload, args=(up, f"{prefix}_deep"), **BTN)


def run_job(job: dict) -> None:
    llm = get_llm()
    deep = job["kind"] == "analyze" or (job["deep"] and llm is not None)
    stages = ui.stages_for(job["kind"], deep)
    slot = st.empty()

    def scaled(lo, hi):
        def cb(f, m):
            slot.markdown(ui.job_html(stages, lo + (hi - lo) * f, m), unsafe_allow_html=True)
        return cb

    try:
        slot.markdown(ui.job_html(stages, 0.0, "Starting…"), unsafe_allow_html=True)
        if job["kind"] == "ingest":
            doc_id = pipeline.ingest(job["data"], job["name"], scaled(0, 0.35 if deep else 1.0))
            st.session_state["doc_id"] = doc_id
            if deep and store.get_document(doc_id)["status"] != "ready":
                pipeline.analyze_document(doc_id, llm, scaled(0.35, 1.0))
        else:
            if llm is None:
                raise LLMError("Add a Gemini API key in the sidebar to run the analysis.")
            pipeline.analyze_document(job["doc_id"], llm, scaled(0, 1.0))
        slot.empty()
        st.toast("Ready, ask away")
        if job["kind"] == "ingest" and job["deep"] and llm is None:
            st.info("Indexed without deep analysis because no Gemini key is set. Add one, then run the analysis.")
    except Exception as e:  # noqa: BLE001
        slot.empty()
        st.error(str(e))


def render_sources(sources: list[dict], text: str, show_all: bool = False) -> None:
    cited = set(range(1, len(sources) + 1)) if show_all else set()
    for grp in re.findall(r"\[([\d,\s]+)\]", text):
        cited |= {int(n) for n in grp.split(",") if n.strip().isdigit()}

    def cards(items, limit):
        out = ""
        for i, s in items:
            pg = f'<span class="pill">page {s["page"]}</span>' if s.get("page") else ""
            out += (f'<div class="src"><div class="srchead"><span class="cite">{i}</span>'
                    f'<b>{ui.esc(s["title"])}</b>{pg}</div>'
                    f'<div class="passage">{ui.esc(s["text"][:limit])}</div></div>')
        return out

    shown = [(i, s) for i, s in enumerate(sources, 1) if i in cited]
    rest = [(i, s) for i, s in enumerate(sources, 1) if i not in cited]
    if shown:
        with st.expander(f"Sources ({len(shown)})"):
            st.markdown(cards(shown, 1800), unsafe_allow_html=True)
    if rest:
        with st.expander(f"Other context searched ({len(rest)})"):
            st.markdown(cards(rest, 600), unsafe_allow_html=True)


def render_message(m: dict) -> None:
    with st.chat_message(m["role"], avatar=AV_USER if m["role"] == "user" else AV_BOT):
        if m["role"] == "user":
            st.markdown(m["content"])
            return
        st.markdown(ui.cite_html(m["content"]), unsafe_allow_html=True)
        if m.get("trail"):
            st.markdown(f'<div class="trail">{ui.esc(m["trail"])}</div>', unsafe_allow_html=True)
        render_sources(m.get("sources", []), m["content"], show_all=m.get("show_all", False))


def describe_trail(evidence: list[dict]) -> str:
    kinds: dict[str, int] = {}
    for e in evidence:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    names = {"summary": "the document summary", "section": "section summaries", "entity": "the entity list",
             "relation": "relationships"}
    parts = [names[k] for k in ("summary", "section", "entity", "relation") if k in kinds]
    if "passage" in kinds:
        parts.append(f"{kinds['passage']} passages")
    if not parts:
        return "Looked at the document"
    return "Looked at " + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0])


def _g(x) -> str:
    """Graph text comes from the uploaded document, so strip angle brackets before it reaches pyvis' HTML."""
    return str(x).replace("<", "‹").replace(">", "›")


GRAPH_OPTIONS = json.dumps({
    "nodes": {"shape": "dot", "borderWidth": 2, "font": {"color": "#EAF0FF", "size": 15, "strokeWidth": 4, "strokeColor": "#0F1526"}},
    "edges": {"width": 1.2, "smooth": {"type": "continuous"}, "arrows": {"to": {"scaleFactor": 0.6}},
              "font": {"color": "#93A0BE", "size": 11, "strokeWidth": 3, "strokeColor": "#0F1526", "align": "middle"}},
    "physics": {"barnesHut": {"gravitationalConstant": -9000, "springLength": 160, "damping": 0.35},
                "stabilization": {"iterations": 150}},
    "interaction": {"hover": True, "tooltipDelay": 120}})


def render_graph(entities, relations, max_nodes, types) -> None:
    from pyvis.network import Network

    ents = [e for e in entities if not types or e["type"] in types][:max_nodes]
    names = {e["name"] for e in ents}
    net = Network(height="600px", width="100%", bgcolor="#0F1526", font_color="#EAF0FF", cdn_resources="remote")
    net.set_options(GRAPH_OPTIONS)
    for e in ents:
        net.add_node(_g(e["name"]), label=_g(e["name"]), size=12 + min(e["mentions"], 20) * 2,
                     color=ui.type_color(e["type"]), title=ui.esc(f"{e['name']} ({e['type']})\n{e['description'][:220]}"))
    for r in relations:
        if r["source"] in names and r["target"] in names:
            net.add_edge(_g(r["source"]), _g(r["target"]), label=_g(r["relation"][:28]),
                         title=ui.esc(r.get("evidence", "")), color="#4B5A7D", arrows="to")
    page = net.generate_html()
    if hasattr(st, "iframe"):
        st.iframe(page, height=620)
    else:
        components.html(page, height=620)


# ------------------------------------------------------------------ jobs run before anything else is drawn
top = st.container()
job = st.session_state.pop("job", None)
if job:
    with top:
        run_job(job)

# ------------------------------------------------------------------ sidebar
docs = store.list_documents()
with st.sidebar:
    st.markdown(ui.brand(), unsafe_allow_html=True)
    env_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if env_key:
        st.markdown(ui.pill("Gemini connected", "good"), unsafe_allow_html=True)
    else:
        st.text_input("Gemini API key", type="password", key="api_key",
                      help="Free key from aistudio.google.com/apikey. Kept in this session only.")
        if st.session_state.get("api_key"):
            st.markdown(ui.pill("Gemini connected", "good"), unsafe_allow_html=True)
    if docs:
        ids = [d["doc_id"] for d in docs]
        if st.session_state.get("doc_id") not in ids:
            st.session_state["doc_id"] = ids[0]
        st.markdown('<div class="sidelabel">Library</div>', unsafe_allow_html=True)
        for d in docs:
            sel = d["doc_id"] == st.session_state["doc_id"]
            st.button(d["name"], key=f"{'libsel' if sel else 'lib'}-{d['doc_id']}", icon=STATUS_ICON.get(d["status"], ":material/description:"),
                      on_click=select_doc, args=(d["doc_id"],), **BTN)
        with st.expander("Add a document"):
            upload_block("side")
        st.markdown('<div class="sidelabel">Answers</div>', unsafe_allow_html=True)
        st.selectbox("Answer style", list(STYLE_CHOICES), key="style_choice", label_visibility="collapsed")
    with st.expander("Models"):
        st.text_input("Fast model (analysis, routing)", value=config.FAST_MODEL, key="fast_model")
        st.text_input("Answer model", value=config.SMART_MODEL, key="smart_model")
        st.caption("If Google retires a model you'll see a 404 error. Paste the replacement name here.")
    if docs and st.button("Delete this document", icon=":material/delete:", **BTN):
        store.delete_document(st.session_state["doc_id"])
        st.session_state.pop("doc_id", None)
        st.rerun()

# ------------------------------------------------------------------ landing (no documents yet)
if not docs:
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown('<div class="hero"><div class="eyebrow">Document intelligence</div>'
                    '<h1>Ask your documents <span class="hl">anything</span>.</h1>'
                    '<p class="lead">Drop in a novel, a paper, a report, a resume or a spreadsheet. DocuMind reads the '
                    'whole thing before you ask, then answers with page references you can check.</p></div>',
                    unsafe_allow_html=True)
        upload_block("hero")
        st.markdown('<div class="fmts">' + "".join(f"<span>{e.lstrip('.').upper()}</span>" for e in SUPPORTED) + "</div>",
                    unsafe_allow_html=True)
    with right:
        st.markdown(ui.hero_preview(), unsafe_allow_html=True)
    st.markdown(ui.feature_cards(), unsafe_allow_html=True)
    st.stop()

# ------------------------------------------------------------------ document header
doc_id = st.session_state["doc_id"]
doc = store.get_document(doc_id)
ov = doc["overview"]
ready = doc["status"] == "ready"
sections = store.get_sections(doc_id)
entities = store.get_entities(doc_id) if ready else []
relations = store.get_relations(doc_id) if ready else []
llm = get_llm()

unit = "slides" if doc["fmt"] == "PowerPoint" else "pages"
pills = ui.pill(doc["fmt"])
if doc["n_pages"]:
    pills += ui.pill(f"{doc['n_pages']} {unit}")
pills += ui.pill(f"{doc['n_sections']} sections")
if ready:
    pills += ui.pill("Fully analysed", "good")
elif doc["status"] == "partial":
    pills += ui.pill("Analysis paused", "warn")
else:
    pills += ui.pill("Quick index only", "warn")
st.markdown(ui.dochead(ov.get("document_type") or "Document", ov.get("title") or doc["name"], pills),
            unsafe_allow_html=True)
for w in doc["warnings"]:
    st.warning(w)
if not ready:
    msg = (f"Analysis was paused: {doc['error']}" if doc["status"] == "partial" and doc["error"] else
           "Quick index only. Specific questions work, but whole-document questions will be thin. "
           "Run the deep analysis to unlock summaries, entities and relationships.")
    c1, c2 = st.columns([4, 1.1], vertical_alignment="center")
    c1.markdown(ui.banner(msg), unsafe_allow_html=True)
    c2.button("Resume analysis" if doc["status"] == "partial" else "Run deep analysis", type="primary",
              disabled=llm is None, on_click=queue, args=({"kind": "analyze", "doc_id": doc_id},), **BTN)

VIEWS = ["Chat", "Overview", "Entities", "Sections"]
if hasattr(st, "segmented_control"):
    view = st.segmented_control("View", VIEWS, default="Chat", key="view", label_visibility="collapsed") or "Chat"
else:
    view = st.radio("View", VIEWS, horizontal=True, key="view", label_visibility="collapsed")

# ---------------------------------------------------------------- chat
if view == "Chat":
    msgs = st.session_state.setdefault("chats", {}).setdefault(doc_id, [])
    for m in msgs:
        render_message(m)
    if not msgs:
        st.markdown(f'<div class="emptychat"><h3>What would you like to know?</h3>'
                    f'<p>Ask anything about {ui.esc(ov.get("title") or doc["name"])}.</p></div>', unsafe_allow_html=True)
        topic = (ov.get("main_topics") or [None])[0]
        ideas = ([("Summarise the whole document", ":material/summarize:"),
                  ("Who or what are the key entities?", ":material/hub:"),
                  (f"Explain {topic}" if topic else "What are the main topics?", ":material/lightbulb:"),
                  ("How does it conclude?", ":material/flag:")]
                 if ready else [("What is this document about?", ":material/help:"),
                                ("What are the main points?", ":material/list:")])
        cols = st.columns(len(ideas))
        for n, (col, (q, ic)) in enumerate(zip(cols, ideas)):
            col.button(q, icon=ic, on_click=ask, args=(q,), key=f"sugg-{n}", **BTN)
    if llm is None:
        st.markdown(ui.banner("No Gemini key yet: questions return the closest passages instead of a written answer. "
                              "Add a key in the sidebar for full answers."), unsafe_allow_html=True)
    prompt = st.chat_input("Ask about this document")
    prompt = prompt or st.session_state.pop("pending_q", None)
    if prompt:
        history = list(msgs)
        msgs.append({"role": "user", "content": prompt})
        render_message(msgs[-1])
        with st.chat_message("assistant", avatar=AV_BOT):
            try:
                if llm is None:  # search-only mode: local embeddings, no Gemini
                    evidence, notes = retrieval.gather(doc_id, router.heuristic_route(prompt))
                    refs = " ".join(f"[{i}]" for i in range(1, len(evidence) + 1))
                    text = "No Gemini key is set, so I can't write an answer. These are the closest parts of the document: " + refs
                    trail = describe_trail(evidence)
                    st.markdown(ui.cite_html(text), unsafe_allow_html=True)
                    st.markdown(f'<div class="trail">{ui.esc(trail)}</div>', unsafe_allow_html=True)
                    render_sources(evidence, text, show_all=True)
                    msgs.append({"role": "assistant", "content": text, "trail": trail, "sources": evidence,
                                 "show_all": True})
                else:
                    with st.status("Working out where to look…") as s:
                        types = sorted({e["type"] for e in entities})
                        r = router.route(llm, prompt, doc, sections, types, history, ready)
                        s.update(label="Searching the document…")
                        evidence, notes = retrieval.gather(doc_id, r)
                        trail = describe_trail(evidence)
                        s.update(label=trail, state="complete", expanded=False)
                    choice = STYLE_CHOICES.get(st.session_state.get("style_choice", "Auto"), "auto")
                    style = r.style if choice == "auto" else choice
                    slot = st.empty()
                    with slot.container():
                        text = st.write_stream(answer.stream(llm, r.standalone or prompt, evidence, notes, style, history))
                    slot.markdown(ui.cite_html(text), unsafe_allow_html=True)
                    st.markdown(f'<div class="trail">{ui.esc(trail)}</div>', unsafe_allow_html=True)
                    render_sources(evidence, text)
                    msgs.append({"role": "assistant", "content": text, "trail": trail, "sources": evidence})
            except Exception as e:  # noqa: BLE001
                st.error(str(e))
                msgs.pop()

# ---------------------------------------------------------------- overview
elif view == "Overview":
    if not ready:
        st.info("Run the deep analysis to see the summary, topics and key facts.")
    else:
        st.markdown(f'<div class="sumcard"><div class="eyebrow">Summary</div><div class="reading">'
                    f'{ui.para(ov.get("overall_summary"))}</div></div>', unsafe_allow_html=True)
        st.markdown(ui.stats([("Sections", doc["n_sections"]), ("Passages", doc["n_chunks"]),
                              ("Entities", len(entities)), ("Relationships", len(relations))]), unsafe_allow_html=True)
        left, right = st.columns([1.25, 1], gap="large")
        with left:
            if ov.get("key_facts"):
                st.markdown('<div class="eyebrow" style="margin:.8rem 0 .6rem">Key facts</div>', unsafe_allow_html=True)
                st.markdown(ui.facts(ov["key_facts"]), unsafe_allow_html=True)
        with right:
            if ov.get("main_topics"):
                st.markdown('<div class="eyebrow" style="margin:.8rem 0 .6rem">Main topics</div>', unsafe_allow_html=True)
                st.markdown(ui.chips(ov["main_topics"]), unsafe_allow_html=True)
            if ov.get("purpose"):
                st.markdown(ui.callout("What it is for", ov["purpose"]), unsafe_allow_html=True)
            if ov.get("conclusion"):
                st.markdown(ui.callout("How it concludes", ov["conclusion"]), unsafe_allow_html=True)
        export = {"document": {k: doc[k] for k in ("name", "fmt", "n_pages", "n_sections")}, "overview": ov,
                  "sections": sections, "entities": entities, "relationships": relations}
        st.download_button("Download analysis (JSON)", json.dumps(export, indent=2, default=str),
                           file_name=f"{doc['name']}.analysis.json", mime="application/json", icon=":material/download:")

# ---------------------------------------------------------------- entities
elif view == "Entities":
    if not entities:
        st.info("Entities and relationships appear after the deep analysis finishes.")
    else:
        all_types = sorted({e["type"] for e in entities})
        c1, c2 = st.columns([2, 1])
        types = c1.multiselect("Filter by type", all_types, default=[])
        limit = c2.slider("Most-mentioned shown", 5, min(80, max(6, len(entities))), min(30, len(entities)))
        st.markdown("".join(f'<span class="chip"><i style="background:{ui.type_color(t)}"></i>{ui.esc(t)}</span>'
                            for t in (types or all_types)), unsafe_allow_html=True)
        try:
            render_graph(entities, relations, limit, types)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Graph unavailable ({e}). The cards below still work.")
        shown = [e for e in entities if not types or e["type"] in types]
        st.markdown('<div class="eyebrow" style="margin-top:1rem">Top entities</div>', unsafe_allow_html=True)
        st.markdown(ui.entity_cards(shown[:12]), unsafe_allow_html=True)
        with st.expander(f"Full table ({len(shown)})"):
            st.dataframe([{"Name": e["name"], "Type": e["type"], "Sections": e["mentions"],
                           "Description": e["description"], "Also called": ", ".join(e["aliases"])} for e in shown],
                         hide_index=True, **DF)

# ---------------------------------------------------------------- sections
else:
    for s in sections:
        pg = (f"  ·  pages {s['page_start']}–{s['page_end']}" if s["page_start"] and s["page_end"] != s["page_start"]
              else f"  ·  page {s['page_start']}" if s["page_start"] else "")
        with st.expander(f"{s['title']}{pg}"):
            if s["summary"]:
                st.markdown(f'<div class="reading">{ui.para(s["summary"])}</div>', unsafe_allow_html=True)
                if s["key_points"]:
                    st.markdown(ui.chips(s["key_points"][:6]), unsafe_allow_html=True)
            else:
                st.caption("Not analysed yet.")
