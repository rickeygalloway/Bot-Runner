# forex_trader

EUR/USD algorithmic trading bot using a 9 EMA / 21 EMA crossover strategy on 4-hour candles via the OANDA API.

## Strategy

| Signal | Condition |
|--------|-----------|
| BUY | 9 EMA crosses above 21 EMA |
| SELL | 9 EMA crosses below 21 EMA |

- **Stop loss:** 15 pips
- **Take profit:** 30 pips (2:1 R:R)
- **Trade size:** 1,000 units (override with `FOREX_TRADE_UNITS` in `.env`)

## Safety rules

- One open EUR/USD position at a time — no stacking
- Flat market filter: skips if EMA spread < 0.0003
- Daily loss limit: halts trading if realised P&L ≤ −$25 in a calendar day

## Required env vars

```
OANDA_API_KEY=
OANDA_ACCOUNT_ID=
OANDA_ENV=practice   # change to "live" deliberately
```

## Schedule

Every 4 hours UTC (`0 */4 * * *`) — aligned with 4H candle closes.
