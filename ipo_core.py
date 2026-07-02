"""IPO analysis core — free feeds -> normalized record -> 3-tier honest scoring.

Mirrors the Stocks / Mutual-Fund tools' shape (analyze -> summarize -> tiered
checks -> verdict) and the same HONESTY SPLIT:

  TIER 1  COMPUTED -> headline LISTING-GAIN score (0-100), from free structured
          feeds (NSE category subscription + investorgain GMP/P/E/anchor):
          L1 QIB · L2 overall sub · L3 NII · L4 froth guard · L5 anchor ·
          L6 GMP (caveated) · L7 valuation sanity
  TIER 2  BEST-EFFORT (shown, flagged): size, lot & min-investment, dates,
          board+exchange, rating, registrar.
  TIER 3  MANUAL REVIEW (the LONG-TERM view; never auto-scored) with deep links
          to the NSE RHP & Basis-of-Issue-Price docs: fresh-vs-OFS split,
          financials, promoter/pledge/RPT, anchor quality, moat, governance.
          Optionally auto-assisted by a free web-search API (Tavily).

Core honesty rules baked in: listing-gain != long-term quality (two separate
verdicts); QIB demand outweighs GMP/retail hype; GMP is unofficial & never sets
the verdict; SME carries a risk modifier + illiquidity warnings.
"""

from __future__ import annotations

import re
from datetime import date

import ipo_data as data

# --------------------------------------------------------------------------- #
#  Normalization / merge
# --------------------------------------------------------------------------- #
_FIRE = "\U0001f525"
_CHECK = "✅"


