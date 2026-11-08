"""Project locations. Source lives in src/; runtime state lives in var/ (gitignored)."""

from pathlib import Path

# This file is src/fantasy_lineup/paths.py, so the project root is three levels up.
ROOT = Path(__file__).resolve().parents[2]

ENV_FILE = ROOT / ".env"

VAR_DIR = ROOT / "var"
SESSION_FILE = VAR_DIR / "session.json"  # website session cookies (mode 600)

CAPTURE_DIR = VAR_DIR / "capture"  # mitmproxy capture output
AUTH_CAPTURE = CAPTURE_DIR / "auth.json"

CACHE_DIR = VAR_DIR / "cache"
HISTORY_DIR = CACHE_DIR / "history"  # weekly snapshots used by the FLEX check
API_CACHE_DIR = CACHE_DIR / "api"  # public API responses
WEB_CACHE_DIR = CACHE_DIR / "web"  # website responses
