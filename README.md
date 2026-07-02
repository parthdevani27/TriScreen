# Stock Analysis Project — Positional Checklist (1–2 month)

Type a stock name → the system downloads full history, runs the **10-criteria
positional checklist** (Minervini Trend Template + CANSLIM style, for a 1–2 month
hold), and saves everything under `output/<STOCK>/`.

```
python run.py TCS            # full checklist + report
python run.py RELIANCE --no-news
```

## The 10 criteria (4 groups)
1. **Market & Liquidity** — C1 index uptrend/sideways · C2 liquidity ≥ 500k avg vol
2. **Technical Momentum** — C3 above rising 50 & 200 SMA · C4 volume ≥1.5× avg · C5 6-month relative strength
3. **Fundamental & Governance** — C6 earnings YoY ≥20% · C7 promoter pledge ≤10%* · C8 institutional holding rising*
4. **Trade Execution** — C9 risk-reward ≥3:1 to resistance · C10 structural stop within 5–8%

\* C7 & C8 need promoter-pledge / FII-DII data that has **no free programmatic
feed** → flagged `[VERIFY]`; check on screener.in / trendlyne / nseindia.com.

## Probability matrix
| Confirmed score | Band | Action |
|---|---|---|
| 9–10 | High (75%+) | Conviction buy, full size — after verifying C7 & C8 |
| 7–8 | Moderate (50–60%) | Caution buy, half size |
| < 7 | Low / failing | Avoid |

> ⚠️ **Honest note.** The 75% / 50–60% figures are the checklist's *design
> targets, not guarantees*. Our own walk-forward backtests (2,500+ trades) showed
> technical edges are modest and rarely beat simply buying — so treat the score
> as **setup quality + risk discipline**, not a promise of profit. Always use the
> stop-loss; risk ≤1–2% of capital per trade. For long-term wealth, low-cost
> index funds historically beat stock-picking. Educational only — not advice.

## Setup (one time)
```bash
python -m pip install -r requirements.txt
```

## Run
```bash
python run.py TCS                      # daily analysis
python run.py RELIANCE --interval weekly
python run.py INFY --interval monthly
```
Use NSE symbols (TCS, INFY, RELIANCE, HDFCBANK). BSE is tried as a fallback.

## What it does (pipeline)
1. **Download** full price history from the very start (Yahoo Finance, free).
2. **Indicators** — EMA 20/50/200, RSI, MACD, ATR, Bollinger, OBV, A/D, VWAP,
   ADX, Stochastic, Supertrend.
3. **Support/Resistance** zones (swing pivots) + Fibonacci levels.
4. **Patterns** — candlesticks (hammer, engulfing, doji…) + chart patterns
   (double top/bottom, head & shoulders).
5. **Volume analysis** — VWAP position, OBV/A-D trend & divergence, volume
   spike, volume profile (high/low volume nodes).
6. **Fundamentals** — sector, valuation, health, liquidity, relative strength
   vs NIFTY, market trend, next earnings date.
7. **10-criteria checklist** → confirmed score /10, probability band, position-size
   action, and a full trade plan (entry, structural stop, target, risk-reward).

## Outputs (per stock, in `output/<STOCK>/`)
| File | Contents |
|---|---|
| `<STOCK>_daily_ohlcv.parquet` | full history + all indicators (load for pattern analysis) |
| `<STOCK>_daily_ohlcv.csv` | same, Excel-friendly |
| `<STOCK>_daily_analysis.json` | all analysis results (machine-readable) |
| `<STOCK>_daily_report.txt` | human-readable report + scorecard |
| `<STOCK>_daily_chart.png` | candlestick chart + EMAs + support/resistance |

## Project structure
```
demo/
├─ run.py              # entry point
├─ requirements.txt
├─ src/               # all code
│   ├─ common.py        # symbol resolution
│   ├─ data.py          # history download / resample
│   ├─ indicators.py    # all indicators
│   ├─ levels.py        # support/resistance + fibonacci
│   ├─ candles.py       # candlestick patterns
│   ├─ chart_patterns.py# double top/bottom, head & shoulders
│   ├─ volume.py        # volume analysis + profile
│   ├─ fundamentals.py  # fundamentals + relative strength
│   ├─ scorecard.py     # combined verdict
│   ├─ plotting.py      # charts
│   ├─ report.py        # text report
│   └─ main.py          # orchestrator
└─ output/            # results, one folder per stock
```

> Educational tool, not investment advice. Always confirm earnings/news,
> FII/DII and delivery % on NSE/Screener, and use a stop-loss before trading.
