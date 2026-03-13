# GitHub Copilot Instructions

BotRunner is a Python 3.11+ bot scheduler with a FastAPI dashboard. Bots run on cron schedules via APScheduler; all share a common framework in `core/`.

## Bot contract

Every bot lives in `bots/<name>/` and must have:
- `bot.py` — exposes `run() -> str | None`. Return value = run message. Raise to mark failure.
- `config.yaml` — requires `name`, `description`, `schedule` (UTC crontab), `enabled`, `notify`

Never register bots manually — the scheduler auto-discovers them at startup.

## Core framework

| Module | Purpose |
|--------|---------|
| `core/config.py` | All secrets and settings — import this, never use `os.getenv` directly |
| `core/logger.py` | `get_logger("bot_name")` — use at module level in every bot |
| `core/database.py` | SQLite run history — `record_run_start`, `record_run_end`, `get_recent_runs` |
| `core/notifier.py` | Called by scheduler after each run — bots never call this directly |
| `core/health.py` | Env var status checks — used by `/setup` dashboard route |

## Coding rules

- `from __future__ import annotations` at the top of every module
- All config/secrets via `core.config` — never hardcode values
- Logger: `log = get_logger("<bot_name>")` at module level; lazy formatting: `log.info("x={}", x)`
- Let exceptions propagate from `run()` — scheduler handles them
- No `asyncio.run()` in bots — Telegram notifier already owns the event loop
- Catch specific exceptions; no bare `except:`

## Security

- Never read, print, or log `.env` contents
- `.env.example` must only contain placeholder values
- Pre-commit hooks (gitleaks) block credential commits — do not suggest bypassing them

## Domain: Forex trader (`bots/forex_trader/`)

- Strategy: 9/21 EMA crossover on EUR/USD 4H candles via OANDA API
- **Safety rules — do not remove or weaken:**
  - One open position at a time
  - Daily loss limit: halt if realised P&L ≤ −$25
  - Flat market filter: skip if EMA spread < 0.0003
- `OANDA_ENV=practice` for paper trading; `live` only when deliberate

## Domain: AI-powered bots

- Use the `anthropic` SDK for Claude API calls
- Expose `ANTHROPIC_API_KEY` via `core/config.py`
- Default model: `claude-sonnet-4-6`; use `claude-haiku-4-5-20251001` for lightweight tasks
- AI calls are blocking — keep inside `run()`, do not spawn threads

## Notification patterns

| Bot type | `notify.on` |
|----------|------------|
| Trading / action | `always` |
| Monitoring / data | `failure` |
| Digest / summary | `always` |
