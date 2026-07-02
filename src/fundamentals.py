"""Fundamentals, market regime, 6-month relative strength, quarterly earnings YoY."""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from .common import NIFTY


def _safe(info, key, default="N/A"):
    v = info.get(key, default)
    return default if v is None else v


def _pct(a, b):
    try:
        return (a - b) / b * 100
    except (TypeError, ZeroDivisionError):
        return None


def _market_regime(nclose: pd.Series) -> str:
    """bull / sideways / bear from NIFTY (50-EMA position + 20-bar slope)."""
    if len(nclose) < 60:
        return "unknown"
    ema50 = nclose.ewm(span=50, adjust=False).mean()
    slope = (ema50.iloc[-1] - ema50.iloc[-20]) / ema50.iloc[-20] * 100
    above = nclose.iloc[-1] > ema50.iloc[-1]
    if above and slope > 1:
        return "bull"
    if not above and slope < -1:
        return "bear"
    return "sideways"


def _earnings_yoy(tk) -> dict:
    """Latest-quarter revenue & EPS growth YoY (best-effort, may be unavailable)."""
    res = {"available": False, "revenue_yoy": None, "eps_yoy": None}
    try:
        q = tk.quarterly_income_stmt
        if q is None or q.empty or q.shape[1] < 5:
            return res
        cols = list(q.columns)  # most-recent first

        def yoy(rownames):
            for r in rownames:
                if r in q.index:
                    s = q.loc[r]
                    a, b = s.iloc[0], s.iloc[4]
                    g = _pct(a, b)
                    if g is not None and g == g:
                        return round(g, 1)
            return None

        res["revenue_yoy"] = yoy(["Total Revenue", "Operating Revenue"])
        res["eps_yoy"] = yoy(["Diluted EPS", "Basic EPS"])
        if res["eps_yoy"] is None:
            res["eps_yoy"] = yoy(["Net Income", "Net Income Common Stockholders"])
        res["available"] = res["revenue_yoy"] is not None or res["eps_yoy"] is not None
    except Exception:
        pass
    return res


def _fnum(x):
    """Coerce to a finite float, else None."""
    try:
        f = float(x)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _stmt_row(dfr, names):
    """Most-recent value of the first matching row in a statement frame."""
    if dfr is None or getattr(dfr, "empty", True):
        return None
    for n in names:
        if n in dfr.index:
            v = _fnum(dfr.loc[n].iloc[0])
            if v is not None:
                return v
    return None


def _compute_roce(tk):
    """ROCE = EBIT / (Total Assets - Current Liabilities). Meaningless for banks."""
    try:
        fin, bs = tk.financials, tk.balance_sheet
        ebit = _stmt_row(fin, ["EBIT", "Operating Income"])
        ta = _stmt_row(bs, ["Total Assets"])
        cl = _stmt_row(bs, ["Current Liabilities"])
        if ebit is not None and ta and cl and (ta - cl) > 0:
            return round(ebit / (ta - cl) * 100, 1)
    except Exception:
        pass
    return None


def _interest_coverage(tk):
    """Interest coverage = EBIT / |Interest Expense| (times)."""
    try:
        fin = tk.financials
        ebit = _stmt_row(fin, ["EBIT", "Operating Income"])
        ie = _stmt_row(fin, ["Interest Expense"])
        if ebit is not None and ie:
            ie = abs(ie)
            if ie > 0:
                return round(ebit / ie, 1)
    except Exception:
        pass
    return None


def gather_quality_metrics(tk, df: pd.DataFrame, info: dict) -> dict:
    """Live fundamental snapshot (valuation / quality / health / cash-flow /
    analyst / ownership). Yahoo-only, current snapshot, sector-aware. Bank-style
    balance-sheet ratios are set N/A for financials (they don't apply)."""
    sector = info.get("sector") or ""
    industry = info.get("industry") or ""
    is_financial = ("Financial" in sector) or ("Bank" in industry) or ("Insurance" in industry)

    price = _fnum(info.get("currentPrice")) or float(df["Close"].iloc[-1])
    de_raw = _fnum(info.get("debtToEquity"))          # Yahoo reports this as a PERCENT
    de_ratio = round(de_raw / 100, 2) if de_raw is not None else None

    target = _fnum(info.get("targetMeanPrice"))
    upside = round((target - price) / price * 100, 1) if (target and price) else None

    def _pct(k):
        v = _fnum(info.get(k))
        return round(v * 100, 1) if v is not None else None

    return {
        "sector": sector, "industry": industry, "is_financial": is_financial,
        "price": round(price, 2) if price else None,
        "valuation": {
            "pe_trailing": _fnum(info.get("trailingPE")),
            "pe_forward": _fnum(info.get("forwardPE")),
            "pb": _fnum(info.get("priceToBook")),
            "ev_ebitda": _fnum(info.get("enterpriseToEbitda")),
        },
        "profitability": {
            "roe_pct": _pct("returnOnEquity"),
            "roce_pct": None if is_financial else _compute_roce(tk),
            "roa_pct": _pct("returnOnAssets"),
            "net_margin_pct": _pct("profitMargins"),
            "operating_margin_pct": _pct("operatingMargins"),
        },
        "health": {
            "debt_to_equity": None if is_financial else de_ratio,
            "current_ratio": None if is_financial else _fnum(info.get("currentRatio")),
            "interest_coverage": None if is_financial else _interest_coverage(tk),
        },
        "cashflow": {
            "free_cashflow": None if is_financial else _fnum(info.get("freeCashflow")),
            "operating_cashflow": _fnum(info.get("operatingCashflow")),
        },
        "growth": {
            "revenue_growth_pct": _pct("revenueGrowth"),
            "earnings_growth_pct": _pct("earningsGrowth"),
        },
        "analyst": {
            "target_mean": round(target, 1) if target else None,
            "upside_pct": upside,
            "recommendation": info.get("recommendationKey"),
            "num_analysts": info.get("numberOfAnalystOpinions"),
        },
        "ownership": {
            "institutions_pct": _pct("heldPercentInstitutions"),
            "insiders_pct": _pct("heldPercentInsiders"),
        },
        "dividend": {
            "yield_pct": _fnum(info.get("dividendYield")),
            "payout_pct": _pct("payoutRatio"),
        },
    }


