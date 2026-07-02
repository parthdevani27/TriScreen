"""
Chart pattern detection (double top/bottom, head & shoulders) using swing pivots.
Pragmatic geometric rules — confirmation with volume/momentum is done in scorecard.
"""

from __future__ import annotations

import pandas as pd

from .levels import find_pivots


def _close(a, b, tol):
    return abs(a - b) / b <= tol


def detect_patterns(df: pd.DataFrame, order: int = 10, tol: float = 0.03) -> list[dict]:
    """Return recently-formed chart patterns from the last pivots."""
    p_high, p_low = find_pivots(df, order=order)
    patterns = []
    last = float(df["Close"].iloc[-1])

    highs = list(p_high.items())   # [(date, price), ...]
    lows = list(p_low.items())

    # --- Double Top: two similar recent peaks with a trough between ---------
    if len(highs) >= 2:
        (d1, h1), (d2, h2) = highs[-2], highs[-1]
        between_lows = [v for dt, v in lows if d1 < dt < d2]
        if _close(h1, h2, tol) and between_lows:
            neckline = min(between_lows)
            patterns.append({
                "pattern": "Double Top", "bias": "bearish",
                "formed": str(d2.date()), "neckline": round(neckline, 2),
                "target": round(neckline - (max(h1, h2) - neckline), 2),
                "confirmed": last < neckline,
            })

    # --- Double Bottom: two similar recent troughs with a peak between ------
    if len(lows) >= 2:
        (d1, l1), (d2, l2) = lows[-2], lows[-1]
        between_highs = [v for dt, v in highs if d1 < dt < d2]
        if _close(l1, l2, tol) and between_highs:
            neckline = max(between_highs)
            patterns.append({
                "pattern": "Double Bottom", "bias": "bullish",
                "formed": str(d2.date()), "neckline": round(neckline, 2),
                "target": round(neckline + (neckline - min(l1, l2)), 2),
                "confirmed": last > neckline,
            })

    # --- Head & Shoulders: 3 peaks, middle highest, shoulders similar ------
    if len(highs) >= 3:
        (da, a), (db, b), (dc, c) = highs[-3], highs[-2], highs[-1]
        if b > a and b > c and _close(a, c, tol):
            necks = [v for dt, v in lows if da < dt < dc]
            if necks:
                neckline = min(necks)
                patterns.append({
                    "pattern": "Head & Shoulders", "bias": "bearish",
                    "formed": str(dc.date()), "neckline": round(neckline, 2),
                    "target": round(neckline - (b - neckline), 2),
                    "confirmed": last < neckline,
                })

    # --- Inverse Head & Shoulders: 3 troughs, middle lowest ----------------
    if len(lows) >= 3:
        (da, a), (db, b), (dc, c) = lows[-3], lows[-2], lows[-1]
        if b < a and b < c and _close(a, c, tol):
            necks = [v for dt, v in highs if da < dt < dc]
            if necks:
                neckline = max(necks)
                patterns.append({
                    "pattern": "Inverse Head & Shoulders", "bias": "bullish",
                    "formed": str(dc.date()), "neckline": round(neckline, 2),
                    "target": round(neckline + (neckline - b), 2),
                    "confirmed": last > neckline,
                })

    return patterns
