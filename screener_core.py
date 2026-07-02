"""
UI-facing wrapper around the analysis pipeline (src.main.analyze).

Responsibilities:
  - run one stock, or a batch of stocks in parallel (I/O-bound downloads)
  - in-process memoization so re-screening the same ticker is instant
  - normalise each result into a flat summary row + a plain-language VERDICT
  - load the saved OHLCV for charting

Honesty note (carried from PROJECT_CONTEXT.md): the score is a *setup / risk*
screener, NOT a profit predictor. The realistic edge is only a few percentage
points and only for 1-2 month+ holds with strict stops. Verdicts below reflect
setup quality, not a promise of returns.
"""

from __future__ import annotations

import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from src.main import analyze, OUTPUT_ROOT
from src.common import resolve_symbol


# ---------------------------------------------------------------------------
# Lightweight ticker VERIFICATION (fast pre-flight check before a full run).
# resolve_symbol tries .NS then .BO with a 5-day history probe — cheap.
# ---------------------------------------------------------------------------
def verify_ticker(name: str) -> dict:
    n = (name or "").strip()
    if not n:
        return {"name": name, "valid": False, "symbol": None, "reason": "empty"}
    try:
        symbol, _ = resolve_symbol(n)
        return {"name": n, "valid": True, "symbol": symbol, "reason": ""}
    except Exception as e:
        return {"name": n, "valid": False, "symbol": None,
                "reason": str(e).split(".")[0][:90] or "not found on Yahoo (NSE/BSE)"}


def verify_tickers(names, max_workers=8, progress_cb=None) -> list[dict]:
    names = [x.strip() for x in names if x and x.strip()]
    seen, ordered = set(), []
    for n in names:
        u = n.upper()
        if u not in seen:
            seen.add(u)
            ordered.append(n)
    results, done, total = {}, 0, len(ordered)
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, total))) as ex:
        futs = {ex.submit(verify_ticker, n): n for n in ordered}
        for fut in as_completed(futs):
            n = futs[fut]
            try:
                results[n] = fut.result()
            except Exception as e:
                results[n] = {"name": n, "valid": False, "symbol": None, "reason": str(e)[:90]}
            done += 1
            if progress_cb:
                progress_cb(done, total, n)
    return [results[n] for n in ordered]


# ---------------------------------------------------------------------------
# In-process cache (survives Streamlit reruns within the same server process).
# Keyed by (upper-cased name, interval, with_news).
# ---------------------------------------------------------------------------
_CACHE: dict[tuple, dict] = {}


def _key(name: str, interval: str, with_news: bool) -> tuple:
    return (name.strip().upper(), interval, bool(with_news))


def analyze_cached(name: str, interval: str = "daily", with_news: bool = False) -> dict:
    """analyze() with memoization. Returns the raw result dict (+ '_error' on failure)."""
    k = _key(name, interval, with_news)
    if k in _CACHE:
        return _CACHE[k]
    try:
        res = analyze(name.strip(), interval, with_news=with_news)
        res["_error"] = None
    except Exception as e:  # network / bad ticker / insufficient history
        res = {"_error": f"{type(e).__name__}: {e}",
               "_trace": traceback.format_exc(), "stock": name.strip().upper(),
               "input_name": name.strip()}
    _CACHE[k] = res
    return res


def clear_cache():
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Verdict logic — maps the scorecard band to a plain-language call.
# ---------------------------------------------------------------------------
def _verdict(score: dict) -> tuple[str, str]:
    """Return (verdict, rationale). Deliberately conservative.

    A count of passed criteria decides the base band, but a conviction ("STRONG
    SETUP") call additionally REQUIRES the risk side to be sound: it is capped to
    WATCH when the reward:risk is below 1:1, when there's no structural stop within
    8%, or when the stock is over-extended above its 50-DMA (a bad entry). Those
    are exactly the risk failures that a pure pass-count would otherwise ignore.
    """
    best = score.get("best_case_score", 0)
    confirmed = score.get("confirmed_score", 0)
    rr = score.get("risk_reward")
    et = score.get("entry_timing") or {}
    extended = bool(et.get("extended"))
    spiked = bool(et.get("spiked_today"))
    structural = bool(score.get("stop_structural"))

    # Hard gate: a broken reward:risk (< 1:1 — you'd risk more than the target
    # payoff) is never worth watching, no matter how many setup boxes tick.
    if rr is not None and rr < MIN_TRADEABLE_RR:
        return "AVOID", (f"Reward:risk is only {rr:.1f}:1 — you'd risk more than the target "
                         "payoff. Not tradeable regardless of the setup score.")

    if best >= 9 and confirmed >= 6:
        blockers = []
        if not structural:
            blockers.append("no structural stop-loss within 8%")
        if extended:
            blockers.append("price is over-extended above its 50-DMA")
        if spiked:
            dm = et.get("day_move_pct")
            blockers.append(f"it spiked ~{dm:.0f}% today (don't chase — wait for a pullback)"
                            if isinstance(dm, (int, float)) else "it spiked today (don't chase)")
        if blockers:
            return "WATCH", ("Meets the technical criteria but held back from a conviction buy — "
                             + "; ".join(blockers) + ". Wait for a cleaner entry.")
        return "STRONG SETUP", "Meets almost all technical criteria — verify the 2 manual checks (pledge, FII/DII) before buying."
    if best >= 7:
        return "WATCH", "A partial setup: some momentum/structure criteria pass but not all. Wait for a cleaner trigger."
    return "AVOID", "Lacks the momentum + structure for a 1-2 month positional hold right now."


