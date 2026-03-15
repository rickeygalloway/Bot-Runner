# news_sentiment

Daily AI-powered market sentiment briefing derived from top financial news headlines. Runs 30 minutes after `news_digest` and delivers a directional call on USD, EUR, and equities.

## How it works

1. Fetches headlines from Reuters Business, BBC News, and Financial Times (same feeds as `news_digest`)
2. Sends to Claude for sentiment analysis and market briefing

## Output format

```
## Overall sentiment: Bearish (confidence: medium)

**USD outlook**: ...
**EUR outlook**: ...
**Equity markets**: Risk-off tone ...

**Key themes**
- Central bank policy uncertainty
- Energy price volatility

**Watch list**
- Fed speakers at 14:00 UTC
```

## Required env vars

```
ANTHROPIC_API_KEY=
EMAIL_SENDER=
EMAIL_PASSWORD=
EMAIL_RECEIVER=
```

## Schedule

Daily at 08:30 UTC (`30 8 * * *`) — 30 minutes after `news_digest`.
