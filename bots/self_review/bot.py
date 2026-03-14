"""
bots/self_review/bot.py
AI-powered code review of recent commits using Claude.

Extracts a git diff of Python file changes in the last 24 hours and sends
it to Claude for a structured review covering bugs, security, performance,
and style. The result is returned as the run message and delivered via
the configured notification provider.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import anthropic
import git

import core.config as cfg
from core.logger import get_logger

log = get_logger("self_review")

MODEL = "claude-sonnet-4-6"
MAX_DIFF_CHARS = 12_000  # ~3k tokens; keeps cost predictable on large days

_STATE_FILE = cfg.DATA_DIR / "self_review_last_sha.txt"

REVIEW_PROMPT = """\
You are an expert Python code reviewer for this specific project. \
Review ONLY the git diff provided below.

## Project conventions
The following rules are enforced in this codebase. Flag any violation as an issue.

{project_context}

## Review focus
- Bugs and logic errors
- Security issues (hardcoded secrets, injection risks, unsafe operations)
- Error handling and robustness
- Performance anti-patterns
- Code clarity and maintainability
- Pythonic improvements and type hint gaps
- Violations of the project conventions listed above

## Response format

**Summary** (1-2 sentences): Overall quality and main theme of changes.

**Strengths**: Bullet points of what was done well.

**Issues & Suggestions**: Numbered list. Each item must include:
  - File and line range
  - Severity: [CRITICAL / HIGH / MEDIUM / LOW / SUGGESTION]
  - Description and suggested fix (reference project conventions where applicable)

**Overall Score**: X/10 with one sentence of justification.

If there are no meaningful issues, say so briefly.
Be specific, actionable, and constructive.

## Git diff
{diff}
"""


def _load_project_context() -> str:
    """Extract the coding standards and domain context sections from CLAUDE.md."""
    claude_md = cfg.ROOT_DIR / "CLAUDE.md"
    if not claude_md.exists():
        return "(CLAUDE.md not found — no project conventions available)"

    text = claude_md.read_text(encoding="utf-8")

    # Extract from "## Coding standards" through end of "## Domain context"
    start = text.find("## Coding standards")
    if start == -1:
        return "(Coding standards section not found in CLAUDE.md)"

    # Stop before "## Custom commands" to avoid including irrelevant content
    end = text.find("## Custom commands", start)
    section = text[start:end].strip() if end != -1 else text[start:].strip()

    # Hard cap so a renamed/missing sentinel never dumps the entire file into the prompt
    return section[:4000]


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _read_last_sha() -> str | None:
    """Return the SHA saved from the previous run, or None if no state exists."""
    if _STATE_FILE.exists():
        sha = _STATE_FILE.read_text().strip()
        return sha if _SHA_RE.match(sha) else None
    return None


def _write_last_sha(sha: str) -> None:
    """Persist the current HEAD SHA so the next run knows where to start."""
    _STATE_FILE.write_text(sha)


def _get_new_diff() -> str | None:
    """
    Return a unified diff of Python changes since the last review run, or None.

    Uses a persisted SHA to anchor the diff — not a time window — so commits
    are never reviewed twice and nothing is missed between runs.
    """
    repo = git.Repo(cfg.ROOT_DIR)
    head_sha = repo.head.commit.hexsha

    if not _SHA_RE.match(head_sha):
        raise ValueError(f"Unexpected HEAD SHA format: {head_sha!r}")

    last_sha = _read_last_sha()

    if last_sha == head_sha:
        log.info("No new commits since last review ({})", head_sha[:8])
        return None

    if last_sha is None:
        # First-ever run — review the last 24 hours as a bootstrap so we don't
        # dump the entire repo history into the prompt.
        log.info("No previous review state — bootstrapping with last 24 hours")
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        commits = [
            c
            for c in repo.iter_commits("HEAD", max_count=500)
            if datetime.fromtimestamp(c.committed_date, tz=timezone.utc) >= since
        ]
        if not commits:
            _write_last_sha(head_sha)
            return None
        base = commits[-1]
        try:
            diff = repo.git.diff(f"{base.hexsha}^", "HEAD", "--", "*.py")
        except git.GitCommandError:
            diff = repo.git.diff(base.hexsha, "HEAD", "--", "*.py")
    else:
        # Normal run — diff from the last reviewed commit to HEAD
        if not _SHA_RE.match(last_sha):
            raise ValueError(f"Unexpected last_sha format: {last_sha!r}")
        log.info("Diffing from {} to {}", last_sha[:8], head_sha[:8])
        diff = repo.git.diff(last_sha, "HEAD", "--", "*.py")

    if not diff.strip():
        log.info("No Python file changes since last review")
        _write_last_sha(head_sha)
        return None

    if len(diff) > MAX_DIFF_CHARS:
        # Truncate at a newline boundary so Claude never sees a half-line or mid-hunk cut
        diff = diff[:MAX_DIFF_CHARS].rsplit("\n", 1)[0]
        diff += (
            "\n\n[diff truncated at 12 000 chars — review covers partial changes only]"
        )
        log.warning("Diff truncated to {} chars", MAX_DIFF_CHARS)

    return diff


def _call_claude(diff: str) -> str:
    """Send the diff to Claude and return the review text."""
    client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    prompt = REVIEW_PROMPT.format(
        project_context=_load_project_context(),
        diff=diff,
    )
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt},
        ],
    )
    return message.content[0].text.strip()


def run() -> str:
    """Entry point called by the BotRunner scheduler."""
    if not cfg.ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set — add it to .env")

    log.info("Self-review starting")

    repo = git.Repo(cfg.ROOT_DIR)
    head_sha = repo.head.commit.hexsha

    diff = _get_new_diff()
    if not diff:
        return "No new Python changes since last review — nothing to review."

    log.info("Sending diff ({} chars) to Claude", len(diff))
    review = _call_claude(diff)

    # Only advance the pointer after a successful review
    _write_last_sha(head_sha)
    log.info("Review complete — state advanced to {}", head_sha[:8])

    return review
