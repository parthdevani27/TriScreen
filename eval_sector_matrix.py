"""
Sector x Horizon x Criteria-passed eval.

~165 stocks across 10 sectors, ~18 historical anchor points each, graded at
2/3/4/5/6-month horizons. Output: for every sector, how many stocks went up at
each horizon, split by how many checklist criteria passed.

Only 7 of 10 criteria are backtestable (C1-C5, C9, C10). Buckets:
  HIGH = 6-7 passed,  MID = 4-5,  LOW = 0-3.

Output: eval/sector_matrix.csv (tidy) + eval/sector_matrix_summary.txt + raw csv.
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

ANCHORS = list(range(126, 1600, 84))      # ~18 points, every ~4 months
HORIZONS = {"2m": 42, "3m": 63, "4m": 84, "5m": 105, "6m": 126}
MIN_HIST = 260

SECTORS = {
    "IT": ["TCS","INFY","WIPRO","HCLTECH","TECHM","LTIM","PERSISTENT","COFORGE",
           "MPHASIS","LTTS","OFSS","KPITTECH","TATAELXSI","BSOFT","CYIENT",
           "ZENSARTECH","NEWGEN","INTELLECT"],
    "Bank": ["HDFCBANK","ICICIBANK","SBIN","AXISBANK","KOTAKBANK","INDUSINDBK",
             "BANKBARODA","PNB","IDFCFIRSTB","FEDERALBNK","AUBANK","BANDHANBNK",
             "CANBK","UNIONBANK","RBLBANK","INDIANB","BANKINDIA"],
    "Finance": ["BAJFINANCE","BAJAJFINSV","HDFCLIFE","SBILIFE","ICICIPRULI",
                "CHOLAFIN","SHRIRAMFIN","MUTHOOTFIN","ICICIGI","HDFCAMC","SBICARD",
                "LICHSGFIN","PFC","RECLTD","M&MFIN","MANAPPURAM"],
    "Auto": ["TATAMOTORS","MARUTI","M&M","EICHERMOT","HEROMOTOCO","BAJAJ-AUTO",
             "TVSMOTOR","ASHOKLEY","BOSCHLTD","MOTHERSON","BALKRISIND","MRF",
             "APOLLOTYRE","BHARATFORG","EXIDEIND","TIINDIA"],
    "Pharma": ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","APOLLOHOSP","LUPIN",
               "AUROPHARMA","BIOCON","TORNTPHARM","ALKEM","ZYDUSLIFE","GLENMARK",
               "IPCALAB","LAURUSLABS","ABBOTINDIA","NATCOPHARM"],
    "FMCG": ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO","GODREJCP",
             "COLPAL","TATACONSUM","VBL","UBL","UNITDSPR","EMAMILTD","RADICO",
             "PGHH","JUBLFOOD"],
    "Metals": ["TATASTEEL","JSWSTEEL","HINDALCO","VEDL","JINDALSTEL","NMDC","SAIL",
               "NATIONALUM","APLAPOLLO","HINDZINC","JSL","RATNAMANI","WELCORP",
               "HINDCOPPER","MOIL"],
    "Energy": ["RELIANCE","ONGC","NTPC","POWERGRID","COALINDIA","BPCL","IOC","GAIL",
               "TATAPOWER","ADANIGREEN","ADANIPOWER","NHPC","OIL","PETRONET","IGL",
               "TORNTPOWER"],
    "Infra": ["ULTRACEMCO","GRASIM","SHREECEM","AMBUJACEM","ACC","LT","ADANIPORTS",
              "DLF","ADANIENT","SIEMENS","ABB","BEL","BHEL","JKCEMENT","DALBHARAT"],
    "Consumer": ["ASIANPAINT","TITAN","DMART","TRENT","PIDILITIND","HAVELLS",
                 "BERGEPAINT","NAUKRI","BHARTIARTL","PAGEIND","VOLTAS","DIXON",
                 "POLYCAB","CROMPTON","BATAINDIA"],
}


def regime_series(nclose):
    ema50 = nclose.ewm(span=50, adjust=False).mean()
    slope = (ema50 - ema50.shift(20)) / ema50.shift(20) * 100
    reg = pd.Series("sideways", index=nclose.index)
    reg[(nclose > ema50) & (slope > 1)] = "bull"
    reg[(nclose < ema50) & (slope < -1)] = "bear"
    return reg


def score_anchor(full, ind, pos, naligned, reg_aligned):
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
    return int(c1)+int(c2)+int(c3)+int(c4)+int(c5)+int(c9)+int(c10), price


def bucket(p):
    return "HIGH(6-7)" if p >= 6 else ("MID(4-5)" if p >= 4 else "LOW(0-3)")


def main():
    os.makedirs("eval", exist_ok=True)
    print("Fetching NIFTY ...")
    nifty = yf.Ticker(NIFTY).history(period="max", auto_adjust=False)[["Close"]].dropna()
    reg = regime_series(nifty["Close"])

    rows = []
    i = 0
    for sector, names in SECTORS.items():
        for name in names:
            i += 1
            try:
                symbol, tk = resolve_symbol(name)
                full = tk.history(period="max", interval="1d", auto_adjust=False)
                full = full[["Open","High","Low","Close","Volume"]].dropna()
            except Exception:
                print(f"  [{i}] ! {name} skipped"); continue
            n = len(full)
            if n < MIN_HIST + max(HORIZONS.values()) + 60:
                print(f"  [{i}] ! {name} short"); continue
            ind = add_indicators(full)
            naligned = nifty["Close"].reindex(ind.index, method="ffill")
            reg_aligned = reg.reindex(ind.index, method="ffill").fillna("sideways")
            cnt = 0
            for anchor in ANCHORS:
                pos = n - anchor - 1
                if pos < MIN_HIST or pos + max(HORIZONS.values()) > n - 1:
                    continue
                try:
                    passed, price = score_anchor(full, ind, pos, naligned, reg_aligned)
                except Exception:
                    continue
                row = {"sector": sector, "stock": symbol.split(".")[0],
                       "anchor_date": str(ind.index[pos].date()),
                       "criteria_passed": passed, "bucket": bucket(passed)}
                for hn, h in HORIZONS.items():
                    row[f"up_{hn}"] = (float(ind["Close"].iloc[pos+h]/price - 1) > 0)
                    row[f"mv_{hn}"] = round(float(ind["Close"].iloc[pos+h]/price - 1)*100, 2)
                rows.append(row); cnt += 1
            print(f"  [{i}] {sector:<9}{symbol.split('.')[0]:<12}{cnt} pts")

    df = pd.DataFrame(rows)
    df.to_csv("eval/sector_matrix_raw.csv", index=False)

    # ---- build tidy aggregate + readable tables ----
    tidy, out = [], []
    L = "=" * 80
    out.append(L); out.append("  SECTOR x HORIZON x CRITERIA — % OF STOCKS THAT WENT UP")
    out.append(L)
    out.append(f"\nStocks={df['stock'].nunique()}  predictions={len(df)}  "
               f"anchors/stock<= {len(ANCHORS)}  horizons=2-6 months")
    out.append("Buckets by criteria passed (of 7): HIGH=6-7, MID=4-5, LOW=0-3\n")

    border = "  " + "-" * 64
    for sector in SECTORS:
        sub = df[df["sector"] == sector]
        if sub.empty:
            continue
        out.append(f"\n### {sector}   (stocks={sub['stock'].nunique()}, setups={len(sub)})")
        out.append(f"  {'bucket':<11}{'2m':<11}{'3m':<11}{'4m':<11}{'5m':<11}{'6m':<11}")
        out.append(border)
        for bk in ["HIGH(6-7)", "MID(4-5)", "LOW(0-3)"]:
            bsub = sub[sub["bucket"] == bk]
            cells = []
            for hn in HORIZONS:
                if len(bsub):
                    up = bsub[f"up_{hn}"].mean() * 100
                    cells.append(f"{up:.0f}%(n{len(bsub)})")
                    tidy.append({"sector": sector, "bucket": bk, "horizon": hn,
                                 "n": len(bsub), "up_pct": round(up, 1),
                                 "avg_move": round(bsub[f"mv_{hn}"].mean(), 2)})
                else:
                    cells.append("-")
            out.append(f"  {bk:<11}" + "".join(f"{c:<11}" for c in cells))

    # ---- headline: HIGH bucket up% by sector x horizon ----
    out.append("\n" + L)
    out.append("  HEADLINE: HIGH setups (6-7 criteria) — % that went up, by sector")
    out.append(L)
    out.append(f"  {'sector':<11}{'2m':<10}{'3m':<10}{'4m':<10}{'5m':<10}{'6m':<10}{'n'}")
    out.append(border)
    hi = df[df["bucket"] == "HIGH(6-7)"]
    for sector in SECTORS:
        s = hi[hi["sector"] == sector]
        if not len(s):
            out.append(f"  {sector:<11}{'(no high setups)'}"); continue
        cells = [f"{s[f'up_{hn}'].mean()*100:.0f}%" for hn in HORIZONS]
        out.append(f"  {sector:<11}" + "".join(f"{c:<10}" for c in cells) + f"{len(s)}")
    out.append(border)
    cells = [f"{hi[f'up_{hn}'].mean()*100:.0f}%" for hn in HORIZONS]
    out.append(f"  {'ALL SECT':<11}" + "".join(f"{c:<10}" for c in cells) + f"{len(hi)}")
    base = [f"{df[f'up_{hn}'].mean()*100:.0f}%" for hn in HORIZONS]
    out.append(f"  {'BASELINE':<11}" + "".join(f"{c:<10}" for c in base) + f"{len(df)}")

    out.append("\n" + L)
    out.append("  Note: 7-criteria proxy; small n per sector cell -> treat as indicative.")
    out.append("  Mostly bull-period sample. Educational only — not investment advice.")
    out.append(L)

    pd.DataFrame(tidy).to_csv("eval/sector_matrix.csv", index=False)
    text = "\n".join(out)
    print("\n" + text)
    with open("eval/sector_matrix_summary.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print("\nSaved -> eval/sector_matrix.csv, eval/sector_matrix_raw.csv, eval/sector_matrix_summary.txt")


if __name__ == "__main__":
    main()
