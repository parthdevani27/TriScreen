# PROJECT CONTEXT & HANDOFF

> Read this first in any future session. It captures the whole project, every
> key finding, the data we have, and what to do next — so we can continue
> without redoing the journey.

_Last updated: 2025-12 (analysis snapshot). Market data via Yahoo Finance (free)._

---

## 1. Who this is for / goal
- **User:** retail investor in **India (NSE/BSE)**. Wants to find stocks with a
  **high probability of profit**, originally short-term, now **1–2 month
  positional** holds.
- **User preferences (important):** wants **brutal honesty, no false promises**,
  evidence over hype. Likes **iterative testing**, bigger samples, and is fine
  running **parallel shell jobs**. Appreciates simple-language explanations.

## 2. What we built
A Python system: **type a stock → full technical + fundamental analysis →
10-criteria positional checklist → score + trade plan**, saved per stock under
`output/<STOCK>/`.

**Run it:** `python run.py TCS`  (add `--no-news` to skip FinBERT for speed).

### Code layout (`src/`)
- `common.py` — Yahoo symbol resolution (NSE `.NS`, BSE `.BO` fallback)
- `data.py` — full-history download + resample
- `indicators.py` — EMA/SMA(50/150/200)/RSI/MACD/ATR/ADX/Stoch/Supertrend/OBV/VWAP/Bollinger
- `levels.py` — support/resistance (scipy pivots) + Fibonacci
- `candles.py`, `chart_patterns.py` — candlestick & chart-pattern detection
- `volume.py` — VWAP/OBV/volume-profile analysis
- `fundamentals.py` — market regime, 6-month relative strength, quarterly earnings YoY
- `scorecard.py` — **the 10-criteria checklist** (`build_checklist`)
- `news.py` — Google-News RSS + **FinBERT** sentiment (transformers+torch installed)
- `plotting.py`, `report.py`, `main.py` — charts, report, orchestrator

### Environment notes
- **Python 3.14** on Windows. Use `python -m pip` (pip not on PATH).
- Console needs UTF-8: scripts call `sys.stdout.reconfigure(encoding="utf-8")`.
- Deps in `requirements.txt` (+ `transformers`, `torch` for FinBERT — installed).

## 3. The 10-criteria checklist (Minervini Trend Template + CANSLIM)
1. Market & Liquidity: **C1** index uptrend/sideways · **C2** liquidity ≥500k avg vol
2. Technical Momentum: **C3** above rising 50&200 SMA · **C4** volume ≥1.5× avg · **C5** 6-mo relative strength
3. Fundamental/Governance: **C6** earnings YoY ≥20% · **C7** promoter pledge ≤10% · **C8** institutional holding rising
4. Trade Execution: **C9** risk-reward ≥3:1 · **C10** structural stop within 5–8%

Probability matrix: 9–10 = High (75% target) · 7–8 = Moderate · <7 = Avoid.

**CRITICAL data limit:** only **7 of 10 are backtestable** (C1–C5, C9, C10).
**C6/C7/C8 have NO free historical feed** (earnings history, promoter pledge,
FII/DII) → they are MANUAL checks in the live tool and EXCLUDED from backtests.
"High setup" in backtests = **6–7 of the 7** testable criteria.

## 4. KEY FINDINGS (the most important knowledge — don't re-derive)
We ran extensive walk-forward backtests (up to **19,115 predictions, 158 stocks,
1996–2025, all regimes**). Conclusions, in order of confidence:

1. **Short-term (≤10 day) direction = no edge.** ~42–54% directional, ~26%
   catastrophic. Coin flip. Do NOT use the system for swing/intraday.
2. **Profitability backtest (2,500+ trades): the signals do NOT beat simply
   buying anything.** Edge vs "buy-anything" benchmark was **negative** for the
   flat signal and the 3-tier gate. Any positive total was **market drift**, not skill.
3. **Positional (1–2 month+) is where a SMALL edge appears.** High setups held
   **3–6 months** beat baseline by **~+2 to +4pp** (best at 6m, ~67% vs ~62%).
   Real but small — NOT the 75% the matrix claims.