_VERDICT_RANK = {"STRONG SETUP": 0, "WATCH": 1, "AVOID": 2}

# A reward:risk below this is "broken" — you'd risk more than the reward — and is
# hard-routed to AVOID. (The C9 criterion still wants >=3:1; this is only the floor
# below which a stock is not worth watching at all.)
MIN_TRADEABLE_RR = 1.0


# ---------------------------------------------------------------------------
# Fundamental QUALITY assessment (separate from the technical setup score).
# Live snapshot only — NOT backtested. Frames quality/risk, not predicted return.
# ---------------------------------------------------------------------------
def _fmt(v, suffix="", prefix="", nd=1):
    if v is None:
        return "—"
    return f"{prefix}{v:,.{nd}f}{suffix}"


def quality_assessment(q: dict) -> dict:
    """Grade the live fundamental snapshot into transparent GOOD/OK/WARN/BAD checks."""
    empty = {"checks": [], "rating": "No data", "good": 0, "applicable": 0,
             "pe": None, "analyst_upside": None, "analyst_rec": None}
    if not q:
        return empty

    val = q.get("valuation", {}); prof = q.get("profitability", {})
    hlth = q.get("health", {}); cf = q.get("cashflow", {})
    ana = q.get("analyst", {}); gro = q.get("growth", {})
    is_fin = q.get("is_financial")
    checks = []  # (group, label, value_str, status, note)

    # ---- Valuation (are you overpaying?) ----
    pe = val.get("pe_trailing") or val.get("pe_forward")
    if pe is not None:
        st = "GOOD" if pe < 25 else "OK" if pe < 40 else "WARN" if pe < 60 else "BAD"
        checks.append(("Valuation", "P/E ratio", _fmt(pe, nd=1), st,
                       "Compare to sector peers & the stock's own history — a high P/E can be justified by growth."))
    pb = val.get("pb")
    if pb is not None:
        lim1, lim2 = (3, 6) if is_fin else (8, 15)
        st = "GOOD" if pb < lim1 else "WARN" if pb < lim2 else "BAD"
        checks.append(("Valuation", "Price / Book", _fmt(pb, nd=1), st, ""))
    ev = val.get("ev_ebitda")
    if ev is not None and not is_fin:
        st = "GOOD" if ev < 15 else "OK" if ev < 25 else "WARN"
        checks.append(("Valuation", "EV / EBITDA", _fmt(ev, nd=1), st, ""))

    # ---- Quality / profitability ----
    roe = prof.get("roe_pct")
    if roe is not None:
        st = "GOOD" if roe >= 15 else "OK" if roe >= 12 else "WARN" if roe >= 8 else "BAD"
        checks.append(("Quality", "Return on Equity (ROE)", _fmt(roe, "%"), st,
                       "Profit earned per rupee of shareholder money."))
    roce = prof.get("roce_pct")
    if roce is not None:
        st = "GOOD" if roce >= 15 else "OK" if roce >= 12 else "WARN"
        checks.append(("Quality", "Return on Capital (ROCE)", _fmt(roce, "%"), st,
                       "Return on all capital used — should beat the ~12% cost of capital."))
    nm = prof.get("net_margin_pct")
    if nm is not None:
        st = "GOOD" if nm >= 12 else "OK" if nm >= 5 else "WARN" if nm >= 0 else "BAD"
        checks.append(("Quality", "Net profit margin", _fmt(nm, "%"), st, ""))

    # ---- Balance-sheet health (non-financials) ----
    if is_fin:
        checks.append(("Health", "Bank balance-sheet metrics", "see manual review", "NA",
                       "Banks use NIM / GNPA / CASA / capital adequacy — not in free data."))
    else:
        de = hlth.get("debt_to_equity")
        if de is not None:
            st = "GOOD" if de < 0.5 else "OK" if de < 1 else "WARN" if de < 2 else "BAD"
            checks.append(("Health", "Debt / Equity", _fmt(de, "x", nd=2), st,
                           "Higher = more fragile if rates rise or sales fall."))
        cr = hlth.get("current_ratio")
        if cr is not None:
            st = "GOOD" if cr >= 1.5 else "OK" if cr >= 1 else "WARN"
            checks.append(("Health", "Current ratio", _fmt(cr, "x", nd=2), st,
                           "Short-term assets vs short-term dues (>1 is safer)."))
        ic = hlth.get("interest_coverage")
        if ic is not None:
            st = "GOOD" if ic >= 5 else "OK" if ic >= 3 else "WARN"
            checks.append(("Health", "Interest coverage", _fmt(ic, "x", nd=1), st,
                           "Profit vs interest bill (higher = safer debt)."))

    # ---- Cash flow (non-financials) ----
    if not is_fin:
        fcf = cf.get("free_cashflow")
        if fcf is not None:
            st = "GOOD" if fcf > 0 else "WARN"
            checks.append(("Cash flow", "Free cash flow", "positive" if fcf > 0 else "negative", st,
                           "Are profits backed by real cash? Negative can be OK during heavy capex — check why."))

    # ---- Analyst consensus (only free forward-ish signal) ----
    rec = ana.get("recommendation"); up = ana.get("upside_pct"); nA = ana.get("num_analysts")
    if rec or up is not None:
        pos = rec in ("strong_buy", "buy")
        st = "GOOD" if (pos and (up or 0) >= 10) else "OK" if (up or 0) >= 0 else "WARN"
        rec_txt = (rec or "n/a").replace("_", " ")
        up_txt = _fmt(up, "%", prefix="+" if (up or 0) >= 0 else "")
        checks.append(("Analyst view", "Consensus & 12-mo target", f"{rec_txt}, {up_txt} ({nA or '?'} analysts)",
                       st, "Analysts herd and are often wrong — a weak proxy for the future, not proof."))

    # ---- Growth ----
    rg = gro.get("revenue_growth_pct")
    if rg is not None:
        st = "GOOD" if rg >= 15 else "OK" if rg >= 5 else "WARN"
        checks.append(("Growth", "Revenue growth (YoY)", _fmt(rg, "%", prefix="+" if rg >= 0 else ""), st, ""))

    scored = [c for c in checks if c[3] != "NA"]
    good = sum(1 for c in scored if c[3] == "GOOD")
    ok = sum(1 for c in scored if c[3] == "OK")
    applicable = len(scored)
    ratio = (good + 0.5 * ok) / applicable if applicable else 0
    if applicable < 4:
        rating = "Insufficient data"
    elif ratio >= 0.7:
        rating = "Strong"
    elif ratio >= 0.45:
        rating = "Mixed"
    else:
        rating = "Weak"

    return {"checks": [{"group": g, "label": l, "value": v, "status": s, "note": n}
                       for (g, l, v, s, n) in checks],
            "rating": rating, "good": good, "applicable": applicable,
            "pe": round(pe, 1) if pe is not None else None,
            "analyst_upside": up, "analyst_rec": rec}


