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

FastAPI app with Jinja2 templates. Read-only except for `POST /api/bots/{name}/toggle` and `POST /api/bots/{name}/run`. All templates extend `dashboard/templates/base.html` — never create a standalone HTML page. New pages use `{% extends "base.html" %}` and fill `{% block title %}`, `{% block header_meta %}`, and `{% block content %}`.

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

## Git rules

- **Never run `git push`** — always leave pushing to the user
- **Always update README.md** when any of the following change:
  - A bot is added, removed, or renamed (`## Included bots` table)
  - An API endpoint is added or removed (`## Dashboard API` table)
  - An env var is added or removed (`## Configuration` table)
  - Setup or run steps change (`## Quick start`)
  - A new dependency is added that requires manual installation

## Security rules

- **Never read, print, or log the contents of `.env`** — treat it as off-limits in all circumstances
- `.env.example` must only contain placeholder values (e.g. `your-api-key`) — never real credentials
- If real credentials are spotted anywhere in committed files, flag them and replace with placeholders before doing anything else

## Coding standards

### Bots
- All config and secrets via `core.config` — never hardcode or use `os.getenv` directly in a bot
- Logger: `log = get_logger("<bot_name>")` at module level; use lazy loguru formatting (`log.info("x={}", x)`)
- Let exceptions propagate from `run()` — the scheduler wrapper handles them and marks the run as `failure`
- No `asyncio.run()` inside bots — the Telegram notifier already uses it; nesting will deadlock

### General Python
- `from __future__ import annotations` at the top of every module
- Catch specific exceptions; avoid bare `except:`
- No mutable default arguments
- Do not run `ruff format` manually — the pre-commit hook formats automatically on every commit

## Domain context

### Forex trader bot (`bots/forex_trader/`)
- Strategy: 9 EMA / 21 EMA crossover on EUR/USD 4H candles via OANDA API
- Safety rules that must not be removed or weakened:
  - One open position at a time — no stacking
  - Daily loss limit: halt trading if realised P&L ≤ −$25 in a calendar day
  - Flat market filter: skip if EMA spread < 0.0003
- Key constants: `STOP_LOSS_PIPS=15`, `TAKE_PROFIT_PIPS=30` (2:1 R:R)
- `OANDA_ENV=practice` for paper trading; only change to `live` deliberately

### Notification patterns
- Use `on: always` for trading/action bots — every run outcome matters
- Use `on: failure` for monitoring/data bots — only alert when something breaks
- Use `on: always` for digest bots — the output is the value

### Adding AI-powered bots
- Use the Anthropic SDK (`anthropic` package) for Claude API calls
- Add `ANTHROPIC_API_KEY` to `.env` and expose it via `core/config.py`
- Default to `claude-sonnet-4-6` unless the task is simple (use `claude-haiku-4-5-20251001`)
- AI calls are blocking — keep them inside `run()`, do not spawn threads

## Custom commands

| Command | Usage |
|---------|-------|
| `/review` | Review staged/unstaged changes or a specific file: `/review bots/my_bot/bot.py` |
| `/new-bot` | Scaffold a new bot: `/new-bot my_bot` |
