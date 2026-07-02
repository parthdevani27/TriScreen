"""Stocks section — positional stock screener.

Ported from the original screener_app.py. Theme/CSS/set_page_config live in the
entrypoint (streamlit_app.py); this file is a section page run by st.navigation.

Honesty (per PROJECT_CONTEXT.md): scores *setup quality & risk*, not future
profit. Realistic edge is a few percentage points, only on 1-2 month+ holds with
strict stops. Educational — not financial advice.
"""

from __future__ import annotations

import datetime
import io
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

import screener_core as core
from src import deep_checks as dc
from components.theme import (PAGE, SURFACE, INK, INK_2, MUTED, GRID, BLUE, VIOLET,
                              GOOD, WARNING, CRITICAL, QUALITY_COLOR, PLOTLY_TEMPLATE)
from components.ui import (badge_html, fmt_pct, fmt_num, stat_tile,
                           style_verdict, style_quality, render_verify_panel)

# --------------------------------------------------------------------------- #
#  Header
# --------------------------------------------------------------------------- #
st.markdown('<p class="app-title">📈 Positional Stock Screener</p>', unsafe_allow_html=True)


def fmt_analyst(s):
    up, rec = s.get("analyst_upside"), s.get("analyst_rec")
    if up is None and not rec:
        return "—"
    return f"{fmt_pct(up)} · {(rec or '').replace('_', ' ')}".strip(" ·")


def _entry_timing_label(et: dict) -> str:
    dm = et.get("day_move_pct")
    if et.get("spiked_today"):
        return f"🔥 spiked{f' +{dm:.0f}%' if isinstance(dm,(int,float)) else ''} today — don't chase, wait 2-3 days"
    if et.get("extended"):
        return "⏫ extended — wait for a pullback"
    return "OK — not extended, no spike to chase"


def _cell(v) -> str:
    """Sanitise a value for a Markdown table cell (escape pipes, flatten newlines)."""
    return str(v).replace("|", "\\|").replace("\n", " ").strip()


def _pledge_line(p: dict) -> str:
    if not p or p.get("error"):
        return f"Pledge: — (source unavailable: {p.get('error', 'n/a') if p else 'n/a'})"
    pl = p.get("pledge_pct")
    if pl is None:
        return "Pledge: —"
    if pl >= 1:
        return f"🔴 Promoters have pledged **{pl:.1f}%** of their holding (red flag — verify trend)"
    return "🟢 No meaningful promoter pledge"


def _trend_line(label: str, d: dict) -> str:
    if not d:
        return f"{label}: —"
    arrow = {"rising": "🔼", "falling": "🔻", "flat": "▪️"}.get(d.get("direction"), "")
    return f"{label}: {d.get('latest')}% ({arrow} {d.get('direction')}, {d.get('delta'):+.2f} pts vs ~2q ago)"


def _forensic_line(f: dict) -> list:
    if not f or f.get("error"):
        return [f"_Forensic scores unavailable: {f.get('error', 'n/a') if f else 'n/a'}_"]
    out = []
    p, a, b = f.get("piotroski"), f.get("altman"), f.get("beneish")
    if p:
        out.append(f"- **Piotroski F**: {p['score']}/{p['used']} ({p['rating']}) — fundamental health")
    if a:
        out.append(f"- **Altman Z″**: {a['z']} ({a['zone']}) — distress risk")
    elif f.get("altman_na"):
        out.append(f"- **Altman Z″**: n/a ({f['altman_na']} — model doesn't apply)")
    if b:
        out.append(f"- **Beneish M**: {b['m']} — {'⚠️ earnings-manipulation flag (> −2.22)' if b['flag'] else 'no earnings-manipulation flag'}")
    return out or ["_No forensic scores computable from the feed._"]


