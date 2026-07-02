# IPO Screener — Research Notes & Build Plan

> Companion to `PROJECT_CONTEXT.md` / `MF_SYSTEM_PLAN.md`. Built 2026-07. Grounded
> in a 3-stream research pass (checklist · free-data feasibility · GMP/filters/SME),
> then every load-bearing endpoint was re-tested by hand from the dev box.

## 0. Goal
A third section (alongside Stocks & Mutual Funds) that screens **Indian IPOs**
(Mainboard + SME) two ways:
1. **Analyze one IPO** — paste a name → run the due-diligence checklist → an honest
   **verdict** (a *computed* Listing-Gain call + a *manual/enriched* Long-Term view).
2. **Live & Upcoming IPO list** — mainboard + SME, with rich filters (status, board,
   GMP, dates, subscription, size…), and an **Analyze** action on each row that jumps
   into (1) pre-loaded.

Same honesty rule as the rest of the app: **never claim data we can't actually get
free.** What free structured feeds give (subscription, GMP, anchor, P/E, board) is
*computed*; what only the RHP has (financials, OFS split, promoter, moat, governance)
is *manual-review* (optionally auto-filled by a free web-search API).

## 1. Tested free data stack (verified live 2026-07-02, from `requests`)
| Source | Access | Gives | Status |
|---|---|---|---|
| **NSE list** | `GET nseindia.com/api/all-upcoming-issues?category=ipo` | list: company, symbol, `series`(**EQ=Mainboard / SME**), start/end dates, price band, issueSize(shares), status(Active/Closed/Forthcoming), isBse | ✅ (browser UA; prime cookies on homepage first — Akamai) |
| **NSE current** | `/api/ipo-current-issue` | open issues + live overall `noOfTime`(× subscribed) | ✅ |
| **NSE detail** | `/api/ipo-detail?symbol=..&series=..` | **21-row category subscription** (QIB/FII/MF/NII/bHNI/sHNI/RII/Emp/Total ×), `issueInfo.dataList` (price range, **Bid Lot**, face value, registrar, **RHP zip link**, **Basis-of-Issue-Price/Ratios link**, Anchor report link) | ✅ authoritative for open/closed issues |
| **investorgain GMP** | `GET webnodejs.investorgain.com/cloud/report/data-read/331/1/1/2026/2025-26/0/all` (Referer req.) | 30 rows: `~ipo_name`, GMP(₹+%), `~gmp_percent_calc`, Rating(🔥), Sub, Price, IPO Size(₹cr), Lot, `~P/E`, Open/Close/BoA/Listing dates, Anchor(✅), `~IPO_Category`(IPO/SME), slug | ✅ clean JSON, **best for the LIST** (no SLA; **FY baked in URL → roll each Apr**) |
| **investorgain sub** | report **333** (same URL shape) | Name+GMP, Total/QIB/SHNI/BHNI/NII/RII ×, Anchor, IPO Size, Price, P/E, close date, IPO/SME | ✅ cross-check / fills list subscription |
| **Moneycontrol** | `moneycontrol.com/ipo/` SSR | issue size ₹cr, lot, subscription, allotment/listing dates, DRHP links | ⚠️ generic table headers → **skipped** (NSE+IG already cover it) |
| **screener.in** | `/company/<SYM>/consolidated/` | **post-listing** financials | ✅ (future: post-listing tracking) |
| **Tavily** | free key 1,000/mo, no card | web-search enrichment (fresh/OFS split, financials, promoter, objects) | ⚠️ **optional** — off by default; app fully works without it |

**Do NOT:** rely on keyless DuckDuckGo (blocked from datacenter IPs); scrape Chittorgarh (mixed Next.js RSC, AI-UA-blocked, no API); depend on Moneycontrol positional tables.

## 2. The honesty split — mirrors Stocks/MF
**TIER 1 — COMPUTED (free structured feeds) → the headline LISTING-GAIN score (0–100):**
| ID | Check | Metric (source) | PASS / CAUTION / FAIL | Wt |
|---|---|---|---|---|
| L1 | **QIB subscription** (smart money) | QIB × (NSE detail / IG 333) | ≥10× / 1–10× / <1× | 28 |
| L2 | Overall subscription | Total × | ≥20× / 3–20× / <1× | 14 |
| L3 | NII/HNI demand (sentiment) | NII × (bHNI split) | ≥10× / 1–10× / <1× | 8 |
| L4 | Retail-vs-QIB balance (froth guard) | QIB vs RII × | QIB≥RII / mild skew / QIB<2× & RII>5× | 10 |
| L5 | Anchor book present | Anchor ✅ (IG) | present / absent | 10 |
| L6 | **GMP** (caveated, soft) | GMP % (IG) | ≥20% / 0–20% / <0% | 15 |
| L7 | Valuation sanity | P/E (IG) | <25 / 25–40 / >40 *(verify vs peers)* | 15 |

