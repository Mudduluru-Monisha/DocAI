import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DOCUMIND_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-3.5-flash-lite")
# Flash-Lite for both: bigger Flash models are limited to ~20 requests/day on free keys.
SMART_MODEL = os.getenv("GEMINI_SMART_MODEL", "gemini-3.5-flash-lite")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

RPM = int(os.getenv("GEMINI_RPM", "8"))

# Chunking (retrieval layer)
CHUNK_CHARS = 1000
CHUNK_OVERLAP = 150
TOP_K = 6

# Sectioning (analysis layer)
WINDOW_CHARS = 20000       # size of an analysis window when a document has no headings
MAX_SECTION_CHARS = 30000  # split headed sections larger than this
MIN_SECTION_CHARS = 2000   # merge headed sections smaller than this
MAX_ANALYSIS_CALLS = int(os.getenv("MAX_ANALYSIS_CALLS", "60"))

EVIDENCE_BUDGET = 26000    # max characters of evidence sent with a question
