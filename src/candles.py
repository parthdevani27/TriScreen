"""Candlestick pattern detection (rule-based), filtered for relevance."""

from __future__ import annotations

import pandas as pd


def _body(o, c):
    return abs(c - o)


def detect_candles(df: pd.DataFrame, lookback: int = 15) -> list[dict]:
    """
    Scan the last `lookback` bars for common candlestick patterns.
    Returns a dated list with a bullish/bearish bias.
    """
    out = []
    w = df.tail(lookback + 2)  # +2 so 2-bar patterns have context
    rows = list(w.itertuples())

    for i in range(2, len(rows)):
        c0, c1 = rows[i], rows[i - 1]
        o, h, l, c = c0.Open, c0.High, c0.Low, c0.Close
        rng = h - l if h != l else 1e-9
        body = _body(o, c)
        upper = h - max(o, c)
        lower = min(o, c) - l
        date = c0.Index.date()
        bull = c > o

        # Doji
        if body <= 0.1 * rng:
            out.append({"date": str(date), "pattern": "Doji", "bias": "neutral"})
        # Hammer (long lower shadow, small body near top)
        elif lower >= 2 * body and upper <= body:
            out.append({"date": str(date), "pattern": "Hammer", "bias": "bullish"})
        # Shooting Star (long upper shadow, small body near bottom)
        elif upper >= 2 * body and lower <= body:
            out.append({"date": str(date), "pattern": "Shooting Star", "bias": "bearish"})
        # Marubozu (very large body, tiny shadows)
        elif body >= 0.9 * rng:
            out.append({"date": str(date), "pattern": "Marubozu",
                        "bias": "bullish" if bull else "bearish"})

        # Engulfing (2-bar)
        po, pc = c1.Open, c1.Close
        if c > o and pc < po and c >= po and o <= pc:
            out.append({"date": str(date), "pattern": "Bullish Engulfing", "bias": "bullish"})
        elif c < o and pc > po and o >= pc and c <= po:
            out.append({"date": str(date), "pattern": "Bearish Engulfing", "bias": "bearish"})

    return out


def at_level(price: float, sr: dict, tolerance: float = 0.02) -> bool:
    """True if `price` sits near any support/resistance zone (adds reliability)."""
    zones = (sr.get("support_zones") or []) + (sr.get("resistance_zones") or [])
    return any(abs(price - z["level"]) / z["level"] <= tolerance for z in zones)
