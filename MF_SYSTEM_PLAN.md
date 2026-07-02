# Mutual Fund Screener — Research Notes & Build Plan

> Companion to `PROJECT_CONTEXT.md`. Built 2026-07. Grounded in a parallel
> research pass (18 agents) whose findings were adversarially critiqued and then
> the two load-bearing APIs were re-tested/calibrated by hand.

## 0. Goal
A second section (alongside Stocks; IPO later) that screens **Indian equity
mutual funds** against a 12-point professional checklist: paste many funds → get
a ranked comparison table → drill into any fund. Same honesty rule as the stock
tool: **never claim data we can't actually get free.**

## 1. Tested free data stack (verified 2026-07-02)
| Source | Access | Gives | Status |
|---|---|---|---|
| **mfapi.in** | `GET api.mfapi.in/mf/{code}` · `/mf/search?q=` | Full NAV history to inception (2013→now for direct), `meta.scheme_category`, `meta.isin_growth` | ✅ solid, no auth |
| **Kuvera (unofficial)** | `GET mf.captnemo.in/kuvera/{ISIN}` **(-L)** | AUM, expense_ratio (direct), fund_manager names, fund_category, start_date, lock_in_period, crisil_rating, portfolio_turnover | ✅ works, no SLA → cache weekly + disk fallback |
| **AMFI NAVAll.txt** | `portal.amfiindia.com/spages/NAVAll.txt` | Scheme master (code↔ISIN↔name), category via section headers | ✅ (optional, for full universe) |
| **Benchmark** | yfinance PRI (`^NSEI`,`^CNX100`,`^CRSLDX`…) v1; freefincal/niftyindices **TRI CSV** drop-in later | Index series for alpha/beta/capture | ⚠️ PRI overstates alpha ~div-yield → labeled |
| **Risk-free** | config constant **0.0525** (91-day T-bill, Jul-2026) | Sharpe/Sortino/alpha | editable |

**Calibrations locked in:** Kuvera `aum ÷ 10 = ₹ crore` (scheme-level, verified 2 funds). Category from `mfapi.meta.scheme_category` (clean string e.g. "Equity Scheme - Flexi Cap Fund"). Query the **direct-growth ISIN** so expense_ratio is the direct-plan TER.
**Do NOT:** use `mftool` (broken); scrape Value Research/Morningstar (ToS).

## 2. The honesty split — three tiers (mirrors stock Setup/Quality/Manual)

**TIER 1 — COMPUTED SCORE (headline, 0–100, from free NAV + benchmark + rf):**
| Check | Metric | Method | Threshold | Wt |
|---|---|---|---|---|
| C2 | Track record **(also a GATE)** | age from Kuvera `start_date` (fallback NAV inception); require ≥1 crash+recovery drawdown episode | ≥5y strong / ≥3y min; <3y or <36 mo obs → **N/A** | 10 |
| C4 | Rolling returns | daily-step **3y & 5y** windows; fund CAGR vs benchmark CAGR; hit-ratio = % windows won | PASS ≥75% (CAUTION if <~250 windows) | 25 |
| C5 | Jensen's Alpha | OLS monthly excess returns vs benchmark; annualized intercept | PASS > 1.5% (report β, R²) | 20 |
| C6 | Sharpe & Sortino | 36+ monthly returns annualized; downside dev vs rf | > category median, ideally >1.0 | 20 |
| C7 | Std Dev & Beta | SD annualized (NAV-only); β vs benchmark (need R²≥0.8) | β≤1.0 (large-cap); SD < cat median | 10 |
| C8 | Downside capture | geometric, months where benchmark<0 | PASS < 90% | 15 |

**TIER 2 — DATA-DEPENDENT (Kuvera; best-effort, flagged, NOT in headline by default; optional toggle):**
- C1 AUM: `aum÷10` cr; category-conditional (small-cap ceiling ~30k, large/index floor ~10k). Startup calibration assertion.
- C11 Expense ratio: direct TER; PASS <1.0% active / <0.2% index; show as-of date.
- C12 lock-in: Kuvera `lock_in_period` (0 = none). Full exit-load schedule → manual.

**TIER 3 — MANUAL REVIEW (never scored, with links):**
- C3 Manager **tenure date** (Kuvera gives names only) → AMC factsheet.
- C9 Top-10 concentration → AMFI/AMC monthly portfolio Excel.
- C10 Active share → holdings + benchmark constituent weights.
- C12 exit-load schedule → SID.

Every metric carries a provenance tag `{computable | free-api-besteffort | manual}` and relative metrics print benchmark + rf + window.

## 3. Category → benchmark map (editable config)
Large→Nifty 100 · Large&Mid→Nifty LargeMidcap 250 · Mid→Nifty Midcap 150 · Small→Nifty Smallcap 250 · Multi→Nifty 500 Multicap · Flexi/ELSS/Focused/Value→Nifty 500 · Index/Sectoral→tracked index (override).

## 4. Architecture — Streamlit native multipage (st.navigation + st.Page, top nav)
```
streamlit_app.py        NEW entrypoint: set_page_config + inject_css ONCE; st.navigation({...}, position="top")
components/theme.py      palette constants + inject_css() + VERDICT_STYLE   (extracted from screener_app.py)
components/ui.py         shared: badge_html, stat tiles, table stylers, criteria/manual rows
views/stocks.py          existing stock UI moved ~verbatim (session_state keys → stocks.*)
views/mutual_funds.py    NEW MF screener page
views/ipo.py             NEW "coming soon" placeholder
mf_data.py               NEW fetchers (mfapi, Kuvera, benchmark) — st.cache_data + disk fallback
mf_core.py               NEW NAV→metrics + 3-tier scoring + summarize/quality/manual (mirrors screener_core.py)
screener_core.py, src/   UNCHANGED
```
Launch: `streamlit run streamlit_app.py` (keep a `screener_app.py` shim during transition).

## 5. Phases
- **Phase 0** — Refactor to multipage; verify stocks unbroken.
- **Phase 1** — `mf_data.py`: fetchers + cache + disk fallback + calibration assertion.
- **Phase 2** — `mf_core.py`: metrics (C2,C4–C8) + Tier-2 (C1,C11,C12) + 3-tier scoring + summarize/quality/manual.
- **Phase 3** — `views/mutual_funds.py`: bulk search/paste → ranked table → deep dive (per-check grid + NAV-vs-benchmark chart + manual panel).
- **Phase 4** — verify (AppTest + live smoke), polish.

## 6. Open risks (from adversarial critique)
Free APIs have no SLA (cache + disk fallback) · TRI unavailable free → PRI proxy labeled · survivorship bias in peer medians (caveat) · must enumerate **direct-growth only** per peer to avoid double-count · manager tenure date permanently manual · direct-NAV floor 2013 → use Kuvera `start_date` for age · 5y rolling meaningless for young funds → gate to N/A.
