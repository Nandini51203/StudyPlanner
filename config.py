import os
from dotenv import load_dotenv
load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
SECRET = os.getenv("SECRET_KEY", "dev")
DB = os.path.join(BASE, "instance", "study.db")

# Upload limits
MAX_MB = 20                # Maximum file size in MB
MAX_PDF_PAGES = 100        # Maximum PDF page count
ALLOWED = {"pdf", "txt"}   # Supported file formats

# Chunking settings for hierarchical summarization
CHUNK_SIZE = 4000           # Target characters per chunk
CHUNK_OVERLAP = 200         # Overlap between chunks to preserve context
MAX_CHUNKS = 25             # Safety limit to avoid excessive API calls

DEMO = not GOOGLE_API_KEY   # no key -> clearly-labelled demo data
