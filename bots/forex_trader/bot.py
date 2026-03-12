"""
bots/forex_trader/bot.py
EUR/USD 4H — 9 EMA / 21 EMA crossover strategy via OANDA API.

Refactored from standalone forex_bot into the BotRunner framework.
Core trading logic is unchanged; only infrastructure (logging, config,
notifications) has moved to core/.

Strategy rules
──────────────
  BUY  signal : 9 EMA crosses ABOVE 21 EMA
  SELL signal : 9 EMA crosses BELOW 21 EMA
  Stop loss   : 15 pips
  Take profit : 30 pips  (2:1 R:R)
  Max units   : 1 000 (configurable via config.yaml)
  Daily loss  : halts after -$25 in a single calendar day

Safety rules
────────────
  - One open position at a time (no stacking)
  - Flat market filter — skips if EMA spread < threshold
  - Daily loss limit enforced before each trade attempt
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, date
from typing import Literal

import oandapyV20
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.positions as positions
import oandapyV20.endpoints.trades as trades
import pandas as pd

from core.logger import get_logger
import core.config as cfg

log = get_logger("forex_trader")

# ── Constants ─────────────────────────────────────────────────────────────────
INSTRUMENT       = "EUR_USD"
GRANULARITY      = "H4"
CANDLE_COUNT     = 50        # enough history for both EMAs to be stable
EMA_FAST         = 9
EMA_SLOW         = 21
PIP_SIZE         = 0.0001    # EUR/USD pip
STOP_LOSS_PIPS   = 15
TAKE_PROFIT_PIPS = 30
FLAT_THRESHOLD   = 0.0003    # minimum EMA spread to consider market trending
DAILY_LOSS_LIMIT = -25.0     # USD — halt trading if daily P&L hits this


# ── OANDA client factory ──────────────────────────────────────────────────────

def _client() -> oandapyV20.API:
    environment = "practice" if cfg.OANDA_ENV != "live" else "live"
    return oandapyV20.API(
        access_token=cfg.OANDA_API_KEY,
        environment=environment,
    )


# ── Market data ───────────────────────────────────────────────────────────────

def _fetch_candles(client: oandapyV20.API) -> pd.DataFrame:
    """Fetch the last N 4H candles for EUR/USD and return as a DataFrame."""
    params = {
        "count": CANDLE_COUNT,
        "granularity": GRANULARITY,
        "price": "M",   # midpoint
    }
    req = instruments.InstrumentsCandles(INSTRUMENT, params=params)
    resp = client.request(req)

    rows = []
    for candle in resp["candles"]:
        if candle["complete"]:
            rows.append({
                "time":  candle["time"],
                "close": float(candle["mid"]["c"]),
            })

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"])
    df.set_index("time", inplace=True)
    return df


def _compute_emas(df: pd.DataFrame) -> tuple[float, float, float, float]:
    """
    Compute 9 EMA and 21 EMA.
    Returns (ema_fast_now, ema_slow_now, ema_fast_prev, ema_slow_prev).
    """
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    return (
        df["ema_fast"].iloc[-1],
        df["ema_slow"].iloc[-1],
        df["ema_fast"].iloc[-2],
        df["ema_slow"].iloc[-2],
    )


def _detect_signal(
    fast_now: float, slow_now: float, fast_prev: float, slow_prev: float
) -> Literal["BUY", "SELL", None]:
    """Return crossover signal or None if no crossover this candle."""
    spread = abs(fast_now - slow_now)
    if spread < FLAT_THRESHOLD:
        log.info("Market flat (spread={:.5f}) — no trade", spread)
        return None

    crossed_above = fast_prev <= slow_prev and fast_now > slow_now
    crossed_below = fast_prev >= slow_prev and fast_now < slow_now

    if crossed_above:
        return "BUY"
    if crossed_below:
        return "SELL"
    return None


# ── Account checks ────────────────────────────────────────────────────────────

def _get_account_summary(client: oandapyV20.API) -> dict:
    req = accounts.AccountSummary(cfg.OANDA_ACCOUNT_ID)
    resp = client.request(req)
    return resp["account"]


def _has_open_position(client: oandapyV20.API) -> bool:
    """Return True if there is already an open EUR/USD position."""
    req = positions.OpenPositions(cfg.OANDA_ACCOUNT_ID)
    resp = client.request(req)
    for pos in resp.get("positions", []):
        if pos["instrument"] == INSTRUMENT:
            long_units  = int(pos["long"]["units"])
            short_units = int(pos["short"]["units"])
            if long_units != 0 or short_units != 0:
                return True
    return False


def _daily_pl(client: oandapyV20.API) -> float:
    """
    Approximate daily P&L by summing realised P&L from closed trades today.
    OANDA doesn't expose a single 'daily P&L' field on practice accounts,
    so we sum today's closed trade profits.
    """
    today = date.today().isoformat()
    params = {"instrument": INSTRUMENT, "count": 50}
    req = trades.TradesList(cfg.OANDA_ACCOUNT_ID, params=params)
    resp = client.request(req)

    daily = 0.0
    for trade in resp.get("trades", []):
        close_time = trade.get("closeTime", "")
        if close_time.startswith(today) and trade.get("state") == "CLOSED":
            daily += float(trade.get("realizedPL", 0))
    return daily


# ── Order placement ───────────────────────────────────────────────────────────

def _place_order(
    client: oandapyV20.API,
    side: Literal["BUY", "SELL"],
    units: int,
    current_price: float,
) -> str:
    """Place a market order with SL and TP. Returns the trade ID."""
    pip = PIP_SIZE
    if side == "BUY":
        sl_price = round(current_price - STOP_LOSS_PIPS   * pip, 5)
        tp_price = round(current_price + TAKE_PROFIT_PIPS * pip, 5)
        unit_str = str(units)
    else:
        sl_price = round(current_price + STOP_LOSS_PIPS   * pip, 5)
        tp_price = round(current_price - TAKE_PROFIT_PIPS * pip, 5)
        unit_str = str(-units)

    order_data = {
        "order": {
            "type":       "MARKET",
            "instrument": INSTRUMENT,
            "units":      unit_str,
            "stopLossOnFill": {
                "price": str(sl_price),
            },
            "takeProfitOnFill": {
                "price": str(tp_price),
            },
            "timeInForce": "FOK",
        }
    }

    req = orders.OrderCreate(cfg.OANDA_ACCOUNT_ID, data=order_data)
    resp = client.request(req)

    trade_id = (
        resp.get("orderFillTransaction", {}).get("tradeOpened", {}).get("tradeID")
        or resp.get("orderFillTransaction", {}).get("tradeID", "unknown")
    )
    return trade_id


# ── Main run() ────────────────────────────────────────────────────────────────

def run() -> str:
    """
    Entry point called by the BotRunner scheduler.
    Returns a human-readable result string (logged and stored in DB).
    Raises on unrecoverable errors so the scheduler marks the run as failed.
    """
    log.info("--- Forex Trader run starting ---")

    # Load trade units from env (default 1000)
    trade_units = int(os.getenv("FOREX_TRADE_UNITS", "1000"))

    client = _client()

    # ── Daily loss limit check ────────────────────────────────────────────────
    daily_pl = _daily_pl(client)
    log.info("Daily P&L so far: ${:.2f}", daily_pl)
    if daily_pl <= DAILY_LOSS_LIMIT:
        msg = f"Daily loss limit hit (${daily_pl:.2f}) — no trade placed."
        log.warning(msg)
        return msg

    # ── Open position guard ───────────────────────────────────────────────────
    if _has_open_position(client):
        msg = "Existing EUR/USD position open — skipping new trade."
        log.info(msg)
        return msg

    # ── Fetch candles and compute EMAs ────────────────────────────────────────
    df = _fetch_candles(client)
    log.info("Fetched {} complete candles", len(df))

    fast_now, slow_now, fast_prev, slow_prev = _compute_emas(df)
    log.info(
        "EMA9={:.5f}  EMA21={:.5f}  (prev: EMA9={:.5f}  EMA21={:.5f})",
        fast_now, slow_now, fast_prev, slow_prev,
    )

    current_price = df["close"].iloc[-1]
    signal = _detect_signal(fast_now, slow_now, fast_prev, slow_prev)

    if signal is None:
        msg = (
            f"No crossover signal. "
            f"EMA9={fast_now:.5f}  EMA21={slow_now:.5f}  "
            f"Price={current_price:.5f}"
        )
        log.info(msg)
        return msg

    # ── Place order ───────────────────────────────────────────────────────────
    log.info("Signal: {} at price {:.5f}", signal, current_price)
    trade_id = _place_order(client, signal, trade_units, current_price)

    pip = PIP_SIZE
    if signal == "BUY":
        sl = round(current_price - STOP_LOSS_PIPS   * pip, 5)
        tp = round(current_price + TAKE_PROFIT_PIPS * pip, 5)
    else:
        sl = round(current_price + STOP_LOSS_PIPS   * pip, 5)
        tp = round(current_price - TAKE_PROFIT_PIPS * pip, 5)

    msg = (
        f"{signal} {trade_units} units EUR/USD | "
        f"Entry={current_price:.5f}  SL={sl:.5f}  TP={tp:.5f} | "
        f"Trade ID={trade_id} | "
        f"EMA9={fast_now:.5f}  EMA21={slow_now:.5f}"
    )
    log.info("Order placed: {}", msg)
    return msg
