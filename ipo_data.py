"""IPO data layer (free sources, tested live 2026-07-02 from `requests`).

  - NSE            -> IPO list (mainboard+SME), live subscription BY CATEGORY,
                      RHP / Basis-of-Issue-Price links.  [Akamai-gated: browser UA
                      + prime cookies on the homepage first; may block DC IPs]
  - investorgain   -> GMP (Rs + %), P/E, anchor flag, per-category subscription,
                      dates, board (IPO/SME).  Unofficial JSON, no SLA; the fiscal
                      year is baked into the URL path (roll each April).
  - Tavily         -> OPTIONAL web-search enrichment for RHP-only items (fresh/OFS
                      split, financials). Off unless an API key is supplied.

No Streamlit imports here (pure + thread-safe + unit-testable). Caching is a small
TTL dict + on-disk JSON fallback under output/_ipo_cache/, mirroring mf_data.py.
Every value that can go stale carries the fetch time so the UI can label it.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, date

import requests

NSE = "https://www.nseindia.com"
IG = "https://webnodejs.investorgain.com/cloud/report/data-read"
IG_GMP_REPORT = 331          # GMP dashboard
IG_SUB_REPORT = 333          # subscription dashboard
CACHE_DIR = os.path.join(os.path.dirname(__file__), "output", "_ipo_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

LIST_TTL = 900               # 15 min — GMP/subscription refresh ~30 min
DETAIL_TTL = 600

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_MEM: dict = {}              # key -> (fetched_epoch, value)
_SESSION: requests.Session | None = None


def clear_cache():
    global _SESSION
    _MEM.clear()
    _SESSION = None


# --------------------------------------------------------------------------- #
#  Small TTL cache with on-disk stale fallback
# --------------------------------------------------------------------------- #
def _disk(name: str) -> str:
    return os.path.join(CACHE_DIR, name)


def _cached(key: str, fetch_fn, ttl: int, disk_name: str):
    """Return (value, meta). meta = {'stale': bool, 'as_of': iso|None}.
    Fresh in-mem hit -> live. On fetch error -> newest disk copy flagged stale."""
    now = time.time()
    hit = _MEM.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1], {"stale": False, "as_of": _iso(hit[0])}
    try:
        val = fetch_fn()
        _MEM[key] = (now, val)
        try:
            json.dump({"t": now, "v": val}, open(_disk(disk_name), "w"))
        except Exception:
            pass
        return val, {"stale": False, "as_of": _iso(now)}
    except Exception:
        if hit:                                   # expired mem copy beats nothing
            return hit[1], {"stale": True, "as_of": _iso(hit[0])}
        p = _disk(disk_name)
        if os.path.exists(p):
            try:
                blob = json.load(open(p))
                return blob["v"], {"stale": True, "as_of": _iso(blob.get("t"))}
            except Exception:
                pass
        raise


def _iso(epoch) -> str | None:
    try:
        return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Parsing helpers (investorgain wraps values in HTML + entities)
# --------------------------------------------------------------------------- #
_TAG = re.compile(r"<[^>]+>")


def _text(s) -> str:
    if s is None:
        return ""
    return html.unescape(_TAG.sub(" ", str(s))).replace("\xa0", " ").strip()


def _num(x):
    """First number in a messy string -> float, else None. Unescapes HTML entities
    FIRST — e.g. '&#8377;42.34 Cr' is '₹42.34 Cr', not the number 8377."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return None if x != x else float(x)
    s = html.unescape(str(x)).replace("–", "-")
    m = re.search(r"-?\d[\d,]*\.?\d*", s)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _badges(name_html: str) -> list[str]:
    return [html.unescape(b).strip()
            for b in re.findall(r'class="badge[^"]*"[^>]*>([^<]+)<', name_html or "")]


def _parse_date(s):
    s = _text(s)
    if not s or s in ("-", "--"):
        return None
    for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%d %b %Y", "%Y-%m-%d", "%d-%b", "%d %b"):
        try:
            d = datetime.strptime(s.split()[0] if fmt in ("%d-%b", "%d %b") else s, fmt)
            if d.year == 1900:
                d = d.replace(year=date.today().year)
            return d.date().isoformat()
        except ValueError:
            continue
    return None


_STATUS_LETTER = {"O": "open", "U": "upcoming", "C": "closed", "L": "listed"}


# --------------------------------------------------------------------------- #
#  NSE (Akamai-gated) — session with homepage cookie prime + retry
# --------------------------------------------------------------------------- #
def _nse_session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    s = requests.Session()
    s.headers.update({"User-Agent": _UA,
                      "Accept": "application/json, text/plain, */*",
                      "Accept-Language": "en-US,en;q=0.9"})
    try:
        s.get(NSE, timeout=20)                    # prime _abck / bm cookies
    except Exception:
        pass
    _SESSION = s
    return s


