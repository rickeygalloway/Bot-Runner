"""
tools/preview_email.py
Preview the HTML email template in your browser — no bot run, no API tokens needed.

Usage:
    python tools/preview_email.py

Edit SAMPLE_BOT, SAMPLE_STATUS, and SAMPLE_MESSAGE below to test different scenarios.
The rendered HTML is written to a temp file and opened in your default browser.
"""

from __future__ import annotations

import sys
import tempfile
import webbrowser
from pathlib import Path

# Ensure project root is on the path so core/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.email_renderer import render_html  # noqa: E402

# ── Edit these to preview different scenarios ─────────────────────────────────

SAMPLE_BOT = "Self Review"
SAMPLE_STATUS = "success"  # "success" or "failure"

SAMPLE_MESSAGE = """\
**Summary**: Recent changes introduce HTML email templates and a preview tool, \
significantly improving notification readability across all bots.

**Strengths**:
- Clean separation of rendering logic in `email_renderer.py` — no config dependency
- Jinja2 template is easy to customise without touching Python code
- Preview script lets you iterate on the template without burning API tokens
- Plain-text fallback ensures deliverability in all email clients

**Issues & Suggestions**:

1. **`bots/self_review/bot.py`, line ~90** | Severity: **HIGH**
   `repo.iter_commits("HEAD", since=...)` passes a naive UTC datetime string to gitpython.
   Git interprets `--after` as local time, so on a non-UTC server this silently
   misses or double-includes commits.
   ```python
   # Fix: use ISO 8601 with explicit UTC offset
   since.strftime("%Y-%m-%dT%H:%M:%S+00:00")
   ```

2. **`core/notifier.py`, line 52** | Severity: **LOW**
   The YAML boolean workaround `notify_config.get("on") or notify_config.get(True, "failure")`
   will misfire if `"on"` is explicitly set to `None` or an empty string in config.
   Consider a more explicit check:
   ```python
   on = notify_config.get("on") or notify_config.get(True) or "failure"
   ```

3. **`bots/forex_trader/bot.py`, line 228** | Severity: **SUGGESTION**
   `os.getenv("FOREX_TRADE_UNITS", "1000")` bypasses `core.config` — violates the
   project convention that all config/secrets go through `core.config`.
   Add `FOREX_TRADE_UNITS = int(_optional("FOREX_TRADE_UNITS", "1000"))` to `config.py`.

**Overall Score**: 8/10 — Well-structured, improves developer experience meaningfully. \
One correctness fix and one convention violation worth addressing.
"""

# ── Failure scenario (uncomment to preview) ───────────────────────────────────
# SAMPLE_BOT = "Forex Trader"
# SAMPLE_STATUS = "failure"
# SAMPLE_MESSAGE = """\
# Traceback (most recent call last):
#   File "bots/forex_trader/bot.py", line 231, in run
#     client = _client()
#   File "bots/forex_trader/bot.py", line 62, in _client
#     return oandapyV20.API(access_token=cfg.OANDA_API_KEY, environment=environment)
# oandapyV20.exceptions.V20Error: 401 {"errorMessage": "Unauthorized"}
# """

# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    html = render_html(
        bot_name=SAMPLE_BOT, status=SAMPLE_STATUS, message=SAMPLE_MESSAGE
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as f:
        f.write(html)
        path = f.name

    print(f"Preview: {path}")
    webbrowser.open(f"file:///{path}")
