"""
Walk-forward eval of the positional checklist across 100 stocks x 10 anchors,
graded at MULTIPLE horizons: 2, 3, 4, 5, 6 months.

Tests the question: do longer holds give a higher probability of profit?

Only 7 of 10 criteria are backtestable (C1-C5, C9, C10); C6/C7/C8 (earnings,
promoter pledge, FII/DII) have no free historical feed. "High setup" = 6-7 of 7.

Output: eval/positional_results.csv  +  eval/positional_summary.txt
"""

from __future__ import annotations

import os
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

# anchors deep enough that all can grade a full 6 months (126 td) forward
ANCHORS = [126, 189, 252, 378, 504, 630, 756, 945, 1134, 1323]
HORIZONS = {"2m": 42, "3m": 63, "4m": 84, "5m": 105, "6m": 126}
MIN_HIST = 260

STOCKS = [
    ("TCS","IT"),("INFY","IT"),("WIPRO","IT"),("HCLTECH","IT"),("TECHM","IT"),
    ("LTIM","IT"),("PERSISTENT","IT"),("COFORGE","IT"),("MPHASIS","IT"),("LTTS","IT"),
    ("HDFCBANK","Bank"),("ICICIBANK","Bank"),("SBIN","Bank"),("AXISBANK","Bank"),
    ("KOTAKBANK","Bank"),("INDUSINDBK","Bank"),("BANKBARODA","Bank"),("PNB","Bank"),
    ("IDFCFIRSTB","Bank"),("FEDERALBNK","Bank"),
    ("BAJFINANCE","Finance"),("BAJAJFINSV","Finance"),("HDFCLIFE","Finance"),
    ("SBILIFE","Finance"),("ICICIPRULI","Finance"),("CHOLAFIN","Finance"),
    ("SHRIRAMFIN","Finance"),("MUTHOOTFIN","Finance"),("ICICIGI","Finance"),("HDFCAMC","Finance"),
    ("TATAMOTORS","Auto"),("MARUTI","Auto"),("M&M","Auto"),("EICHERMOT","Auto"),
    ("HEROMOTOCO","Auto"),("BAJAJ-AUTO","Auto"),("TVSMOTOR","Auto"),("ASHOKLEY","Auto"),
    ("BOSCHLTD","Auto"),("MOTHERSON","Auto"),
    ("SUNPHARMA","Pharma"),("DRREDDY","Pharma"),("CIPLA","Pharma"),("DIVISLAB","Pharma"),
    ("APOLLOHOSP","Pharma"),("LUPIN","Pharma"),("AUROPHARMA","Pharma"),("BIOCON","Pharma"),
    ("TORNTPHARM","Pharma"),("ALKEM","Pharma"),
    ("HINDUNILVR","FMCG"),("ITC","FMCG"),("NESTLEIND","FMCG"),("BRITANNIA","FMCG"),
    ("DABUR","FMCG"),("MARICO","FMCG"),("GODREJCP","FMCG"),("COLPAL","FMCG"),
    ("TATACONSUM","FMCG"),("VBL","FMCG"),
    ("TATASTEEL","Metals"),("JSWSTEEL","Metals"),("HINDALCO","Metals"),("VEDL","Metals"),
    ("JINDALSTEL","Metals"),("NMDC","Metals"),("SAIL","Metals"),("NATIONALUM","Metals"),
    ("APLAPOLLO","Metals"),("HINDZINC","Metals"),
    ("RELIANCE","Energy"),("ONGC","Energy"),("NTPC","Energy"),("POWERGRID","Energy"),
    ("COALINDIA","Energy"),("BPCL","Energy"),("IOC","Energy"),("GAIL","Energy"),
    ("TATAPOWER","Energy"),("ADANIGREEN","Energy"),
    ("ULTRACEMCO","Infra"),("GRASIM","Infra"),("SHREECEM","Infra"),("AMBUJACEM","Infra"),
    ("ACC","Infra"),("LT","Infra"),("ADANIPORTS","Infra"),("DLF","Infra"),
    ("ADANIENT","Infra"),("SIEMENS","Infra"),
    ("ASIANPAINT","Consumer"),("TITAN","Consumer"),("DMART","Consumer"),("TRENT","Consumer"),
    ("PIDILITIND","Consumer"),("HAVELLS","Consumer"),("BERGEPAINT","Consumer"),
    ("NAUKRI","Consumer"),("BHARTIARTL","Consumer"),("PAGEIND","Consumer"),
]


def regime_series(nclose: pd.Series) -> pd.Series:
    ema50 = nclose.ewm(span=50, adjust=False).mean()
    slope = (ema50 - ema50.shift(20)) / ema50.shift(20) * 100
    reg = pd.Series("sideways", index=nclose.index)
    reg[(nclose > ema50) & (slope > 1)] = "bull"
    reg[(nclose < ema50) & (slope < -1)] = "bear"
    return reg


