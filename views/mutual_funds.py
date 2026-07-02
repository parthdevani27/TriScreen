"""Mutual Funds section — equity MF screener (12-point professional checklist).

Honesty split (mirrors the stock tool): a computed TIER-1 score from free NAV +
benchmark + risk-free; TIER-2 data-dependent items (AUM/TER/lock-in) shown but
flagged; TIER-3 manual-review panel for what no free tool can verify.
"""

from __future__ import annotations

import io

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import mf_core as mf
import mf_data as mfd
from components.theme import (PAGE, SURFACE, INK, INK_2, MUTED, GRID, BLUE,
                              AQUA, GOOD, WARNING, CRITICAL, PLOTLY_TEMPLATE)
from components.ui import (badge_html, fmt_pct, fmt_num, stat_tile, style_verdict,
                           check_row, manual_row, group_label)

# --------------------------------------------------------------------------- #
#  Header
# --------------------------------------------------------------------------- #
st.markdown('<p class="app-title">📊 Mutual Fund Screener</p>', unsafe_allow_html=True)


def parse_names(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


# --------------------------------------------------------------------------- #
#  Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### Screen mutual funds")
    funds_text = st.text_area(
        "Fund names or scheme codes (one per line)",
        value=("Parag Parikh Flexi Cap Direct Growth\n"
               "Mirae Asset Large Cap Direct Growth\n"
               "Nippon India Small Cap Direct Growth\n"
               "HDFC Mid-Cap Opportunities Direct Growth\n"
               "UTI Nifty 50 Index Direct Growth"),
        height=150, placeholder="One fund per line — prefer the Direct-Growth plan")
    rf = st.number_input("Risk-free rate (annual %)", min_value=0.0, max_value=15.0,
                         value=mf.RISK_FREE_DEFAULT * 100, step=0.25,
                         help="Short-term risk-free (91-day T-bill ≈ 5.26%, Jul-2026) — the textbook "
                              "rate for Sharpe/alpha. The 10-yr G-sec (~6.7%) is a different, "
                              "longer-duration instrument; set it if you prefer. Barely changes the "
                              "relative ranking either way.") / 100
    tiebreak = st.radio(
        "Break score ties by",
        ["Risk-adjusted (consistency + Sharpe)", "Recent return (3Y CAGR)"],
        index=0,
        help="Funds often share a score (it's built from discrete PASS/CAUTION/FAIL checks). "
             "Default breaks ties by rolling consistency & Sharpe (the system's risk-adjusted thesis). "
             "Switch to CAGR for a returns-first order.")
    run = st.button("Run analysis", type="primary", use_container_width=True)
    if st.button("Clear cache", use_container_width=True, key="mf_clear"):
        mf.clear_cache()
        st.session_state.pop("mf.results", None)
        st.toast("Cache cleared")
    st.markdown('<div class="disclaimer">Educational only — <b>not financial advice</b>. '
                'Benchmark is a <b>price index</b> (true TRI isn\'t free) so alpha is '
                'overstated by ~the index dividend yield. Data from free community APIs '
                '(mfapi.in, Kuvera) with no SLA — verify before acting.</div>',
                unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
#  Run
# --------------------------------------------------------------------------- #
if run:
    names = parse_names(funds_text)
    if not names:
        st.warning("Enter at least one fund.")
    else:
        prog = st.progress(0.0, text="Starting…")

        def cb(done, total, q):
            prog.progress(done / total, text=f"Analyzed {done}/{total} — {q}")

        st.session_state["mf.results"] = mf.run_batch(names, rf=rf, progress_cb=cb)
        st.session_state["mf.rf"] = rf
        prog.empty()

results = st.session_state.get("mf.results")
if not results:
    st.info("👈 Enter fund names in the sidebar and hit **Run analysis** to begin.")
    st.stop()

summaries = [mf.summarize(r) for r in results]
ok = [s for s in summaries if s["verdict"] != "ERROR"]
errs = [s for s in summaries if s["verdict"] == "ERROR"]
skey = mf.make_sort_key("returns" if tiebreak.startswith("Recent") else "risk")
ok.sort(key=skey)

# ---- stat tiles ----
cnt = {}
for s in ok:
    cnt[s["verdict"]] = cnt.get(s["verdict"], 0) + 1
t1, t2, t3, t4, t5 = st.columns(5)
stat_tile(t1, "Screened", len(summaries), INK)
stat_tile(t2, "Strong", cnt.get("STRONG", 0), GOOD)
stat_tile(t3, "Decent", cnt.get("DECENT", 0), BLUE)
stat_tile(t4, "Weak / Poor", cnt.get("WEAK", 0) + cnt.get("POOR", 0), WARNING)
stat_tile(t5, "Untested", cnt.get("UNTESTED", 0), MUTED)
st.markdown("<br>", unsafe_allow_html=True)

if errs:
    with st.expander(f"⚠️ {len(errs)} fund(s) not found / failed", expanded=False):
        for e in errs:
            st.write(f"**{e['name']}** — {e['error']}")

# ---- ranked comparison — isolated BY CATEGORY (a small-cap ≠ a large-cap) ----
st.markdown("### Ranked comparison")

CORE_ORDER = ["large", "large_mid", "flexi", "multi", "mid", "small",
              "value", "focused", "elss", "equity_other"]

_COLCFG = {
    "Fund": st.column_config.TextColumn("Fund", width="medium"),
    "Category": st.column_config.TextColumn("Category", help="⚠️ = benchmark is a proxy (sector/foreign), so alpha here is unreliable."),
    "Why": st.column_config.TextColumn("Why", width="large"),
    "Score": st.column_config.TextColumn("Score", help="Computed 0-100 (rolling/alpha/Sharpe/SD-beta/capture/track-record). Not a prediction of future return."),
    "Roll 3y": st.column_config.TextColumn("Roll 3y", help="% of daily-step 3-yr windows the fund beat its benchmark (the consistency measure that drives the score)."),
    "CAGR 3y": st.column_config.TextColumn("CAGR 3y", help="Trailing point-to-point — shown for context; NOT what the score uses."),
    "Alpha": st.column_config.TextColumn("Alpha", help="Annualized excess vs a PRICE index → overstated ~dividend yield."),
    "Dn-cap": st.column_config.TextColumn("Dn-cap", help="Share of the market's falls the fund absorbs. Lower is better (<90%)."),
    "Expense": st.column_config.TextColumn("Expense", help="Direct-plan TER (best-effort, Kuvera). Lower is better."),
    "AUM ₹cr": st.column_config.TextColumn("AUM ₹cr", help="Best-effort (Kuvera); not in the headline score by default."),
}


def render_group(subset, show_category=False):
    subset = sorted(subset, key=skey)
    rows = []
    for i, s in enumerate(subset, 1):
        row = {"#": i, "Verdict": s["verdict"], "Fund": s["name"]}
        if show_category:
            row["Category"] = s["category_label"] + (" ⚠️" if s.get("benchmark_proxy") else "")
        rows.append({
            **row,
            "Score": s["score"] if (s["score"] is not None and s["verdict"] != "UNTESTED") else "—",
            "Roll 3y": fmt_pct(s["hit_3y"], sign=False) if s.get("hit_3y") is not None else "—",
            "CAGR 3y": fmt_pct(s["cagr_3y"], sign=False),
            "Alpha": fmt_pct(s["alpha"]),
            "Sharpe": s["sharpe"] if s["sharpe"] is not None else "—",
            "Dn-cap": fmt_pct(s["downside_capture"], sign=False) if s["downside_capture"] is not None else "—",
            "Expense": fmt_pct(s["expense_ratio"], sign=False) if s["expense_ratio"] is not None else "—",
            "AUM ₹cr": f'{s["aum_cr"]:,.0f}' if isinstance(s.get("aum_cr"), (int, float)) else "—",
            "Why": s["rationale"],
        })
    tbl = pd.DataFrame(rows)
    styled = tbl.style.map(style_verdict, subset=["Verdict"]).set_properties(**{"font-size": "0.85rem"})
    # size to fit ALL rows (up to a tall cap) so the fullscreen ⛶ view fills the
    # screen instead of showing ~11 rows over a big empty area.
    height = min(1500, 38 + 35 * (len(tbl) + 1))
    st.dataframe(styled, use_container_width=True, hide_index=True,
                 height=height, column_config=_COLCFG)


core = [s for s in ok if s.get("bucket") == "core"]
satellite = [s for s in ok if s.get("bucket") == "satellite"]
passive = [s for s in ok if s.get("bucket") == "passive"]
hybrid = [s for s in ok if s.get("bucket") == "hybrid"]

from collections import defaultdict
bycat = defaultdict(list)
for s in core:
    bycat[s["category"]].append(s)
order = CORE_ORDER + [c for c in bycat if c not in CORE_ORDER]
present_cats = [c for c in order if bycat.get(c)]

# ---- view selector: one unified ranked table, filterable by category ----
ALL_LABEL = "🏆 All core equity — ranked head-to-head"
view_opts = [ALL_LABEL] + [bycat[c][0]["category_label"] for c in present_cats]
if hybrid:
    view_opts.append("⚖️ Hybrid / Multi-Asset")
if satellite:
    view_opts.append("🛰️ Satellite (thematic / international)")
if passive:
    view_opts.append("📉 Index / Passive")
view = st.selectbox(
    "View", view_opts, index=0,
    help="'All' ranks every actively-managed equity fund together. This is fair because the "
         "score is benchmark-relative & risk-adjusted (each fund vs its OWN peers), not raw returns. "
         "Pick a category to drill in.")

if view == ALL_LABEL:
    if core:
        render_group(core, show_category=True)
    else:
        st.info("No core equity funds in this run — see the Satellite / Index views.")
elif view.startswith("⚖️"):
    st.warning("⚖️ **Hybrid / multi-asset funds hold gold + debt + equity**, so their low volatility "
               "**inflates Sharpe & downside-capture** — that high score is diversification, *not* equity "
               "skill. Don't compare these to pure-equity compounders; they're a lower-risk, lower-growth "
               "sleeve. This is why they're kept OUT of the 'All core equity' ranking.")
    render_group(hybrid, show_category=True)
elif view.startswith("🛰️"):
    st.warning("⚠️ Benchmarked to a generic index (no free sector/foreign index) — **Alpha & "
               "downside-capture are unreliable** here. Judge these on the theme's outlook, not the score.")
    render_group(satellite, show_category=True)
elif view.startswith("📉"):
    st.caption("Index funds are meant to **match** the market — judge on low tracking error & expense "
               "ratio, not alpha/Sharpe. A small positive alpha ≈ the index dividend yield.")
    render_group(passive, show_category=True)
else:
    cat = next((c for c in present_cats if bycat[c][0]["category_label"] == view), None)
    if cat:
        render_group(bycat[cat], show_category=False)

# CSV mirrors the grouped display: sorted by group, with an in-category rank column.
csv_rows = []


def _add_group(group_name, subset):
    for i, s in enumerate(sorted(subset, key=skey), 1):
        base = {k: v for k, v in s.items() if k not in ("tier1", "tier2")}
        csv_rows.append({"group": group_name, "rank_in_group": i, **base})


for cat in order:
    grp = bycat.get(cat)
    if grp:
        _add_group(grp[0]["category_label"], grp)
if hybrid:
    _add_group("Hybrid / Multi-Asset", hybrid)
if satellite:
    _add_group("Satellite (thematic/international)", satellite)
if passive:
    _add_group("Index/Passive", passive)

buf = io.StringIO()
pd.DataFrame(csv_rows).to_csv(buf, index=False)
st.download_button("⬇ Download results (CSV — grouped & ranked by category)", buf.getvalue(),
                   file_name="mf_screener_results.csv", mime="text/csv")

st.markdown("---")

# --------------------------------------------------------------------------- #
#  Deep dive
# --------------------------------------------------------------------------- #
st.markdown("### Deep dive")
options = [s["name"] for s in ok] + [s["name"] for s in errs]
if not options:
    st.stop()
pick = st.selectbox("", options, key="mf_pick")

sel_res = next((r for r in results if (r.get("name") or r.get("query")) == pick), None)
sel_sum = next((s for s in summaries if s["name"] == pick), None)
if sel_res is None or sel_res.get("_error"):
    st.error(f"No analysis for {pick}: {sel_res.get('_error') if sel_res else 'not found'}")
    st.stop()

enr = sel_res.get("enrichment") or {}

# ---- header metrics ----
h1, h2, h3, h4, h5, h6 = st.columns([1.6, 1, 1, 1, 1, 1])
with h1:
    st.markdown(f"#### {pick}")
    st.markdown(badge_html(sel_sum["verdict"]), unsafe_allow_html=True)
h2.metric("Score", f'{sel_sum["score"]}/100' if (sel_sum["score"] is not None and sel_sum["verdict"] != "UNTESTED") else "—",
          help="Computed Tier-1 score. Not a prediction of future return.")
h3.metric("CAGR 3y / 5y", f'{fmt_pct(sel_sum["cagr_3y"], sign=False)} / {fmt_pct(sel_sum["cagr_5y"], sign=False)}')
h4.metric("Alpha", fmt_pct(sel_sum["alpha"]), help="vs price index → overstated ~div yield.")
h5.metric("Sharpe / Sortino", f'{sel_sum["sharpe"] if sel_sum["sharpe"] is not None else "—"} / {sel_sum["sortino"] if sel_sum["sortino"] is not None else "—"}')
h6.metric("Down-capture", fmt_pct(sel_sum["downside_capture"], sign=False) if sel_sum["downside_capture"] is not None else "—")

stale = " · ⚠️ enrichment stale (cached)" if sel_sum.get("stale_enrichment") else ""
st.caption(f"{sel_sum['category_label']} · benchmark {sel_res['benchmark_name']} · "
           f"NAV from {sel_res['nav_start']} · rf {sel_res['rf']*100:.2f}%{stale}")

if sel_sum.get("bucket") == "satellite":
    st.warning("🛰️ **Satellite fund** (sectoral / thematic / international) — benchmarked to a generic "
               "index because no free sector/foreign index is available. **Alpha, beta and downside-capture "
               "below are unreliable** (e.g. a negative downside-capture is a benchmark/currency artifact). "
               "Judge this fund on its theme's outlook, not the computed score.")
elif sel_sum.get("benchmark_proxy"):
    st.caption(f"⚠️ Benchmark is an approximation ({sel_res['benchmark_name']}) — alpha/beta are indicative, "
               "not exact, for this category.")

left, right = st.columns([1.12, 1])

# ---- Tier-1 computed check grid ----
with left:
    st.markdown("##### Computed checks (Tier 1 — the score)")
    for c in sel_sum["tier1"]["checks"]:
        check_row(c["label"], c["value"], c["status"], c["note"], cid=c["id"])
    st.caption("PASS/CAUTION/FAIL vs category-aware thresholds. Fully computed from free NAV + benchmark.")

# ---- Tier-2 data-dependent ----
with right:
    st.markdown("##### Cost & size (Tier 2 — best-effort)")
    t2 = sel_sum["tier2"]
    if t2:
        for c in t2:
            check_row(c["label"], c["value"], c["status"], c["note"], cid=c["id"])
    else:
        st.info("AUM / expense unavailable from the free feed right now.")
    mgr = enr.get("fund_manager")
    if mgr:
        st.caption(f"**Manager(s):** {mgr}")
    if enr.get("crisil_rating"):
        st.caption(f"Vendor risk rating: {enr.get('crisil_rating')}")
    st.caption("Kuvera (unofficial) — flagged, and NOT folded into the headline score by default.")

# ---- NAV vs benchmark growth chart ----
st.markdown("---")
st.markdown("##### Growth of ₹100 — fund vs benchmark (rebased)")
try:
    _, nav_df = mfd.fetch_nav_history(sel_res["code"])
    nav = nav_df["nav"]
    bench = mfd.fetch_benchmark_series(sel_res["benchmark_kind"], sel_res["benchmark_ref"])
    fig = go.Figure()
    common_start = nav.index[0]
    if bench is not None:
        b = bench.reindex(nav.index, method="ffill").dropna()
        common_start = max(nav.index[0], b.index[0])
        b = b.loc[common_start:]
        b100 = b / b.iloc[0] * 100
        fig.add_trace(go.Scatter(x=b100.index, y=b100.values, name=sel_res["benchmark_name"],
                                 line=dict(color=MUTED, width=1.5)))
    f = nav.loc[common_start:]
    f100 = f / f.iloc[0] * 100
    fig.add_trace(go.Scatter(x=f100.index, y=f100.values, name="Fund",
                             line=dict(color=AQUA, width=2)))
    fig.update_layout(template=PLOTLY_TEMPLATE, paper_bgcolor=PAGE, plot_bgcolor=SURFACE,
                      height=430, margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
                      font=dict(color=INK_2), hovermode="x unified")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    st.plotly_chart(fig, use_container_width=True)
    if bench is not None:
        st.caption("Benchmark is a PRICE index (excludes dividends), so the fund's lead is "
                   "flattered by ~the index dividend yield each year.")
except Exception as e:
    st.info(f"Chart unavailable: {e}")

# ---- Tier-3 manual review ----
st.markdown(f'##### ⚠️ Manual review required '
            f'<span style="color:{MUTED};font-weight:400;font-size:.9rem">'
            f'— the tool can\'t verify these from free data</span>', unsafe_allow_html=True)
for m in mf.manual_review_items(sel_res):
    manual_row(m["title"], m["detail"], m["where"], m["sev"])
st.caption("Manager tenure, portfolio concentration and active share are where closet-indexing and "
           "key-person risk hide — the computed score can't see them.")