def _deepdive_markdown(pick, sel_res, sel_sum, score, qa, manual, auto=None) -> str:
    """Assemble the entire deep-dive view as a self-contained Markdown document."""
    rr = score.get("risk_reward")
    rr_str = f"{rr:.1f}:1" if isinstance(rr, (int, float)) else "open"
    an_up, an_rec = sel_sum.get("analyst_upside"), (sel_sum.get("analyst_rec") or "n/a").replace("_", " ")
    L = [f"# {pick} — {sel_sum.get('verdict')}", ""]
    L.append(f"*As of {sel_res.get('as_of')} · Setup completeness: {score.get('band')}*  ")
    L.append(f"**Verdict:** {sel_sum.get('rationale')}")
    L += ["", "| Metric | Value |", "|---|---|"]
    L.append(f"| Price | {fmt_num(sel_sum.get('price'), p='₹')} |")
    L.append(f"| Setup (technical) | {score.get('confirmed_score')}→{score.get('best_case_score')}/10 |")
    L.append(f"| Quality (fundamental) | {qa.get('rating')} ({qa.get('good')}/{qa.get('applicable')} good) |")
    L.append(f"| Reward:Risk | {rr_str} |")
    L.append(f"| Analyst target | {fmt_pct(an_up)} · {an_rec} |")

    warns = []
    dq = sel_res.get("data_quality") or {}
    et = score.get("entry_timing") or {}
    if dq.get("partial_trimmed"):
        warns.append(f"⏱️ Today's in-progress candle ({dq.get('partial_date')}) excluded — analysis on the last complete session.")
    if et.get("spiked_today"):
        warns.append(f"🔥 Spiked ~{et.get('day_move_pct')}% today — don't chase; wait 2-3 days for a pullback.")
    if dq.get("suspect_gap"):
        warns.append(f"⚠️ Possible unadjusted corporate action (~{dq.get('move_pct')}% on {dq.get('date')}) — verify before trusting the setup.")
    if et.get("extended"):
        warns.append(f"⏫ Extended ~{et.get('pct_above_sma50')}% above the 50-DMA — poor entry.")
    if warns:
        L += ["", "## Flags"] + [f"- {w}" for w in warns]

    L += ["", "## 10-criteria checklist", "| # | Criterion | Status | Detail |", "|---|---|---|---|"]
    for c in score.get("criteria", []):
        L.append(f"| {c['id']} | {_cell(c['label'])} | {c['status']} | {_cell(c['detail'])} |")

    L += ["", "## Trade plan", "| Field | Value |", "|---|---|"]
    L.append(f"| Entry (last close) | {fmt_num(sel_sum.get('price'), p='₹')} |")
    L.append(f"| Stop-loss | {'₹' + str(score.get('stop_price')) if score.get('stop_price') else '—'} |")
    sd = score.get("stop_dist_pct")
    L.append(f"| Stop distance | {fmt_pct(-sd) if isinstance(sd, (int, float)) else '—'} |")
    if score.get("target_price"):
        L.append(f"| Target (resistance) | ₹{score.get('target_price')} |")
        L.append(f"| Upside to target | {fmt_pct(score.get('upside_pct')) if score.get('upside_pct') is not None else '—'} |")
        L.append(f"| Reward:Risk | {rr_str} |")
    elif score.get("atr_target"):
        L.append(f"| Target (3×ATR, blue-sky) | ₹{score.get('atr_target')} |")
        L.append(f"| Reward:Risk | {score.get('atr_rr')}:1 (ATR est.) |" if score.get("atr_rr") else "| Reward:Risk | open |")
    else:
        L.append("| Target | open upside |")
    L.append(f"| Stop type | {'structural support' if score.get('stop_structural') else '8% hard stop (no support)'} |")
    L.append(f"| Entry timing | {_entry_timing_label(et)} |")

    L += ["", f"## Fundamental quality — {qa.get('rating')} ({qa.get('good')}/{qa.get('applicable')} good)"]
    if qa.get("checks"):
        L += ["| Group | Check | Value | Status |", "|---|---|---|---|"]
        for cq in qa["checks"]:
            L.append(f"| {_cell(cq['group'])} | {_cell(cq['label'])} | {_cell(cq['value'])} | {cq['status']} |")
    else:
        L.append("_No fundamental data available from the feed._")

    if auto:
        f, p, g = auto.get("forensic"), auto.get("pledge"), auto.get("gov")
        L += ["", "## 🤖 Automated deep checks (free sources — verify the big ones)"]
        L += ["**Governance & accounting (forensic scores):**"] + _forensic_line(f)
        L += ["", f"**Promoter pledge (C7):** {_pledge_line(p)}"]
        if p and not p.get("error"):
            L += ["", "**Institutional trend (C8):**",
                  f"- {_trend_line('Promoters', p.get('promoter'))}",
                  f"- {_trend_line('FIIs', p.get('fii'))}",
                  f"- {_trend_line('DIIs', p.get('dii'))}"]
        if g and not g.get("error"):
            if g.get("governance"):
                L += ["", "**Recent governance / auditor filings (BSE):**"]
                L += [f"- {gi['date']} — {_cell(gi['subject'])}" for gi in g["governance"]]
            if g.get("transcript"):
                L += ["", f"**Latest concall transcript:** {g['transcript'].get('date')} — {g['transcript'].get('pdf')}"]
        L += ["", "_Auto-checks are best-effort from free sources (yfinance statements · screener.in · BSE) — hints, not verified truth._"]

    L += ["", "## ⚠️ Manual review required (not in free data)"]
    for m in manual:
        L.append(f"- **{m['title']}** ({m['sev']}) — {_cell(m['detail'])} · _Check:_ {m['where']}")

    news = sel_res.get("news")
    if news and news.get("headlines"):
        L += ["", "## Recent headlines"] + [f"- {h.get('title', '')}" for h in news["headlines"][:5]]

    L += ["", "_Educational only — not financial advice. Setup quality & risk, not a profit prediction._"]
    return "\n".join(L)