def _norm(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    for w in ("limited", "ltd", "private", "pvt", "the", "ipo", "sme"):
        n = re.sub(rf"\b{w}\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _status_from_badges(badges: list[str]) -> str:
    for b in reversed(badges):                    # status letter is the last badge
        s = data._STATUS_LETTER.get(b.strip().upper())
        if s:
            return s
    return "upcoming"


def _derive_status(open_d, close_d, listing_d, badges) -> str:
    """Dates are authoritative (investorgain's status badge is unreliable — often
    missing or a non-letter like 'CT'). Fall back to the badge only when dateless."""
    today = date.today().isoformat()
    if listing_d and listing_d <= today:
        return "listed"
    if close_d and close_d < today:
        return "closed"
    if open_d and open_d <= today and (close_d is None or today <= close_d):
        return "open"
    if open_d and open_d > today:
        return "upcoming"
    return _status_from_badges(badges)


def _board_exchange(cat: str, badges: list[str]) -> tuple[str, str]:
    board = "SME" if (cat or "").strip().upper() == "SME" else "Mainboard"
    exch = ""
    for b in badges:
        u = b.upper()
        if "BSE" in u:
            exch = "BSE"
        elif "NSE" in u:
            exch = "NSE"
    return board, exch


def _records() -> list[dict]:
    """Merge investorgain GMP(331) + subscription(333) into normalized IPO rows."""
    gmp = data.fetch_ig_gmp()
    sub = {}
    try:
        for r in data.fetch_ig_sub():
            sub[str(r.get("~id"))] = r
    except Exception:
        pass

    out = []
    for r in gmp:
        name = data._text(r.get("~ipo_name")) or data._text(r.get("Name"))
        if not name:
            continue
        badges = data._badges(r.get("Name", ""))
        board, exch = _board_exchange(r.get("~IPO_Category"), badges)
        open_d = data._parse_date(r.get("Open"))
        close_d = data._parse_date(r.get("Close"))
        listing_d = data._parse_date(r.get("Listing"))
        status = _derive_status(open_d, close_d, listing_d, badges)
        rating = data._text(r.get("Rating", "")).count(_FIRE)   # entity &#128293; -> 🔥
        gmp_field = data._text(r.get("GMP")).split("(")[0]     # "Rs 27 " before "(15.88%)"
        price = data._num(r.get("Price (₹)")) or data._num(r.get("Price"))
        gmp_rs = data._num(gmp_field)
        gmp_pct = data._num(r.get("~gmp_percent_calc"))
        if (gmp_pct in (None, 0)) and gmp_rs and price:       # keep ₹ and % consistent
            gmp_pct = round(gmp_rs / price * 100, 2)
        lot = data._num(r.get("Lot"))
        srow = sub.get(str(r.get("~id"))) or {}

        def snum(key):                                        # subscription x
            return data._num(srow.get(key))

        rec = {
            "name": name, "norm": _norm(name), "id": r.get("~id"),
            "board": board, "exchange": exch, "status": status,
            "gmp_rs": gmp_rs, "gmp_pct": gmp_pct,
            "rating": rating,
            "price": price, "size_cr": data._num(r.get("IPO Size")), "lot": lot,
            "min_invest": (lot * price) if (lot and price) else None,
            "pe": data._num(r.get("~P/E")),
            "open_date": open_d, "close_date": close_d, "listing_date": listing_d,
            "boa_date": data._parse_date(r.get("BoA Dt")),
            "anchor": (_CHECK in data._text(r.get("Anchor", ""))),
            "slug": r.get("~urlrewrite_folder_name"),
            "updated_on": data._text(r.get("Updated-On")),
            "sub": {"total": snum("Total"), "qib": snum("QIB"), "nii": snum("NII"),
                    "rii": snum("RII"), "shni": snum("SHNI"), "bhni": snum("BHNI")},
            "sub_source": "investorgain" if srow else None,
        }
        out.append(rec)
    return out


def list_records() -> list[dict]:
    return _records()


# --------------------------------------------------------------------------- #
#  NSE authoritative overlay (category subscription + RHP links) for deep dive
# --------------------------------------------------------------------------- #
_URL = re.compile(r"https?://[^\s\"'<>]+")


def _first_url(s: str):
    m = _URL.search(str(s or ""))
    return m.group(0) if m else None


def _nse_lookup(query_norm: str) -> dict | None:
    try:
        rows = list(data.fetch_nse_list()) + list(data.fetch_nse_current())
    except Exception:
        return None
    best, best_score = None, 0.0
    qtok = set(query_norm.split())
    for r in rows:
        cn = _norm(r.get("companyName", ""))
        if not cn:
            continue
        ctok = set(cn.split())
        if not ctok:
            continue
        overlap = len(qtok & ctok) / max(1, len(qtok | ctok))
        if cn == query_norm or query_norm in cn or cn in query_norm:
            overlap = max(overlap, 0.9)
        if overlap > best_score:
            best, best_score = r, overlap
    if best and best_score >= 0.5:
        return {"symbol": best.get("symbol"),
                "series": best.get("series", "EQ") or "EQ",
                "status": best.get("status"), "isBse": best.get("isBse")}
    return None


_CAT_SR = {"1": "qib", "2": "nii", "2.1": "bhni", "2.2": "shni", "3": "rii", "4": "emp"}


def _nse_overlay(symbol: str, series: str) -> dict:
    d = data.fetch_nse_detail(symbol, series)
    if not d:
        return {}
    sub = {}
    for row in d.get("bidDetails", []) or []:
        sr = str(row.get("srNo") or "").strip()
        t = data._num(row.get("noOfTime"))
        if sr in _CAT_SR and t is not None:
            sub[_CAT_SR[sr]] = t
        elif (row.get("category") or "").strip().lower() == "total" and t is not None:
            sub["total"] = t
    info = {}
    for it in (d.get("issueInfo", {}) or {}).get("dataList", []):
        t = (it.get("title") or "").strip()
        if t:
            info[t] = data._text(it.get("value"))
    links = {}
    for label, key in (("Red Herring Prospectus", "rhp"),
                       ("Ratios / Basis of Issue Price", "basis"),
                       ("Anchor Allocation Report", "anchor")):
        raw = next((it.get("value") for it in (d.get("issueInfo", {}) or {}).get("dataList", [])
                    if (it.get("title") or "").strip() == label), "")
        u = _first_url(raw)
        if u:
            links[key] = u
    return {"sub": sub, "info": info, "links": links,
            "price_band": info.get("Price Range"), "bid_lot": info.get("Bid Lot"),
            "registrar": info.get("Name of the Registrar")}


# --------------------------------------------------------------------------- #
#  TIER 1 — computed listing-gain checks + score
# --------------------------------------------------------------------------- #
def _chk(cid, label, value, status, note=""):
    return {"id": cid, "label": label, "value": value, "status": status, "note": note}


WEIGHTS = {"L1": 28, "L2": 14, "L3": 8, "L4": 10, "L5": 10, "L6": 15, "L7": 15}
_PTS = {"PASS": 1.0, "CAUTION": 0.5, "FAIL": 0.0}
SME_PENALTY = 12


def _fx(x, nd=2):
    return f"{x:.{nd}f}x" if isinstance(x, (int, float)) else "—"


def tier1_checks(rec: dict) -> dict:
    s = rec.get("sub") or {}
    qib, total, nii, rii = s.get("qib"), s.get("total"), s.get("nii"), s.get("rii")
    gmp_pct, pe = rec.get("gmp_pct"), rec.get("pe")
    open_yet = rec.get("status") in ("open", "closed", "listed")
    checks = []

    # L1 QIB
    if qib is None:
        st, val = "NA", ("not open yet" if not open_yet else "awaited")
    else:
        st = "PASS" if qib >= 10 else "CAUTION" if qib >= 1 else "FAIL"
        val = _fx(qib)
    checks.append(_chk("L1", "QIB subscription (smart money)", val, st,
                       "Institutions do the deepest due-diligence — the strongest single signal (want ≥10x)."))

    # L2 overall
    if total is None:
        st, val = "NA", ("not open yet" if not open_yet else "awaited")
    else:
        st = "PASS" if total >= 20 else "CAUTION" if total >= 1 else "FAIL"
        val = _fx(total)
    checks.append(_chk("L2", "Overall subscription", val, st,
                       "Total demand vs shares on offer (want ≥20x; <1x = undersubscribed)."))

    # L3 NII/HNI
    if nii is None:
        st, val = "NA", ("not open yet" if not open_yet else "awaited")
    else:
        st = "PASS" if nii >= 10 else "CAUTION" if nii >= 1 else "FAIL"
        val = _fx(nii)
    checks.append(_chk("L3", "NII / HNI subscription", val, st,
                       "High-net-worth demand — often leveraged & listing-pop driven; read as sentiment."))

    # L4 froth guard (retail vs QIB)
    if qib is None or rii is None:
        st, val = "NA", "awaited"
    elif qib < 2 and rii > 5:
        st, val = "FAIL", f"QIB {_fx(qib)} vs retail {_fx(rii)}"
    elif qib >= rii:
        st, val = "PASS", f"QIB {_fx(qib)} ≥ retail {_fx(rii)}"
    else:
        st, val = "CAUTION", f"QIB {_fx(qib)} < retail {_fx(rii)}"
    checks.append(_chk("L4", "Retail-vs-institutional balance", val, st,
                       "Retail hype without institutional conviction is a classic weak-listing setup."))

    # L5 anchor
    if rec.get("anchor"):
        st, val = "PASS", "present"
    else:
        st, val = "CAUTION", "none/unknown"
    checks.append(_chk("L5", "Anchor book", val, st,
                       "Institutions committing 1 day before the issue opens = pre-certification (quality is manual)."))

    # L6 GMP (caveated, soft)
    if gmp_pct is None:
        st, val = "NA", "no GMP"
    else:
        st = "PASS" if gmp_pct >= 20 else "CAUTION" if gmp_pct >= 0 else "FAIL"
        val = f"{gmp_pct:+.1f}%"
    note = "Unofficial grey-market sentiment — manipulable, not predictive; never the verdict."
    if rec.get("board") == "SME":
        note = "⚠️ SME grey market is thin & easily manipulated — treat with extra suspicion. " + note
    checks.append(_chk("L6", "Grey Market Premium (GMP)", val, st, note))

    # L7 valuation sanity
    if pe is None or pe <= 0:
        st, val = "NA", "no/neg P/E"
    else:
        st = "PASS" if pe < 25 else "CAUTION" if pe <= 40 else "FAIL"
        val = f"{pe:.1f}x"
    checks.append(_chk("L7", "Valuation sanity (P/E)", val, st,
                       "Rough bar only — compare to listed-peer median in the RHP (manual, below)."))

    scored = [c for c in checks if c["status"] in _PTS]
    got = sum(WEIGHTS[c["id"]] * _PTS[c["status"]] for c in scored)
    tot = sum(WEIGHTS[c["id"]] for c in scored)
    raw = (got / tot * 100) if tot else None
    score = raw
    sme_adj = False
    if raw is not None and rec.get("board") == "SME":
        score = max(0, raw - SME_PENALTY)
        sme_adj = True

    # critical-FAIL veto — only once the book is actually closed (an open Day-1
    # book legitimately shows <1x, so we never veto a still-open issue).
    veto = None
    if rec.get("status") in ("closed", "listed"):
        if total is not None and total < 1:
            veto = "Undersubscribed (overall < 1x)."
        elif qib is not None and qib < 1:
            veto = "QIB under-subscribed (< 1x) — institutions stayed away."
        elif gmp_pct is not None and gmp_pct < 0 and (total is None or total < 3):
            veto = "Negative GMP with weak demand."

    # gate: too early to call listing gains until there's real demand data
    too_early = (qib is None and total is None)

    return {"checks": checks, "score": (round(score) if score is not None else None),
            "raw_score": (round(raw) if raw is not None else None),
            "scored_weight": tot, "sme_adjusted": sme_adj, "qib": qib, "total": total,
            "veto": veto, "too_early": bool(too_early)}


def listing_verdict(t1: dict) -> tuple[str, str]:
    if t1["too_early"]:
        return "WATCH", "Book not open / no meaningful demand yet — decide near close (Day 3)."
    if t1["veto"]:
        return "AVOID", t1["veto"]
    sc = t1["score"]
    if sc is None:
        return "WATCH", "Not enough computable signals yet."
    qib = t1.get("qib")
    # QIB > GMP/retail hype: never call APPLY on weak institutional demand.
    if sc >= 70 and (qib is None or qib >= 5):
        return "APPLY", "Strong institutional demand & sentiment on the computed signals (listing-gain view)."
    if sc >= 70 and qib is not None and qib < 5:
        return "NEUTRAL", (f"Score is high but QIB is only {qib:.1f}x — institutional conviction is the "
                           "signal that matters most, so this is a selective call, not a clear apply.")
    if sc >= 45:
        return "NEUTRAL", "Mixed computed signals — selective; small ticket / low-allotment only."
    return "AVOID", "Weak computed demand/valuation signals for a listing-gain trade."


# --------------------------------------------------------------------------- #
#  Long-term view (manual-first; light computed flags only)
# --------------------------------------------------------------------------- #
def long_term_view(rec: dict) -> dict:
    flags = []
    pe = rec.get("pe")
    if pe is not None and pe > 40:
        flags.append(f"P/E {pe:.0f}x looks rich — justify vs peer median in the RHP.")
    if pe is not None and 0 < pe <= 22:
        flags.append(f"P/E {pe:.0f}x is undemanding vs typical IPO pricing (still verify quality).")
    q = (rec.get("sub") or {}).get("qib")
    if q is not None and q >= 10:
        flags.append("Heavy QIB interest suggests institutional conviction (necessary, not sufficient).")
    if rec.get("board") == "SME":
        flags.append("SME: lighter disclosure, low liquidity and a ~₹1–2 lakh ticket — hold only with eyes open.")
    rating = "Needs RHP review"      # honest default — fundamentals aren't in free feeds
    return {"rating": rating, "flags": flags}


# --------------------------------------------------------------------------- #
#  TIER 3 — manual review items (with deep links)
# --------------------------------------------------------------------------- #
def manual_review_items(rec: dict, links: dict | None = None) -> list[dict]:
    links = links or {}
    rhp = links.get("rhp")
    basis = links.get("basis")
    rhp_where = f"NSE RHP: {rhp}" if rhp else "RHP / DRHP on nseindia.com, bseindia.com or SEBI"
    basis_where = f"NSE 'Basis for Issue Price': {basis}" if basis else "RHP → 'Basis for Issue Price' section"
    items = [
        {"sev": "high", "title": "Objects of the issue — Fresh vs OFS split",
         "detail": "OFS proceeds go to selling shareholders, not the company. OFS > 50% = strong red flag "
                   "(promoters/PE cashing out); fresh-issue for capex/debt-reduction is better. (SEBI caps SME OFS at 20%.)",
         "where": rhp_where},
        {"sev": "high", "title": "Financials — growth, margins, RoE/RoCE, debt, cash flow",
         "detail": "3-5y revenue & PAT CAGR, EBITDA/net margin trend, RoE/RoCE >15%, D/E <1x, and crucially "
                   "CFO vs PAT (is the profit backed by cash?). Watch a profit spike only in the pre-IPO year.",
         "where": rhp_where},
        {"sev": "high", "title": "Valuation vs listed peers",
         "detail": "The RHP's 'Basis for Issue Price' table compares the issuer's P/E & RoNW to listed peers. "
                   "Priced at/below peer median = fair; 1.5x+ peers without better growth = expensive.",
         "where": basis_where},
        {"sev": "high", "title": "Promoter — post-issue holding, pledge, background, RPT",
         "detail": "Post-issue promoter holding (>50% = strong skin-in-game; near the 20% floor = weak), any share "
                   "pledging, promoter track record / SEBI actions, and scale of related-party transactions.",
         "where": rhp_where + " · shareholding on nseindia.com / bseindia.com"},
        {"sev": "medium", "title": "Anchor investor quality",
         "detail": "Marquee mutual funds (SBI/ICICI Pru/HDFC) & top FPIs = real diligence; unknown/related names = weak. "
                   "Anchor lock-in: 50% for 30 days, 50% for 90 days.",
         "where": (f"Anchor report: {links.get('anchor')}" if links.get("anchor")
                   else "Anchor allotment circular on the exchange")},
        {"sev": "medium", "title": "Sector outlook, moat & market position",
         "detail": "Structural tailwind vs declining sector; a durable competitive advantage; leader vs fringe player.",
         "where": "RHP 'Industry Overview' & 'Our Business'"},
        {"sev": "medium", "title": "Risk factors, litigation, contingent liabilities, auditor",
         "detail": "Read the first 15-20 risk factors, material litigation vs net worth, contingent liabilities, and any "
                   "qualified audit opinion / adverse CARO remarks / frequent restatements or auditor changes.",
         "where": rhp_where + " → 'Risk Factors' & auditor's report"},
    ]
    return items


# --------------------------------------------------------------------------- #
#  Analyze one IPO + summarize
# --------------------------------------------------------------------------- #
def find_record(query: str, records: list[dict] | None = None) -> dict | None:
    records = records if records is not None else _records()
    qn = _norm(query)
    if not qn:
        return None
    exact = [r for r in records if r["norm"] == qn]
    if exact:
        return exact[0]
    qtok = set(qn.split())
    best, best_score = None, 0.0
    for r in records:
        rtok = set(r["norm"].split())
        if not rtok:
            continue
        ov = len(qtok & rtok) / max(1, len(qtok | rtok))
        if qn in r["norm"] or r["norm"] in qn:
            ov = max(ov, 0.85)
        if ov > best_score:
            best, best_score = r, ov
    return best if best_score >= 0.45 else None


def analyze(query: str, tavily_key: str = "") -> dict:
    records = _records()
    rec = find_record(query, records)
    if not rec:
        avail = ", ".join(sorted({r["name"] for r in records})[:12])
        return {"_error": f"No live/recent IPO matched '{query}'. Try one of: {avail} …",
                "query": query}
    rec = dict(rec)                                # copy — we may overlay NSE data

    # authoritative NSE overlay (category subscription + RHP links) when matchable
    links, nse_info = {}, {}
    nse = _nse_lookup(rec["norm"])
    if nse and nse.get("symbol"):
        ov = _nse_overlay(nse["symbol"], nse.get("series", "EQ"))
        links = ov.get("links", {})
        nse_info = {"price_band": ov.get("price_band"), "bid_lot": ov.get("bid_lot"),
                    "registrar": ov.get("registrar"), "symbol": nse["symbol"]}
        nsub = ov.get("sub") or {}
        if nsub:                                   # NSE is authoritative for subscription
            merged = dict(rec["sub"])
            merged.update({k: v for k, v in nsub.items() if v is not None})
            rec["sub"] = merged
            rec["sub_source"] = "NSE (live)"
        if ov.get("price_band"):
            rec["price_band"] = ov["price_band"]

    enrichment = []
    if tavily_key:
        enrichment = data.tavily_search(
            f"{rec['name']} IPO review fresh issue OFS offer for sale financials RHP", tavily_key)

    t1 = tier1_checks(rec)
    lv, lrat = listing_verdict(t1)
    return {"_error": None, "query": query, "record": rec,
            "links": links, "nse_info": nse_info, "enrichment": enrichment,
            "tier1": t1, "listing_verdict": lv, "listing_rationale": lrat,
            "long_term": long_term_view(rec),
            "manual": manual_review_items(rec, links)}


def quick_verdict(rec: dict) -> tuple[str, int | None]:
    """Lightweight verdict for the list view (same engine, no NSE overlay)."""
    t1 = tier1_checks(rec)
    v, _ = listing_verdict(t1)
    return v, t1["score"]


# --------------------------------------------------------------------------- #
#  Filtering + sorting for the live list
# --------------------------------------------------------------------------- #
_VRANK = {"APPLY": 0, "NEUTRAL": 1, "WATCH": 2, "AVOID": 3}


def filter_records(records, *, status="All", board="All", exchange="All",
                   gmp_mode="Any", size_min=None, min_qib=None, min_total=None,
                   close_from=None, close_to=None, search="") -> list[dict]:
    """gmp_mode: 'Any' | 'Positive (>0)' | 'Negative (<0)' | 'Has live GMP'.
    close_from/close_to: ISO date strings (inclusive) on the IPO's close date."""
    out = []
    q = _norm(search) if search else ""
    for r in records:
        if isinstance(status, (list, tuple, set)):
            if r["status"] not in status:
                continue
        elif status != "All" and r["status"] != status:
            continue
        if board != "All" and r["board"] != board:
            continue
        if exchange != "All" and (r.get("exchange") or "") != exchange:
            continue
        gp, gr = r.get("gmp_pct"), r.get("gmp_rs")
        if gmp_mode == "Positive (>0)" and not (gp is not None and gp > 0):
            continue
        if gmp_mode == "Negative (<0)" and not (gp is not None and gp < 0):
            continue
        if gmp_mode == "Has live GMP" and not gr:
            continue
        if size_min is not None and (r.get("size_cr") is None or r["size_cr"] < size_min):
            continue
        sub = r.get("sub") or {}
        if min_qib is not None and (sub.get("qib") is None or sub["qib"] < min_qib):
            continue
        if min_total is not None and (sub.get("total") is None or sub["total"] < min_total):
            continue
        cd = r.get("close_date")
        if close_from and (cd is None or cd < close_from):
            continue
        if close_to and (cd is None or cd > close_to):
            continue
        if q and q not in r["norm"]:
            continue
        out.append(r)
    return out


_DATE_FIELDS = ("open_date", "close_date", "listing_date", "boa_date")


def sort_records(records, by="gmp_pct", desc=True):
    def key(r):
        if by == "verdict":                       # best signal first (own direction)
            v, sc = quick_verdict(r)
            return (_VRANK.get(v, 4), -(sc or 0))
        val = (r.get("sub") or {}).get(by) if by in ("qib", "total") else r.get(by)
        if val is not None:
            return val
        return "" if by in _DATE_FIELDS else float("-inf")   # None sorts last under desc
    reverse = desc and by != "verdict"
    return sorted(records, key=key, reverse=reverse)