Score = Σ wt·{PASS 1 / CAUTION .5 / FAIL 0} over *available* checks.
**GATE:** if IPO is **Upcoming** (subscription not out) → L1–L4 = N/A → verdict **WATCH — decide near close** (like MF UNTESTED). **SME risk modifier:** −12 pts (or higher bar) + illiquidity/₹1–2L-ticket/light-disclosure warnings; GMP down-weighted (SME grey market thin & manipulable).
**Critical-FAIL veto (caps verdict at AVOID):** overall <1× at close, QIB <1× at close, or negative GMP with weak subscription.

**TIER 2 — BEST-EFFORT (flagged, shown, not always scored):** GMP trend, rating, issue size/liquidity, lot & **min investment** (lot×price), reservation route (50/15/35 profitable vs 75/15/10 loss-making = itself a flag), dates (open/close/allot/listing), registrar, board+exchange.

**TIER 3 — MANUAL REVIEW (RHP-buried; never auto-scored — the LONG-TERM view):** with deep links to the NSE **RHP** & **Basis-of-Issue-Price** docs. Optionally auto-filled by Tavily.
- Objects of issue — **Fresh vs OFS split** (OFS>50% = red flag; SEBI caps SME OFS at 20%).
- Financials — 3y revenue/PAT CAGR, EBITDA/net margin, RoE/RoCE, D/E, **CFO vs PAT** (earnings quality), receivable days.
- Valuation vs **listed-peer median** P/E / P/B / EV-EBITDA (RHP Basis-of-Issue-Price table).
- Promoter — post-issue holding, **pledging**, background/track record, **RPT**.
- Anchor **quality** (marquee MFs/FPIs vs unknown).
- Sector tailwind / moat / market position.
- Risk factors, litigation, contingent liabilities, **auditor qualifications/CARO**, board independence.

## 3. Verdict framing (two tracks — the research's core insight)
Listing-gain ≠ long-term quality → show **both**, kept visibly separate.
- **Listing-Gain verdict** (computed): **APPLY (gains)** LG≥70 · **NEUTRAL/SELECTIVE** 45–70 · **AVOID** <45 or veto · **WATCH** if upcoming.
- **Long-Term view** (manual/enriched): Strong / Mixed / **Manual-review-needed**, driven by Tier-3 (RHP). Never set from GMP.
- Rules encoded: QIB > GMP/retail-hype; valuation is the swing factor on both; GMP never sets the verdict; SME modifier on top.

## 4. Live-IPO list — FILTER SPEC (mirrors IPO Watch / investorgain / Chittorgarh)
Controls: **Status** (Open / Upcoming / Closed / Listed) · **Board** (Mainboard / SME / All) · **Exchange** (NSE/BSE) · **GMP %** range (allow negative) · **GMP** has/none · **Price band** ₹ range · **Issue size** ₹cr buckets · **Min investment** range · **Overall / QIB / NII / Retail subscription** × ranges · **Open/Close/Listing date** ranges · **Sector** (best-effort) · **Sort by** (GMP% ▼ default, GMP₹, dates, subscription×, size, listing gain%).
Columns: Company · Board badge · Exchange · Status · Price band · Lot / min-invest · Size ₹cr · GMP ₹ · GMP % · trend · est. listing % · open · close · allot · listing · Sub overall/QIB/NII/RII × · listing-gain% (if listed) · **Analyze ▶** action · updated-at.

## 5. Architecture (mirrors MF section)
```
views/ipo.py       REPLACE placeholder: st.segmented_control("Analyze" | "Live & Upcoming")
                   Analyze: text input (+ prefilled from list) → deep dive
                   List: filters → dataframe → per-row Analyze ▶ (sets state + switches mode)
ipo_data.py        NEW fetchers: nse_ipo_list / nse_ipo_current / nse_ipo_detail /
                   investorgain_gmp(331) / investorgain_sub(333) / (optional) tavily_search
                   requests.Session w/ browser UA + NSE cookie-prime + in-mem & disk cache/fallback
ipo_core.py        NEW: normalize+merge feeds → analyze → Tier1 checks + LG score +
                   Tier2 best-effort + Tier3 manual + dual verdict; list_ipos(filters); run_analysis(name)
components/*        REUSED as-is (badge/check_row/manual_row/stat_tile/theme)
streamlit_app.py   move IPO from "Coming soon" into "Screeners"
```
Reuse `check_row`, `manual_row`, `badge_html`, `stat_tile`, `VERDICT_STYLE` (add IPO verdicts).

## 6. Open risks
NSE behind Akamai (UA + homepage cookie-prime; may block datacenter IPs) · investorgain FY hard-coded in URL (roll each April) + HTML entities in values · GMP unofficial/unregulated/manipulable (esp. SME) — caveated, low weight, never the verdict · fresh/OFS + financials not free-structured → manual/RHP-link or optional Tavily · subscription only meaningful after Day-3 close → gate upcoming issues to WATCH.

## 7. Phases
- **P1** `ipo_data.py` — fetchers + cache/disk fallback + NSE cookie-prime + name↔symbol match.
- **P2** `ipo_core.py` — merge/normalize + Tier1 LG score + Tier2 + Tier3 + dual verdict + list/filter.
- **P3** `views/ipo.py` — Analyze view + Live-list view + filters + Analyze▶ wiring.
- **P4** verify (live smoke on a current IPO + AppTest), polish, nav move.