def gather_fundamentals(tk, df: pd.DataFrame) -> dict:
    try:
        info = tk.info or {}
    except Exception:
        info = {}

    last = float(df["Close"].iloc[-1])
    hi52 = float(df["Close"].tail(252).max())
    lo52 = float(df["Close"].tail(252).min())
    avg_vol_20 = float(df["Volume"].tail(20).mean())

    # Market regime + relative strength vs NIFTY over 3m AND 6m. For a short
    # (1-week-to-few-months) horizon the 3-month window is the primary momentum
    # read (it turns faster than 6m); 6m is kept as context / fallback.
    regime, rel = "unknown", None
    try:
        nclose = yf.Ticker(NIFTY).history(period="1y")["Close"]
        regime = _market_regime(nclose)

        def _rs(n):
            if n <= 20 or n >= len(nclose) or n >= len(df):
                return None
            nret = _pct(nclose.iloc[-1], nclose.iloc[-n])
            sret = _pct(last, float(df["Close"].iloc[-n]))
            if nret is None or sret is None:
                return None
            return {"stock": round(sret, 2), "nifty": round(nret, 2), "out": sret > nret}

        r6 = _rs(min(126, len(nclose) - 1, len(df) - 1))   # ~6 months
        r3 = _rs(min(63, len(nclose) - 1, len(df) - 1))    # ~3 months
        if r6 or r3:
            rel = {
                "stock_6m_return_pct": r6["stock"] if r6 else None,
                "nifty_6m_return_pct": r6["nifty"] if r6 else None,
                "stock_3m_return_pct": r3["stock"] if r3 else None,
                "nifty_3m_return_pct": r3["nifty"] if r3 else None,
                # short horizon → judge primarily on 3-month, fall back to 6-month
                "outperforming": (r3["out"] if r3 else r6["out"]),
                "outperforming_3m": r3["out"] if r3 else None,
                "outperforming_6m": r6["out"] if r6 else None,
            }
    except Exception:
        pass

    # Next earnings date
    earnings_date = "N/A"
    try:
        cal = tk.calendar
        if isinstance(cal, dict) and cal.get("Earnings Date"):
            ed = cal["Earnings Date"]
            earnings_date = str(ed[0] if isinstance(ed, (list, tuple)) else ed)
    except Exception:
        pass

    return {
        "identity": {
            "name": _safe(info, "longName"),
            "sector": _safe(info, "sector"),
            "industry": _safe(info, "industry"),
        },
        "price": {
            "last": round(last, 2),
            "week52_high": round(hi52, 2),
            "week52_low": round(lo52, 2),
            "pct_from_52w_high": round(_pct(last, hi52), 2),
            "pct_above_52w_low": round(_pct(last, lo52), 2),
        },
        "valuation": {
            "market_cap": _safe(info, "marketCap"),
            "pe_trailing": _safe(info, "trailingPE"),
            "pb": _safe(info, "priceToBook"),
            "eps": _safe(info, "trailingEps"),
        },
        "health": {
            "roe": _safe(info, "returnOnEquity"),
            "debt_to_equity": _safe(info, "debtToEquity"),
            "profit_margin": _safe(info, "profitMargins"),
            "revenue_growth": _safe(info, "revenueGrowth"),
        },
        "liquidity": {"avg_daily_volume_20": int(avg_vol_20) if avg_vol_20 == avg_vol_20 else "N/A"},
        "market_regime": regime,
        "relative_strength": rel,
        "earnings_growth": _earnings_yoy(tk),
        "next_earnings_date": earnings_date,
        "quality": gather_quality_metrics(tk, df, info),
    }
