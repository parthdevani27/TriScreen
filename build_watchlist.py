"""
Build a watchlist: stocks that (1) qualify on TODAY's data AND (2) historically
went up consistently when they qualified (from eval/sector_matrix_raw.csv).

Current score uses the 7 backtestable criteria (C1-C5, C9, C10).
History uses each stock's HIGH-setup (6-7) record at the 6-month horizon.
"""

from __future__ import annotations

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
import yfinance as yf

from src.common import NIFTY, resolve_symbol
from src.indicators import add_indicators
from src.levels import support_resistance
from eval_worker import SECTORS, regime_series


def current_score(full, ind, naligned, reg_aligned):
    pos = len(ind) - 1
    price = float(ind["Close"].iloc[pos])
    c1 = reg_aligned.iloc[pos] in ("bull", "sideways")
    c2 = float(ind["Volume"].iloc[pos - 20:pos + 1].mean()) > 500_000
    sma50, sma200 = ind["SMA50"].iloc[pos], ind["SMA200"].iloc[pos]
    c3 = bool(sma50 == sma50 and sma200 == sma200 and price > sma50 > sma200
              and sma50 > ind["SMA50"].iloc[pos - 20] and sma200 > ind["SMA200"].iloc[pos - 20])
    volma = ind["Vol_MA20"].iloc[pos]
    c4 = bool(volma == volma and volma and ind["Volume"].iloc[pos] >= 1.5 * volma)
    c5 = (price / float(ind["Close"].iloc[pos - 126]) - 1) > (
        float(naligned.iloc[pos]) / float(naligned.iloc[pos - 126]) - 1) if pos - 126 >= 0 else False
    sr = support_resistance(full)
    nsup, nres = sr.get("nearest_support"), sr.get("nearest_resistance")
    stop_price, structural = price * 0.92, False
    if nsup and nsup["level"] < price and (price - nsup["level"]) / price <= 0.08:
        stop_price, structural = nsup["level"] * 0.99, True
    stop_dist = (price - stop_price) / price * 100
    if nres and nres["level"] > price:
        rr = ((nres["level"] - price) / price * 100) / stop_dist if stop_dist > 0 else None
        c9 = rr is not None and rr >= 3
    else:
        c9 = True
    c10 = bool(structural and stop_dist <= 8)
    return int(c1) + int(c2) + int(c3) + int(c4) + int(c5) + int(c9) + int(c10), round(price, 2)


def main():
    # ---- historical track record per stock ----
    raw = pd.read_csv("eval/sector_matrix_raw.csv")
    for c in ["up_6m"]:
        if raw[c].dtype == object:
            raw[c] = raw[c].map({"True": True, "False": False})
    hist = {}
    for stock, g in raw.groupby("stock"):
        hi = g[g["criteria_passed"] >= 6]
        hist[stock] = {
            "hist_high_n": len(hi),
            "hist_high_up6": round(hi["up_6m"].mean() * 100, 0) if len(hi) else np.nan,
            "hist_high_avg6": round(hi["mv_6m"].mean(), 1) if len(hi) else np.nan,
            "hist_all_avg6": round(g["mv_6m"].mean(), 1),
        }

    # ---- current score per stock ----
    print("Scoring today's data for all stocks ...")
    nifty = yf.Ticker(NIFTY).history(period="max", auto_adjust=False)[["Close"]].dropna()
    reg = regime_series(nifty["Close"])
    rows = []
    for sector, names in SECTORS.items():
        for name in names:
            try:
                symbol, tk = resolve_symbol(name)
                full = tk.history(period="max", interval="1d", auto_adjust=False)
                full = full[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(full) < 300:
                    continue
                ind = add_indicators(full)
                naligned = nifty["Close"].reindex(ind.index, method="ffill")
                reg_aligned = reg.reindex(ind.index, method="ffill").fillna("sideways")
                passed, price = current_score(full, ind, naligned, reg_aligned)
            except Exception:
                continue
            st = symbol.split(".")[0]
            h = hist.get(st, {})
            rows.append({"stock": st, "sector": sector, "price": price,
                         "now_passed": passed, **h})
    df = pd.DataFrame(rows)
    df.to_csv("eval/watchlist_full.csv", index=False)

    # ---- final list: qualifies now (>=6) AND historically consistent ----
    qual = df[df["now_passed"] >= 6].copy()
    consistent = qual[(qual["hist_high_n"] >= 5) & (qual["hist_high_up6"] >= 60)
                      & (qual["hist_high_avg6"] > 0)]
    consistent = consistent.sort_values(["hist_high_up6", "hist_high_avg6"], ascending=False)

    near = df[(df["now_passed"] == 5) & (df["hist_high_n"] >= 5)
              & (df["hist_high_up6"] >= 60)].sort_values("hist_high_up6", ascending=False)

    L = "=" * 78
    print("\n" + L)
    print("  WATCHLIST — qualifies on TODAY's data AND historically consistent")
    print(L)
    print(f"  {'stock':<12}{'sector':<10}{'price':<10}{'now/7':<7}"
          f"{'hist_up6m':<11}{'hist_avg6m':<12}{'hist_n'}")
    print("  " + "-" * 70)
    if len(consistent):
        for _, r in consistent.iterrows():
            print(f"  {r['stock']:<12}{r['sector']:<10}{r['price']:<10}{int(r['now_passed'])}/7    "
                  f"{r['hist_high_up6']:.0f}%       {r['hist_high_avg6']:+.1f}%       {int(r['hist_high_n'])}")
    else:
        print("  (no stock both qualifies today AND meets the historical bar)")

    print(f"\n  Stocks qualifying today (now>=6): {len(qual)}  "
          f"-> of which historically consistent: {len(consistent)}")

    print("\n  NEAR-MISS (now 5/7 + good history) to watch:")
    if len(near):
        for _, r in near.head(12).iterrows():
            print(f"   {r['stock']:<12}{r['sector']:<10}now 5/7  "
                  f"hist_up6m {r['hist_high_up6']:.0f}%  avg {r['hist_high_avg6']:+.1f}%  n={int(r['hist_high_n'])}")
    else:
        print("   none")

    print("\n" + L)
    print("  Reminder: 'qualifies + good history' raises odds modestly (our edge was")
    print("  ~+2-4pp); it is NOT a guarantee. Verify C6/C7/C8 (earnings, pledge, FII/DII)")
    print("  manually, hold 3-6 months, use a stop-loss. Educational only — not advice.")
    print(L)
    pd.DataFrame(consistent).to_csv("eval/watchlist_final.csv", index=False)
    print("\nSaved -> eval/watchlist_final.csv and eval/watchlist_full.csv")


if __name__ == "__main__":
    main()
