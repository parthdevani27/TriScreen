"""
Automated stand-ins for the 'manual review' checks — best-effort, clearly labelled,
FREE sources only. Everything degrades gracefully to a value of None + an 'error'
string so the UI can fall back to the plain manual note when a source is unavailable.

  1. forensic_scores(tk, is_financial)  — Piotroski F / Altman Z'' / Beneish M,
     computed from the financial statements yfinance already returns. No new source.
     (Statistical red flags, NOT fraud detection.)
  2. screener_shareholding(symbol)      — promoter PLEDGE % + quarterly Promoter/FII/
     DII trend, scraped from screener.in ('/company/' is robots-allowed).
  3. bse_governance(symbol)             — recent auditor-change / governance
     announcements + the latest concall-transcript PDF link, from the BSE API.

The two network functions are cached on disk per (source, symbol, day), so a daily
local run touches each source at most once. Fragile by nature (HTML/endpoints shift,
NSE/BSE block datacenter IPs) — fine for a personal machine, treat as a hint.
"""

from __future__ import annotations

import json
import os
import re
import time

import requests

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")


# --------------------------------------------------------------------------- #
#  Tiny disk cache (per source + symbol + calendar day)
# --------------------------------------------------------------------------- #
def _today() -> str:
    return time.strftime("%Y%m%d")


def _cache_get(source: str, key: str, max_age_days: int = 1):
    try:
        path = os.path.join(_CACHE_DIR, f"{source}_{key.upper()}.json")
        if not os.path.exists(path):
            return None
        if (time.time() - os.path.getmtime(path)) > max_age_days * 86400:
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _cache_put(source: str, key: str, value: dict):
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(os.path.join(_CACHE_DIR, f"{source}_{key.upper()}.json"), "w", encoding="utf-8") as f:
            json.dump(value, f)
    except Exception:
        pass


# =========================================================================== #
#  1. FORENSIC SCORES  (no network beyond yfinance's cached statements)
# =========================================================================== #
_REV = ["Total Revenue", "Operating Revenue"]
_COGS = ["Cost Of Revenue", "Cost Of Goods Sold", "Reconciled Cost Of Revenue"]
_GP = ["Gross Profit"]
_SGA = ["Selling General And Administration", "Selling General And Administrative"]
_EBIT = ["EBIT", "Operating Income", "Total Operating Income As Reported"]
_NI = ["Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations"]
_DEP = ["Reconciled Depreciation", "Depreciation And Amortization", "Depreciation Amortization Depletion"]
_TA = ["Total Assets"]
_CA = ["Current Assets", "Total Current Assets"]
_CL = ["Current Liabilities", "Total Current Liabilities"]
_RE = ["Retained Earnings"]
_TL = ["Total Liabilities Net Minority Interest", "Total Liabilities"]
_PPE = ["Net PPE", "Net Property Plant And Equipment", "Properties Plant And Equipment Net"]
_RECV = ["Receivables", "Accounts Receivable", "Net Receivables", "Gross Accounts Receivable"]
_LTD = ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]
_EQ = ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"]
_SHARES = ["Ordinary Shares Number", "Share Issued"]
_CFO = ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
        "Total Cash From Operating Activities"]


def _row(df, names, col=0):
    """Most-recent-first value of the first matching statement row, else None."""
    if df is None or getattr(df, "empty", True) or df.shape[1] <= col:
        return None
    for n in names:
        if n in df.index:
            try:
                v = float(df.loc[n].iloc[col])
                if v == v:  # not NaN
                    return v
            except Exception:
                pass
    return None


def _stmts(tk):
    def safe(attrs):
        for a in attrs:
            try:
                df = getattr(tk, a)
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass
        return None
    return (safe(["income_stmt", "financials"]),
            safe(["balance_sheet", "balancesheet"]),
            safe(["cashflow", "cash_flow"]))


def _gross_profit(inc, col):
    gp = _row(inc, _GP, col)
    if gp is not None:
        return gp
    rev, cogs = _row(inc, _REV, col), _row(inc, _COGS, col)
    return (rev - cogs) if (rev is not None and cogs is not None) else None