4. **The system only fires in up/sideways markets** (C1 requires market uptrend)
   → it **sits out bear markets by design** (only ~1 HIGH setup in bear regime
   across 30 years). Good risk behaviour; can't be judged in crashes.
5. **~58–63% baseline "up rate" is just Indian equities' long-term drift** over
   2–6 months — an index fund captures that for free.
6. **Sector "winners" shuffle every run → mostly noise.** Metals looked best on a
   small sample, then REVERSED to worst with more data (classic small-sample
   illusion). No sector is robustly superior.
7. **"Qualifies today" ≠ "will go up."** e.g. ASIANPAINT qualified historically
   but its HIGH setups went up only 50%.

**Bottom line:** the system is a good **descriptive + risk-discipline screener**,
NOT a profit predictor. For wealth, **low-cost index SIP** beats it. Realistic
active edge ≈ a few percentage points, only with long holds + strict stops.

## 5. Saved data (in `eval/`) — fully browsable
- **`sector_matrix_raw.csv`** ⭐ — every prediction (19,115 rows): stock, sector,
  anchor_date, regime, criteria_passed, bucket, up_2m..up_6m, mv_2m..mv_6m.
  This is the per-stock, per-time-period history. Open in Excel or ask me to query.
- `sector_matrix.csv` / `sector_matrix_summary.txt` — sector × horizon × bucket up%.
- `watchlist_full.csv` — every stock's today-score + historical record.
- `watchlist_final.csv` — filtered (qualifies now + consistent).
- `positional_results.csv` — earlier 980-row run.

### Eval/utility scripts (root)
- `eval_worker.py` + `eval_merge.py` — parallel walk-forward eval (run 10 workers,
  one per sector, then merge). 2-month spacing across full history.
- `eval_sector_matrix.py` — single-process sector matrix (older).
- `eval_positional.py` — multi-horizon (2–6m) eval.
- `build_watchlist.py` — qualifies-today ∩ historically-consistent list.
- `analyze_list.py` — run checklist + show history for a CUSTOM list (edit `WANTED`).

## 6. Watchlist snapshot (as of 2025-12-19 — re-run to refresh)
- **Qualifies today (6/10):** ASIANPAINT, COALINDIA (Moderate) — but weak/thin history.
- **Historically most consistent (NOT qualifying now — watch for trigger):**
  MOTHERSON, **INDUSINDBK (5/7, closest)**, HDFCBANK, BAJFINANCE, POWERGRID.
- Caveat: small overlapping samples, bull-biased. Treat as higher-odds, not sure.

## 7. Known limitations
- Free data only (yfinance): no historical earnings/pledge/FII-DII → C6/C7/C8 not backtestable.
- Backtest samples **overlap** (correlated → effective n < nominal).
- Period is **mostly bull** (Indian equities rose) → inflates baseline up-rates.
- ETFs (GOLDBEES, MON100, GROWWDEFNC, etc.): the **stock checklist doesn't apply**
  (no fundamentals) — judge ETFs by trend/allocation instead.
- News/FinBERT is **live only** (no historical news) → not in backtests.

## 8. Open next steps (if user wants to continue)
- Stress-test any "good" sector by **bull vs sideways split + costs + 20% STCG**.
- Get **point-in-time fundamentals (paid)** to finally test C6/C7/C8 — the
  untested half is where CANSLIM's real edge supposedly lives.
- Build a proper **ML model** (features incl. fundamentals) with strict
  train/test time split — realistic ceiling ~52–55% directional.
- Add a **daily watchlist alert** (re-run `build_watchlist.py`, flag new qualifiers).
- Possibly a `history.py <STOCK>` helper to print any stock's saved breakdown.

## 9. How to resume in a future session
Say e.g.: *"Read PROJECT_CONTEXT.md and continue."* Then I can immediately:
- query `eval/sector_matrix_raw.csv` for any stock's full history,
- re-run `python build_watchlist.py` for fresh qualifiers,
- run `python analyze_list.py` (edit the list) for custom stocks,
- or pick up an open next-step above.

> Honesty principle to carry forward: report results faithfully, flag small
> samples, never claim an edge the data doesn't support, and keep recommending
> risk management + index investing as the high-probability core.
