"""
bots/dependency_audit/bot.py
Weekly dependency audit using Claude.

Reads requirements.txt, checks PyPI for the latest version of each pinned package,
and asks Claude to summarise what's outdated and flag any known security concerns.
No external API key required for PyPI lookups — uses the public JSON API.
"""

from __future__ import annotations

import json
import re
import urllib.request

import anthropic

import core.config as cfg
from core.database import record_token_usage
from core.logger import get_logger

log = get_logger("dependency_audit")

MODEL = "claude-haiku-4-5-20251001"
REQUIREMENTS_FILE = cfg.ROOT_DIR / "requirements.txt"

SYSTEM_PROMPT = """\
You are a Python dependency auditor reviewing a project's requirements.txt.
You will be given a table of packages: their pinned version and the latest available on PyPI.

Write a concise audit report that:
- Lists outdated packages grouped by how far behind they are (major, minor, patch)
- Flags any packages with known security vulnerabilities or deprecation notices
- Highlights packages that are significantly out of date (2+ major versions behind)
- Notes packages that are already up to date

Response format:

## Dependency Audit

### Up to date
- <package> <version>

### Outdated
- <package> <pinned> → <latest> [MAJOR / MINOR / PATCH] — <brief note if notable>

### Security / deprecation concerns
- <package>: <concern>

### Summary
1-2 sentences on overall health and recommended priority.\
"""


def _parse_requirements() -> dict[str, str]:
    """Return {package_name: pinned_version} from requirements.txt, skipping comments."""
    packages: dict[str, str] = {}
    pattern = re.compile(r"^([A-Za-z0-9_\-]+)==([^\s#]+)")
    for line in REQUIREMENTS_FILE.read_text().splitlines():
        m = pattern.match(line.strip())
        if m:
            packages[m.group(1).lower()] = m.group(2)
    return packages


def _latest_pypi_version(package: str) -> str | None:
    """Query PyPI JSON API for the latest stable release of a package."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:  # noqa: S310
            data = json.loads(resp.read())
        return data["info"]["version"]
    except Exception as exc:
        log.warning("PyPI lookup failed for {}: {}", package, exc)
        return None


def _build_audit_table(packages: dict[str, str]) -> str:
    """Fetch latest versions and return a plain-text comparison table."""
    lines = ["Package | Pinned | Latest", "--------|--------|-------"]
    for name, pinned in sorted(packages.items()):
        latest = _latest_pypi_version(name) or "unknown"
        lines.append(f"{name} | {pinned} | {latest}")
    return "\n".join(lines)


def _call_claude(table: str) -> tuple[str, str]:
    client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": f"requirements.txt audit:\n\n{table}"}],
    )
    usage = message.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0)
    cache_write = getattr(usage, "cache_creation_input_tokens", 0)
    log.info(
        "Token usage — input: {} (cache_read: {}) output: {}",
        usage.input_tokens,
        cache_read,
        usage.output_tokens,
    )
    record_token_usage(
        bot_name="dependency_audit",
        model=MODEL,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
    body = message.content[0].text.strip()
    footer = f"\n\n---\n*Model: `{MODEL}` · Tokens: {usage.input_tokens} in"
    if cache_read:
        footer += f" ({cache_read} cached)"
    footer += f" / {usage.output_tokens} out*"
    return body, footer


def run() -> str:
    """Entry point called by the BotRunner scheduler."""
    if not cfg.ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set — add it to .env")

    if not REQUIREMENTS_FILE.exists():
        raise FileNotFoundError(f"requirements.txt not found at {REQUIREMENTS_FILE}")

    log.info("Dependency audit starting")
    packages = _parse_requirements()
    log.info("Checking {} pinned packages against PyPI", len(packages))

    table = _build_audit_table(packages)
    body, footer = _call_claude(table)
    log.info("Audit complete")

    return body + footer
