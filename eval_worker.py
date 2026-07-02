"""
Worker: collect walk-forward predictions for a subset of sectors.
Usage: python eval_worker.py <tag> <SECTOR> [<SECTOR> ...]
Writes eval/partial_<tag>.csv

~100 time points per stock (spread across the stock's valid history), graded at
2/3/4/5/6-month horizons. Only the 7 backtestable criteria (C1-C5, C9, C10).
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

from src.common import NIFTY, resolve_symbol
from src.indicators import add_indicators
from src.levels import support_resistance

HORIZONS = {"2m": 42, "3m": 63, "4m": 84, "5m": 105, "6m": 126}
STEP = 42                 # ~2-month gap between time points (full history)
MIN_HIST = 260
MAXH = max(HORIZONS.values())

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
    tag = sys.argv[1]
    sectors = sys.argv[2:]
    os.makedirs("eval", exist_ok=True)
    nifty = yf.Ticker(NIFTY).history(period="max", auto_adjust=False)[["Close"]].dropna()
    reg = regime_series(nifty["Close"])

    rows = []
    for sector in sectors:
        for name in SECTORS[sector]:
            try:
                symbol, tk = resolve_symbol(name)
                full = tk.history(period="max", interval="1d", auto_adjust=False)
                full = full[["Open","High","Low","Close","Volume"]].dropna()
            except Exception:
                print(f"  {sector} {name} skipped", flush=True); continue
            n = len(full)
            if n < MIN_HIST + MAXH + 60:
                print(f"  {sector} {name} short", flush=True); continue
            ind = add_indicators(full)
            naligned = nifty["Close"].reindex(ind.index, method="ffill")
            reg_aligned = reg.reindex(ind.index, method="ffill").fillna("sideways")
            positions = list(range(MIN_HIST, n - MAXH, STEP))  # every ~2 months
            cnt = 0
            for pos in positions:
                try:
                    passed, price = score_anchor(full, ind, pos, naligned, reg_aligned)
                except Exception:
                    continue
                row = {"sector": sector, "stock": symbol.split(".")[0],
                       "anchor_date": str(ind.index[pos].date()),
                       "regime": str(reg_aligned.iloc[pos]),
                       "criteria_passed": passed, "bucket": bucket(passed)}
                for hn, h in HORIZONS.items():
                    row[f"up_{hn}"] = bool(ind["Close"].iloc[pos+h] > price)
                    row[f"mv_{hn}"] = round(float(ind["Close"].iloc[pos+h]/price - 1)*100, 2)
                rows.append(row); cnt += 1
            print(f"  {sector:<9}{symbol.split('.')[0]:<12}{cnt} pts", flush=True)

    pd.DataFrame(rows).to_csv(f"eval/partial_{tag}.csv", index=False)
    print(f"DONE {tag}: {len(rows)} rows", flush=True)


if __name__ == "__main__":
    main()