def manual_review_items(res: dict) -> list[dict]:
    """The checks the tool CANNOT do from free data — surfaced so the user knows."""
    fund = res.get("fundamentals", {}) or {}
    q = fund.get("quality", {}) or {}
    items = [
        {"sev": "high", "title": "Promoter pledge & insider selling (C7)",
         "detail": "A high or rising promoter share-pledge, or promoters selling, is a serious red flag.",
         "where": "screener.in · nseindia.com (shareholding) · trendlyne"},
        {"sev": "high", "title": "Institutional trend — FII / DII / MF (C8)",
         "detail": "We show a current holding-% snapshot, but not whether big investors are net buying or selling over the last 2 quarters.",
         "where": "trendlyne · screener.in (shareholding pattern)"},
        {"sev": "high", "title": "Governance & accounting quality",
         "detail": "Auditor changes, related-party transactions, contingent liabilities, promoter conduct. No ratio catches fraud (see IndusInd).",
         "where": "annual report · audit notes · exchange disclosures"},
        {"sev": "medium", "title": "Forward guidance & management commentary",
         "detail": "The market prices the FUTURE; this tool only measures the past. Read what management is guiding for the coming quarters.",
         "where": "latest earnings-call transcript · investor presentation"},
    ]
    dq = res.get("data_quality") or {}
    if dq.get("suspect_gap"):
        items.insert(0, {
            "sev": "high", "title": "Possible unadjusted corporate action (data integrity)",
            "detail": (f"A ~{dq.get('move_pct')}% single-day move on {dq.get('date')} looks like an "
                       "unadjusted demerger / spin-off (yfinance doesn't adjust these) rather than a "
                       "real crash. If so, this stock's 6-month return, moving averages, support/"
                       "resistance and reward:risk are DISTORTED — don't trust the setup until verified."),
            "where": "nseindia.com (corporate actions) · screener.in · the company's exchange filings"})
    blob = (q.get("sector") or "") + " " + (q.get("industry") or "")
    if any(k in blob for k in ("Industrial", "Aerospace", "Defense", "Construction",
                               "Engineering", "Infrastructure", "Machinery")):
        items.append({"sev": "medium", "title": "Order-book execution & capacity",
                      "detail": "A large order book only becomes profit if the company can actually execute and convert it to revenue on time.",
                      "where": "concall · management guidance on execution & margins"})
    if q.get("is_financial"):
        items.append({"sev": "high", "title": "Bank / NBFC health metrics",
                      "detail": "NIM, Gross/Net NPA, slippages, CASA, capital adequacy (CAR), provisioning — none come from free price data.",
                      "where": "bank's quarterly investor presentation · screener.in"})
    if not (fund.get("earnings_growth", {}) or {}).get("available"):
        items.append({"sev": "medium", "title": "Latest quarterly earnings (data gap)",
                      "detail": "Quarterly revenue/EPS growth was unavailable from the feed — verify the most recent results yourself.",
                      "where": "screener.in · company results"})
    val = q.get("valuation", {}) or {}
    pe = val.get("pe_trailing") or val.get("pe_forward")
    if pe is not None and pe >= 40:
        items.append({"sev": "medium", "title": f"Rich valuation (P/E ≈ {pe:.0f}) — justify it",
                      "detail": "A high multiple only makes sense if growth is strong and durable. Compare to sector peers and the stock's own 5-yr range.",
                      "where": "screener.in (peer comparison · historical P/E)"})
    return items


