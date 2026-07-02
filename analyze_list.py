"""
Run the checklist on a custom list + show saved history (if any).
Usage: python analyze_list.py
"""

from __future__ import annotations

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from src.common import resolve_symbol
from src.indicators import add_indicators
from src.levels import support_resistance
from src.volume import analyze_volume
from src.fundamentals import gather_fundamentals
from src.scorecard import build_checklist

# requested name -> corrected NSE symbol
WANTED = ["ASIANPAINT", "COALINDIA", "GOLDBEES", "GROWWDEFNC",
          "HINDCOPPER", "MON100", "VEDL"]
ETFS = {"GOLDBEES", "MON100", "GROWWDEFNC"}

try:
    RAW = pd.read_csv("eval/sector_matrix_raw.csv")
    for c in ["up_3m", "up_6m"]:
        if RAW[c].dtype == object:
            RAW[c] = RAW[c].map({"True": True, "False": False})
except Exception:
    RAW = None

ICON = {"PASS": "[P]", "FAIL": "[ ]", "MANUAL": "[M]", "UNKNOWN": "[?]"}


def history_for(stock: str):
    if RAW is None:
        return None
    g = RAW[RAW["stock"] == stock]
    if g.empty:
        return None
    hi = g[g["criteria_passed"] >= 6]
    return {
        "periods": len(g),
        "span": f"{g['anchor_date'].min()} -> {g['anchor_date'].max()}",
        "all_up6": round(g["up_6m"].mean() * 100),
        "all_avg6": round(g["mv_6m"].mean(), 1),
        "high_n": len(hi),
        "high_up3": round(hi["up_3m"].mean() * 100) if len(hi) else None,
        "high_up6": round(hi["up_6m"].mean() * 100) if len(hi) else None,
        "high_avg6": round(hi["mv_6m"].mean(), 1) if len(hi) else None,
    }


def main():
    for name in WANTED:
        L = "=" * 70
        print("\n" + L)
        try:
            symbol, tk = resolve_symbol(name)
            full = tk.history(period="max", interval="1d", auto_adjust=False)
            full = full[["Open", "High", "Low", "Close", "Volume"]].dropna()
            df = add_indicators(full)
            sr = support_resistance(df)
            vol = analyze_volume(df)
            fund = gather_fundamentals(tk, df)
            sc = build_checklist(df, fund, sr, vol)
        except Exception as e:
            print(f"  {name}: FAILED ({e})")
            continue

        is_etf = name in ETFS
        tag = "  [ETF — fundamental criteria N/A; technical only]" if is_etf else ""
        print(f"  {name} ({symbol})  price {fund['price']['last']}{tag}")
        print(L)
        print(f"  CURRENT SCORE: {sc['confirmed_score']}/10 confirmed "
              f"(up to {sc['best_case_score']}/10 with manual)  ->  {sc['band']}")
        # compact criteria line
        line = "  ".join(f"{ICON[c['status']]}{c['id']}" for c in sc["criteria"])
        print("  " + line)
        print(f"  Trade plan: entry {fund['price']['last']}  stop {sc['stop_price']} "
              f"({sc['stop_dist_pct']}%)  " +
              (f"target {sc['target_price']} (RR 1:{sc['risk_reward']})" if sc['target_price']
               else "open upside"))

        # history
        h = history_for(symbol.split(".")[0])
        if h:
            print(f"\n  HISTORY ({h['periods']} time periods, {h['span']}):")
            print(f"    All setups: up after 6m = {h['all_up6']}%  (avg {h['all_avg6']:+.1f}%)")
            if h["high_n"]:
                print(f"    When it qualified HIGH (6-7): n={h['high_n']}  "
                      f"up_3m={h['high_up3']}%  up_6m={h['high_up6']}%  avg_6m={h['high_avg6']:+.1f}%")
            else:
                print("    Never reached a HIGH (6-7) setup in history.")
        elif is_etf:
            print("\n  HISTORY: ETF — not in our backtest dataset (we tested stocks only).")
        else:
            print("\n  HISTORY: not in saved dataset.")
    print("\n" + "=" * 70)
    print("  Educational only — not investment advice. Verify earnings/pledge/FII-DII,")
    print("  hold 3-6 months, use a stop-loss. ETFs: fundamentals don't apply.")


if __name__ == "__main__":
    main()