def _nse_get(path: str):
    s = _nse_session()
    r = s.get(NSE + path, timeout=25)
    if r.status_code in (401, 403):               # cookies went stale -> re-prime once
        try:
            s.get(NSE, timeout=20)
        except Exception:
            pass
        r = s.get(NSE + path, timeout=25)
    r.raise_for_status()
    return r.json()


def fetch_nse_list() -> list[dict]:
    """all-upcoming-issues -> raw NSE rows (mainboard+SME via `series`)."""
    def go():
        d = _nse_get("/api/all-upcoming-issues?category=ipo")
        return d if isinstance(d, list) else []
    val, _ = _cached("nse_list", go, LIST_TTL, "nse_list.json")
    return val


def fetch_nse_current() -> list[dict]:
    def go():
        d = _nse_get("/api/ipo-current-issue")
        return d if isinstance(d, list) else []
    val, _ = _cached("nse_current", go, DETAIL_TTL, "nse_current.json")
    return val


def fetch_nse_detail(symbol: str, series: str = "EQ") -> dict:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {}

    def go():
        return _nse_get(f"/api/ipo-detail?symbol={symbol}&series={series}") or {}
    try:
        val, _ = _cached(f"nse_detail:{symbol}:{series}", go, DETAIL_TTL,
                         f"nse_detail_{symbol}_{series}.json")
        return val or {}
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
#  investorgain (unofficial JSON) — GMP + subscription, FY resolved robustly
# --------------------------------------------------------------------------- #
def _fy_candidates() -> list[str]:
    """Path segment '<calYear>/<fyLabel>'. The label is part of the report id, not
    a live filter, so we try a few around 'now' plus a known-good seed and keep the
    first that returns rows."""
    y = date.today().year
    fy_start = y if date.today().month >= 4 else y - 1
    labels = {f"{fy_start}-{(fy_start + 1) % 100:02d}",
              f"{fy_start - 1}-{fy_start % 100:02d}"}
    cals = {y, y + 1, fy_start, fy_start + 1}
    combos = [f"{c}/{lab}" for c in sorted(cals, reverse=True) for lab in sorted(labels, reverse=True)]
    seed = "2026/2025-26"                          # verified-good 2026-07
    return list(dict.fromkeys([seed] + combos))


def _ig_fetch(report: int) -> list[dict]:
    hdr = {"User-Agent": _UA, "Referer": "https://www.investorgain.com/",
           "Accept": "application/json"}
    last_exc = None
    for fy in _fy_candidates():
        url = f"{IG}/{report}/1/1/{fy}/0/all"
        try:
            r = requests.get(url, headers=hdr, timeout=20)
            if r.status_code != 200:
                continue
            rows = (r.json() or {}).get("reportTableData")
            if rows:
                return rows
        except Exception as e:
            last_exc = e
    if last_exc:
        raise last_exc
    return []


def fetch_ig_gmp() -> list[dict]:
    val, _ = _cached("ig_gmp", lambda: _ig_fetch(IG_GMP_REPORT), LIST_TTL, "ig_gmp.json")
    return val


def fetch_ig_sub() -> list[dict]:
    val, _ = _cached("ig_sub", lambda: _ig_fetch(IG_SUB_REPORT), LIST_TTL, "ig_sub.json")
    return val


def list_as_of() -> dict:
    """Freshness of the two list feeds for UI labelling (no fetch if cached)."""
    def age(key):
        hit = _MEM.get(key)
        return _iso(hit[0]) if hit else None
    return {"ig_gmp": age("ig_gmp"), "ig_sub": age("ig_sub"), "nse_list": age("nse_list")}


# --------------------------------------------------------------------------- #
#  OPTIONAL web-search enrichment (Tavily) — off unless a key is supplied
# --------------------------------------------------------------------------- #
def tavily_search(query: str, api_key: str, max_results: int = 5) -> list[dict]:
    """Return [{title,url,content}]. [] on any failure or missing key."""
    if not api_key:
        return []
    try:
        r = requests.post("https://api.tavily.com/search", timeout=25, json={
            "api_key": api_key, "query": query, "max_results": max_results,
            "search_depth": "advanced", "include_answer": True})
        r.raise_for_status()
        d = r.json()
        out = [{"title": x.get("title"), "url": x.get("url"), "content": x.get("content")}
               for x in (d.get("results") or [])]
        if d.get("answer"):
            out.insert(0, {"title": "Tavily answer", "url": None, "content": d["answer"]})
        return out
    except Exception:
        return []
