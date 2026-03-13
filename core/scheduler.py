"""
core/scheduler.py
APScheduler-based bot runner.

Responsibilities
────────────────
- Auto-discover every bot in bots/<name>/bot.py + config.yaml
- Register each enabled bot on its cron schedule
- Wrap each run() call: DB record, exception handling, notification, status.json
- Expose start() / stop() for main.py
- Send the startup report notification
"""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import core.config as cfg
from core.database import init_db, record_run_start, record_run_end
from core.logger import framework_logger as log, get_logger
from core.notifier import notify

# ── Internal state ────────────────────────────────────────────────────────────
_scheduler = BackgroundScheduler(timezone="UTC")
_registered_bots: list[dict[str, Any]] = []  # populated by _discover_bots()


# ── Bot discovery ─────────────────────────────────────────────────────────────


def _load_bot_module(bot_dir: Path):
    """Dynamically import bots/<name>/bot.py and return the module."""
    bot_file = bot_dir / "bot.py"
    spec = importlib.util.spec_from_file_location(f"bots.{bot_dir.name}.bot", bot_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_bot_config(bot_dir: Path) -> dict:
    config_file = bot_dir / "config.yaml"
    with open(config_file) as f:
        return yaml.safe_load(f)


def _discover_bots() -> list[dict]:
    """
    Walk bots/ directory, load each bot module + config.
    Returns a list of bot descriptors (dict with keys: name, module, config, dir).
    """
    bots = []
    for bot_dir in sorted(cfg.BOTS_DIR.iterdir()):
        if not bot_dir.is_dir():
            continue
        bot_py = bot_dir / "bot.py"
        config_yml = bot_dir / "config.yaml"

        if not bot_py.exists() or not config_yml.exists():
            log.warning("Skipping {}: missing bot.py or config.yaml", bot_dir.name)
            continue

        try:
            module = _load_bot_module(bot_dir)
            bot_config = _load_bot_config(bot_dir)

            if not hasattr(module, "run"):
                raise AttributeError("bot.py must expose a run() function")

            bots.append(
                {
                    "name": bot_dir.name,
                    "module": module,
                    "config": bot_config,
                    "dir": bot_dir,
                    "error": None,
                }
            )
            log.info("Discovered bot: {}", bot_dir.name)
        except Exception as exc:
            log.error("Failed to load bot '{}': {}", bot_dir.name, exc)
            bots.append(
                {
                    "name": bot_dir.name,
                    "module": None,
                    "config": {},
                    "dir": bot_dir,
                    "error": str(exc),
                }
            )

    return bots


# ── Job wrapper ───────────────────────────────────────────────────────────────


def _make_job(bot: dict):
    """Return a zero-argument callable for APScheduler."""

    def job():
        bot_name = bot["name"]
        bot_config = bot["config"]
        bot_log = get_logger(bot_name)
        run_id = record_run_start(bot_name)
        status = "failure"
        message = ""

        bot_log.info("Run started (id={})", run_id)
        try:
            result = bot["module"].run()
            status = "success"
            message = str(result) if result is not None else "completed successfully"
            bot_log.info("Run succeeded: {}", message)
        except Exception:
            message = traceback.format_exc()
            bot_log.error("Run failed:\n{}", message)
        finally:
            record_run_end(run_id, status, message)
            _write_status(bot_name, status, message)
            notify(
                bot_name=bot_config.get("name", bot_name),
                status=status,
                message=message,
                notify_config=bot_config.get("notify", {}),
            )

    job.__name__ = f"bot_{bot['name']}"
    return job


# ── status.json writer ────────────────────────────────────────────────────────


def _write_status(bot_name: str, status: str, message: str) -> None:
    """Append/update this bot's entry in status.json."""
    try:
        if cfg.STATUS_FILE.exists():
            with open(cfg.STATUS_FILE) as f:
                data = json.load(f)
        else:
            data = {}

        data[bot_name] = {
            "status": status,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with open(cfg.STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        log.error("Failed to write status.json: {}", exc)


# ── Startup report ────────────────────────────────────────────────────────────


def _send_startup_report(bots: list[dict]) -> None:
    """Send one notification per bot summarising load status."""
    for bot in bots:
        if bot["error"]:
            message = f"❌ FAILED TO REGISTER\n" f"Error: {bot['error']}"
            status = "failure"
        else:
            bc = bot["config"]
            enabled = bc.get("enabled", True)
            message = (
                f"{'✅' if enabled else '⏸️'} Bot registered\n"
                f"Schedule : {bc.get('schedule', 'n/a')}\n"
                f"Enabled  : {enabled}\n"
                f"Notifier : {bc.get('notify', {}).get('provider', 'none')} "
                f"on {bc.get('notify', {}).get('on', 'n/a')}\n"
                f"Desc     : {bc.get('description', '')}"
            )
            status = "success"

        notify(
            bot_name=bot["config"].get("name", bot["name"])
            if bot["config"]
            else bot["name"],
            status=status,
            message=message,
            notify_config=bot["config"].get("notify", {}) if bot["config"] else {},
        )


# ── Public API ────────────────────────────────────────────────────────────────


def get_registered_bots() -> list[dict]:
    """Return the list of discovered bot descriptors (used by dashboard)."""
    return _registered_bots


def start() -> None:
    """Discover bots, register schedules, send startup report, start scheduler."""
    init_db()

    global _registered_bots
    _registered_bots = _discover_bots()

    for bot in _registered_bots:
        if bot["error"]:
            continue  # already logged
        if not bot["config"].get("enabled", True):
            log.info("Bot '{}' is disabled — skipping registration", bot["name"])
            continue

        schedule = bot["config"].get("schedule")
        if not schedule:
            log.warning("Bot '{}' has no schedule — skipping", bot["name"])
            continue

        try:
            _scheduler.add_job(
                _make_job(bot),
                trigger=CronTrigger.from_crontab(schedule, timezone="UTC"),
                id=bot["name"],
                replace_existing=True,
                misfire_grace_time=60,
            )
            log.info("Registered '{}' on schedule '{}'", bot["name"], schedule)
        except Exception as exc:
            log.error("Failed to schedule '{}': {}", bot["name"], exc)
            bot["error"] = str(exc)

    _send_startup_report(_registered_bots)
    _scheduler.start()
    log.info("Scheduler started with {} job(s)", len(_scheduler.get_jobs()))


def stop() -> None:
    """Gracefully shut down the scheduler."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler stopped")
