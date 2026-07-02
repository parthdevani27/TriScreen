"""Mutual-fund data layer (free sources, tested 2026-07).

  - mfapi.in        -> NAV history to inception + meta (category, ISIN)   [solid]
  - Kuvera (unoff.) -> AUM, expense ratio, manager, category, lock-in     [no SLA]
  - yfinance        -> benchmark PRICE index (TRI not free -> alpha caveat)

No Streamlit imports here (pure + thread-safe + unit-testable). Caching is an
in-process dict + on-disk CSV/JSON fallback under output/_mf_cache/, mirroring
the stock tool's screener_core._CACHE pattern.

CALIBRATED (verified against published AUM for 2 funds, 2026-07-02):
  Kuvera `aum` is scheme-level in units of ~Rs 10 lakh  ->  AUM_cr = aum / 10.
"""

from __future__ import annotations

import json
import os

import pandas as pd
import requests

MFAPI = "https://api.mfapi.in"
KUVERA = "https://mf.captnemo.in/kuvera"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "output", "_mf_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

_MEM: dict = {}
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def clear_cache():
    _MEM.clear()


def _get_json(url, timeout=25):
    r = requests.get(url, timeout=timeout, headers=_HEADERS)
    r.raise_for_status()
    return r.json()


def _num(x):
    try:
        f = float(x)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
#  Scheme search / resolution (mfapi)
# --------------------------------------------------------------------------- #
def search_schemes(query: str, limit: int = 40) -> list[dict]:
    try:
        d = _get_json(f"{MFAPI}/mf/search?q={requests.utils.quote(query)}")
        return d[:limit] if isinstance(d, list) else []
    except Exception:
        return []


def resolve_scheme(query: str) -> dict | None:
    """A user token -> {code, name}. Digits => scheme code. Else search and
    prefer the DIRECT + GROWTH plan (so TER/returns are direct-plan)."""
    q = (query or "").strip()
    if not q:
        return None
    if q.isdigit():
        return {"code": q, "name": None}
    hits = search_schemes(q, limit=60)
    if not hits:
        return None

    def score(h):
        n = (h.get("schemeName") or "").lower()
        s = 0
        if "direct" in n:
            s += 3
        if "growth" in n:
            s += 1
        if any(k in n for k in ("idcw", "dividend", "payout", "reinvest")):
            s -= 3
        if "regular" in n:
            s -= 2
        if any(k in n for k in ("bonus", "segregated", "annual", "half yearly", "quarterly")):
            s -= 4
        return s

    hits.sort(key=score, reverse=True)
    top = hits[0]
    return {"code": str(top.get("schemeCode")), "name": top.get("schemeName")}


# --------------------------------------------------------------------------- #
#  NAV history (mfapi) — memoized + disk fallback
# --------------------------------------------------------------------------- #
def fetch_nav_history(code: str):
    """Return (meta: dict, df: DataFrame[nav] indexed by date). Raises if no data
    and no disk fallback."""
    code = str(code).strip()
    key = f"nav:{code}"
    if key in _MEM:
        return _MEM[key]
    disk = os.path.join(CACHE_DIR, f"nav_{code}.csv")
    meta_disk = os.path.join(CACHE_DIR, f"meta_{code}.json")
    try:
        d = _get_json(f"{MFAPI}/mf/{code}")
        meta = d.get("meta", {}) or {}
        data = d.get("data", []) or []
        df = pd.DataFrame(data)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")
            df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
            df = df.dropna().sort_values("date").set_index("date")[["nav"]]
        try:
            df.to_csv(disk)
            with open(meta_disk, "w") as f:
                json.dump(meta, f)
        except Exception:
            pass
        res = (meta, df)
        _MEM[key] = res
        return res
    except Exception:
        if os.path.exists(disk):
            df = pd.read_csv(disk, index_col=0, parse_dates=True)
            meta = {}
            if os.path.exists(meta_disk):
                try:
                    meta = json.load(open(meta_disk))
                except Exception:
                    meta = {}
            meta["_stale"] = True
            return (meta, df)
        raise


# --------------------------------------------------------------------------- #
#  Enrichment (Kuvera) — AUM / TER / manager / category / lock-in
# --------------------------------------------------------------------------- #
def _parse_kuvera(d: dict) -> dict:
    aum = _num(d.get("aum"))
    return {
        "name": d.get("name"),
        "aum_cr": round(aum / 10, 1) if aum is not None else None,  # unit = Rs 10 lakh
        "aum_raw": aum,
        "expense_ratio": _num(d.get("expense_ratio")),
        "expense_ratio_date": d.get("expense_ratio_date"),
        "fund_manager": d.get("fund_manager"),
        "fund_category": d.get("fund_category"),
        "plan": d.get("plan"),
        "start_date": d.get("start_date"),
        "lock_in_period": _num(d.get("lock_in_period")),
        "crisil_rating": d.get("crisil_rating") or d.get("fund_rating"),
        "portfolio_turnover": _num(d.get("portfolio_turnover")),
        "isin": d.get("ISIN") or d.get("isin"),
        "stale": bool(d.get("_stale")),
    }


def fetch_enrichment(isin: str) -> dict:
    """Kuvera fund detail by ISIN. {} if unavailable (never raises)."""
    isin = (isin or "").strip()
    if not isin:
        return {}
    key = f"kuvera:{isin}"
    if key in _MEM:
        return _MEM[key]
    disk = os.path.join(CACHE_DIR, f"kuvera_{isin}.json")
    try:
        d = _get_json(f"{KUVERA}/{isin}")  # requests follows the redirect
        d = d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else {})
        out = _parse_kuvera(d)
        try:
            json.dump(out, open(disk, "w"))
        except Exception:
            pass
        _MEM[key] = out
        return out
    except Exception:
        if os.path.exists(disk):
            try:
                out = json.load(open(disk))
                out["stale"] = True
                return out
            except Exception:
                pass
        return {}


# --------------------------------------------------------------------------- #
#  Benchmark (yfinance PRICE index — TRI not free)
# --------------------------------------------------------------------------- #
def fetch_benchmark(symbol: str):
    """Return a tz-naive Close price Series, or None. Robust to yfinance symbols
    that reject period='max' (some NSE index tickers) by retrying with a start date."""
    key = f"bench:{symbol}"
    if key in _MEM:
        return _MEM[key]
    import yfinance as yf
    s = None
    for how in ("max", "start"):
        try:
            tk = yf.Ticker(symbol)
            h = (tk.history(period="max", auto_adjust=False) if how == "max"
                 else tk.history(start="2005-01-01", auto_adjust=False))
            cs = h["Close"].dropna()
            if len(cs) >= 100:
                s = cs
                break
        except Exception:
            continue
    if s is None or s.empty:
        return None
    s.index = pd.to_datetime(s.index).tz_localize(None)
    _MEM[key] = s
    return s


def fetch_benchmark_series(kind: str, ref: str):
    """Unified benchmark accessor. kind='yf' -> yfinance price index;
    kind='mf' -> an index-FUND NAV via mfapi (a TRI-equivalent for the exact
    category, used where a free price index isn't available, e.g. Smallcap 250)."""
    if kind == "mf":
        try:
            _, df = fetch_nav_history(ref)
            return df["nav"] if (df is not None and not df.empty) else None
        except Exception:
            return None
    return fetch_benchmark(ref)
