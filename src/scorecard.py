"""
10-criteria positional checklist (1-2 month horizon).
Based on Mark Minervini's Trend Template + CANSLIM principles.

  1. Market & Liquidity
     C1 Market Trend Accord     - index uptrend or sideways (not a correction)
     C2 Liquidity Minimum       - 20-day avg volume high enough for clean fills
  2. Technical Momentum
     C3 Moving-Average Alignment- price above rising 50 & 200 SMA (50 > 200)
     C4 Volume Expansion        - latest volume >= 1.5x 20-day average
     C5 Relative Strength       - outperforming the index over 6 months
  3. Fundamental & Governance
     C6 Accelerating Earnings   - latest-quarter revenue & EPS YoY >= 20%
     C7 Zero Promoter Red Flags - pledge <=10%, no insider selling  [MANUAL]
     C8 Institutional Sponsorship- MF/FII/DII holding rising 2 quarters [MANUAL]
  4. Trade Execution
     C9 Asymmetric Risk-Reward  - upside to resistance >= 3x stop distance
     C10 Hard Stop-Loss         - structural support within 5-8% below entry

C7 & C8 need promoter-pledge / FII-DII data that has no free programmatic feed,
so they are flagged MANUAL (verify on NSE / Screener.in / Trendlyne).
"""

from __future__ import annotations

import pandas as pd

MANUAL_LINKS = ("verify on screener.in (shareholding) / trendlyne / "
                "nseindia.com (shareholding pattern)")

# A single-session move at/above this % marks a stock as "spiked today" — a chase
# risk for a short (1-4 week) hold (roughly an NSE circuit-band-sized daily pop).
SPIKE_TODAY_PCT = 5.0

# For blue-sky stocks (no overhead resistance) the reward target is a measured
# extension of this many ATRs above entry — a volatility-appropriate stand-in for
# a structural resistance level, so R:R is still computable.
ATR_TARGET_MULT = 3.0


def _num(x):
    return x if isinstance(x, (int, float)) else None


def _slope_up(series: pd.Series, lookback=20) -> bool:
    s = series.dropna()
    if len(s) < lookback + 1:
        return False
    return s.iloc[-1] > s.iloc[-lookback - 1]


def _rs_detail(rs) -> str:
    """C5 detail line: show the 3-month read (primary), with 6-month as context."""
    if not rs:
        return "n/a"
    parts = []
    if rs.get("stock_3m_return_pct") is not None:
        parts.append(f"3m {rs['stock_3m_return_pct']:+.1f}% vs NIFTY {rs['nifty_3m_return_pct']:+.1f}%")
    if rs.get("stock_6m_return_pct") is not None:
        parts.append(f"6m {rs['stock_6m_return_pct']:+.1f}%")
    return " · ".join(parts) if parts else "n/a"


def _entry_note(extended: bool, ext_pct, spiked_today: bool, day_move) -> str:
    """Plain-language entry-timing call combining the two chase risks."""
    if spiked_today and extended:
        return (f"Up ~{day_move:.0f}% today AND ~{ext_pct:.0f}% above the 50-DMA — do NOT chase; "
                "move to watch and wait 2-3 days for it to stabilise near support.")
    if spiked_today:
        return (f"Up ~{day_move:.0f}% today — do NOT chase an intraday spike; wait 2-3 days for a "
                "pullback/consolidation near support before entering.")
    if extended:
        return f"Extended ~{ext_pct:.0f}% above the 50-DMA — poor entry; wait for a pullback or base."
    return "Entry zone acceptable — not over-extended and no spike to chase."


