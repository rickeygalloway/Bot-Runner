"""
core/database.py
SQLite-backed run history.
All reads and writes go through this module — no other module touches the DB directly.

Schema
------
runs
  id          INTEGER PRIMARY KEY AUTOINCREMENT
  bot_name    TEXT    NOT NULL
  start_time  TEXT    NOT NULL   -- ISO-8601 UTC
  end_time    TEXT               -- NULL while running
  status      TEXT    NOT NULL   -- "running" | "success" | "failure"
  message     TEXT               -- human-readable result or error
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from core.config import DATABASE_URL
from core.logger import framework_logger as log

# ── Helpers ──────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(DATABASE_URL, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ── Initialisation ────────────────────────────────────────────────────────────


def init_db() -> None:
    """Create tables if they don't exist. Called once at startup."""
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name   TEXT    NOT NULL,
                start_time TEXT    NOT NULL,
                end_time   TEXT,
                status     TEXT    NOT NULL DEFAULT 'running',
                message    TEXT
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_runs_bot ON runs (bot_name)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_runs_start ON runs (start_time)")

        con.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp          TEXT    NOT NULL,
                bot_name           TEXT    NOT NULL,
                model              TEXT    NOT NULL,
                input_tokens       INTEGER NOT NULL DEFAULT 0,
                output_tokens      INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens INTEGER NOT NULL DEFAULT 0
            )
        """)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_tokens_bot ON token_usage (bot_name)"
        )
    log.info("Database initialised at {}", DATABASE_URL)


# ── Write helpers ─────────────────────────────────────────────────────────────


def record_run_start(bot_name: str) -> int:
    """Insert a 'running' row and return its id."""
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO runs (bot_name, start_time, status) VALUES (?, ?, 'running')",
            (bot_name, _now_iso()),
        )
        run_id = cur.lastrowid
    log.debug("Run started: {} (id={})", bot_name, run_id)
    return run_id


def record_run_end(run_id: int, status: str, message: str = "") -> None:
    """Update an existing run row with end time, status, and result message."""
    if status not in ("success", "failure"):
        raise ValueError(f"status must be 'success' or 'failure', got {status!r}")
    with _conn() as con:
        con.execute(
            "UPDATE runs SET end_time=?, status=?, message=? WHERE id=?",
            (_now_iso(), status, message, run_id),
        )
    log.debug("Run finished: id={} status={}", run_id, status)


# ── Read helpers ──────────────────────────────────────────────────────────────


def get_recent_runs(bot_name: str, limit: int = 50) -> list[dict]:
    """Return the most recent *limit* runs for a bot, newest first."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT id, bot_name, start_time, end_time, status, message
            FROM runs
            WHERE bot_name = ?
            ORDER BY start_time DESC
            LIMIT ?
            """,
            (bot_name, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_last_run(bot_name: str) -> dict | None:
    """Return the single most recent completed run for a bot, or None."""
    with _conn() as con:
        row = con.execute(
            """
            SELECT id, bot_name, start_time, end_time, status, message
            FROM runs
            WHERE bot_name = ? AND status != 'running'
            ORDER BY start_time DESC
            LIMIT 1
            """,
            (bot_name,),
        ).fetchone()
    return dict(row) if row else None


def get_all_runs(limit: int = 200) -> list[dict]:
    """Return recent runs across all bots — used by the dashboard chart."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT id, bot_name, start_time, end_time, status, message
            FROM runs
            ORDER BY start_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_run_stats(bot_name: str) -> dict:
    """Return success/failure counts for a bot."""
    with _conn() as con:
        row = con.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'success') AS successes,
                COUNT(*) FILTER (WHERE status = 'failure') AS failures,
                COUNT(*) AS total
            FROM runs
            WHERE bot_name = ?
            """,
            (bot_name,),
        ).fetchone()
    return dict(row) if row else {"successes": 0, "failures": 0, "total": 0}


# ── Token usage ───────────────────────────────────────────────────────────────


def record_token_usage(
    *,
    bot_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> None:
    """Persist token usage from a single AI API call."""
    with _conn() as con:
        con.execute(
            """
            INSERT INTO token_usage
                (timestamp, bot_name, model, input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now_iso(),
                bot_name,
                model,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_write_tokens,
            ),
        )


def get_token_usage_summary() -> list[dict]:
    """Return lifetime token totals grouped by bot and model."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                bot_name,
                model,
                COUNT(*)                    AS run_count,
                SUM(input_tokens)           AS total_input,
                SUM(output_tokens)          AS total_output,
                SUM(cache_read_tokens)      AS total_cache_read,
                SUM(cache_write_tokens)     AS total_cache_write
            FROM token_usage
            GROUP BY bot_name, model
            ORDER BY bot_name, model
            """
        ).fetchall()
    return [dict(row) for row in rows]