def _piotroski(inc, bs, cf) -> dict | None:
    ni0, ni1 = _row(inc, _NI, 0), _row(inc, _NI, 1)
    ta0, ta1 = _row(bs, _TA, 0), _row(bs, _TA, 1)
    cfo0 = _row(cf, _CFO, 0)
    if ta0 in (None, 0) or ni0 is None:
        return None
    score, used, tests = 0, 0, []

    def add(name, ok):
        nonlocal score, used
        if ok is None:
            return
        used += 1
        score += 1 if ok else 0
        tests.append(f"{'✓' if ok else '✗'} {name}")

    add("ROA > 0", ni0 > 0)
    add("Operating cash flow > 0", (cfo0 > 0) if cfo0 is not None else None)
    add("ROA improving", (ni0 / ta0 > ni1 / ta1) if (ni1 is not None and ta1) else None)
    add("Earnings backed by cash (CFO>NI)", (cfo0 > ni0) if cfo0 is not None else None)
    ltd0, ltd1 = _row(bs, _LTD, 0), _row(bs, _LTD, 1)
    add("Leverage falling", (ltd0 / ta0 < ltd1 / ta1) if (ltd1 is not None and ta1) else None)
    ca0, cl0, ca1, cl1 = _row(bs, _CA, 0), _row(bs, _CL, 0), _row(bs, _CA, 1), _row(bs, _CL, 1)
    add("Current ratio improving",
        (ca0 / cl0 > ca1 / cl1) if (None not in (ca0, cl0, ca1, cl1) and cl0 and cl1) else None)
    sh0, sh1 = _row(bs, _SHARES, 0), _row(bs, _SHARES, 1)
    add("No share dilution", (sh0 <= sh1 * 1.01) if (sh0 is not None and sh1) else None)
    gp0, gp1 = _gross_profit(inc, 0), _gross_profit(inc, 1)
    rev0, rev1 = _row(inc, _REV, 0), _row(inc, _REV, 1)
    add("Gross margin improving",
        (gp0 / rev0 > gp1 / rev1) if (None not in (gp0, gp1, rev0, rev1) and rev0 and rev1) else None)
    add("Asset turnover improving",
        (rev0 / ta0 > rev1 / ta1) if (rev0 is not None and rev1 is not None and ta1) else None)

    if used < 4:
        return None
    rating = "strong" if score >= 7 else "weak" if score <= 3 else "ok"
    return {"score": score, "used": used, "rating": rating, "tests": tests}


def _altman_zdd(inc, bs) -> dict | None:
    ta = _row(bs, _TA, 0)
    if not ta:
        return None
    ca, cl = _row(bs, _CA, 0), _row(bs, _CL, 0)
    re_, ebit, tl, eq = _row(bs, _RE, 0), _row(inc, _EBIT, 0), _row(bs, _TL, 0), _row(bs, _EQ, 0)
    if None in (ca, cl, re_, ebit, tl, eq) or tl == 0:
        return None
    x1, x2, x3, x4 = (ca - cl) / ta, re_ / ta, ebit / ta, eq / tl
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    zone = "safe" if z > 2.6 else "distress" if z < 1.1 else "grey"
    return {"z": round(z, 2), "zone": zone}


