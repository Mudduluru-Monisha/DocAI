"""Headless UI test with Streamlit AppTest (fake Gemini + embeddings). Run: python tests/ui_test.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke_test as st_  # noqa: E402  (sets a temp data dir, fake embeddings)
from streamlit.testing.v1 import AppTest  # noqa: E402

from core import llm as llm_mod, pipeline, store  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def check(at, label):
    assert not at.exception, (label, [e.value for e in at.exception])
    print("ok:", label)


at = AppTest.from_file(APP, default_timeout=60)
at.run()
check(at, "empty state")
assert any("anything" in m.value and "Ask your documents" in m.value for m in at.markdown)

files = st_.make_files()
fake = st_.FakeLLM()
did = pipeline.ingest(files["story.txt"], "story.txt")
pipeline.analyze_document(did, fake)
pipeline.ingest(files["t.csv"], "t.csv")  # quick-index only doc

os.environ.pop("GEMINI_API_KEY", None)
at = AppTest.from_file(APP, default_timeout=60)
at.session_state["doc_id"] = did
at.run()
assert not at.chat_input[0].disabled
at.chat_input[0].set_value("What happens at the harbour?").run()
check(at, "chat without API key (passages only)")
assert [m.name for m in at.chat_message] == ["user", "assistant"]

os.environ["GEMINI_API_KEY"] = "fake-key"
llm_mod.LLM = st_.FakeLLM

at = AppTest.from_file(APP, default_timeout=60)
at.session_state["doc_id"] = did
at.run()
check(at, "document loaded")

for view in ("Overview", "Entities", "Sections"):
    at.session_state["view"] = view
    at.run()
    check(at, f"view {view}")

at.session_state["view"] = "Chat"
at.run()
at.chat_input[0].set_value("Who are all the characters?").run()
check(at, "chat answer")
roles = [m.name for m in at.chat_message]
assert roles == ["user", "assistant"], roles

at.session_state["doc_id"] = pipeline.doc_id_for(files["t.csv"])
at.run()
check(at, "quick-index doc")
assert any("quick index" in m.value.lower() for m in at.markdown)
os.environ.pop("GEMINI_API_KEY", None)
at = AppTest.from_file(APP, default_timeout=60)
at.session_state["doc_id"] = did
at.run()
check(at, "no-key state")
assert not at.chat_input[0].disabled
at.chat_input[0].set_value("Who is Alice?").run()
check(at, "search-only answer")
assert [m.name for m in at.chat_message] == ["user", "assistant"]
print("UI OK")
