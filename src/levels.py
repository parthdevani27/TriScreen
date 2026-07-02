"""Support/Resistance zones (via swing-pivot detection) + Fibonacci levels."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def find_pivots(df: pd.DataFrame, order: int = 10):
    """Return (pivot_highs, pivot_lows) as Series of price at swing points."""
    highs = df["High"].values
    lows = df["Low"].values
    hi_idx = argrelextrema(highs, np.greater, order=order)[0]
    lo_idx = argrelextrema(lows, np.less, order=order)[0]
    return (
        pd.Series(df["High"].iloc[hi_idx].values, index=df.index[hi_idx]),
        pd.Series(df["Low"].iloc[lo_idx].values, index=df.index[lo_idx]),
    )


def cluster_levels(prices, tolerance=0.02):
    """Group nearby pivot prices into zones. Returns sorted list of zone centers."""
    if len(prices) == 0:
        return []
    vals = sorted(float(p) for p in prices)
    clusters = [[vals[0]]]
    for v in vals[1:]:
        if abs(v - clusters[-1][-1]) / clusters[-1][-1] <= tolerance:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    # zone strength = number of touches
    return [{"level": round(float(np.mean(c)), 2), "touches": len(c)} for c in clusters]


def support_resistance(df: pd.DataFrame, order: int = 10, tolerance: float = 0.02,
                       lookback: int = 252, max_each: int = 6):
    """
    Clustered S/R zones near the current price + nearest support/resistance.
    Uses only the last `lookback` bars so old (pre-split) prices don't pollute
    the result — what matters for short-term trading is recent structure.
    """
    window = df.tail(lookback)
    p_high, p_low = find_pivots(window, order=order)
    resistance = cluster_levels(p_high.values, tolerance)
    support = cluster_levels(p_low.values, tolerance)
    last = float(df["Close"].iloc[-1])

    res_above = sorted([z for z in resistance if z["level"] > last], key=lambda z: z["level"])
    sup_below = sorted([z for z in support if z["level"] < last], key=lambda z: z["level"], reverse=True)

    # Keep only the closest few zones each side (most relevant for trading).
    return {
        "resistance_zones": res_above[:max_each],
        "support_zones": sup_below[:max_each],
        "nearest_resistance": res_above[0] if res_above else None,
        "nearest_support": sup_below[0] if sup_below else None,
        "last_price": round(last, 2),
    }


def fibonacci(df: pd.DataFrame, lookback: int = 120):
    """Fibonacci retracement over the last `lookback` bars (swing high->low)."""
    window = df.tail(lookback)
    hi = float(window["High"].max())
    lo = float(window["Low"].min())
    diff = hi - lo
    levels = {
        "0%": round(hi, 2),
        "23.6%": round(hi - 0.236 * diff, 2),
        "38.2%": round(hi - 0.382 * diff, 2),
        "50%": round(hi - 0.5 * diff, 2),
        "61.8%": round(hi - 0.618 * diff, 2),
        "78.6%": round(hi - 0.786 * diff, 2),
        "100%": round(lo, 2),
    }
    return {"swing_high": round(hi, 2), "swing_low": round(lo, 2), "levels": levels}
