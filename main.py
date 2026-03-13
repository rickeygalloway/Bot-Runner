"""
main.py
Single entry point — starts the APScheduler bot runner and FastAPI dashboard together.

Usage:
    python main.py

Both run in the same process:
  - Scheduler runs in a background thread (BackgroundScheduler)
  - Uvicorn serves the dashboard on the main thread
"""

from __future__ import annotations

import signal
import sys

import uvicorn

from core.scheduler import start as start_scheduler, stop as stop_scheduler
from core.logger import framework_logger as log
import core.config as cfg


def _handle_shutdown(signum, frame):
    log.info("Shutdown signal received — stopping scheduler...")
    stop_scheduler()
    sys.exit(0)


def main():
    # Register graceful shutdown on Ctrl+C / SIGTERM
    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    log.info("=" * 60)
    log.info("BotRunner starting up")
    log.info("=" * 60)

    # Start APScheduler + bot discovery + startup notifications
    start_scheduler()

    log.info(
        "Dashboard available at http://{}:{}",
        cfg.DASHBOARD_HOST,
        cfg.DASHBOARD_PORT,
    )

    # Import here so scheduler is already running when FastAPI starts
    from dashboard.app import app

    try:
        uvicorn.run(
            app,
            host=cfg.DASHBOARD_HOST,
            port=cfg.DASHBOARD_PORT,
            log_level="warning",  # suppress uvicorn noise; loguru handles logging
        )
    finally:
        stop_scheduler()


if __name__ == "__main__":
    main()
