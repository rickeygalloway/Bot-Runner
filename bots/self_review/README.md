# self_review

AI-powered code review of recent commits using Claude. Extracts a git diff of Python changes from the last 24 hours and sends it to Claude for a structured review covering bugs, security, performance, and style.

## How it works

1. Walks `git log HEAD` for commits in the last 24 hours
2. Diffs Python files from just before the oldest commit to HEAD
3. Truncates to 12,000 characters if the diff is large (~3k tokens)
4. Sends to Claude (`claude-sonnet-4-6`) with a structured review prompt
5. Returns the review as the run message — delivered via email

## Review format

- **Summary** — overall quality and main theme of changes
- **Strengths** — what was done well
- **Issues & Suggestions** — numbered, with file/line, severity, and fix
- **Overall Score** — X/10 with justification

Severity levels: `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` / `SUGGESTION`

## Required env vars

```
ANTHROPIC_API_KEY=
EMAIL_SENDER=
EMAIL_PASSWORD=
EMAIL_RECEIVER=
```

## Schedule

Daily at 03:00 UTC (`0 3 * * *`).
