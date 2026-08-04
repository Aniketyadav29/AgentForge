"""Runtime paths that work both locally and in Vercel Functions."""

import os
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
IS_VERCEL = os.environ.get("VERCEL") == "1"
DATA_ROOT = Path(os.environ.get("AGENTFORGE_DATA_DIR", "")) if os.environ.get("AGENTFORGE_DATA_DIR") else (
    Path(tempfile.gettempdir()) / "agentforge" if IS_VERCEL else PROJECT_ROOT
)
UPLOAD_DIR = DATA_ROOT / "uploads"
VECTOR_DIR = DATA_ROOT / "chroma_db"
DB_PATH = DATA_ROOT / "agentforge.db"


def ensure_runtime_dirs() -> None:
    """Create the writable directories used for transient application data."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)

