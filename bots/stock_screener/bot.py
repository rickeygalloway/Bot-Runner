"""
bots/stock_screener/bot.py
Weekly AI-powered stock screener.

Pulls price data for a configurable watchlist via yfinance, computes key
metrics (RSI, distance from 52-week high/low, recent momentum), and asks
Claude to identify the most interesting buy opportunities.

For informational purposes only — not financial advice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import anthropic
import pandas as pd
import yaml
import yfinance as yf

import core.config as cfg
from core.database import record_token_usage
from core.logger import get_logger

log = get_logger("stock_screener")

MODEL = "claude-haiku-4-5-20251001"

DEFAULT_WATCHLIST = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "NVDA",
    "META",  # Tech
    "JPM",
    "V",
    "BAC",  # Finance
    "JNJ",
    "UNH",  # Healthcare
    "AMZN",
    "WMT",  # Consumer
    "XOM",
    "CVX",  # Energy
    "TSLA",  # EV / Growth
]

SYSTEM_PROMPT = """\
You are an equity analyst reviewing a weekly stock screen.
You will be given a table of stocks with key technical and valuation metrics.

Identify the top 3-5 most interesting buy opportunities and explain why.
Consider:
- RSI below 40 as potentially oversold
- Stocks near 52-week lows (within 15%) as potential value entries
- Stocks with strong recent momentum (positive 1-week and 1-month returns)
- Reasonable PE ratios relative to sector peers

Response format:

## Weekly Stock Screen — {DATE}

### Top Picks
1. **TICKER** — <1-2 sentence rationale>
2. ...

### Honorable Mentions
- <TICKER>: <brief note>

### Market Observations
1-2 sentences on overall market tone based on the data.

---
*For informational purposes only. Not financial advice.*\
"""


def _load_watchlist() -> list[str]:
    """Load watchlist from config.yaml if present, else use default."""
    config_path = Path(__file__).parent / "config.yaml"
    try:
        config = yaml.safe_load(config_path.read_text())
        return config.get("stocks", DEFAULT_WATCHLIST)
    except Exception:
        return DEFAULT_WATCHLIST


def _compute_rsi(prices: pd.Series, period: int = 14) -> float | None:
    """Compute RSI for a price series. Returns None if insufficient data."""
    if len(prices) < period + 1:
        return None
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 1) if pd.notna(val) else None


def _fetch_metrics(ticker: str) -> dict | None:
    """Fetch key metrics for a single ticker. Returns None on failure."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if hist.empty or len(hist) < 20:
            log.warning("Insufficient history for {}", ticker)
            return None

        close = hist["Close"]
        price = round(float(close.iloc[-1]), 2)
        week_52_high = round(float(close.max()), 2)
        week_52_low = round(float(close.min()), 2)
        pct_from_high = round((price - week_52_high) / week_52_high * 100, 1)
        pct_from_low = round((price - week_52_low) / week_52_low * 100, 1)

        ret_1w = (
            round((price / float(close.iloc[-6]) - 1) * 100, 1)
            if len(close) >= 6
            else None
        )
        ret_1m = (
            round((price / float(close.iloc[-22]) - 1) * 100, 1)
            if len(close) >= 22
            else None
        )

        rsi = _compute_rsi(close)

        info = t.info
        pe = info.get("trailingPE")
        pe = round(pe, 1) if pe and pe > 0 else None

        return {
            "ticker": ticker,
            "price": price,
            "52w_high": week_52_high,
            "52w_low": week_52_low,
            "pct_from_high": pct_from_high,
            "pct_from_low": pct_from_low,
            "rsi": rsi,
            "ret_1w": ret_1w,
            "ret_1m": ret_1m,
            "pe": pe,
        }
    except Exception as exc:
        log.error("Failed to fetch metrics for {}: {}", ticker, exc)
        return None


def _build_metrics_table(watchlist: list[str]) -> str:
    """Fetch metrics for all tickers and format as a text table."""
    rows = []
    for ticker in watchlist:
        m = _fetch_metrics(ticker)
        if m:
            rows.append(m)
            log.info(
                "Fetched {}: price={} RSI={} PE={}",
                ticker,
                m["price"],
                m["rsi"],
                m["pe"],
            )

    if not rows:
        raise RuntimeError("Failed to fetch data for any ticker in the watchlist")

    def fmt(v: float | None, suffix: str = "") -> str:
        return f"{v}{suffix}" if v is not None else "n/a"

    lines = [
        "Ticker | Price | 52W High | 52W Low | %FromHigh | %FromLow | RSI  | 1W%  | 1M%  | PE",
        "-------|-------|----------|---------|-----------|----------|------|------|------|---",
    ]
    for m in rows:
        lines.append(
            f"{m['ticker']:<6} | {m['price']:>6} | {m['52w_high']:>8} | {m['52w_low']:>7} | "
            f"{fmt(m['pct_from_high'], '%'):>9} | {fmt(m['pct_from_low'], '%'):>8} | "
            f"{fmt(m['rsi']):>4} | {fmt(m['ret_1w'], '%'):>4} | {fmt(m['ret_1m'], '%'):>4} | "
            f"{fmt(m['pe'])}"
        )

    return "\n".join(lines)


def _call_claude(table: str, date: str) -> tuple[str, str]:
    client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    system_text = SYSTEM_PROMPT.replace("{DATE}", date)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": f"Stock metrics:\n\n{table}"}],
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
        bot_name="stock_screener",
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

    log.info("Stock screener starting")
    watchlist = _load_watchlist()
    log.info("Screening {} tickers", len(watchlist))

    table = _build_metrics_table(watchlist)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body, footer = _call_claude(table, date)
    log.info("Screen complete")

    return body + footer
