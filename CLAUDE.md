# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the application

```bash
# Install dependencies (Python 3.11+)
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env

# Run the full stack (scheduler + dashboard)
python main.py
```

The dashboard is available at `http://127.0.0.1:8000` by default.

## Architecture overview

BotRunner is a single-process bot scheduler with a web dashboard. Two subsystems share the same process:

- **APScheduler** (`BackgroundScheduler`) runs bots on cron schedules in background threads
- **FastAPI + Uvicorn** serves the dashboard on the main thread

### Core modules (`core/`)

| Module | Responsibility |
|--------|---------------|
| `config.py` | Single source of truth for all settings — reads `.env`, exposes typed constants. All secrets live here; bots import `core.config` directly. |
| `scheduler.py` | Discovers bots, registers APScheduler jobs, wraps each `run()` call (DB record → execute → DB update → status.json → notify). Public API: `start()`, `stop()`, `get_registered_bots()`. |
| `database.py` | SQLite run history via raw `sqlite3`. Schema: single `runs` table. No ORM. |
| `logger.py` | Loguru factory — `get_logger(bot_name)` returns a logger bound to a per-bot rotating file sink at `logs/<bot_name>.log`. `framework_logger` is used by core/ modules. |
| `notifier.py` | Notification router — reads each bot's `notify:` config block and dispatches to Telegram or Gmail SMTP. Never called by bots directly. |

### Bot contract

Every bot is a directory under `bots/<name>/` containing exactly:
- `bot.py` — must expose a `run() -> str | None` function; return value is stored as the run message
- `config.yaml` — schema:
  ```yaml
  name: Display Name
  description: What it does
  schedule: "0 */4 * * *"   # standard crontab (UTC)
  enabled: true
  notify:
    provider: telegram   # or "email"
    on: always           # "success" | "failure" | "always"
  ```

The scheduler auto-discovers bots at startup — no registration code needed. Bots that raise an exception are marked as `failure`; returning a string marks them `success`.

### Dashboard (`dashboard/`)

FastAPI app with Jinja2 templates. Read-only except for `POST /api/bots/{name}/toggle`, which writes back to the bot's `config.yaml` and live-updates the scheduler. The dashboard reads bot state from three sources: in-memory scheduler state, SQLite run history, and `status.json` (last run outcome, written by the scheduler after each run).

### Data flow

```
startup → _discover_bots() → APScheduler registers jobs
                                      ↓
cron fires → _make_job() wrapper → bot.run()
                                      ↓
                          record_run_end() → _write_status() → notify()
```

### Generated files (not committed)

- `data/botrunner.db` — SQLite database
- `status.json` — last run outcome per bot
- `logs/<bot_name>.log` — per-bot rotating logs