_COPY_HTML = """
<div style="font-family:sans-serif;">
  <button id="ddcopy" style="background:#3987e5;color:#fff;border:none;padding:7px 15px;
    border-radius:7px;cursor:pointer;font-size:0.85rem;font-weight:600;">📋 Copy deep dive (Markdown)</button>
  <span id="ddmsg" style="margin-left:10px;color:#22c55e;font-size:0.82rem;"></span>
</div>
<script>
const t = __PAYLOAD__;
const b = document.getElementById('ddcopy'), m = document.getElementById('ddmsg');
b.onclick = async () => {
  let ok = false;
  try { await navigator.clipboard.writeText(t); ok = true; }
  catch (e) {
    const a = document.createElement('textarea');
    a.value = t; a.style.position = 'fixed'; a.style.opacity = '0';
    document.body.appendChild(a); a.focus(); a.select();
    try { ok = document.execCommand('copy'); } catch (e2) { ok = false; }
    document.body.removeChild(a);
  }
  m.textContent = ok ? '✓ Copied to clipboard' : 'Copy failed — select the text and copy manually';
  setTimeout(() => { m.textContent = ''; }, 2500);
};
</script>
"""


def _copy_button(md_text: str):
    components.html(_COPY_HTML.replace("__PAYLOAD__", json.dumps(md_text)), height=46)


def parse_tickers(text: str) -> list[str]:
    parts = []
    for chunk in (text or "").replace(",", "\n").replace(";", "\n").replace(" ", "\n").splitlines():
        c = chunk.strip()
        if c:
            parts.append(c)
    return parts


