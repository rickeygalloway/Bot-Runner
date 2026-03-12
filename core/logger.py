"""
core/logger.py
Loguru-based logging factory.
Each bot gets its own rotating log file at logs/<bot_name>.log,
plus a shared sink to stderr for dev visibility.
"""

from __future__ import annotations

import sys
from pathlib import Path
from loguru import logger as _root_logger

from core.config import LOGS_DIR

# Remove loguru's default stderr sink; we'll add our own with formatting
_root_logger.remove()

# ── Shared stderr sink (all bots, INFO+) ────────────────────────────────────
_root_logger.add(
    sys.stderr,
    level="INFO",
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[bot]}</cyan> | "
        "{message}"
    ),
    colorize=True,
)

# Track which per-bot file sinks we've already registered
_registered: set[str] = set()


def get_logger(bot_name: str):
    """
    Return a loguru logger bound to *bot_name*.

    First call for a given bot_name also registers a rotating file sink at
    logs/<bot_name>.log (10 MB max, 7-day retention, compressed).
    """
    if bot_name not in _registered:
        log_path: Path = LOGS_DIR / f"{bot_name}.log"
        _root_logger.add(
            str(log_path),
            level="DEBUG",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
                "{extra[bot]} | {message}"
            ),
            rotation="10 MB",
            retention="7 days",
            compression="zip",
            filter=lambda record, name=bot_name: record["extra"].get("bot") == name,
            enqueue=True,   # thread-safe for APScheduler workers
        )
        _registered.add(bot_name)

    return _root_logger.bind(bot=bot_name)


# Convenience: a framework-level logger for core/ modules themselves
framework_logger = _root_logger.bind(bot="framework")
