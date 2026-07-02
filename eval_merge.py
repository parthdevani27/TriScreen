"""Merge all eval/partial_*.csv and build the sector x horizon x criteria tables."""

from __future__ import annotations

import glob
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

HORIZONS = ["2m", "3m", "4m", "5m", "6m"]
SECTOR_ORDER = ["IT", "Bank", "Finance", "Auto", "Pharma", "FMCG", "Metals",
                "Energy", "Infra", "Consumer"]


def _b(s):
    return s.map({"True": True, "False": False, True: True, False: False}) if s.dtype == object else s


def main():
    files = glob.glob("eval/partial_*.csv")
    if not files:
        print("No partial files found."); return
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    for h in HORIZONS:
        df[f"up_{h}"] = _b(df[f"up_{h}"])
    df.to_csv("eval/sector_matrix_raw.csv", index=False)

    out, tidy = [], []
    L = "=" * 84
    out.append(L); out.append("  SECTOR x HORIZON x CRITERIA — % WENT UP   (100 time points/stock)")
    out.append(L)
    out.append(f"\nStocks={df['stock'].nunique()}  predictions={len(df):,}  horizons=2-6 months")
    out.append("Buckets by criteria passed (of 7): HIGH=6-7, MID=4-5, LOW=0-3")

    sectors = [s for s in SECTOR_ORDER if s in df["sector"].unique()]
    border = "  " + "-" * 70
    for sector in sectors:
        sub = df[df["sector"] == sector]
        out.append(f"\n### {sector}   (stocks={sub['stock'].nunique()}, setups={len(sub):,})")
        out.append(f"  {'bucket':<12}{'2m':<12}{'3m':<12}{'4m':<12}{'5m':<12}{'6m':<12}")
        out.append(border)
        for bk in ["HIGH(6-7)", "MID(4-5)", "LOW(0-3)"]:
            bsub = sub[sub["bucket"] == bk]
            cells = []
            for h in HORIZONS:
                if len(bsub):
                    up = bsub[f"up_{h}"].mean() * 100
                    cells.append(f"{up:.0f}% (n{len(bsub)})")
                    tidy.append({"sector": sector, "bucket": bk, "horizon": h,
                                 "n": len(bsub), "up_pct": round(up, 1),
                                 "avg_move": round(bsub[f"mv_{h}"].mean(), 2)})
                else:
                    cells.append("-")
            out.append(f"  {bk:<12}" + "".join(f"{c:<12}" for c in cells))

    # Headline HIGH table
    out.append("\n" + L)
    out.append("  HEADLINE: HIGH setups (6-7 criteria) — % went up, by sector x horizon")
    out.append(L)
    out.append(f"  {'sector':<11}{'2m':<11}{'3m':<11}{'4m':<11}{'5m':<11}{'6m':<11}{'n'}")
    out.append(border)
    hi = df[df["bucket"] == "HIGH(6-7)"]
    for sector in sectors:
        s = hi[hi["sector"] == sector]
        if not len(s):
            out.append(f"  {sector:<11}(no high setups)"); continue
        cells = [f"{s[f'up_{h}'].mean()*100:.0f}%" for h in HORIZONS]
        out.append(f"  {sector:<11}" + "".join(f"{c:<11}" for c in cells) + f"{len(s)}")
    out.append(border)
    cells = [f"{hi[f'up_{h}'].mean()*100:.0f}% (n{len(hi)})" for h in HORIZONS]
    out.append(f"  {'ALL HIGH':<11}" + "".join(f"{c:<11}" for c in cells))
    cells = [f"{df[f'up_{h}'].mean()*100:.0f}%" for h in HORIZONS]
    out.append(f"  {'BASELINE':<11}" + "".join(f"{c:<11}" for c in cells) + f"{len(df):,}")
    out.append(border)
    cells = [f"{(hi[f'up_{h}'].mean()-df[f'up_{h}'].mean())*100:+.1f}pp" for h in HORIZONS]
    out.append(f"  {'EDGE':<11}" + "".join(f"{c:<11}" for c in cells))

    # Regime breakdown (the key robustness test: does it work in bad times?)
    if "regime" in df.columns:
        out.append("\n" + L)
        out.append("  ROBUSTNESS: HIGH setups (6-7) by MARKET REGIME at entry")
        out.append(L)
        out.append(f"  {'regime':<11}{'2m':<11}{'3m':<11}{'4m':<11}{'5m':<11}{'6m':<11}{'n'}")
        out.append(border)
        for rg in ["bull", "sideways", "bear"]:
            s = hi[hi["regime"] == rg]
            if not len(s):
                out.append(f"  {rg:<11}(none)"); continue
            cells = [f"{s[f'up_{h}'].mean()*100:.0f}%" for h in HORIZONS]
            out.append(f"  {rg:<11}" + "".join(f"{c:<11}" for c in cells) + f"{len(s)}")
        out.append(border)
        out.append("  (baseline, ALL setups by regime:)")
        for rg in ["bull", "sideways", "bear"]:
            s = df[df["regime"] == rg]
            if not len(s):
                continue
            cells = [f"{s[f'up_{h}'].mean()*100:.0f}%" for h in HORIZONS]
            out.append(f"  {rg:<11}" + "".join(f"{c:<11}" for c in cells) + f"{len(s):,}")
        # date span
        out.append(f"\n  Time span: {df['anchor_date'].min()} -> {df['anchor_date'].max()}")

    out.append("\n" + L)
    out.append("  Note: time points per stock OVERLAP -> correlated samples (effective")
    out.append("  sample < nominal n). Full-history 2-month spacing. Educational — not advice.")
    out.append(L)

    pd.DataFrame(tidy).to_csv("eval/sector_matrix.csv", index=False)
    text = "\n".join(out)
    print(text)
    with open("eval/sector_matrix_summary.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("\nSaved -> eval/sector_matrix_summary.txt, eval/sector_matrix.csv, eval/sector_matrix_raw.csv")


if __name__ == "__main__":
    main()