# --------------------------------------------------------------------------- #
#  Sidebar — inputs
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("### Screen stocks")
    tickers_text = st.text_area(
        "Tickers (comma / space / newline separated)",
        value="TITAN, BEL, INDIANB, LUPIN, DRREDDY",
        height=120, placeholder="e.g. TCS, RELIANCE, HDFCBANK")

    interval = st.selectbox("Interval", ["daily", "weekly", "monthly"], index=0,
                            help="Daily is the only interval the criteria are calibrated for; "
                                 "weekly/monthly re-scale the lookbacks and are experimental.")
    _today = datetime.date.today()
    as_of = st.date_input("Analyse as of", value=_today, max_value=_today,
                          help="Default = today (normal live analysis). Pick a PAST date to "
                               "back-test: technicals are computed on price data up to that date "
                               "only. (Fundamentals/pledge are live and can't be back-dated.)")
    _is_pit = as_of < _today
    with_news = st.toggle("Include news sentiment", value=False,
                          help="Fetches Google-News headlines + keyword sentiment. "
                               "Slower; not part of the backtested edge.")
    with_ownership = st.toggle("Include pledge & institution checks", value=True,
                               disabled=_is_pit,
                               help="For the shortlist (non-AVOID) only: fetches promoter pledge %, "
                                    "FII/DII trend & Altman distress and folds them into the verdict + "
                                    "ranking. Adds a few seconds on the first run of the day (then cached).")
    if _is_pit:
        st.caption(f"⏳ Point-in-time mode ({as_of}) — pledge/institution checks are off "
                   "(live data can't be back-dated).")
    verify = st.button("✓ Verify tickers", use_container_width=True, key="stocks_verify",
                       help="Quick check that every ticker resolves on NSE/BSE — before a full run.")
    run = st.button("Run analysis", type="primary", use_container_width=True)
    if st.button("Clear cache", use_container_width=True, key="stocks_clear"):
        core.clear_cache()
        st.session_state.pop("stocks.results", None)
        st.session_state.pop("stocks.verify", None)
        st.toast("Cache cleared")

    st.markdown('<div class="disclaimer">Educational only — <b>not financial advice</b>. '
                'The score reflects setup quality &amp; risk discipline, not a promise of '
                'returns. Always use a stop-loss and size positions sensibly.</div>',
                unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
#  Run
# --------------------------------------------------------------------------- #
if run:
    names = parse_tickers(tickers_text)
    if not names:
        st.warning("Enter at least one ticker.")
    else:
        prog = st.progress(0.0, text="Starting…")

        def cb(done, total, name):
            prog.progress(done / total, text=f"Analyzed {done}/{total} — {name}")

        results = core.run_batch(names, interval=interval, with_news=with_news,
                                 with_ownership=with_ownership,
                                 as_of=(as_of if _is_pit else None), progress_cb=cb)
        prog.empty()
        st.session_state["stocks.results"] = results
        st.session_state["stocks.as_of"] = str(as_of) if _is_pit else None
        st.session_state["stocks.interval"] = interval

# --------------------------------------------------------------------------- #
#  Verify (pre-flight ticker check)
# --------------------------------------------------------------------------- #
if verify:
    _vnames = parse_tickers(tickers_text)
    if not _vnames:
        st.warning("Enter at least one ticker to verify.")
    else:
        _vp = st.progress(0.0, text="Verifying…")
        st.session_state["stocks.verify"] = core.verify_tickers(
            _vnames, progress_cb=lambda d, t, n: _vp.progress(d / t, text=f"Checked {d}/{t} — {n}"))
        _vp.empty()

_vres = st.session_state.get("stocks.verify")
if _vres:
    st.markdown("### Ticker check")
    render_verify_panel(_vres, item="ticker")
    st.markdown("---")

# --------------------------------------------------------------------------- #
#  Results
# --------------------------------------------------------------------------- #
results = st.session_state.get("stocks.results")
if not results:
    st.info("👈 Enter tickers in the sidebar and hit **Run analysis** to begin.")
    st.stop()

interval = st.session_state.get("stocks.interval", "daily")
summaries = [core.summarize(r) for r in results]
ok = [s for s in summaries if s["verdict"] != "ERROR"]
errs = [s for s in summaries if s["verdict"] == "ERROR"]
ok.sort(key=core.sort_key)

_run_asof = st.session_state.get("stocks.as_of")
if _run_asof:
    st.warning(f"⏳ **Point-in-time analysis as of {_run_asof}.** The technical setup, momentum, "
               "levels and verdict use price data **up to that date only** — this is how the screen "
               "would have looked then. Fundamentals (Quality, P/E, analyst) are **live/today** and "
               "pledge/institution checks are **off** (no free historical data). The deep-dive chart "
               "shows the full price path since, so you can see what happened after.")

# ---- overview stat tiles ----
c = {"STRONG SETUP": 0, "WATCH": 0, "AVOID": 0}
for s in ok:
    c[s["verdict"]] = c.get(s["verdict"], 0) + 1

t1, t2, t3, t4 = st.columns(4)
stat_tile(t1, "Screened", len(summaries), INK)
stat_tile(t2, "Strong setups", c["STRONG SETUP"], GOOD)
stat_tile(t3, "Watch", c["WATCH"], WARNING)
stat_tile(t4, "Avoid", c["AVOID"], CRITICAL)

st.markdown("<br>", unsafe_allow_html=True)

if errs:
    with st.expander(f"⚠️ {len(errs)} ticker(s) failed", expanded=False):
        for e in errs:
            st.write(f"**{e['stock']}** — {e['error']}")

# ---- ranked table ----
st.markdown("### Ranked shortlist")

def _instn(s):
    a = {"rising": "🔼", "falling": "🔻", "flat": "▪️"}
    fii, dii = s.get("fii_dir"), s.get("dii_dir")
    if not fii and not dii:
        return "—"
    return f'FII{a.get(fii, "")} DII{a.get(dii, "")}'


rows = []
for s in ok:
    flags = []
    if s.get("data_flag"):
        flags.append("⚠️ data")
    if s.get("pledged"):
        pl = s.get("pledge_pct")
        flags.append(f"⛓️ pledged{f' {pl:.0f}%' if isinstance(pl,(int,float)) else ''}")
    if s.get("distress"):
        flags.append("🔴 distress")
    if s.get("spiked_today"):
        dm = s.get("day_move_pct")
        flags.append(f"🔥 spiked{f' +{dm:.0f}%' if isinstance(dm,(int,float)) else ''}")
    if s.get("extended"):
        flags.append("⏫ extended")
    why = s["rationale"]
    if s.get("data_flag"):
        why = "⚠️ Verify data (possible unadjusted corporate action) — " + why
    rows.append({
        "Verdict": s["verdict"],
        "Stock": s["stock"],
        "Flags": " · ".join(flags) or "—",
        "Price": fmt_num(s["price"], p="₹"),
        "P/E": f'{s["pe"]:.0f}' if isinstance(s.get("pe"), (int, float)) else "—",
        "Setup": f'{s["confirmed"]}→{s["best_case"]}/10' if s["confirmed"] is not None else "—",
        "Quality": s.get("quality_rating") or "—",
        "RS 3m": fmt_pct(s.get("rs_3m")),
        "Reward:Risk": f'{s["rr"]:.1f}:1' if isinstance(s["rr"], (int, float)) else "open",
        "Instns": _instn(s),
        "Analyst": fmt_analyst(s),
        "Why": why,
    })
tbl = pd.DataFrame(rows)

styled = (tbl.style
          .map(style_verdict, subset=["Verdict"])
          .map(style_quality, subset=["Quality"])
          .set_properties(**{"font-size": "0.88rem"}))
st.dataframe(styled, use_container_width=True, hide_index=True, height=min(560, 90 + 38 * len(tbl)),
             column_config={
                 "Flags": st.column_config.TextColumn(
                     "Flags",
                     help="⚠️ data = unadjusted corporate action may distort stats — verify. "
                          "⛓️ pledged = promoters pledged ≥25% of their holding (≥50% → AVOID). "
                          "🔴 distress = Altman balance-sheet distress zone. "
                          "🔥 spiked = up ≥5% today — don't chase, wait 2-3 days. "
                          "⏫ extended = >25% above the 50-DMA (chasing entry)."),
                 "Instns": st.column_config.TextColumn(
                     "Instns",
                     help="Institutional holding trend vs ~2 quarters ago (from screener.in): "
                          "🔼 rising / 🔻 falling / ▪️ flat. FII = foreign, DII = domestic. "
                          "Informational — shown for the shortlist only."),
                 "Why": st.column_config.TextColumn("Why", width="large"),
                 "Setup": st.column_config.TextColumn(
                     "Setup", help="Technical/momentum score (confirmed → best-case /10). Backtested."),
                 "Quality": st.column_config.TextColumn(
                     "Quality", help="Fundamental snapshot — valuation, returns, balance sheet. Live only, NOT backtested."),
                 "Analyst": st.column_config.TextColumn(
                     "Analyst", help="Mean 12-month analyst target upside · consensus rating."),
                 "RS 3m": st.column_config.TextColumn(
                     "RS 3m",
                     help="3-month return vs the stock's own recent trend — the primary momentum "
                          "read for a short (1-week-to-few-months) horizon. Full 3m/6m detail is in the deep dive."),
                 "Reward:Risk": st.column_config.TextColumn(
                     "Reward:Risk",
                     help="Reward ÷ risk (upside% ÷ stop%). Higher is better — e.g. 4.3:1 = 4.3 units of "
                          "gain per 1 unit risked. Below 1:1 is auto-AVOID. 'open' = blue-sky (no overhead "
                          "resistance in the last year); the deep dive shows a 3×ATR planning target for it."),
             })

# ---- CSV download ----
buf = io.StringIO()
pd.DataFrame(ok).to_csv(buf, index=False)
st.download_button("⬇ Download results (CSV)", buf.getvalue(),
                   file_name="screener_results.csv", mime="text/csv")

st.markdown("---")

# --------------------------------------------------------------------------- #
#  Detail view
# --------------------------------------------------------------------------- #
st.markdown("### Deep dive")
options = [s["stock"] for s in ok] + [s["stock"] for s in errs]
if not options:
    st.stop()
pick = st.selectbox("Pick a stock", options)

sel_res = next((r for r in results if r.get("stock") == pick), None)
sel_sum = next((s for s in summaries if s["stock"] == pick), None)

if sel_res is None or sel_res.get("_error"):
    st.error(f"No analysis available for {pick}: {sel_res.get('_error') if sel_res else 'not found'}")
    st.stop()

score = sel_res.get("scorecard", {})
qa = core.quality_assessment(sel_res.get("fundamentals", {}).get("quality") or {})
manual = core.manual_review_items(sel_res)

# ---- automated deep checks (free sources; cached per day; best-effort) ----
_q = sel_res.get("fundamentals", {}).get("quality") or {}
_isfin = bool(_q.get("is_financial"))
auto = {"forensic": {}, "pledge": {}, "gov": {}}
with st.spinner("Running auto-checks (forensics · pledge · institutions · filings)…"):
    try:
        auto["forensic"] = dc.forensic_scores_cached(
            sel_res.get("symbol", ""), _isfin, _q.get("sector", ""), _q.get("industry", ""))
    except Exception as e:
        auto["forensic"] = {"error": str(e)[:80]}
    try:
        auto["pledge"] = dc.screener_shareholding(pick)
    except Exception as e:
        auto["pledge"] = {"error": str(e)[:80]}
    try:
        auto["gov"] = dc.bse_governance(pick)
    except Exception as e:
        auto["gov"] = {"error": str(e)[:80]}

# ---- header row: verdict + key metrics ----
h1, h2, h3, h4, h5, h6 = st.columns([1.5, 1, 1, 1, 1, 1])
with h1:
    st.markdown(f"#### {pick}")
    st.markdown(badge_html(sel_sum["verdict"]), unsafe_allow_html=True)
h2.metric("Price", fmt_num(sel_sum["price"], p="₹"))
h3.metric("Setup (technical)", f'{score.get("confirmed_score")}→{score.get("best_case_score")}/10',
          help="Backtested 10-criteria momentum + risk score (confirmed → best-case with manual checks).")
h4.metric("Quality (fundamental)", sel_sum.get("quality_rating") or "—",
          help=f"Live fundamental snapshot ({qa['good']}/{qa['applicable']} checks good). NOT backtested.")
h5.metric("Reward : Risk", f'{score.get("risk_reward"):.1f}:1'
          if isinstance(score.get("risk_reward"), (int, float)) else "open",
          help="'open' = blue-sky (no overhead resistance in the last year). "
               "The trade plan below shows a 3×ATR planning target for such stocks.")
h6.metric("Analyst target", fmt_pct(sel_sum.get("analyst_upside")),
          help=f"Consensus: {(sel_sum.get('analyst_rec') or 'n/a').replace('_', ' ')}. "
               "Mean 12-month target vs current price.")

# Setup band describes technical completeness; the VERDICT rationale is the
# authoritative call (a risk gate can turn a "HIGH setup" into AVOID, so show the
# rationale rather than the scorecard's pre-verdict "buy" action to avoid contradiction).
st.caption(f"As of {sel_res.get('as_of')} · Setup completeness: {score.get('band')} · "
           f"**Verdict:** {sel_sum.get('rationale')}")

# One-click: copy the ENTIRE deep dive as Markdown
_copy_button(_deepdive_markdown(pick, sel_res, sel_sum, score, qa, manual, auto))

dq = sel_res.get("data_quality") or {}
if dq.get("partial_trimmed"):
    st.caption(f"⏱️ Today's in-progress candle ({dq.get('partial_date')}) was excluded — analysis is on the "
               "last complete session, so it's stable no matter what time you run it.")

et_top = score.get("entry_timing") or {}
if et_top.get("spiked_today"):
    dm = et_top.get("day_move_pct")
    st.warning(
        f"🔥 **Spiked today ({f'+{dm:.0f}%' if isinstance(dm,(int,float)) else 'big up day'}).** "
        "Don't chase the intraday pop — a routine cooling-off pullback would stop you out. "
        "Move it to your watch list and wait 2-3 days for it to stabilise near support before entering.")

if dq.get("suspect_gap"):
    st.warning(
        f"⚠️ **Possible unadjusted corporate action.** A ~{dq.get('move_pct')}% single-day move on "
        f"{dq.get('date')} looks like a demerger/spin-off that the data feed hasn't adjusted (splits & "
        "dividends *are* adjusted; spin-offs are not). If so, the 6-month return, moving averages, "
        "levels and reward:risk for this stock are distorted — verify the corporate action before trusting the setup.")

et = score.get("entry_timing") or {}
if et.get("extended"):
    st.warning(
        f"⏫ **Extended entry.** Price is ~{et.get('pct_above_sma50'):.0f}% above its 50-DMA. "
        "The trend may be intact, but this is a poor place to enter — you're chasing a vertical move with "
        "no cushion back to support. Wait for a pullback or a fresh base.")

left, right = st.columns([1.15, 1])

# ---- criteria checklist ----
with left:
    st.markdown("##### 10-criteria checklist")
    st_colors = {"PASS": GOOD, "FAIL": CRITICAL, "MANUAL": WARNING, "UNKNOWN": MUTED}
    for cr in score.get("criteria", []):
        sc = st_colors.get(cr["status"], MUTED)
        st.markdown(
            f'<div class="crit-row">'
            f'<div class="crit-id">{cr["id"]}</div>'
            f'<div style="flex:1;"><div class="crit-lab">{cr["label"]}</div>'
            f'<div class="crit-det">{cr["detail"]}</div></div>'
            f'<div class="crit-st" style="color:{sc};background:{sc}22;">{cr["status"]}</div>'
            f'</div>', unsafe_allow_html=True)
    st.caption("MANUAL = verify on screener.in / trendlyne / nseindia (promoter pledge, FII/DII). "
               "These aren't in the free data feed.")

# ---- trade plan ----
with right:
    st.markdown("##### Trade plan")
    # structural target if there's overhead resistance; else a 3×ATR blue-sky target
    if score.get("target_price"):
        tgt_rows = [("Target (resistance)", f'₹{score.get("target_price")}'),
                    ("Upside to target", fmt_pct(score.get("upside_pct")) if score.get("upside_pct") is not None else "—"),
                    ("Reward : Risk", f'{score.get("risk_reward"):.1f}:1' if isinstance(score.get("risk_reward"), (int, float)) else "open")]
    elif score.get("atr_target"):
        _atgt = score["atr_target"]
        _aup = round((_atgt - sel_sum["price"]) / sel_sum["price"] * 100, 1) if sel_sum.get("price") else None
        tgt_rows = [("Target (3×ATR, blue-sky)", f'₹{_atgt}'),
                    ("Upside to target", fmt_pct(_aup) if _aup is not None else "—"),
                    ("Reward : Risk", f'{score.get("atr_rr")}:1 (ATR est.)' if score.get("atr_rr") else "open")]
    else:
        tgt_rows = [("Target", "open upside"), ("Upside to target", "—"), ("Reward : Risk", "open")]
    tp = [
        ("Entry (last close)", fmt_num(sel_sum["price"], p="₹")),
        ("Stop-loss", f'₹{score.get("stop_price")}' if score.get("stop_price") else "—"),
        ("Stop distance", fmt_pct(-score["stop_dist_pct"]) if isinstance(score.get("stop_dist_pct"), (int, float)) else "—"),
        *tgt_rows,
        ("Stop type", "structural support" if score.get("stop_structural") else "8% hard stop (no support)"),
        ("Entry timing", _entry_timing_label(score.get("entry_timing") or {})),
    ]
    rows_html = "".join(
        f'<div class="row"><span class="lab">{k}</span><span class="val">{v}</span></div>'
        for k, v in tp)
    st.markdown(f'<div class="plan">{rows_html}</div>', unsafe_allow_html=True)

    news = sel_res.get("news")
    if news and news.get("headlines"):
        st.markdown("##### Recent headlines")
        senti = news.get("overall_sentiment")
        if senti is not None:
            st.caption(f"Sentiment: {senti:+.2f} ({news.get('backend','')})")
        for h in news["headlines"][:5]:
            st.markdown(f"- {h.get('title','')}")

# ---- fundamental quality panel ----
st.markdown("---")
qcolor = QUALITY_COLOR.get(qa["rating"], MUTED)
st.markdown(f'##### Fundamental quality — <span style="color:{qcolor}">{qa["rating"]}</span>'
            f' <span style="color:{MUTED};font-weight:400;font-size:.9rem">'
            f'({qa["good"]}/{qa["applicable"]} checks good · live snapshot, not backtested)</span>',
            unsafe_allow_html=True)

if not qa["checks"]:
    st.info("No fundamental data available from the feed for this stock.")
else:
    QST = {"GOOD": GOOD, "OK": BLUE, "WARN": WARNING, "BAD": CRITICAL, "NA": MUTED}
    last_group = None
    for cq in qa["checks"]:
        if cq["group"] != last_group:
            st.markdown(f'<div style="color:{MUTED};font-size:.72rem;text-transform:uppercase;'
                        f'letter-spacing:.07em;margin:.6rem 0 .25rem;">{cq["group"]}</div>',
                        unsafe_allow_html=True)
            last_group = cq["group"]
        color = QST.get(cq["status"], MUTED)
        note = f'<div class="crit-det">{cq["note"]}</div>' if cq["note"] else ""
        st.markdown(
            f'<div class="crit-row">'
            f'<div style="flex:1;"><div class="crit-lab">{cq["label"]}</div>{note}</div>'
            f'<div class="crit-lab" style="min-width:6rem;text-align:right;">{cq["value"]}</div>'
            f'<div class="crit-st" style="color:{color};background:{color}22;margin-left:.7rem;">{cq["status"]}</div>'
            f'</div>', unsafe_allow_html=True)
    st.caption("Valuation thresholds are rough rules of thumb — a high P/E can be justified by growth. "
               "Always compare to sector peers and the stock's own history.")

# ---- automated deep checks ----
st.markdown("---")
st.markdown(f'##### 🤖 Automated deep checks '
            f'<span style="color:{MUTED};font-weight:400;font-size:.9rem">'
            f'— free sources, best-effort; verify the big ones before acting</span>',
            unsafe_allow_html=True)

_f = auto.get("forensic") or {}
if _f.get("error"):
    st.caption(f"Forensic scores unavailable: {_f['error']}")
else:
    a1, a2, a3 = st.columns(3)
    _p, _al, _bn = _f.get("piotroski"), _f.get("altman"), _f.get("beneish")
    a1.metric("Piotroski F", f"{_p['score']}/{_p['used']}" if _p else "—",
              help="Fundamental health (0–9). ≥7 strong · ≤3 weak.")
    a2.metric("Altman Z″", (f"{_al['z']} · {_al['zone']}" if _al
              else (f"n/a ({_f.get('altman_na')})" if _f.get("altman_na") else "—")),
              help="Financial-distress risk. >2.6 safe · <1.1 distress. Skipped for banks/NBFCs & utilities.")
    a3.metric("Beneish M", ((f"{_bn['m']}" + (" ⚠️" if _bn.get('flag') else "")) if _bn else "—"),
              help="Earnings-manipulation flag when M > −2.22.")
    for fl in _f.get("flags", []):
        st.markdown(f'<div class="crit-det" style="color:{CRITICAL};">🔴 {fl}</div>', unsafe_allow_html=True)

_pl = auto.get("pledge") or {}
if _pl.get("error"):
    st.caption(f"Pledge / shareholding (screener.in) unavailable: {_pl['error']}")
else:
    _p_pct = _pl.get("pledge_pct")
    if _p_pct and _p_pct >= 1:
        st.markdown(f'<div class="crit-det" style="color:{CRITICAL};">🔴 <b>Promoter pledge: {_p_pct:.1f}%</b>'
                    f' — C7 red flag, verify the trend</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="crit-det" style="color:{GOOD};">🟢 No meaningful promoter pledge (C7)</div>',
                    unsafe_allow_html=True)

    def _tl(lbl, d):
        if not d:
            return f"{lbl}: —"
        arrow = {"rising": "🔼", "falling": "🔻", "flat": "▪️"}.get(d.get("direction"), "")
        col = GOOD if d.get("direction") == "rising" else CRITICAL if d.get("direction") == "falling" else MUTED
        return f'<span style="color:{col};">{lbl} {d.get("latest")}% {arrow} {d.get("direction")} ({d.get("delta"):+.2f})</span>'
    st.markdown(f'<div class="crit-det">Institutional trend (C8, vs ~2 quarters ago): '
                f'{_tl("Promoter", _pl.get("promoter"))} · {_tl("FII", _pl.get("fii"))} · '
                f'{_tl("DII", _pl.get("dii"))}</div>', unsafe_allow_html=True)

_g = auto.get("gov") or {}
if _g.get("error"):
    st.caption(f"BSE filings unavailable: {_g['error']}")
else:
    if _g.get("governance"):
        st.markdown(f'<div class="crit-det" style="color:{WARNING};">⚠️ Recent governance / auditor filings (BSE):</div>',
                    unsafe_allow_html=True)
        for gi in _g["governance"][:5]:
            _lnk = f' · <a href="{gi["pdf"]}" target="_blank">PDF</a>' if gi.get("pdf") else ""
            st.markdown(f'<div class="crit-det" style="margin-left:.6rem;">• {gi["date"]} — {gi["subject"]}{_lnk}</div>',
                        unsafe_allow_html=True)
    else:
        st.caption("No auditor-change / governance red-flag filings in the last ~180 days.")
    if _g.get("transcript") and _g["transcript"].get("pdf"):
        st.markdown(f'<div class="crit-det">📄 Latest concall transcript: '
                    f'<a href="{_g["transcript"]["pdf"]}" target="_blank">{_g["transcript"].get("date")} — PDF</a>'
                    f' <span style="color:{MUTED};">(read it for forward guidance)</span></div>',
                    unsafe_allow_html=True)
st.caption("Sources: yfinance statements · screener.in · BSE filings. Best-effort hints from free data — "
           "confirm pledge/governance at the source before acting. Forensic scores flag statistics, not proven fraud.")

# ---- manual review ----
st.markdown(f'##### ⚠️ Manual review required '
            f'<span style="color:{MUTED};font-weight:400;font-size:.9rem">'
            f'— the tool can\'t verify these from free data</span>', unsafe_allow_html=True)
sev_color = {"high": CRITICAL, "medium": WARNING, "info": MUTED}
sev_label = {"high": "MUST CHECK", "medium": "CHECK", "info": "NOTE"}
for m in manual:
    color = sev_color.get(m["sev"], MUTED)
    st.markdown(
        f'<div class="crit-row" style="border-left:3px solid {color};">'
        f'<div style="flex:1;"><div class="crit-lab">{m["title"]}</div>'
        f'<div class="crit-det">{m["detail"]}</div>'
        f'<div class="crit-det" style="color:{color};">🔎 Check on: {m["where"]}</div></div>'
        f'<div class="crit-st" style="color:{color};background:{color}22;white-space:nowrap;">{sev_label.get(m["sev"], "CHECK")}</div>'
        f'</div>', unsafe_allow_html=True)
st.caption("These — promoter pledge, institutional trend, governance/fraud, forward guidance — are where "
           "real losses and real edges hide. The score above is only as good as your check of these.")

# ---- chart ----
st.markdown("---")
_pit = bool(sel_res.get("is_point_in_time"))
_asof = sel_res.get("as_of")
st.markdown("##### Price · SMA50 / SMA200 · levels"
            + (f"  ·  ⏳ analysed as of {_asof}" if _pit else ""))
df = core.load_ohlcv(pick, interval, full=_pit)   # full series (incl. post-as-of) in PIT mode
if df is None or not len(df):
    st.info("Chart data not found.")
else:
    if _pit and _asof:
        _idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
        n_after = int((_idx > pd.Timestamp(_asof)).sum())   # bars since the analysis date
        view = df.tail(max(300, n_after + 250))
    else:
        view = df.tail(300)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.76, 0.24],
                        vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=view.index, open=view["Open"], high=view["High"], low=view["Low"], close=view["Close"],
        name="Price", increasing_line_color=GOOD, decreasing_line_color=CRITICAL,
        increasing_fillcolor=GOOD, decreasing_fillcolor=CRITICAL, line_width=1), row=1, col=1)
    for col, color, name in [("SMA50", BLUE, "SMA50"), ("SMA200", VIOLET, "SMA200")]:
        if col in view.columns:
            fig.add_trace(go.Scatter(x=view.index, y=view[col], name=name,
                                     line=dict(color=color, width=2)), row=1, col=1)
    if _pit and _asof:
        # shade everything AFTER the analysis date + a dotted boundary line
        fig.add_vrect(x0=_asof, x1=str(view.index[-1].date()),
                      fillcolor=WARNING, opacity=0.10, line_width=0,
                      annotation_text="after analysis date", annotation_position="top right",
                      annotation_font_color=WARNING, row=1, col=1)
        fig.add_vline(x=_asof, line=dict(color=WARNING, width=2, dash="dot"),
                      annotation_text=f"as of {_asof}", annotation_font_color=WARNING, row=1, col=1)
    if score.get("stop_price"):
        fig.add_hline(y=score["stop_price"], line=dict(color=CRITICAL, width=1, dash="dash"),
                      annotation_text="stop", annotation_font_color=CRITICAL, row=1, col=1)
    if score.get("target_price"):
        fig.add_hline(y=score["target_price"], line=dict(color=GOOD, width=1, dash="dash"),
                      annotation_text="target", annotation_font_color=GOOD, row=1, col=1)
    vol_colors = [GOOD if c >= o else CRITICAL for c, o in zip(view["Close"], view["Open"])]
    fig.add_trace(go.Bar(x=view.index, y=view["Volume"], name="Volume",
                         marker_color=vol_colors, marker_line_width=0, opacity=0.55), row=2, col=1)
    fig.update_layout(
        template=PLOTLY_TEMPLATE, paper_bgcolor=PAGE, plot_bgcolor=SURFACE,
        height=560, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        xaxis_rangeslider_visible=False, font=dict(color=INK_2),
        hovermode="x unified")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    st.plotly_chart(fig, use_container_width=True)
