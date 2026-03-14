"""
bots/self_review/bot.py
AI-powered code review of recent commits using Claude.

Extracts a git diff of Python file changes in the last 24 hours and sends
it to Claude for a structured review covering bugs, security, performance,
and style. The result is returned as the run message and delivered via
the configured notification provider.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import anthropic
import git

import core.config as cfg
from core.logger import get_logger

log = get_logger("self_review")

MODEL = "claude-sonnet-4-6"
MAX_DIFF_CHARS = 12_000  # ~3k tokens; keeps cost predictable on large days

REVIEW_PROMPT = """\
You are an expert Python code reviewer. Review ONLY the git diff provided below.

Focus on:
- Bugs and logic errors
- Security issues (hardcoded secrets, injection risks, unsafe operations)
- Error handling and robustness
- Performance anti-patterns
- Code clarity and maintainability
- Pythonic improvements and type hint gaps

Structure your response exactly as follows:

**Summary** (1-2 sentences): Overall quality and main theme of changes.

**Strengths**: Bullet points of what was done well.

**Issues & Suggestions**: Numbered list. Each item must include:
  - File and line range
  - Severity: [CRITICAL / HIGH / MEDIUM / LOW / SUGGESTION]
  - Description and suggested fix

**Overall Score**: X/10 with one sentence of justification.

If there are no meaningful issues, say so briefly.
Be specific, actionable, and constructive.

Git diff:
{diff}
"""


def _get_recent_diff(hours: int = 24) -> str | None:
    """Return a unified diff of Python file changes in the last N hours, or None."""
    repo = git.Repo(cfg.ROOT_DIR)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    commits = list(repo.iter_commits("HEAD", since=since.strftime("%Y-%m-%d %H:%M:%S")))
    if not commits:
        log.info("No commits in the last {} hours", hours)
        return None

    oldest = commits[-1]
    log.info(
        "Found {} commit(s) since {}", len(commits), since.strftime("%Y-%m-%d %H:%M")
    )

    # Diff from just before the oldest commit to HEAD, Python files only
    try:
        diff = repo.git.diff(f"{oldest.hexsha}^", "HEAD", "--", "*.py")
    except git.GitCommandError:
        # oldest commit has no parent (initial commit edge case)
        diff = repo.git.diff(oldest.hexsha, "HEAD", "--", "*.py")

    if not diff.strip():
        log.info("No Python file changes in the diff")
        return None

    if len(diff) > MAX_DIFF_CHARS:
        diff = (
            diff[:MAX_DIFF_CHARS] + "\n\n[diff truncated — too large to review in full]"
        )
        log.warning("Diff truncated to {} chars", MAX_DIFF_CHARS)

    return diff


def _call_claude(diff: str) -> str:
    """Send the diff to Claude and return the review text."""
    client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {"role": "user", "content": REVIEW_PROMPT.format(diff=diff)},
        ],
    )
    return message.content[0].text.strip()


def run() -> str:
    """Entry point called by the BotRunner scheduler."""
    if not cfg.ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set — add it to .env")

    log.info("Self-review starting")

    diff = _get_recent_diff(hours=24)
    if not diff:
        return "No Python changes in the last 24 hours — nothing to review."

    log.info("Sending diff ({} chars) to Claude", len(diff))
    review = _call_claude(diff)
    log.info("Review complete")

    return review
