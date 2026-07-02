"""All technical indicators, computed with pandas/numpy (no TA-Lib needed)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    al = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = ag / al
    return 100 - (100 / (1 + rs))


def macd(s: pd.Series, fast=12, slow=26, signal=9):
    line = ema(s, fast) - ema(s, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def true_range(df: pd.DataFrame) -> pd.Series:
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"] - df["Close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def bollinger(s: pd.Series, period=20, num_std=2.0):
    mid = s.rolling(period).mean()
    std = s.rolling(period).std()
    return mid, mid + num_std * std, mid - num_std * std


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume — accumulation/distribution proxy."""
    direction = np.sign(df["Close"].diff().fillna(0))
    return (direction * df["Volume"]).cumsum()


def ad_line(df: pd.DataFrame) -> pd.Series:
    """Accumulation/Distribution line (volume weighted by close location)."""
    rng = (df["High"] - df["Low"]).replace(0, np.nan)
    mfm = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / rng
    mfm = mfm.fillna(0)
    return (mfm * df["Volume"]).cumsum()


def rolling_vwap(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Rolling VWAP over `period` bars (daily-data friendly)."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    pv = (tp * df["Volume"]).rolling(period).sum()
    vol = df["Volume"].rolling(period).sum()
    return pv / vol


def adx(df: pd.DataFrame, period: int = 14):
    """Return (adx, plus_di, minus_di) — trend strength & direction."""
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(df)
    atr_ = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index)
                     .ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index)
                      .ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_ = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx_, plus_di, minus_di


def stochastic(df: pd.DataFrame, k=14, d=3):
    low_k = df["Low"].rolling(k).min()
    high_k = df["High"].rolling(k).max()
    pct_k = 100 * (df["Close"] - low_k) / (high_k - low_k).replace(0, np.nan)
    return pct_k, pct_k.rolling(d).mean()


def supertrend(df: pd.DataFrame, period=10, multiplier=3.0):
    """Classic Supertrend. Returns (supertrend_line, direction[1=up,-1=down])."""
    atr_ = atr(df, period)
    hl2 = (df["High"] + df["Low"]) / 2
    upper = hl2 + multiplier * atr_
    lower = hl2 - multiplier * atr_

    st = pd.Series(index=df.index, dtype="float64")
    dir_ = pd.Series(index=df.index, dtype="float64")
    close = df["Close"]
    fu, fl, prev_dir = np.nan, np.nan, 1
    for i in range(len(df)):
        if i == 0 or np.isnan(atr_.iloc[i]):
            fu, fl, prev_dir = upper.iloc[i], lower.iloc[i], 1
            st.iloc[i], dir_.iloc[i] = lower.iloc[i], 1
            continue
        fu = min(upper.iloc[i], fu) if close.iloc[i - 1] <= fu else upper.iloc[i]
        fl = max(lower.iloc[i], fl) if close.iloc[i - 1] >= fl else lower.iloc[i]
        if close.iloc[i] > fu:
            prev_dir = 1
        elif close.iloc[i] < fl:
            prev_dir = -1
        dir_.iloc[i] = prev_dir
        st.iloc[i] = fl if prev_dir == 1 else fu
    return st, dir_


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the full indicator set used across the analysis modules."""
    out = df.copy()
    out["EMA20"] = ema(out["Close"], 20)
    out["EMA50"] = ema(out["Close"], 50)
    out["EMA200"] = ema(out["Close"], 200)
    out["SMA50"] = out["Close"].rolling(50).mean()
    out["SMA150"] = out["Close"].rolling(150).mean()
    out["SMA200"] = out["Close"].rolling(200).mean()
    out["RSI14"] = rsi(out["Close"], 14)
    out["MACD"], out["MACD_signal"], out["MACD_hist"] = macd(out["Close"])
    out["ATR14"] = atr(out, 14)
    out["BB_mid"], out["BB_upper"], out["BB_lower"] = bollinger(out["Close"])
    out["Vol_MA20"] = out["Volume"].rolling(20).mean()
    out["OBV"] = obv(out)
    out["AD"] = ad_line(out)
    out["VWAP20"] = rolling_vwap(out, 20)
    out["ADX14"], out["plus_DI"], out["minus_DI"] = adx(out, 14)
    out["Stoch_K"], out["Stoch_D"] = stochastic(out)
    out["Supertrend"], out["ST_dir"] = supertrend(out)
    return out


def divergence(price: pd.Series, indicator: pd.Series, lookback: int = 40) -> str:
    """
    Crude price-vs-indicator divergence over the last `lookback` bars.
    Returns 'bullish', 'bearish', or 'none'.
    """
    p = price.tail(lookback)
    ind = indicator.tail(lookback)
    if len(p) < lookback // 2:
        return "none"
    price_up = p.iloc[-1] > p.iloc[0]
    ind_up = ind.iloc[-1] > ind.iloc[0]
    if price_up and not ind_up:
        return "bearish"   # price higher, indicator weaker
    if not price_up and ind_up:
        return "bullish"   # price lower, indicator stronger
    return "none"