def _beneish_m(inc, bs, cf) -> dict | None:
    def idx(names, c):  # helper
        return _row(inc, names, c), _row(bs, names, c)

    rev0, rev1 = _row(inc, _REV, 0), _row(inc, _REV, 1)
    ta0, ta1 = _row(bs, _TA, 0), _row(bs, _TA, 1)
    recv0, recv1 = _row(bs, _RECV, 0), _row(bs, _RECV, 1)
    ni0, cfo0 = _row(inc, _NI, 0), _row(cf, _CFO, 0)
    gp0, gp1 = _gross_profit(inc, 0), _gross_profit(inc, 1)
    ca0, ca1 = _row(bs, _CA, 0), _row(bs, _CA, 1)
    ppe0, ppe1 = _row(bs, _PPE, 0), _row(bs, _PPE, 1)
    dep0, dep1 = _row(inc, _DEP, 0), _row(inc, _DEP, 1)
    cl0, cl1 = _row(bs, _CL, 0), _row(bs, _CL, 1)
    ltd0, ltd1 = _row(bs, _LTD, 0) or 0, _row(bs, _LTD, 1) or 0
    # essentials for a meaningful M-score
    if None in (rev0, rev1, ta0, ta1, ni0, cfo0) or 0 in (rev1, ta0, ta1):
        return None
    try:
        dsri = ((recv0 / rev0) / (recv1 / rev1)) if (recv0 is not None and recv1) else 1.0
        gmi = ((gp1 / rev1) / (gp0 / rev0)) if (None not in (gp0, gp1) and gp0 and rev0) else 1.0
        aqi = 1.0
        if None not in (ca0, ppe0, ca1, ppe1):
            aq0, aq1 = 1 - (ca0 + ppe0) / ta0, 1 - (ca1 + ppe1) / ta1
            aqi = (aq0 / aq1) if aq1 else 1.0
        sgi = rev0 / rev1
        depi = 1.0
        if None not in (dep0, dep1, ppe0, ppe1) and (dep0 + ppe0) and (dep1 + ppe1):
            depi = (dep1 / (dep1 + ppe1)) / (dep0 / (dep0 + ppe0))
        sgai = 1.0  # SG&A usually absent for Indian names → neutral
        lvgi = 1.0
        if None not in (cl0, cl1):
            lvgi = ((ltd0 + cl0) / ta0) / ((ltd1 + cl1) / ta1)
        tata = (ni0 - cfo0) / ta0
        m = (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi
             + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
        return {"m": round(m, 2), "flag": m > -2.22}
    except Exception:
        return None


def _is_utility(sector: str = "", industry: str = "") -> bool:
    """Altman Z was built for manufacturers and structurally mis-flags capital-
    intensive, heavily-leveraged UTILITIES (power/gas) as 'distress' — so we skip
    them just like banks/NBFCs (e.g. TATAPOWER / JSWENERGY / ADANIGREEN)."""
    s, i = (sector or "").lower(), (industry or "").lower()
    return ("utilit" in s) or any(k in i for k in
                                  ("utilit", "power producer", "electric", "renewable"))


def forensic_scores_cached(symbol_ns: str, is_financial: bool = False,
                           sector: str = "", industry: str = "") -> dict:
    """forensic_scores keyed by the '.NS'/'.BO' symbol, with a per-day disk cache
    (Streamlit reruns the page on every interaction — this avoids re-fetching the
    statements each time). Cache tag 'forensic2' = the utility-exclusion version."""
    import yfinance as yf
    key = symbol_ns.replace(".", "_")
    cached = _cache_get("forensic2", key)
    if cached is not None:
        return cached
    out = forensic_scores(yf.Ticker(symbol_ns), is_financial, sector, industry)
    if not out.get("error"):
        _cache_put("forensic2", key, out)
    return out


def forensic_scores(tk, is_financial: bool = False, sector: str = "", industry: str = "") -> dict:
    """Piotroski F / Altman Z'' / Beneish M from statements. Altman is skipped for
    banks/NBFCs AND utilities (structurally invalid there); the rest are best-effort."""
    skip_altman = bool(is_financial) or _is_utility(sector, industry)
    out = {"piotroski": None, "altman": None, "beneish": None,
           "is_financial": bool(is_financial), "flags": [], "error": None,
           "altman_na": ("bank/NBFC" if is_financial else "utility") if skip_altman else None}
    try:
        inc, bs, cf = _stmts(tk)
        if inc is None or bs is None:
            out["error"] = "financial statements unavailable from the feed"
            return out
        out["piotroski"] = _piotroski(inc, bs, cf)
        out["beneish"] = _beneish_m(inc, bs, cf)
        out["altman"] = None if skip_altman else _altman_zdd(inc, bs)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    p, a, b = out["piotroski"], out["altman"], out["beneish"]
    if p and p["rating"] == "weak":
        out["flags"].append(f"Weak fundamentals — Piotroski {p['score']}/{p['used']}")
    if a and a["zone"] == "distress":
        out["flags"].append(f"Financial-distress zone — Altman Z''={a['z']}")
    if b and b["flag"] and not is_financial:
        out["flags"].append(f"Earnings-quality red flag — Beneish M={b['m']} (> −2.22)")
    return out


# =========================================================================== #
#  2. SCREENER.IN  — promoter pledge % + quarterly Promoter/FII/DII trend
# =========================================================================== #
def _pct(s):
    try:
        return float(str(s).replace("%", "").replace(",", "").strip())
    except Exception:
        return None


def _direction(series):
    """(label, latest, delta_vs_~2q_ago) from a list of (quarter, 'x%') pairs."""
    vals = [(_pct(v)) for _, v in series if _pct(v) is not None]
    if len(vals) < 2:
        return None
    latest, ref = vals[-1], vals[max(0, len(vals) - 3)]
    d = round(latest - ref, 2)
    lab = "rising" if d > 0.3 else "falling" if d < -0.3 else "flat"
    return {"latest": latest, "delta": d, "direction": lab}


def screener_shareholding(symbol: str, retries: int = 3) -> dict:
    """Retries with backoff on failure and caches SUCCESS ONLY, so a rate-limited
    stock isn't stuck 'failed' for the rest of the day (it retries next run)."""
    from bs4 import BeautifulSoup
    cached = _cache_get("screener", symbol)
    if cached is not None:
        return cached
    out = {"pledge_pct": None, "promoter": None, "fii": None, "dii": None,
           "quarters": [], "source": "screener.in", "error": None}
    last_err = None
    for attempt in range(max(1, retries)):
        try:
            r = requests.get(f"https://www.screener.in/company/{symbol}/",
                             headers={"User-Agent": _UA}, timeout=15)
            if r.status_code == 200:
                m = re.search(r"pledged\s+([\d.]+)\s*%", r.text, re.I)
                out["pledge_pct"] = float(m.group(1)) if m else 0.0
                soup = BeautifulSoup(r.text, "html.parser")
                sec = soup.find(id="shareholding")
                tab = sec.find("table") if sec else None
                if tab:
                    rows = tab.find_all("tr")
                    hdr = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
                    quarters = hdr[1:]
                    out["quarters"] = quarters[-6:]
                    for row in rows[1:]:
                        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                        if not cells:
                            continue
                        label = cells[0].replace("+", "").strip().lower()
                        series = list(zip(quarters, cells[1:]))
                        if label.startswith("promoter"):
                            out["promoter"] = _direction(series)
                        elif label.startswith("fii"):
                            out["fii"] = _direction(series)
                        elif label.startswith("dii"):
                            out["dii"] = _direction(series)
                _cache_put("screener", symbol, out)   # cache SUCCESS only
                return out
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = type(e).__name__
        time.sleep(1.5 * (attempt + 1))   # backoff before retry (rate-limit friendly)
    out["error"] = f"screener {last_err}"
    return out   # errors are NOT cached → retried on the next run


# =========================================================================== #
#  3. BSE  — auditor / governance announcements + concall transcript link
# =========================================================================== #
_BSE_MAP = None
_GOV_KW = ["auditor", "resignation", "resign", "pledge", "encumbr", "fraud", "sebi",
           "default", "downgrade", "credit rating", "insolvency", "nclt", "forensic"]
_TRANS_KW = ["transcript", "earnings call", "earnings conference", "concall", "con call"]


def _bse_scrip_map() -> dict:
    """symbol -> BSE scrip code, from the (disk-cached, weekly) scrip master."""
    global _BSE_MAP
    if _BSE_MAP is not None:
        return _BSE_MAP
    cached = _cache_get("bse_master", "all", max_age_days=7)
    if cached:
        _BSE_MAP = cached
        return _BSE_MAP
    _BSE_MAP = {}
    try:
        r = requests.get("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w",
                         headers={"User-Agent": _UA, "Referer": "https://www.bseindia.com/"},
                         params={"Group": "", "Scripcode": "", "industry": "",
                                 "segment": "Equity", "status": "Active"}, timeout=30)
        for row in r.json():
            sid = str(row.get("scrip_id", "")).strip().upper()
            code = str(row.get("SCRIP_CD", "")).strip()
            if sid and code:
                _BSE_MAP[sid] = code
        if _BSE_MAP:
            _cache_put("bse_master", "all", _BSE_MAP)
    except Exception:
        pass
    return _BSE_MAP


def bse_governance(symbol: str, lookback_days: int = 180) -> dict:
    cached = _cache_get("bse", symbol)
    if cached is not None:
        return cached
    out = {"code": None, "governance": [], "transcript": None,
           "source": "bseindia.com", "error": None}
    code = _bse_scrip_map().get(symbol.upper())
    if not code:
        out["error"] = "no BSE scrip code for this symbol"
        _cache_put("bse", symbol, out)
        return out
    out["code"] = code
    try:
        frm = time.strftime("%Y%m%d", time.localtime(time.time() - lookback_days * 86400))
        r = requests.get("https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
                         headers={"User-Agent": _UA, "Referer": "https://www.bseindia.com/"},
                         params={"pageno": 1, "strCat": "-1", "strPrevDate": frm,
                                 "strScrip": code, "strSearch": "P",
                                 "strToDate": _today(), "strType": "C", "subcategory": "-1"},
                         timeout=20)
        rows = r.json().get("Table", []) or []
        pdf_base = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
        for x in rows:
            subj = (str(x.get("NEWSSUB", "")) + " " + str(x.get("HEADLINE", ""))).strip()
            low = subj.lower()
            att = x.get("ATTACHMENTNAME") or ""
            date = str(x.get("NEWS_DT", ""))[:10]
            if out["transcript"] is None and any(k in low for k in _TRANS_KW):
                out["transcript"] = {"date": date, "pdf": pdf_base + att if att else None}
            if any(k in low for k in _GOV_KW):
                out["governance"].append({"date": date, "subject": subj[:120],
                                          "pdf": pdf_base + att if att else None})
        out["governance"] = out["governance"][:6]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:80]}"
    if not out.get("error"):
        _cache_put("bse", symbol, out)   # cache success only
    return out
