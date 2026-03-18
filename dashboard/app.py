"""
dashboard/app.py
FastAPI dashboard — dark mode, read-only except for the enable/disable toggle.
Runs at http://localhost:8000
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import core.config as cfg
from core.database import (
    get_all_runs,
    get_last_run,
    get_recent_runs,
    get_run_stats,
    get_token_usage_summary,
)
from core.health import env_file_exists, get_env_status
from core.scheduler import get_registered_bots

# ── App setup ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="BotRunner Dashboard", docs_url=None, redoc_url=None)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ── Helpers ───────────────────────────────────────────────────────────────────


def _next_run_time(bot_name: str) -> str:
    """Return ISO string of next scheduled run, or 'n/a'."""
    try:
        from core.scheduler import _scheduler

        job = _scheduler.get_job(bot_name)
        if job and job.next_run_time:
            return job.next_run_time.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        pass
    return "n/a"


def _read_status_json() -> dict:
    if cfg.STATUS_FILE.exists():
        try:
            with open(cfg.STATUS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _build_bot_cards() -> list[dict]:
    """Build the per-bot data cards for the dashboard index."""
    registered = {b["name"]: b for b in get_registered_bots()}
    status_data = _read_status_json()
    cards = []

    for bot_name, bot in registered.items():
        last_run = get_last_run(bot_name)
        stats = get_run_stats(bot_name)
        _status = status_data.get(bot_name, {})
        bc = bot.get("config", {})

        cards.append(
            {
                "name": bot_name,
                "display": bc.get("name", bot_name),
                "description": bc.get("description", ""),
                "schedule": bc.get("schedule", ""),
                "enabled": bc.get("enabled", True),
                "error": bot.get("error"),
                "last_run": last_run["start_time"][:19].replace("T", " ")
                if last_run
                else "never",
                "last_status": last_run["status"] if last_run else "—",
                "last_result": (last_run["message"] or "")[:120] if last_run else "—",
                "next_run": _next_run_time(bot_name),
                "successes": stats["successes"],
                "failures": stats["failures"],
                "total": stats["total"],
                "notify": bc.get("notify", {}),
                "is_ai": bool(bc.get("ai", False)),
            }
        )

    return cards


def _build_chat_system_prompt(
    cards: list[dict], token_usage: list[dict], recent_runs: list[dict]
) -> str:
    lines = [
        "You are a helpful assistant embedded in BotRunner, an automated bot scheduler.",
        f"Current time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Bot Status",
        "Name | Enabled | Last Status | Last Run | Next Run | Schedule | Successes | Failures",
        "-----|---------|-------------|----------|----------|----------|-----------|--------",
    ]
    for c in cards:
        lines.append(
            f"{c['display']} | {'yes' if c['enabled'] else 'no'} | {c['last_status']} | "
            f"{c['last_run']} | {c['next_run']} | {c['schedule']} | "
            f"{c['successes']} | {c['failures']}"
        )

    lines += [
        "",
        "## Recent Runs (up to 100, newest first)",
        "Bot | Status | Time | Message",
    ]
    lines.append("----|--------|------|-------")
    for r in recent_runs[:100]:
        msg = (r.get("message") or "").replace("\n", " ")[:120]
        lines.append(
            f"{r['bot_name']} | {r['status']} | {r['start_time'][:19]} | {msg}"
        )

    if token_usage:
        lines += ["", "## Token Usage", "Bot | Model | Runs | Input | Output | Total"]
        lines.append("----|-------|------|-------|--------|------")
        for t in token_usage:
            total = t["total_input"] + t["total_output"]
            lines.append(
                f"{t['bot_name']} | {t['model']} | {t['run_count']} | "
                f"{t['total_input']:,} | {t['total_output']:,} | {total:,}"
            )

    lines += [
        "",
        "Answer questions about bot performance, failures, run history, and token costs.",
        "Be concise and specific. Use numbers from the data above when relevant.",
    ]
    return "\n".join(lines)


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not env_file_exists():
        return RedirectResponse(url="/setup")
    cards = _build_bot_cards()
    all_runs = get_all_runs(limit=300)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "bots": cards,
            "all_runs": all_runs,
            "token_usage": get_token_usage_summary(),
            "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        },
    )


@app.get("/api/bots", response_class=HTMLResponse)
async def api_bots():
    """JSON endpoint for bot status — useful for external monitoring."""
    import json

    return HTMLResponse(
        content=json.dumps(_build_bot_cards(), indent=2),
        media_type="application/json",
    )


@app.get("/api/runs/{bot_name}")
async def api_runs(bot_name: str, limit: int = 50):
    return get_recent_runs(bot_name, limit=limit)


@app.post("/api/bots/{bot_name}/toggle")
async def toggle_bot(bot_name: str):
    """
    Toggle a bot's enabled flag in its config.yaml.
    This is the only write operation the dashboard performs.
    """
    registered = {b["name"]: b for b in get_registered_bots()}
    if bot_name not in registered:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    bot = registered[bot_name]
    config_path: Path = bot["dir"] / "config.yaml"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    config["enabled"] = not config.get("enabled", True)
    new_state = config["enabled"]

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    # Update in-memory config so dashboard reflects change immediately
    bot["config"]["enabled"] = new_state

    # Update scheduler — add or remove job
    try:
        from core.scheduler import _scheduler, _make_job
        from apscheduler.triggers.cron import CronTrigger

        if new_state:
            schedule = config.get("schedule")
            if schedule:
                _scheduler.add_job(
                    _make_job(bot),
                    trigger=CronTrigger.from_crontab(schedule, timezone="UTC"),
                    id=bot_name,
                    replace_existing=True,
                )
        else:
            if _scheduler.get_job(bot_name):
                _scheduler.remove_job(bot_name)
    except Exception:
        pass  # toggle still succeeds even if live scheduler update fails

    return {"bot": bot_name, "enabled": new_state}


@app.post("/api/bots/{bot_name}/run")
async def run_bot(bot_name: str):
    """Trigger an immediate run through the full scheduler wrapper (logged to DB)."""
    import asyncio
    from core.scheduler import _make_job

    registered = {b["name"]: b for b in get_registered_bots()}
    if bot_name not in registered:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_name}' not found")

    bot = registered[bot_name]
    if bot.get("error"):
        raise HTTPException(status_code=400, detail=f"Bot '{bot_name}' failed to load")

    job = _make_job(bot)
    await asyncio.get_event_loop().run_in_executor(None, job)
    return {"bot": bot_name, "status": "completed"}


@app.get("/api/logs/{bot_name}", response_class=PlainTextResponse)
async def get_log(bot_name: str, lines: int = 200):
    """Return the last N lines of a bot's log file."""
    log_path = cfg.LOGS_DIR / f"{bot_name}.log"
    if not log_path.exists():
        return PlainTextResponse(f"No log file found for '{bot_name}'")
    with open(log_path, "r", errors="replace") as f:
        all_lines = f.readlines()
    tail = all_lines[-lines:]
    return PlainTextResponse("".join(tail))


@app.get("/api/token-usage")
async def api_token_usage():
    """Return aggregated token usage grouped by bot and model."""
    return get_token_usage_summary()


@app.post("/api/chat")
async def chat(request: Request):
    """Stream a Claude response about live bot data via Server-Sent Events."""
    if not cfg.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    body = await request.json()
    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="messages required")

    cards = _build_bot_cards()
    token_usage = get_token_usage_summary()
    recent_runs = get_all_runs(limit=100)
    system_prompt = _build_chat_system_prompt(cards, token_usage, recent_runs)

    async def generate():
        client = anthropic.AsyncAnthropic(api_key=cfg.ANTHROPIC_API_KEY)
        try:
            async with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/setup", response_class=HTMLResponse)
async def setup(request: Request):
    """Environment variable status and setup instructions."""
    return templates.TemplateResponse(
        "setup.html",
        {
            "request": request,
            "groups": get_env_status(),
            "env_file_exists": env_file_exists(),
        },
    )
