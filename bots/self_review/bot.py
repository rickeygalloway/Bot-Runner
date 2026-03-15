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
from core.database import record_token_usage
from core.logger import get_logger

log = get_logger("self_review")

MODEL = "claude-haiku-4-5-20251001"  # sufficient for structured review; ~10x cheaper than Sonnet
MAX_DIFF_CHARS = 12_000  # ~3k tokens; keeps cost predictable on large days

_STATE_FILE = cfg.DATA_DIR / "self_review_last_sha.txt"
_REVIEW_FILE = cfg.DATA_DIR / "self_review_latest.txt"

# Static part — sent as a cacheable system prompt to avoid re-charging on repeated runs.
# Contains one placeholder: {project_context}, formatted inside _call_claude().
SYSTEM_PROMPT = """\
You are an expert Python code reviewer for this specific project.
Review ONLY the git diff provided in the user message.

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
Be specific, actionable, and constructive.\
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


# Loaded once at module import — CLAUDE.md doesn't change between runs
_PROJECT_CONTEXT: str = _load_project_context()

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


def _write_latest_review(review: str) -> None:
    """Overwrite the cached review file with the latest output."""
    _REVIEW_FILE.write_text(review, encoding="utf-8")


def _read_latest_review() -> str | None:
    """Return the cached review text, or None if no review has been run yet."""
    if _REVIEW_FILE.exists():
        return _REVIEW_FILE.read_text(encoding="utf-8").strip() or None
    return None


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


def _call_claude(diff: str) -> tuple[str, str]:
    """
    Send the diff to Claude and return (review_body, token_footer).

    Returned separately so the caller can cache the body without the footer —
    token counts from a previous run would be stale if included in the cache.
    """
    client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    system_text = SYSTEM_PROMPT.format(project_context=_PROJECT_CONTEXT)

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": system_text,
                # Cache the static system prompt — saves tokens on repeated manual runs
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": f"## Git diff\n\n{diff}"},
        ],
    )

    usage = message.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0)
    cache_write = getattr(usage, "cache_creation_input_tokens", 0)
    log.info(
        "Token usage — input: {} (cache_read: {} cache_write: {}) output: {}",
        usage.input_tokens,
        cache_read,
        cache_write,
        usage.output_tokens,
    )
    record_token_usage(
        bot_name="self_review",
        model=MODEL,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )

    review = message.content[0].text.strip()

    footer = f"\n\n---\n*Model: `{MODEL}` · Tokens: {usage.input_tokens} in"
    if cache_read:
        footer += f" ({cache_read} cached)"
    footer += f" / {usage.output_tokens} out*"

    return review, footer


def run() -> str:
    """Entry point called by the BotRunner scheduler."""
    if not cfg.ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set — add it to .env")

    log.info("Self-review starting")

    repo = git.Repo(cfg.ROOT_DIR)
    head_sha = repo.head.commit.hexsha

    diff = _get_new_diff()
    if not diff:
        cached = _read_latest_review()
        if cached:
            log.info("No new commits — resending cached review")
            return (
                "_No new commits since last review. Previous results below._\n\n---\n\n"
                + cached
            )
        return "No new commits since last review and no previous review on file."

    log.info("Sending diff ({} chars) to Claude", len(diff))
    review_body, token_footer = _call_claude(diff)

    # Cache the body only — token counts would be stale if shown from a cached run
    _write_last_sha(head_sha)
    _write_latest_review(review_body)
    log.info("Review complete — state advanced to {}", head_sha[:8])

    return review_body + token_footer