def build_checklist(df: pd.DataFrame, fund: dict, sr: dict, vol: dict = None,
                    patterns: list = None, candles: list = None, news: dict = None) -> dict:
    last = df.iloc[-1]
    price = float(last["Close"])
    crit = []   # (id, group, label, status, detail)  status: PASS/FAIL/MANUAL/UNKNOWN

    # ---- 1. MARKET & LIQUIDITY ----
    regime = fund.get("market_regime")
    crit.append(("C1", "Market & Liquidity", "Market trend (uptrend/sideways, not correction)",
                 "PASS" if regime in ("bull", "sideways") else "FAIL", f"NIFTY regime: {regime}"))

    vol20 = fund["liquidity"]["avg_daily_volume_20"]
    liquid = isinstance(vol20, int) and vol20 >= 500_000
    crit.append(("C2", "Market & Liquidity", "Liquidity (20-day avg volume >= 500k)",
                 "PASS" if liquid else "FAIL", f"avg vol = {vol20}"))

    # ---- 2. TECHNICAL MOMENTUM ----
    sma50, sma200 = last.get("SMA50"), last.get("SMA200")
    ma_ok = (sma50 == sma50 and sma200 == sma200 and price > sma50 > sma200
             and _slope_up(df["SMA50"]) and _slope_up(df["SMA200"]))
    crit.append(("C3", "Technical Momentum", "Above rising 50 & 200 SMA (50>200)",
                 "PASS" if ma_ok else "FAIL",
                 f"price {price:.1f} / SMA50 {sma50:.1f} / SMA200 {sma200:.1f}" if sma50 == sma50 else "insufficient history"))

    volx = last["Volume"] / last["Vol_MA20"] if last["Vol_MA20"] == last["Vol_MA20"] and last["Vol_MA20"] else None
    crit.append(("C4", "Technical Momentum", "Volume expansion (latest >= 1.5x 20d avg)",
                 "PASS" if (volx and volx >= 1.5) else "FAIL",
                 f"{volx:.2f}x avg" if volx else "n/a"))

    rs = fund.get("relative_strength")
    crit.append(("C5", "Technical Momentum", "Relative strength (outperforming index, 3m)",
                 "PASS" if (rs and rs.get("outperforming")) else "FAIL", _rs_detail(rs)))

    # ---- 3. FUNDAMENTAL & GOVERNANCE ----
    eg = fund.get("earnings_growth", {})
    if eg.get("available"):
        rev, eps = eg.get("revenue_yoy"), eg.get("eps_yoy")
        ok = (rev is not None and rev >= 20) and (eps is not None and eps >= 20)
        crit.append(("C6", "Fundamental & Governance", "Accelerating earnings (rev & EPS YoY >=20%)",
                     "PASS" if ok else "FAIL", f"rev {rev}% / EPS {eps}% YoY"))
    else:
        crit.append(("C6", "Fundamental & Governance", "Accelerating earnings (rev & EPS YoY >=20%)",
                     "UNKNOWN", "quarterly data unavailable — verify on screener.in"))

    crit.append(("C7", "Fundamental & Governance", "Zero promoter red flags (pledge<=10%, no insider selling)",
                 "MANUAL", MANUAL_LINKS))
    crit.append(("C8", "Fundamental & Governance", "Institutional sponsorship rising (MF/FII/DII, 2 qtrs)",
                 "MANUAL", MANUAL_LINKS))

    # ---- 4. TRADE EXECUTION ----
    # Entry timing has TWO failure modes for a 1-4 week hold:
    #  (a) structurally extended — price stretched far above its 50-DMA (parabolic);
    #  (b) spiked today — a big single-session pop / upper-circuit day. Chasing
    #      either means a routine cooling-off pullback stops you out unnecessarily.
    ext_pct = ((price - sma50) / sma50 * 100) if (sma50 == sma50 and sma50) else None
    extended = ext_pct is not None and ext_pct >= 25

    prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else None
    day_move = ((price - prev_close) / prev_close * 100) if prev_close else None
    spiked_today = day_move is not None and day_move >= SPIKE_TODAY_PCT   # don't chase
    poor_entry = extended or spiked_today

    nearest_sup = sr.get("nearest_support")
    nearest_res = sr.get("nearest_resistance")
    # stop: structural support within 8%, else hard 8%
    stop_price = round(price * 0.92, 2)
    structural = False
    if nearest_sup and (price - nearest_sup["level"]) / price <= 0.08 and nearest_sup["level"] < price:
        stop_price = round(nearest_sup["level"] * 0.99, 2)
        structural = True
    stop_dist = (price - stop_price) / price * 100

    # target & reward:risk to the nearest STRUCTURAL resistance
    if nearest_res and nearest_res["level"] > price:
        target = nearest_res["level"]
        upside = (target - price) / price * 100
    else:
        target = None
        upside = None   # blue-sky: no overhead resistance in the last year
    rr = (upside / stop_dist) if (upside is not None and stop_dist > 0) else None

    # For blue-sky names a measured 3xATR extension gives a CONCRETE planning target
    # + estimated R:R (surfaced in the trade plan) — but it does NOT gate the score:
    # a breakout's reward is open-ended, so we don't cap it at 3xATR or punish it for
    # having no ceiling. (Gemini's ATR-target idea, minus its false divide-by-zero.)
    atr = last.get("ATR14")
    atr = float(atr) if (atr == atr and atr) else None    # NaN / zero guard
    atr_target = round(price + ATR_TARGET_MULT * atr, 2) if (target is None and atr) else None
    atr_rr = (round(((atr_target - price) / price * 100) / stop_dist, 1)
              if (atr_target and stop_dist > 0) else None)

    # C9: a real >=3:1 to resistance, OR a clean blue-sky breakout (open upside) that
    # isn't a poor entry (extended / spiked — you can't capture it chasing a spike).
    open_upside_ok = (target is None) and not poor_entry
    rr_ok = (rr is not None and rr >= 3) or open_upside_ok
    if rr is not None:
        c9_det = f"RR {rr:.1f}:1 (upside {upside:.1f}% / risk {stop_dist:.1f}%)"
    elif poor_entry:
        c9_det = (f"open upside but poor entry "
                  f"({'spiked today' if spiked_today else 'extended'}) — wait for a pullback")
    else:
        c9_det = (f"open upside (no resistance in 1y)"
                  f"{f'; ~{atr_rr}:1 to a 3xATR target' if atr_rr else ''}; risk {stop_dist:.1f}%")
    crit.append(("C9", "Trade Execution", "Asymmetric risk-reward (>= 3:1)",
                 "PASS" if rr_ok else "FAIL", c9_det))

    stop_ok = structural and stop_dist <= 8
    crit.append(("C10", "Trade Execution", "Hard stop-loss (structural, within 5-8%)",
                 "PASS" if stop_ok else "FAIL",
                 f"stop {stop_price} ({stop_dist:.1f}% below){' [structural]' if structural else ' [no support within 8% — use 8% hard stop]'}"))

    # ---- scoring & probability matrix ----
    passes = sum(1 for c in crit if c[3] == "PASS")
    manual = [c[0] for c in crit if c[3] == "MANUAL"]
    unknown = [c[0] for c in crit if c[3] == "UNKNOWN"]
    auto_eval = sum(1 for c in crit if c[3] in ("PASS", "FAIL"))

    # best case: confirmed passes + (manual assumed pass) — used for the band,
    # but conviction REQUIRES verifying the manual items.
    best_case = passes + len(manual)

    if best_case >= 9:
        band = "HIGH (75%+ setup)"
        action = "Conviction buy — but ONLY after verifying the 2 manual checks. Max allowed position size."
    elif best_case >= 7:
        band = "MODERATE (50-60% setup)"
        action = "Caution buy — reduce position size by half. Verify manual checks first."
    else:
        band = "LOW / FAILING setup"
        action = "Avoid — lacks the structural + momentum criteria for a 1-2 month hold."

    return {
        "criteria": [{"id": c[0], "group": c[1], "label": c[2], "status": c[3], "detail": c[4]} for c in crit],
        "passes": passes, "manual": manual, "unknown": unknown,
        "confirmed_score": passes, "best_case_score": best_case, "out_of": 10,
        "band": band, "action": action,
        "stop_price": stop_price, "stop_dist_pct": round(stop_dist, 1),
        "stop_structural": structural,
        "target_price": target, "upside_pct": round(upside, 1) if upside is not None else None,
        "atr_target": atr_target, "atr_rr": atr_rr,
        "risk_reward": round(rr, 1) if rr is not None else None,
        "entry_timing": {
            "extended": extended,
            "spiked_today": spiked_today,
            "poor_entry": poor_entry,
            "pct_above_sma50": round(ext_pct, 1) if ext_pct is not None else None,
            "day_move_pct": round(day_move, 1) if day_move is not None else None,
            "note": _entry_note(extended, ext_pct, spiked_today, day_move),
        },
    }