def summarize(res: dict) -> dict:
    """Flatten a raw result dict into one table row."""
    if res.get("_error"):
        return {"stock": res.get("stock", "?"), "error": res["_error"],
                "verdict": "ERROR", "confirmed": None, "best_case": None,
                "price": None, "rs_6m": None, "rs_3m": None, "rr": None,
                "atr_target": None, "atr_rr": None, "upside_pct": None,
                "stop_dist_pct": None, "band": None, "as_of": None,
                "pe": None, "quality_rating": None, "analyst_upside": None, "analyst_rec": None,
                "extended": None, "spiked_today": None, "day_move_pct": None,
                "poor_entry": None, "entry_note": None, "stop_structural": None,
                "data_flag": False, "data_flag_detail": {}, "partial_trimmed": False}

    score = res.get("scorecard", {})
    fund = res.get("fundamentals", {})
    rs = fund.get("relative_strength") or {}
    qa = quality_assessment(fund.get("quality") or {})
    verdict, rationale = _verdict(score)

    return {
        "pe": qa["pe"],
        "quality_rating": qa["rating"],
        "quality_good": qa["good"],
        "quality_applicable": qa["applicable"],
        "analyst_upside": qa["analyst_upside"],
        "analyst_rec": qa["analyst_rec"],
        "stock": res.get("stock"),
        "symbol": res.get("symbol"),
        "as_of": res.get("as_of"),
        "verdict": verdict,
        "rationale": rationale,
        "confirmed": score.get("confirmed_score"),
        "best_case": score.get("best_case_score"),
        "band": score.get("band"),
        "action": score.get("action"),
        "price": _last_price(res),
        "rs_6m": rs.get("stock_6m_return_pct"),
        "rs_3m": rs.get("stock_3m_return_pct"),
        "nifty_6m": rs.get("nifty_6m_return_pct"),
        "outperforming": rs.get("outperforming"),
        "rr": score.get("risk_reward"),
        "atr_target": score.get("atr_target"),
        "atr_rr": score.get("atr_rr"),
        "target_price": score.get("target_price"),
        "upside_pct": score.get("upside_pct"),
        "stop_price": score.get("stop_price"),
        "stop_dist_pct": score.get("stop_dist_pct"),
        "stop_structural": score.get("stop_structural"),
        "extended": (score.get("entry_timing") or {}).get("extended"),
        "spiked_today": (score.get("entry_timing") or {}).get("spiked_today"),
        "day_move_pct": (score.get("entry_timing") or {}).get("day_move_pct"),
        "poor_entry": (score.get("entry_timing") or {}).get("poor_entry"),
        "entry_note": (score.get("entry_timing") or {}).get("note"),
        "data_flag": bool((res.get("data_quality") or {}).get("suspect_gap")),
        "data_flag_detail": res.get("data_quality") or {},
        "partial_trimmed": bool((res.get("data_quality") or {}).get("partial_trimmed")),
        "error": None,
    }


