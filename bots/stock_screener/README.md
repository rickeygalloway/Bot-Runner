# stock_screener

Weekly AI-powered stock screen. Pulls price data for a configurable watchlist, computes RSI, 52-week positioning, and recent momentum, then asks Claude to identify the top buy opportunities.

## How it works

1. Loads the watchlist from `config.yaml` (falls back to built-in defaults)
2. Fetches 1 year of price history per ticker via `yfinance`
3. Computes: RSI (14-day), % from 52-week high/low, 1-week and 1-month returns, trailing PE
4. Sends the metrics table to Claude for analysis

## Metrics used

| Metric | Source |
|--------|--------|
| RSI (14) | Calculated from 1Y price history |
| % from 52W high / low | Calculated from 1Y price history |
| 1W / 1M return | Calculated from 1Y price history |
| Trailing PE | yfinance `info` |

## Customising the watchlist

Edit the `stocks:` list in `config.yaml`. Any valid Yahoo Finance ticker works.

## Required env vars

```
ANTHROPIC_API_KEY=
```

## Dependencies

```
yfinance
```

## Schedule

Every Friday at 21:00 UTC (`0 21 * * 5`) — after US market close.

---
*For informational purposes only. Not financial advice.*
