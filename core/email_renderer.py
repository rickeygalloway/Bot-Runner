"""
core/email_renderer.py
Renders the HTML notification email from a Jinja2 template.
No dependency on core.config — safe to import standalone (e.g. from preview scripts).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import markdown as md
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

_TEMPLATE_DIR = Path(__file__).parent
_TEMPLATE_NAME = "email_template.html"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)

_MD_EXTENSIONS = ["fenced_code", "tables", "sane_lists"]


def render_html(*, bot_name: str, status: str, message: str) -> str:
    """Render a bot notification as an HTML email string."""
    message_html = Markup(md.markdown(message, extensions=_MD_EXTENSIONS))
    status_color = "#27ae60" if status == "success" else "#c0392b"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    template = _env.get_template(_TEMPLATE_NAME)
    return template.render(
        bot_name=bot_name,
        status=status,
        status_color=status_color,
        message_html=message_html,
        timestamp=timestamp,
    )