def sort_key(row: dict):
    """Ranking within a verdict tier, tuned for a short-term shortlist:

      1. verdict            STRONG > WATCH > AVOID
      2. data-suspect sinks corrupt levels/RS make the whole score untrustworthy,
                            so a ⚠️-flagged stock goes to the BOTTOM of its tier
                            (fixes VEDL ranking #2 on a demerger-corrupted 7.7:1).
      3. best_case / confirmed  more criteria passed ranks higher.
      4. extended sinks     an over-extended (poor-entry) name is demoted among
                            otherwise-equal setups.
      5. reward:risk        'open upside' (no overhead resistance) is treated as
                            FAVOURABLE (~3:1), not as zero — so a clean breakout
                            ranks above a weak-R:R dud instead of below it.
      6. 6-month momentum   final tiebreak, stronger first.
    """
    rr = row.get("rr")
    rr_rank = rr if isinstance(rr, (int, float)) else 3.0   # open upside ≈ a solid 3:1
    # momentum tiebreak: 3-month (the short-horizon window C5 uses), 6m as fallback
    rs = row.get("rs_3m")
    if not isinstance(rs, (int, float)):
        rs = row.get("rs_6m")
    poor_entry = row.get("poor_entry") or row.get("extended") or row.get("spiked_today")
    return (
        _VERDICT_RANK.get(row.get("verdict"), 3),
        1 if row.get("data_flag") else 0,
        -(row.get("best_case") or 0),
        -(row.get("confirmed") or 0),
        1 if poor_entry else 0,
        -rr_rank,
        -(rs if isinstance(rs, (int, float)) else -999),
    )


def _last_price(res: dict):
    """Last close from the saved OHLCV (falls back to None)."""
    df = load_ohlcv(res.get("stock"), res.get("interval", "daily"))
    if df is not None and len(df):
        return round(float(df["Close"].iloc[-1]), 2)
    return None


# ---------------------------------------------------------------------------
# Batch runner (parallel; calls progress_cb(done, total, last_name) as it goes).
# ---------------------------------------------------------------------------
def run_batch(names, interval="daily", with_news=False, max_workers=6, progress_cb=None):
    names = [n.strip() for n in names if n and n.strip()]
    # de-dupe, preserve order
    seen, ordered = set(), []
    for n in names:
        u = n.upper()
        if u not in seen:
            seen.add(u)
            ordered.append(n)

    results: dict[str, dict] = {}
    total = len(ordered)
    done = 0
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, total))) as ex:
        futs = {ex.submit(analyze_cached, n, interval, with_news): n for n in ordered}
        for fut in as_completed(futs):
            n = futs[fut]
            try:
                results[n] = fut.result()
            except Exception as e:
                results[n] = {"_error": f"{type(e).__name__}: {e}", "stock": n.upper()}
            done += 1
            if progress_cb:
                progress_cb(done, total, n)
    # return in the user's input order
    return [results[n] for n in ordered]


# ---------------------------------------------------------------------------
# Chart data
# ---------------------------------------------------------------------------
def load_ohlcv(stock: str | None, interval: str = "daily"):
    if not stock:
        return None
    path = os.path.join(OUTPUT_ROOT, stock, f"{stock}_{interval}_ohlcv.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df
    except Exception:
        return None
