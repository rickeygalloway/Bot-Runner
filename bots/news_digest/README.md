# news_digest

Fetches the top headlines from three RSS feeds and emails a plain-text daily digest.

## Sources

| Feed | Articles |
|------|----------|
| Reuters Business | 5 |
| BBC News | 5 |
| Financial Times | 5 |

## Output

Returns a formatted digest string — the notifier delivers it via email. If all three feeds fail, the run is marked as failure.

## Required env vars

Email delivery uses the shared Gmail SMTP config:

```
EMAIL_SENDER=
EMAIL_PASSWORD=
EMAIL_RECEIVER=
```

## Schedule

Daily at 08:00 UTC (`0 8 * * *`).
