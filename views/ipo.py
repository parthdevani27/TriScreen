"""IPO section — Indian IPO screener (Mainboard + SME).

Two views (toggle):
  • Analyze an IPO — paste a name → run the due-diligence checklist → an honest
    dual verdict: a COMPUTED Listing-Gain call (subscription/GMP/anchor/P/E from
    free feeds) + a MANUAL Long-Term view (financials/OFS/promoter/governance from
    the RHP, with deep links). Same honesty split as the Stocks/MF tools.
  • Live & Upcoming — filterable list of live/upcoming/recent IPOs; pick a row and
    hit Analyze ▶ to jump into the analyzer pre-loaded.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import ipo_core as core
from components.theme import MUTED, INK, GOOD, BLUE, WARNING
from components.ui import (badge_html, stat_tile, check_row, manual_row,
                           style_verdict)

ANALYZE, LIST = "🔍 Analyze an IPO", "📋 Live & Upcoming"

st.markdown('<p class="app-title">🚀 IPO Screener</p>', unsafe_allow_html=True)
st.markdown('<p class="app-sub">Mainboard &amp; SME. A <b>computed listing-gain</b> read '
            '(subscription · GMP · anchor · valuation from free feeds) kept honestly separate from the '
            '<b>long-term view</b> (financials · fresh-vs-OFS · promoter · governance — RHP-only, linked below).</p>',
            unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #
def fmt_date(iso):
    if not iso:
        return "—"
    try:
        return date.fromisoformat(iso).strftime("%d-%b")
    except Exception:
        return iso


def fmt_x(v):
    return f"{v:.1f}x" if isinstance(v, (int, float)) else "—"


def fmt_rs(v, cr=False):
    if not isinstance(v, (int, float)):
        return "—"
    return f"₹{v:,.0f}cr" if cr else f"₹{v:,.0f}"


def tavily_key() -> str:
    try:
        return st.secrets.get("tavily_api_key", "") or ""
    except Exception:
        return ""


# Reconcile a programmatic mode switch (from the list's Analyze ▶) BEFORE the
# segmented_control is instantiated — a widget key can't be written after its
# widget renders in the same run.
if "ipo._pending_mode" in st.session_state:
    st.session_state["ipo.mode"] = st.session_state.pop("ipo._pending_mode")
st.session_state.setdefault("ipo.mode", LIST)
mode = st.segmented_control("View", [LIST, ANALYZE], key="ipo.mode",
                            label_visibility="collapsed") or st.session_state["ipo.mode"]

st.markdown("<br>", unsafe_allow_html=True)


def go_analyze(name: str):
    # Called from LIST mode, where neither the segmented_control's target value nor
    # the analyze text box are instantiated yet, so these writes are safe.
    st.session_state["ipo.query"] = name
    st.session_state["ipo.analyze.input"] = name      # prefill the name box
    st.session_state["ipo._pending_mode"] = ANALYZE    # switched to on next run
    st.session_state["ipo.autorun"] = True             # auto-run analysis on arrival
    st.rerun()


# =========================================================================== #
#  LIVE & UPCOMING LIST
# =========================================================================== #
if mode == LIST:
    try:
        records = core.list_records()
    except Exception as e:
        st.error(f"Couldn't load the IPO list from the free feeds right now: {e}")
        st.caption("These are unofficial, no-SLA sources (NSE behind bot-protection, investorgain). "
                   "Try again shortly or hit Clear cache.")
        st.stop()

    as_of = core.data.list_as_of().get("ig_gmp")
    upd = next((r.get("updated_on") for r in records if r.get("updated_on")), None)

    # ---- stat tiles ----
    n_open = sum(1 for r in records if r["status"] == "open")
    n_up = sum(1 for r in records if r["status"] == "upcoming")
    n_sme = sum(1 for r in records if r["board"] == "SME")
    gmps = [r["gmp_pct"] for r in records if isinstance(r.get("gmp_pct"), (int, float))]
    t1, t2, t3, t4 = st.columns(4)
    stat_tile(t1, "Tracked", len(records), INK)
    stat_tile(t2, "Open now", n_open, GOOD)
    stat_tile(t3, "Upcoming", n_up, BLUE)
    stat_tile(t4, "SME", n_sme, WARNING)
    st.markdown("<br>", unsafe_allow_html=True)

    # ---- filters ----
    f1, f2, f3, f4 = st.columns([1.4, 1, 1, 1])
    search = f1.text_input("Search", key="ipo.f.search", placeholder="company name…")
    status_opt = f2.selectbox("Status", ["Live + Upcoming", "Open", "Upcoming", "Closed", "Listed", "All"],
                              key="ipo.f.status")
    status = {"Live + Upcoming": ("open", "upcoming"), "All": "All"}.get(status_opt, status_opt.lower())
    board = f3.selectbox("Board", ["All", "Mainboard", "SME"], key="ipo.f.board")
    sort_by = f4.selectbox("Sort by", ["verdict", "gmp_pct", "size_cr", "qib", "total", "close_date"],
                           format_func=lambda x: {"verdict": "Signal", "gmp_pct": "GMP %",
                                                  "size_cr": "Issue size", "qib": "QIB ×",
                                                  "total": "Overall ×", "close_date": "Close date"}[x],
                           key="ipo.f.sort")
    with st.expander("More filters"):
        g1, g2, g3, g4 = st.columns(4)
        exch = g1.selectbox("Exchange", ["All", "NSE", "BSE"], key="ipo.f.exch")
        gmp_mode = g2.selectbox("GMP type", ["Any", "Positive (>0)", "Negative (<0)", "Has live GMP"],
                                key="ipo.f.gmp")
        min_qib = g3.number_input("Min QIB ×", 0.0, 500.0, 0.0, step=1.0, key="ipo.f.qib")
        min_total = g4.number_input("Min overall ×", 0.0, 500.0, 0.0, step=1.0, key="ipo.f.total")
        h1, h2, h3 = st.columns(3)
        size_min = h1.number_input("Min issue size (₹cr)", 0.0, 50000.0, 0.0, step=50.0, key="ipo.f.size")
        c_from = h2.date_input("Closing on/after", value=None, key="ipo.f.cfrom")
        c_to = h3.date_input("Closing on/before", value=None, key="ipo.f.cto")

    filtered = core.filter_records(
        records, status=status, board=board, exchange=exch, gmp_mode=gmp_mode,
        size_min=(size_min or None), min_qib=(min_qib or None), min_total=(min_total or None),
        close_from=(c_from.isoformat() if c_from else None),
        close_to=(c_to.isoformat() if c_to else None), search=search)
    filtered = core.sort_records(filtered, by=sort_by, desc=True)

    if not filtered:
        st.info("No IPOs match these filters.")
        st.stop()

    # ---- build table ----
    rows = []
    for r in filtered:
        v, sc = core.quick_verdict(r)
        sub = r.get("sub") or {}
        rows.append({
            "Signal": v,
            "Company": r["name"],
            "Board": r["board"] + (f" · {r['exchange']}" if r.get("exchange") else ""),
            "Status": r["status"].title(),
            "Price": fmt_rs(r.get("price")),
            "GMP ₹": fmt_rs(r.get("gmp_rs")),
            "GMP %": f"{r['gmp_pct']:+.1f}%" if isinstance(r.get("gmp_pct"), (int, float)) else "—",
            "🔥": "🔥" * int(r.get("rating") or 0) or "—",
            "Size": fmt_rs(r.get("size_cr"), cr=True),
            "Min ₹": fmt_rs(r.get("min_invest")),
            "Sub ×": fmt_x(sub.get("total")),
            "QIB ×": fmt_x(sub.get("qib")),
            "RII ×": fmt_x(sub.get("rii")),
            "Open": fmt_date(r.get("open_date")),
            "Close": fmt_date(r.get("close_date")),
            "Listing": fmt_date(r.get("listing_date")),
        })
    df = pd.DataFrame(rows)
    styled = df.style.map(style_verdict, subset=["Signal"]).set_properties(**{"font-size": "0.85rem"})

    st.caption(f"Select a row, then hit **Analyze ▶**. "
               f"{('Grey-market updated ' + upd + ' · ') if upd else ''}"
               f"{('list cached ' + as_of) if as_of else ''} · **Signal** = the computed listing-gain read.")
    event = st.dataframe(
        styled, use_container_width=True, hide_index=True,
        height=min(1200, 44 + 35 * (len(df) + 1)), on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Company": st.column_config.TextColumn("Company", width="medium"),
            "Signal": st.column_config.TextColumn("Signal", help="Computed listing-gain verdict: APPLY / NEUTRAL / AVOID / WATCH (too early). Not the long-term view."),
            "GMP %": st.column_config.TextColumn("GMP %", help="Grey-market premium — unofficial & manipulable (esp. SME). A soft signal, never the verdict."),
            "🔥": st.column_config.TextColumn("🔥", help="investorgain's crowd rating (0-5)."),
            "Min ₹": st.column_config.TextColumn("Min ₹", help="Minimum investment = lot × cap price. SME lots are ~₹1-2 lakh."),
            "Sub ×": st.column_config.TextColumn("Sub ×", help="Overall subscription (times)."),
            "QIB ×": st.column_config.TextColumn("QIB ×", help="Qualified-institutional subscription — the strongest quality signal."),
        })

    sel = event.selection.rows if event and event.selection else []
    picked = filtered[sel[0]] if sel else None
    cta1, cta2 = st.columns([1, 3])
    if cta1.button("Analyze ▶", type="primary", use_container_width=True, disabled=picked is None):
        go_analyze(picked["name"])
    if picked is not None:
        cta2.caption(f"Selected: **{picked['name']}** ({picked['board']}) — click Analyze ▶ for the full checklist.")
    else:
        cta2.caption("Tip: click a row to select an IPO.")

    st.markdown('<div class="disclaimer">Educational only — <b>not financial advice</b>. Data from '
                'free, unofficial, no-SLA sources (NSE, investorgain); GMP is unregulated grey-market '
                'sentiment. Verify on the exchange/RHP before acting.</div>', unsafe_allow_html=True)
    st.stop()


# =========================================================================== #
#  ANALYZE AN IPO
# =========================================================================== #
st.session_state.setdefault("ipo.analyze.input", st.session_state.get("ipo.query", ""))
c1, c2 = st.columns([3, 1])
query = c1.text_input("IPO name", key="ipo.analyze.input",
                      placeholder="e.g. Knack Packaging  ·  or pick from Live & Upcoming")
run = c2.button("Analyze", type="primary", use_container_width=True)

tkey = tavily_key()
if not tkey:
    with st.expander("Optional: web-search enrichment (Tavily free key)"):
        st.caption("Leave blank to run keyless. A free Tavily key (or `tavily_api_key` in "
                   "`.streamlit/secrets.toml`) lets the tool pull fresh-vs-OFS split & financials from the web "
                   "to assist the long-term view. Core analysis works fully without it.")
        tkey = st.text_input("Tavily API key", type="password", key="ipo.tavily")

if st.session_state.pop("ipo.autorun", False):     # arrived via Analyze ▶ from the list
    run = True
if run and query.strip():
    st.session_state["ipo.query"] = query.strip()
    with st.spinner(f"Analyzing {query.strip()}…"):
        st.session_state["ipo.result"] = core.analyze(query.strip(), tavily_key=tkey)

res = st.session_state.get("ipo.result")
if not res or (res.get("query") or "").lower() != (st.session_state.get("ipo.query") or "").lower():
    st.info("👆 Enter an IPO name and hit **Analyze**, or pick one from **Live & Upcoming**.")
    st.stop()

if res.get("_error"):
    st.error(res["_error"])
    st.stop()

rec = res["record"]
t1 = res["tier1"]
sub = rec.get("sub") or {}
lt = res["long_term"]

# ---- header ----
h1, h2, h3, h4, h5, h6 = st.columns([1.9, 1, 1, 1, 1, 1])
with h1:
    st.markdown(f"#### {rec['name']}")
    st.markdown(badge_html(res["listing_verdict"]), unsafe_allow_html=True)
    st.caption(f"{rec['board']}{(' · ' + rec['exchange']) if rec.get('exchange') else ''} · {rec['status'].title()}")
h2.metric("Listing-gain score", f"{t1['score']}/100" if t1["score"] is not None else "—",
          help="Computed from free signals (subscription/GMP/anchor/valuation). Not the long-term quality.")
h3.metric("GMP", f"{rec['gmp_pct']:+.1f}%" if isinstance(rec.get("gmp_pct"), (int, float)) else "—",
          help="Grey-market premium — unofficial & manipulable; a soft signal only.")
h4.metric("QIB ×", fmt_x(sub.get("qib")), help="Institutional subscription — the strongest signal.")
h5.metric("Overall ×", fmt_x(sub.get("total")))
h6.metric("P/E", f"{rec['pe']:.1f}x" if isinstance(rec.get("pe"), (int, float)) else "—",
          help="Compare to listed-peer median in the RHP (manual).")

st.caption(f"**Listing-gain verdict:** {res['listing_rationale']}"
           + (f" · subscription: {rec.get('sub_source')}" if rec.get("sub_source") else "")
           + (f" · GMP updated {rec['updated_on']}" if rec.get("updated_on") else ""))

if t1["too_early"]:
    st.info("⏳ **Too early for a listing-gain call** — the book isn't open / has no meaningful demand yet. "
            "Subscription (esp. QIB) mostly builds on the **final day** — check back near close before deciding.")
if rec["board"] == "SME":
    st.warning("⚠️ **SME IPO.** Lighter disclosure (exchange-vetted, not SEBI), **low liquidity**, high volatility, "
               "and a large **~₹1–2 lakh minimum ticket**. The grey market here is thin & easily manipulated — "
               "treat GMP with extra suspicion. The listing-gain score already carries an SME risk penalty.")
if t1.get("veto"):
    st.error(f"⛔ **Critical flag:** {t1['veto']}")

left, right = st.columns([1.12, 1])

# ---- Tier-1 computed checks ----
with left:
    st.markdown("##### Computed checks (the listing-gain score)")
    for c in t1["checks"]:
        check_row(c["label"], c["value"], c["status"], c["note"], cid=c["id"])
    st.caption("PASS/CAUTION/FAIL vs thresholds, from free structured feeds. **QIB demand is weighted "
               "highest** — it outranks GMP & retail hype. GMP is included but caveated & low-weight.")

# ---- Tier-2 best-effort details + subscription breakdown ----
with right:
    st.markdown("##### Issue details")
    nse = res.get("nse_info") or {}
    details = [
        ("Price band", nse.get("price_band") or (fmt_rs(rec.get("price")) if rec.get("price") else "—")),
        ("Lot", nse.get("bid_lot") or (f"{rec['lot']:.0f} shares" if rec.get("lot") else "—")),
        ("Min investment", fmt_rs(rec.get("min_invest"))),
        ("Issue size", fmt_rs(rec.get("size_cr"), cr=True)),
        ("Open → Close", f"{fmt_date(rec.get('open_date'))} → {fmt_date(rec.get('close_date'))}"),
        ("Allotment", fmt_date(rec.get("boa_date"))),
        ("Listing", fmt_date(rec.get("listing_date"))),
        ("Anchor book", "✅ present" if rec.get("anchor") else "—"),
        ("Registrar", nse.get("registrar") or "—"),
    ]
    rows_html = "".join(f'<div class="row"><span class="lab">{k}</span><span class="val">{v}</span></div>'
                        for k, v in details)
    st.markdown(f'<div class="plan">{rows_html}</div>', unsafe_allow_html=True)

    st.markdown("##### Subscription by category")
    subrows = [("QIB (institutions)", sub.get("qib")), ("bHNI (>₹10L)", sub.get("bhni")),
               ("sHNI (₹2-10L)", sub.get("shni")), ("NII / HNI", sub.get("nii")),
               ("Retail", sub.get("rii")), ("Overall", sub.get("total"))]
    sr_html = "".join(f'<div class="row"><span class="lab">{k}</span>'
                      f'<span class="val">{fmt_x(v)}</span></div>' for k, v in subrows)
    st.markdown(f'<div class="plan">{sr_html}</div>', unsafe_allow_html=True)
    st.caption(f"Source: {rec.get('sub_source') or 'investorgain'}. Institutional (QIB) demand is the "
               "signal that matters; retail froth without it is a weak-listing setup.")

# ---- Long-term view ----
st.markdown("---")
st.markdown(f'##### Long-term view '
            f'<span style="color:{MUTED};font-weight:400;font-size:.9rem">'
            f'— {lt["rating"]} (fundamentals aren\'t in free feeds; grade them from the RHP below)</span>',
            unsafe_allow_html=True)
if lt["flags"]:
    for fl in lt["flags"]:
        st.markdown(f"- {fl}")
st.caption("A great listing pop ≠ a great business. This view is deliberately manual — the checklist below "
           "links to the exact RHP & 'Basis for Issue Price' pages so you can verify the fundamentals.")

# ---- optional web-search enrichment ----
enr = res.get("enrichment") or []
if enr:
    with st.expander(f"🔎 Web-search enrichment ({len(enr)} results)"):
        for e in enr:
            if e.get("url"):
                st.markdown(f"**[{e.get('title','link')}]({e['url']})**")
            elif e.get("title"):
                st.markdown(f"**{e['title']}**")
            if e.get("content"):
                st.caption(e["content"][:600])
        st.caption("Auto-gathered from the web (Tavily) — unverified; use to locate the fresh/OFS split & financials, not as fact.")

# ---- Tier-3 manual review ----
links = res.get("links") or {}
st.markdown(f'##### ⚠️ Manual review — the long-term checklist '
            f'<span style="color:{MUTED};font-weight:400;font-size:.9rem">'
            f'— what no free feed can verify</span>', unsafe_allow_html=True)
if links.get("rhp") or links.get("basis"):
    ln = []
    if links.get("rhp"):
        ln.append(f"[📄 Red Herring Prospectus (RHP)]({links['rhp']})")
    if links.get("basis"):
        ln.append(f"[📊 Basis for Issue Price / peer valuation]({links['basis']})")
    if links.get("anchor"):
        ln.append(f"[⚓ Anchor allotment]({links['anchor']})")
    st.markdown(" · ".join(ln))
for m in res["manual"]:
    manual_row(m["title"], m["detail"], m["where"], m["sev"])
st.caption("Fresh-vs-OFS split, cash-backed profits, promoter pledge, RPTs, litigation & auditor qualifications "
           "are where the real long-term risk hides — the computed score can't see them.")

st.markdown('<div class="disclaimer">Educational only — <b>not financial advice</b>. The listing-gain score '
            'reflects computed demand/valuation signals, not a promise of listing gains. GMP is unofficial, '
            'unregulated grey-market data. Long-term quality needs the RHP. Data from free, no-SLA sources — '
            'verify before applying.</div>', unsafe_allow_html=True)
