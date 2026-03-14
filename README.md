# BotRunner

A single-process bot scheduler with a web dashboard. Bots run on cron schedules via APScheduler; a FastAPI dashboard provides live status, run history, manual run controls, and enable/disable toggles.

## Quick start

```bash
# Python 3.11+ required
pip install -r requirements.txt

cp .env.example .env   # fill in your values

pre-commit install     # activate git hooks (auto-format + credential scanning)

python main.py
```

Dashboard: `http://127.0.0.1:8000`
Setup / env status: `http://127.0.0.1:8000/setup`

## Configuration

All settings are read from `.env` (see `.env.example`). If `.env` is missing, the dashboard redirects to `/setup` with per-variable instructions. Bot-level config lives in each bot's `config.yaml`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `DASHBOARD_HOST` | `127.0.0.1` | Dashboard bind address |
| `DASHBOARD_PORT` | `8000` | Dashboard port |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | — | Telegram notifications |
| `EMAIL_SENDER` / `EMAIL_PASSWORD` / `EMAIL_RECEIVER` | — | Gmail SMTP notifications |
| `OANDA_API_KEY` / `OANDA_ACCOUNT_ID` / `OANDA_ENV` | — | Forex trader bot |
| `ANTHROPIC_API_KEY` | — | Self-review bot (Claude API) |

## Adding a bot

Create `bots/<name>/bot.py` with a `run()` function and a `config.yaml`:

```
bots/
└── my_bot/
    ├── bot.py        # must expose run() -> str | None
    └── config.yaml
```

`config.yaml` schema:

```yaml
name: My Bot
description: What it does
schedule: "0 9 * * 1-5"   # standard crontab, UTC
enabled: true
notify:
  provider: telegram       # "telegram" or "email"
  "on": failure            # "success" | "failure" | "always"
```

The scheduler picks up the new bot automatically on next startup — no registration code needed.

- `run()` returning a string → stored as the run message, marked **success**
- `run()` raising an exception → traceback stored, marked **failure**
- Bot-level logging: `from core.logger import get_logger; log = get_logger("my_bot")`
- Config/secrets: `import core.config as cfg`

## Included bots

| Bot | Schedule | Description |
|-----|----------|-------------|
| `forex_trader` | Every 4 hours (UTC) | EUR/USD 9/21 EMA crossover strategy via OANDA API. Enforces one open position, daily loss limit, and flat-market filter. |
| `news_digest` | Daily 08:00 UTC | Fetches top headlines from Reuters, BBC, and FT via RSS and emails a plain-text digest. |
| `self_review` | Daily 03:00 UTC | AI-powered code review of recent commits using Claude — sends findings by email. Requires `ANTHROPIC_API_KEY`. |
| `commit_explainer` | Monday 07:00 UTC | Weekly plain-English changelog of the past 7 days of commits, grouped by theme. Requires `ANTHROPIC_API_KEY`. |

## Dashboard API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI (redirects to `/setup` if `.env` is missing) |
| `/setup` | GET | Environment variable status and setup instructions |
| `/api/bots` | GET | JSON status for all bots |
| `/api/runs/{name}` | GET | Run history for a bot (`?limit=50`) |
| `/api/logs/{name}` | GET | Last N log lines (`?lines=200`) |
| `/api/bots/{name}/toggle` | POST | Enable/disable a bot |
| `/api/bots/{name}/run` | POST | Trigger an immediate run (logged to DB) |

## Development

Pre-commit hooks run automatically on every `git commit`:

| Hook | Action |
|------|--------|
| `ruff` | Lint and auto-fix Python |
| `ruff-format` | Auto-format Python in place |
| `gitleaks` | Block commits containing credentials or high-entropy secrets |
| `detect-private-key` | Block PEM private keys |

Run `pre-commit install` once after cloning. If a commit is blocked due to formatting changes, re-stage the modified files and commit again.