def score_anchor(full, ind, pos, naligned, reg_aligned) -> dict:
    price = float(ind["Close"].iloc[pos])
    c1 = reg_aligned.iloc[pos] in ("bull", "sideways")
    avg20 = float(ind["Volume"].iloc[pos - 20:pos + 1].mean())
    c2 = avg20 > 500_000
    sma50, sma200 = ind["SMA50"].iloc[pos], ind["SMA200"].iloc[pos]
    c3 = bool(sma50 == sma50 and sma200 == sma200 and price > sma50 > sma200
              and sma50 > ind["SMA50"].iloc[pos - 20] and sma200 > ind["SMA200"].iloc[pos - 20])
    volma = ind["Vol_MA20"].iloc[pos]
    c4 = bool(volma == volma and volma and ind["Volume"].iloc[pos] >= 1.5 * volma)
    if pos - 126 >= 0:
        sret = price / float(ind["Close"].iloc[pos - 126]) - 1
        nret = float(naligned.iloc[pos]) / float(naligned.iloc[pos - 126]) - 1
        c5 = sret > nret
    else:
        c5 = False
    sr = support_resistance(full.iloc[:pos + 1])
    nsup, nres = sr.get("nearest_support"), sr.get("nearest_resistance")
    stop_price = price * 0.92
    structural = False
    if nsup and nsup["level"] < price and (price - nsup["level"]) / price <= 0.08:
        stop_price = nsup["level"] * 0.99
        structural = True
    stop_dist = (price - stop_price) / price * 100
    if nres and nres["level"] > price:
        upside = (nres["level"] - price) / price * 100
        rr = upside / stop_dist if stop_dist > 0 else None
        c9 = rr is not None and rr >= 3
    else:
        c9 = True
    c10 = bool(structural and stop_dist <= 8)
    passed = int(c1) + int(c2) + int(c3) + int(c4) + int(c5) + int(c9) + int(c10)
    return {"regime": str(reg_aligned.iloc[pos]), "passed": passed, "price": price}


def main():
    os.makedirs("eval", exist_ok=True)
    print("Fetching NIFTY ...")
    nifty = yf.Ticker(NIFTY).history(period="max", auto_adjust=False)[["Close"]].dropna()
    reg = regime_series(nifty["Close"])

    rows = []
    for i, (name, sector) in enumerate(STOCKS, 1):
        try:
            symbol, tk = resolve_symbol(name)
            full = tk.history(period="max", interval="1d", auto_adjust=False)
            full = full[["Open", "High", "Low", "Close", "Volume"]].dropna()
        except Exception as e:
            print(f"[{i}] ! {name}: {e}")
            continue
        n = len(full)
        if n < MIN_HIST + max(HORIZONS.values()) + 60:
            print(f"[{i}] ! {symbol.split('.')[0]}: short history")
            continue
        ind = add_indicators(full)
        naligned = nifty["Close"].reindex(ind.index, method="ffill")
        reg_aligned = reg.reindex(ind.index, method="ffill").fillna("sideways")

        cnt = 0
        for anchor in ANCHORS:
            pos = n - anchor - 1
            if pos < MIN_HIST or pos + max(HORIZONS.values()) > n - 1:
                continue
            try:
                s = score_anchor(full, ind, pos, naligned, reg_aligned)
            except Exception:
                continue
            row = {"stock": symbol.split(".")[0], "sector": sector,
                   "anchor_date": str(ind.index[pos].date()), "regime": s["regime"],
                   "criteria_passed": s["passed"]}
            for hname, h in HORIZONS.items():
                mv = float(ind["Close"].iloc[pos + h] / s["price"] - 1) * 100
                row[f"move_{hname}"] = round(mv, 2)
                row[f"up_{hname}"] = mv > 0
            rows.append(row)
            cnt += 1
        print(f"[{i}] {symbol.split('.')[0]:<12} {cnt} anchors")

    df = pd.DataFrame(rows)
    df.to_csv("eval/positional_results.csv", index=False)

    # ---- summary ----
    out, L = [], "=" * 72
    out.append(L); out.append("  POSITIONAL CHECKLIST — LONGER HORIZONS (2-6 months)")
    out.append(L)
    out.append(f"\nStocks={df['stock'].nunique()}  predictions={len(df)}")
    out.append("Backtested criteria: C1-C5, C9, C10 (C6/C7/C8 not historically available)")

    high = df[df["criteria_passed"] >= 6]

    out.append("\n[ UP-RATE BY HORIZON ]")
    out.append(f"  {'horizon':<9}{'ALL up%':<10}{'ALL avg':<10}{'HIGH up%':<11}{'HIGH avg':<10}{'HIGH n'}")
    for hname in HORIZONS:
        allu = df[f"up_{hname}"].mean() * 100
        alla = df[f"move_{hname}"].mean()
        hu = high[f"up_{hname}"].mean() * 100 if len(high) else float("nan")
        ha = high[f"move_{hname}"].mean() if len(high) else float("nan")
        out.append(f"  {hname:<9}{allu:<10.0f}{alla:<+10.2f}{hu:<11.0f}{ha:<+10.2f}{len(high)}")

    out.append("\n[ HIGH-SETUP (>=6/7) up-rate by # criteria, 3-month horizon ]")
    g = df.groupby("criteria_passed")
    for k, sub in g:
        out.append(f"  {k} passed: n={len(sub):<5} up_3m={sub['up_3m'].mean()*100:>4.0f}%  "
                   f"up_6m={sub['up_6m'].mean()*100:>4.0f}%  avg_6m={sub['move_6m'].mean():+.2f}%")

    # best horizon for high setups vs all
    out.append("\n[ DOES HOLDING LONGER HELP? (HIGH setup up-rate) ]")
    for hname in HORIZONS:
        if len(high):
            edge = (high[f"up_{hname}"].mean() - df[f"up_{hname}"].mean()) * 100
            out.append(f"  {hname}: HIGH {high[f'up_{hname}'].mean()*100:.0f}%  "
                       f"vs ALL {df[f'up_{hname}'].mean()*100:.0f}%  (edge {edge:+.1f}pp)")

    out.append("\n" + L)
    out.append("  Note: 7-criteria proxy; C6/C7/C8 not backtestable. Educational only.")
    text = "\n".join(out)
    print("\n" + text)
    with open("eval/positional_summary.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("\nSaved -> eval/positional_results.csv and eval/positional_summary.txt")


if __name__ == "__main__":
    main()
