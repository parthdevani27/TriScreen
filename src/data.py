"""Download full price history and resample."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from .common import resolve_symbol

# NSE regular equity session closes 15:30 IST; give the feed a few minutes to
# finalise the daily candle before we treat it as complete.
_IST = timezone(timedelta(hours=5, minutes=30))
_SESSION_DONE = (15, 35)  # (hour, minute) IST after which today's candle is final

_RESAMPLE = {"daily": None, "weekly": "W", "monthly": "ME"}


def download_history(name: str) -> tuple[str, "object", pd.DataFrame]:
    """Return (symbol, Ticker, full daily OHLCV from the very start).

    auto_adjust=True back-adjusts the OHLC series for splits AND dividends, so
    momentum / relative-strength / moving-average / support-resistance / R:R math
    reflect true economic return rather than raw quotes that dip on every ex-date.
    (Volume is left unadjusted by yfinance, which is correct for liquidity checks.)
    """
    symbol, tk = resolve_symbol(name)
    df = tk.history(period="max", interval="1d", auto_adjust=True)
    if df.empty:
        raise ValueError(f"No history available for {symbol}")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.index.name = "Date"
    return symbol, tk, df


def trim_partial_candle(daily: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Drop today's IN-PROGRESS daily candle if the NSE session hasn't closed yet.

    A mid-session data pull returns a partial candle with incomplete volume, which
    breaks C4 (volume-expansion) and shows a live, unsettled close. Trimming it means
    the screen always runs on the last COMPLETE session — so you can run it any time
    of day and get a stable, next-morning game plan (not just after 15:30 IST).
    """
    info = {"partial_trimmed": False, "partial_date": None}
    if len(daily) < 2:
        return daily, info
    try:
        last_ts = daily.index[-1]
        last_date = last_ts.date()
        now_ist = datetime.now(_IST)
        before_close = (now_ist.hour, now_ist.minute) < _SESSION_DONE
        if last_date == now_ist.date() and before_close:
            info = {"partial_trimmed": True, "partial_date": str(last_date)}
            return daily.iloc[:-1], info
    except Exception:
        pass
    return daily, info


def detect_corporate_action_gap(daily: pd.DataFrame, lookback: int = 190,
                                threshold: float = 0.25) -> dict:
    """Flag a suspiciously large single-day DROP in the recent (~9-month) window.

    Prices are auto-adjusted for splits & dividends, but yfinance does NOT cleanly
    adjust demergers / spin-offs (e.g. Vedanta, 2026). Those leave a huge one-day
    gap that looks like a crash but isn't — this catches what adjustment can't.
    A genuine one-day crash (fraud, results shock) trips it too; either way the
    honest call is the same: the derived stats may be distorted — verify.
    """
    close = daily["Close"].dropna().tail(lookback)
    if len(close) < 5:
        return {"suspect_gap": False}
    rets = close.pct_change().dropna()
    if rets.empty:
        return {"suspect_gap": False}
    worst = float(rets.min())
    if worst <= -threshold:
        return {"suspect_gap": True, "date": str(rets.idxmin().date()),
                "move_pct": round(worst * 100, 1)}
    return {"suspect_gap": False}


def resample_ohlcv(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    rule = _RESAMPLE[interval]
    if rule is None:
        return df
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    return df.resample(rule).agg(agg).dropna()
