"""
core/config.py
Loads the shared .env file and exposes typed settings to the rest of the framework.
All secrets and environment-specific values live here — never hardcoded elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve the repo root (two levels up from this file: core/ -> my-bots/)
ROOT_DIR = Path(__file__).resolve().parent.parent

# Load .env from repo root; override=False keeps real env vars if already set
load_dotenv(ROOT_DIR / ".env", override=False)


def _require(key: str) -> str:
    """Return env var or raise a clear error at startup."""
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is missing. "
            f"Add it to {ROOT_DIR / '.env'}"
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ── Paths ────────────────────────────────────────────────────────────────────
BOTS_DIR = ROOT_DIR / "bots"
LOGS_DIR = ROOT_DIR / "logs"
DATA_DIR = ROOT_DIR / "data"
STATUS_FILE = ROOT_DIR / "status.json"

# Ensure directories exist at import time
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = str(DATA_DIR / "botrunner.db")

# ── Dashboard ────────────────────────────────────────────────────────────────
DASHBOARD_HOST = _optional("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(_optional("DASHBOARD_PORT", "8000"))

# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = _optional("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _optional("TELEGRAM_CHAT_ID")

# ── Email (Gmail SMTP) ────────────────────────────────────────────────────────
EMAIL_SENDER = _optional("EMAIL_SENDER")
EMAIL_PASSWORD = _optional("EMAIL_PASSWORD")  # Gmail App Password
EMAIL_RECEIVER = _optional("EMAIL_RECEIVER")
SMTP_HOST = _optional("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_optional("SMTP_PORT", "587"))

# ── OANDA (forex_trader bot) ──────────────────────────────────────────────────
OANDA_API_KEY = _optional("OANDA_API_KEY")
OANDA_ACCOUNT_ID = _optional("OANDA_ACCOUNT_ID")
OANDA_ENV = _optional("OANDA_ENV", "practice")  # "practice" | "live"

# ── Anthropic (AI-powered bots) ───────────────────────────────────────────────
ANTHROPIC_API_KEY = _optional("ANTHROPIC_API_KEY")
