"""Mutual-fund analysis core — NAV -> metrics -> 3-tier honest scoring.

Mirrors the stock tool's screener_core.py shape (analyze -> summarize ->
quality/manual -> run_batch), and its HONESTY SPLIT:

  TIER 1  COMPUTED SCORE (headline 0-100), from free NAV + benchmark + rf:
          C2 track-record(gate) · C4 rolling outperformance · C5 alpha ·
          C6 Sharpe/Sortino · C7 SD/beta · C8 downside capture
  TIER 2  DATA-DEPENDENT (Kuvera, best-effort, flagged, NOT in headline):
          C1 AUM · C11 expense ratio · C12 lock-in
  TIER 3  MANUAL REVIEW (never scored): C3 manager tenure date · C9 top-10
          concentration · C10 active share · exit-load schedule

Caveats baked in: benchmark is a PRICE index (TRI not free) so alpha is
overstated ~dividend yield; Sharpe/Sortino use a config risk-free rate;
peer-relative tests are future work (absolute thresholds for now).
"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

import mf_data as data

RISK_FREE_DEFAULT = 0.0525          # 91-day T-bill, Jul-2026 (editable)
_CACHE: dict = {}


def clear_cache():
    _CACHE.clear()
    data.clear_cache()


# --------------------------------------------------------------------------- #
#  Fund-name VERIFICATION (fast pre-flight: does the name resolve to a scheme?)
# --------------------------------------------------------------------------- #
def verify_fund(name: str) -> dict:
    n = (name or "").strip()
    if not n:
        return {"name": name, "valid": False, "symbol": None, "reason": "empty"}
    try:
        r = data.resolve_scheme(n)
        if not r:
            return {"name": n, "valid": False, "symbol": None,
                    "reason": "no matching scheme on mfapi (check spelling / plan)"}
        return {"name": n, "valid": True,
                "symbol": r.get("name") or f"code {r['code']}", "reason": ""}
    except Exception as e:
        return {"name": n, "valid": False, "symbol": None, "reason": str(e)[:90]}


def verify_funds(names, max_workers=6, progress_cb=None) -> list[dict]:
    names = [x.strip() for x in names if x and x.strip()]
    seen, ordered = set(), []
    for n in names:
        u = n.lower()
        if u not in seen:
            seen.add(u)
            ordered.append(n)
    results, done, total = {}, 0, len(ordered)
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, total))) as ex:
        futs = {ex.submit(verify_fund, n): n for n in ordered}
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


# --------------------------------------------------------------------------- #
#  Category classification + benchmark map (editable config)
# --------------------------------------------------------------------------- #
_INTL_KEYS = ("us ", "u.s", "nasdaq", "s&p 500", "global", "international",
              "greater china", "emerging market", "world", "overseas", "nyse",
              "hang seng", "taiwan", "japan")


def _is_international(name: str) -> bool:
    n = f" {(name or '').lower()} "
    return any(k in n for k in _INTL_KEYS)


def classify_category(*strings) -> str:
    blob = " ".join(s for s in strings if s).lower()
    # Hybrid / multi-asset FIRST: these hold gold/debt, so their low volatility
    # inflates Sharpe/downside-capture — they are NOT pure-equity and must not be
    # ranked against equity funds (SEBI classifies them as a separate Hybrid group).
    if any(k in blob for k in ("hybrid", "balanced", "multi asset", "multi-asset",
                               "asset allocation", "arbitrage", "equity savings",
                               "dynamic asset")):
        return "hybrid"
    # Index / ETF BEFORE cap keywords: a "Nifty Midcap 150 ... Index" fund is
    # passive, not an active mid-cap — it shouldn't be judged on alpha.
    if "index" in blob or "etf" in blob:
        return "index"
    if "large" in blob and "mid" in blob:
        return "large_mid"
    if "large" in blob:
        return "large"
    if "mid" in blob:
        return "mid"
    if "small" in blob:
        return "small"
    if "flexi" in blob:
        return "flexi"
    if "multi" in blob and "cap" in blob:
        return "multi"
    if "focused" in blob:
        return "focused"
    if "elss" in blob or "tax" in blob:
        return "elss"
    if "value" in blob or "contra" in blob:
        return "value"
    if "index" in blob or "etf" in blob:
        return "index"
    if "sector" in blob or "thematic" in blob:
        return "thematic"
    return "equity_other"

# Category benchmark per SEBI category. Each: (kind, ref, display_name, is_proxy).
# kind 'yf' = yfinance price index; kind 'mf' = an index-FUND NAV (TRI-equivalent)
# used where a free price index has no usable history (Nifty Smallcap 250). Editable.
SMALLCAP250_IDX = "148519"   # Nippon India Nifty Smallcap 250 Index Fund (Direct) — proper small-cap TRI, from 2020-10
BENCHMARK = {
    "large": ("yf", "^CNX100", "Nifty 100", False),
    "large_mid": ("yf", "^CNX100", "Nifty 100 (≈ proxy for LargeMidcap 250)", True),
    "mid": ("yf", "NIFTYMIDCAP150.NS", "Nifty Midcap 150", False),
    "small": ("mf", SMALLCAP250_IDX, "Nifty Smallcap 250 (index-fund NAV)", False),
    "flexi": ("yf", "^CRSLDX", "Nifty 500", False),
    "multi": ("yf", "^CRSLDX", "Nifty 500", False),
    "focused": ("yf", "^CRSLDX", "Nifty 500", False),
    "elss": ("yf", "^CRSLDX", "Nifty 500", False),
    "value": ("yf", "^CRSLDX", "Nifty 500", False),
    "thematic": ("yf", "^CRSLDX", "Nifty 500 (proxy — sector index not free)", True),
    "hybrid": ("yf", "^CRSLDX", "Nifty 500 (proxy — hybrid holds non-equity)", True),
    "index": ("yf", "^NSEI", "Nifty 50", False),
    "equity_other": ("yf", "^CRSLDX", "Nifty 500", False),
}
_FALLBACK = ("yf", "^CRSLDX", "Nifty 500 [fallback]", True)

CAT_LABEL = {
    "large": "Large Cap", "large_mid": "Large & Mid Cap", "mid": "Mid Cap",
    "small": "Small Cap", "flexi": "Flexi Cap", "multi": "Multi Cap",
    "focused": "Focused", "elss": "ELSS", "value": "Value/Contra",
    "index": "Index/ETF", "thematic": "Sectoral/Thematic",
    "hybrid": "Hybrid / Multi-Asset", "equity_other": "Equity",
}

# category-specific thresholds (editable)
AUM_RULE = {
    "small": {"ceiling": 30000, "floor": 500},
    "mid": {"ceiling": 25000, "floor": 500},
    "large": {"floor": 10000},
    "large_mid": {"floor": 3000},
    "index": {"floor": 1000},
}
BETA_MAX = {"large": 1.05, "large_mid": 1.10, "index": 1.05}   # else 1.15
EXPENSE_MAX = {"index": 0.40}                                   # else 1.00


# --------------------------------------------------------------------------- #
#  Metric primitives
# --------------------------------------------------------------------------- #
def _monthly(nav: pd.Series) -> pd.Series:
    return nav.resample("ME").last().pct_change().dropna()


def track_record(nav: pd.DataFrame, start_date=None) -> dict:
    px = nav["nav"]
    idx = px.index
    inception = idx[0]
    if start_date:
        try:
            sd = pd.to_datetime(start_date)
            inception = min(inception, sd)
        except Exception:
            pass
    age = (idx[-1] - inception).days / 365.25
    run_max = px.cummax()
    dd = px / run_max - 1
    max_dd = float(dd.min() * 100)
    trough = dd.idxmin()
    pre_peak = run_max.loc[:trough].max()
    post_max = px.loc[trough:].max()
    recovered = bool(post_max >= pre_peak * 0.98)
    n_months = len(px.resample("ME").last())
    return {"age_years": round(age, 1), "inception": str(inception.date()),
            "max_dd_pct": round(max_dd, 1),
            "crash_recovery": bool(max_dd <= -20 and recovered),
            "covers_covid": bool(idx[0] <= pd.Timestamp("2020-02-01")),
            "n_months": int(n_months)}


def cagr(nav: pd.Series, years: float):
    if len(nav) < 2:
        return None
    end = nav.index[-1]
    start_dt = end - pd.Timedelta(days=int(365.25 * years))
    window = nav.loc[:start_dt]
    if window.empty:
        return None
    start_val = window.iloc[-1]
    if start_val <= 0:
        return None
    return round(((nav.iloc[-1] / start_val) ** (1 / years) - 1) * 100, 1)


def rolling_outperf(nav: pd.Series, bench: pd.Series, years: float):
    """Daily-step rolling CAGR: % of windows the fund beats the benchmark."""
    if bench is None:
        return None, 0
    n = int(252 * years)
    b = bench.reindex(nav.index, method="ffill")
    fr = (nav / nav.shift(n)) ** (1 / years) - 1
    br = (b / b.shift(n)) ** (1 / years) - 1
    valid = fr.notna() & br.notna() & (nav.shift(n) > 0) & (b.shift(n) > 0)
    n_win = int(valid.sum())
    if n_win < 30:
        return None, n_win
    return round(float((fr[valid] > br[valid]).mean() * 100), 0), n_win


def capm(fund_m: pd.Series, bench_m: pd.Series, rf_annual: float):
    if bench_m is None:
        return None
    rf_m = (1 + rf_annual) ** (1 / 12) - 1
    df = pd.concat([fund_m, bench_m], axis=1, keys=["f", "b"]).dropna()
    if len(df) < 24:
        return None
    x = (df["b"] - rf_m).values
    y = (df["f"] - rf_m).values
    beta, alpha_m = np.polyfit(x, y, 1)
    resid = y - (beta * x + alpha_m)
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    return {"alpha_pct": round(((1 + alpha_m) ** 12 - 1) * 100, 2),
            "beta": round(float(beta), 2),
            "r2": round(float(r2), 2) if r2 is not None else None, "n": len(df)}


def sharpe_sortino(fund_m: pd.Series, rf_annual: float):
    if len(fund_m) < 24:
        return {"sharpe": None, "sortino": None}
    rf_m = (1 + rf_annual) ** (1 / 12) - 1
    ex = fund_m - rf_m
    sd = fund_m.std()
    sharpe = float(ex.mean() / sd * np.sqrt(12)) if sd > 0 else None
    downside = ex[ex < 0]
    dd = float(np.sqrt((downside ** 2).mean())) if len(downside) else 0.0
    sortino = float(ex.mean() / dd * np.sqrt(12)) if dd > 0 else None
    return {"sharpe": round(sharpe, 2) if sharpe is not None else None,
            "sortino": round(sortino, 2) if sortino is not None else None}


def annualized_sd(fund_m: pd.Series):
    if len(fund_m) < 24:
        return None
    return round(float(fund_m.std() * np.sqrt(12) * 100), 1)


def downside_capture(fund_m: pd.Series, bench_m: pd.Series):
    if bench_m is None:
        return None
    df = pd.concat([fund_m, bench_m], axis=1, keys=["f", "b"]).dropna()
    down = df[df["b"] < 0]
    if len(down) < 6:
        return None
    fund_cum = (1 + down["f"]).prod() - 1
    bench_cum = (1 + down["b"]).prod() - 1
    if bench_cum == 0:
        return None
    return round(float(fund_cum / bench_cum * 100), 0)


# --------------------------------------------------------------------------- #
#  Analyze one fund
# --------------------------------------------------------------------------- #
def analyze_fund(query: str, rf: float = RISK_FREE_DEFAULT) -> dict:
    resolved = data.resolve_scheme(query)
    if not resolved:
        return {"_error": f"No scheme found for '{query}'", "query": query}
    code = resolved["code"]
    meta, nav_df = data.fetch_nav_history(code)
    if nav_df is None or nav_df.empty or len(nav_df) < 60:
        return {"_error": f"Insufficient NAV history for '{query}' (code {code})", "query": query}

    nav = nav_df["nav"]
    isin = meta.get("isin_growth")
    enr = data.fetch_enrichment(isin) if isin else {}
    name = (enr.get("name") or meta.get("scheme_name") or resolved.get("name") or query)

    cat = classify_category(meta.get("scheme_category"), enr.get("fund_category"), name)
    intl = _is_international(name)
    # bucket by CATEGORY TYPE (not benchmark quality): hybrids hold non-equity so
    # their risk-adjusted metrics aren't comparable to pure equity; sector/thematic
    # & foreign-equity are satellites; index funds are passive.
    if cat == "hybrid":
        bucket = "hybrid"
    elif cat == "thematic" or intl:
        bucket = "satellite"
    elif cat == "index":
        bucket = "passive"
    else:
        bucket = "core"

    b_kind, b_ref, bench_name, is_proxy = BENCHMARK.get(cat, BENCHMARK["equity_other"])
    if intl:  # foreign-equity fund: an Indian index is meaningless
        b_kind, b_ref, bench_name, is_proxy = "yf", "^CRSLDX", "Nifty 500 (proxy — foreign-equity fund)", True
    bench = data.fetch_benchmark_series(b_kind, b_ref)
    if bench is None and not (b_kind == "yf" and b_ref == "^CRSLDX"):
        bench = data.fetch_benchmark_series(_FALLBACK[0], _FALLBACK[1])  # graceful fallback
        if bench is not None:
            b_kind, b_ref, bench_name, is_proxy = _FALLBACK
    benchmark_proxy = bool(is_proxy)

    fund_m = _monthly(nav)
    bench_m = _monthly(bench) if bench is not None else None

    tr = track_record(nav_df, enr.get("start_date"))
    hit3, n3 = rolling_outperf(nav, bench, 3)
    hit5, n5 = rolling_outperf(nav, bench, 5)
    reg = capm(fund_m, bench_m, rf) or {}
    ss = sharpe_sortino(fund_m, rf)
    sd = annualized_sd(fund_m)
    dcap = downside_capture(fund_m, bench_m)

    return {
        "_error": None, "query": query, "code": code, "name": name, "isin": isin,
        "category": cat, "category_label": CAT_LABEL.get(cat, "Equity"),
        "bucket": bucket, "benchmark_proxy": benchmark_proxy, "international": intl,
        "benchmark_kind": b_kind, "benchmark_ref": b_ref, "benchmark_name": bench_name,
        "benchmark_ok": bench is not None,
        "rf": rf, "as_of": str(nav.index[-1].date()),
        "nav_start": str(nav.index[0].date()),
        "returns": {"cagr_1y": cagr(nav, 1), "cagr_3y": cagr(nav, 3), "cagr_5y": cagr(nav, 5)},
        "track_record": tr,
        "rolling": {"hit_3y": hit3, "n_3y": n3, "hit_5y": hit5, "n_5y": n5},
        "capm": reg, "sharpe_sortino": ss, "sd_pct": sd, "downside_capture": dcap,
        "enrichment": enr,
    }


def analyze_cached(query: str, rf: float = RISK_FREE_DEFAULT) -> dict:
    key = (query.strip().lower(), round(rf, 4))
    if key in _CACHE:
        return _CACHE[key]
    try:
        res = analyze_fund(query, rf)
    except Exception as e:
        res = {"_error": f"{type(e).__name__}: {e}", "_trace": traceback.format_exc(),
               "query": query, "name": query}
    _CACHE[key] = res
    return res


# --------------------------------------------------------------------------- #
#  TIER 1 — computed checks + score
# --------------------------------------------------------------------------- #
def _chk(cid, label, value, status, note=""):
    return {"id": cid, "label": label, "value": value, "status": status, "note": note}


WEIGHTS = {"C4": 25, "C5": 20, "C6": 20, "C8": 15, "C7": 10, "C2": 10}
_PTS = {"PASS": 1.0, "CAUTION": 0.5, "FAIL": 0.0}


def tier1_checks(res: dict) -> dict:
    tr = res["track_record"]; roll = res["rolling"]; reg = res.get("capm") or {}
    ss = res.get("sharpe_sortino") or {}; sd = res.get("sd_pct")
    dcap = res.get("downside_capture"); cat = res["category"]
    checks = []

    # C2 track record (gate)
    age = tr["age_years"]
    if age >= 5 and tr["crash_recovery"]:
        st = "PASS"
    elif age >= 3:
        st = "CAUTION"
    else:
        st = "FAIL"
    checks.append(_chk("C2", "Track record / age",
                       f"{age:.1f}y, maxDD {tr['max_dd_pct']:.0f}%", st,
                       ("Survived a crash+recovery." if tr["crash_recovery"]
                        else "Not yet tested by a real crash+recovery.")))

    # C4 rolling outperformance (headline weight)
    hits = [h for h in (roll["hit_3y"], roll["hit_5y"]) if h is not None]
    if not res["benchmark_ok"] or not hits:
        st, val = "NA", "no benchmark"
    else:
        avg = sum(hits) / len(hits)
        thin = (roll["n_3y"] or 0) < 250
        st = "PASS" if avg >= 75 else "CAUTION" if (avg >= 60 or thin) else "FAIL"
        val = f"3y {roll['hit_3y'] or '—'}% · 5y {roll['hit_5y'] or '—'}%"
    checks.append(_chk("C4", "Rolling returns beat benchmark", val, st,
                       "% of daily-step 3y/5y windows the fund beat its index (want ≥75%)."))

    # C5 alpha
    a = reg.get("alpha_pct")
    if a is None:
        st, val = "NA", "no benchmark"
    else:
        st = "PASS" if a > 1.5 else "CAUTION" if a > 0 else "FAIL"
        val = f"{a:+.1f}% (β {reg.get('beta')}, R² {reg.get('r2')})"
    checks.append(_chk("C5", "Alpha (vs benchmark)", val, st,
                       "Annualized excess return. PRICE-index proxy → overstated ~dividend yield."))

    # C6 Sharpe & Sortino
    sh, so = ss.get("sharpe"), ss.get("sortino")
    if sh is None:
        st, val = "NA", "<24 mo"
    else:
        st = "PASS" if sh >= 1.0 else "CAUTION" if sh >= 0.7 else "FAIL"
        val = f"Sharpe {sh} · Sortino {so if so is not None else '—'}"
    checks.append(_chk("C6", "Risk-adjusted return", val, st,
                       "Return per unit of risk (absolute bar; peer-relative is future work)."))

    # C7 SD & beta
    beta = reg.get("beta")
    bmax = BETA_MAX.get(cat, 1.15)
    if sd is None and beta is None:
        st, val = "NA", "<24 mo"
    else:
        beta_ok = beta is not None and beta <= bmax
        st = "PASS" if beta_ok else "CAUTION" if (beta is not None and beta <= bmax + 0.15) else "FAIL"
        val = f"SD {sd if sd is not None else '—'}% · β {beta if beta is not None else '—'}"
    checks.append(_chk("C7", "Volatility & beta", val, st,
                       f"Beta ≤ {bmax} preferred for {CAT_LABEL.get(cat, 'this category')}."))

    # C8 downside capture
    if dcap is None:
        st, val = "NA", "no benchmark"
    else:
        st = "PASS" if dcap < 90 else "CAUTION" if dcap < 100 else "FAIL"
        val = f"{dcap:.0f}%"
    checks.append(_chk("C8", "Downside capture", val, st,
                       "How much of the market's falls it absorbs (want < 90%)."))

    # score
    scored = [c for c in checks if c["status"] in _PTS]
    got = sum(WEIGHTS[c["id"]] * _PTS[c["status"]] for c in scored)
    tot = sum(WEIGHTS[c["id"]] for c in scored)
    score = round(got / tot * 100) if tot else None

    # gate
    gate_fail = tr["age_years"] < 3 or tr["n_months"] < 36
    return {"checks": checks, "score": score, "scored_weight": tot,
            "gate_untested": bool(gate_fail)}


def verdict_of(score, gate_untested) -> tuple[str, str]:
    if gate_untested or score is None:
        return "UNTESTED", "Too young / too little history to judge (needs 3y+ and a crash cycle)."
    if score >= 70:
        return "STRONG", "Consistent, risk-efficient outperformance on the computed metrics."
    if score >= 55:
        return "DECENT", "Solid but not exceptional on the computed metrics."
    if score >= 42:
        return "WEAK", "Mixed — several computed checks fall short."
    return "POOR", "Lags its benchmark on most computed risk/return checks."


# --------------------------------------------------------------------------- #
#  TIER 2 — data-dependent (Kuvera): AUM, expense ratio, lock-in
# --------------------------------------------------------------------------- #
def tier2_checks(res: dict) -> list[dict]:
    enr = res.get("enrichment") or {}
    cat = res["category"]
    out = []

    aum = enr.get("aum_cr")
    rule = AUM_RULE.get(cat, {})
    if aum is None:
        out.append(_chk("C1", "AUM (fund size)", "N/A", "NA",
                        "Not available from the free feed right now."))
    else:
        st = "PASS"
        note = f"₹{aum:,.0f} cr · {CAT_LABEL.get(cat)}"
        if "ceiling" in rule and aum > rule["ceiling"]:
            st, note = "CAUTION", f"₹{aum:,.0f} cr — large for {CAT_LABEL.get(cat)}; size can hurt agility."
        elif "floor" in rule and aum < rule["floor"]:
            st, note = "CAUTION", f"₹{aum:,.0f} cr — below preferred minimum for {CAT_LABEL.get(cat)}."
        out.append(_chk("C1", "AUM (fund size)", f"₹{aum:,.0f} cr", st, note))

    ter = enr.get("expense_ratio")
    emax = EXPENSE_MAX.get(cat, 1.00)
    if ter is None:
        out.append(_chk("C11", "Expense ratio (direct)", "N/A", "NA",
                        "Not available from the free feed right now."))
    else:
        st = "PASS" if ter <= emax else "CAUTION" if ter <= emax + 0.4 else "FAIL"
        asof = enr.get("expense_ratio_date")
        out.append(_chk("C11", "Expense ratio (direct)", f"{ter:.2f}%", st,
                        f"Direct-plan TER; want ≤ {emax:.2f}% for {CAT_LABEL.get(cat)}."
                        + (f" (as of {asof})" if asof else "")))

    lock = enr.get("lock_in_period")
    if lock is not None:
        st = "PASS" if lock == 0 else "CAUTION"
        val = "none" if lock == 0 else f"{int(lock)} days"
        out.append(_chk("C12", "Lock-in", val, st,
                        "ELSS funds have a mandatory 3-year lock-in; full exit-load schedule is in the SID."))
    return out


# --------------------------------------------------------------------------- #
#  TIER 3 — manual review (never scored)
# --------------------------------------------------------------------------- #
def manual_review_items(res: dict) -> list[dict]:
    enr = res.get("enrichment") or {}
    mgr = enr.get("fund_manager")
    items = [
        {"sev": "high", "title": "Fund-manager tenure (C3)",
         "detail": (f"Managers: {mgr}. " if mgr else "") +
                   "The 'managing since' DATE isn't in any free API — a great 5-yr record means nothing if the manager just left. Confirm the lead manager has ≥3 years on THIS scheme.",
         "where": "AMC factsheet / Value Research 'fund managers' tab"},
        {"sev": "high", "title": "Portfolio concentration — top-10 holdings (C9)",
         "detail": "Needs the full holdings list (not derivable from NAV). Want top-10 < ~50-60% unless it's a focused fund.",
         "where": "AMC monthly portfolio disclosure / AMFI / Value Research"},
        {"sev": "medium", "title": "Active share vs benchmark (C10)",
         "detail": "Detects a 'closet index fund' charging active fees. Needs full holdings + benchmark weights (no free source). Want > 60-70%.",
         "where": "AMC factsheet / Morningstar / Value Research"},
        {"sev": "medium", "title": "Exit-load schedule (C12 detail)",
         "detail": "Lock-in is shown above, but the full exit-load slab (e.g. 1% if redeemed < 1 year) is in the scheme document.",
         "where": "Scheme Information Document (SID) / AMC site"},
    ]
    if not res.get("benchmark_ok"):
        items.insert(0, {"sev": "high", "title": "Benchmark unavailable — alpha/beta/capture skipped",
                         "detail": "Could not fetch the benchmark index, so relative metrics (C4/C5/C7/C8) were not scored. Re-run or check manually.",
                         "where": "the fund's own benchmark on the AMC factsheet"})
    return items


# --------------------------------------------------------------------------- #
#  Summary row + batch
# --------------------------------------------------------------------------- #
def summarize(res: dict) -> dict:
    if res.get("_error"):
        return {"name": res.get("name") or res.get("query", "?"), "error": res["_error"],
                "verdict": "ERROR", "score": None, "category_label": None}
    t1 = tier1_checks(res)
    t2 = tier2_checks(res)
    verdict, rationale = verdict_of(t1["score"], t1["gate_untested"])
    reg = res.get("capm") or {}; ss = res.get("sharpe_sortino") or {}
    enr = res.get("enrichment") or {}
    ter = enr.get("expense_ratio")
    return {
        "name": res["name"], "code": res["code"], "verdict": verdict, "rationale": rationale,
        "score": t1["score"], "gate_untested": t1["gate_untested"],
        "category": res["category"], "category_label": res["category_label"],
        "bucket": res.get("bucket", "core"), "benchmark_proxy": bool(res.get("benchmark_proxy")),
        "international": bool(res.get("international")), "benchmark_name": res["benchmark_name"],
        "age_years": res["track_record"]["age_years"],
        "cagr_3y": res["returns"]["cagr_3y"], "cagr_5y": res["returns"]["cagr_5y"],
        "hit_3y": res["rolling"]["hit_3y"],
        "alpha": reg.get("alpha_pct"), "beta": reg.get("beta"),
        "sharpe": ss.get("sharpe"), "sortino": ss.get("sortino"),
        "downside_capture": res.get("downside_capture"),
        "aum_cr": enr.get("aum_cr"), "expense_ratio": ter,
        "stale_enrichment": bool(enr.get("stale")),
        "tier1": t1, "tier2": t2, "error": None,
    }


_VRANK = {"STRONG": 0, "DECENT": 1, "WEAK": 2, "POOR": 3, "UNTESTED": 4, "ERROR": 5}


def _n(v, floor):
    return v if v is not None else floor


def make_sort_key(mode: str = "risk"):
    """Return a sort key fn. Ties (equal score, common here since scores are
    discrete) break either by risk-adjusted consistency (default) or by recent
    return. Both keep verdict + score as the top two keys."""
    def risk(row):   # rolling consistency -> Sharpe -> alpha -> trailing CAGR
        return (_VRANK.get(row.get("verdict"), 6), -(row.get("score") or 0),
                -_n(row.get("hit_3y"), -1), -_n(row.get("sharpe"), -9),
                -_n(row.get("alpha"), -99), -_n(row.get("cagr_3y"), -99))

    def returns(row):  # recent 3Y CAGR -> 5Y CAGR -> alpha -> Sharpe
        return (_VRANK.get(row.get("verdict"), 6), -(row.get("score") or 0),
                -_n(row.get("cagr_3y"), -99), -_n(row.get("cagr_5y"), -99),
                -_n(row.get("alpha"), -99), -_n(row.get("sharpe"), -9))

    return returns if mode == "returns" else risk


sort_key = make_sort_key("risk")   # default (backward-compatible)


def run_batch(queries, rf=RISK_FREE_DEFAULT, max_workers=6, progress_cb=None):
    queries = [q.strip() for q in queries if q and q.strip()]
    seen, ordered = set(), []
    for q in queries:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            ordered.append(q)
    results, done, total = {}, 0, len(ordered)
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, total))) as ex:
        futs = {ex.submit(analyze_cached, q, rf): q for q in ordered}
        for fut in as_completed(futs):
            q = futs[fut]
            try:
                results[q] = fut.result()
            except Exception as e:
                results[q] = {"_error": f"{type(e).__name__}: {e}", "query": q, "name": q}
            done += 1
            if progress_cb:
                progress_cb(done, total, q)
    # de-duplicate by RESOLVED scheme code (two different query strings can map to
    # the same fund, e.g. "...Direct Growth" vs "...Fund Direct") — keep the first.
    out, seen_codes = [], set()
    for q in ordered:
        r = results[q]
        code = r.get("code")
        if code and code in seen_codes:
            continue
        if code:
            seen_codes.add(code)
        out.append(r)
    return out
