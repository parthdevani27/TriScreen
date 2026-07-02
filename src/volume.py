"""Volume analysis — VWAP position, OBV trend & divergence, volume profile."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import divergence


def analyze_volume(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    price = float(last["Close"])

    # VWAP positioning
    vwap = float(last["VWAP20"]) if not np.isnan(last["VWAP20"]) else None
    vwap_pos = None
    if vwap:
        vwap_pos = "above (buyers in control)" if price > vwap else "below (sellers in control)"

    # OBV trend (last 20 bars) + divergence vs price
    obv_tail = df["OBV"].tail(20)
    obv_trend = "rising (accumulation)" if obv_tail.iloc[-1] > obv_tail.iloc[0] else "falling (distribution)"
    obv_div = divergence(df["Close"], df["OBV"], lookback=40)

    # A/D line trend
    ad_tail = df["AD"].tail(20)
    ad_trend = "rising (accumulation)" if ad_tail.iloc[-1] > ad_tail.iloc[0] else "falling (distribution)"

    # Volume spike vs 20-day average
    vol = float(last["Volume"])
    vol_ma = float(last["Vol_MA20"]) if not np.isnan(last["Vol_MA20"]) else None
    vol_ratio = round(vol / vol_ma, 2) if vol_ma else None
    vol_state = None
    if vol_ratio is not None:
        if vol_ratio >= 2:
            vol_state = "high spike (strong participation)"
        elif vol_ratio >= 1.2:
            vol_state = "above average"
        elif vol_ratio <= 0.6:
            vol_state = "dried up (weak)"
        else:
            vol_state = "average"

    return {
        "vwap20": round(vwap, 2) if vwap else None,
        "price_vs_vwap": vwap_pos,
        "obv_trend": obv_trend,
        "obv_divergence": obv_div,
        "ad_trend": ad_trend,
        "volume_vs_avg_ratio": vol_ratio,
        "volume_state": vol_state,
    }


def volume_profile(df: pd.DataFrame, bins: int = 20, lookback: int = 250) -> dict:
    """Histogram of traded volume by price -> High/Low Volume Nodes (S/R)."""
    w = df.tail(lookback)
    prices = (w["High"] + w["Low"] + w["Close"]) / 3
    hist, edges = np.histogram(prices, bins=bins, weights=w["Volume"])
    centers = (edges[:-1] + edges[1:]) / 2
    poc_idx = int(np.argmax(hist))  # Point of Control = most-traded price
    return {
        "point_of_control": round(float(centers[poc_idx]), 2),
        "high_volume_nodes": [round(float(centers[i]), 2)
                              for i in np.argsort(hist)[-3:][::-1]],
        "low_volume_nodes": [round(float(centers[i]), 2)
                             for i in np.argsort(hist)[:3]],
    }
