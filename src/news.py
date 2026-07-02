"""
News + AI sentiment module.

- Headlines: Google News RSS (free, no API key, no quota, decent India coverage).
- Sentiment: FinBERT (finance-tuned AI) if transformers+torch are installed;
  otherwise falls back to VADER (lightweight) or a tiny keyword lexicon.

Returns a per-stock sentiment score in [-1, +1] plus the scored headlines, used
as a LIVE risk/sentiment signal in run.py. (It is intentionally NOT used in the
historical backtest — free news has no reliable point-in-time history, so using
current news on a past date would be lookahead bias.)
"""

from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_FINBERT = None          # lazy-loaded pipeline
_BACKEND = None          # "finbert" | "vader" | "lexicon"

_POS_WORDS = {"surge", "jump", "gain", "profit", "beat", "record", "high", "rise",
              "rally", "upgrade", "growth", "strong", "wins", "boost", "soar"}
_NEG_WORDS = {"fall", "drop", "loss", "plunge", "decline", "downgrade", "weak",
              "cut", "fraud", "probe", "slump", "crash", "miss", "warn", "ban",
              "fine", "lawsuit", "resign", "default"}


# ---------------------------------------------------------------------------
# Headlines
# ---------------------------------------------------------------------------
def fetch_headlines(query: str, limit: int = 20) -> list[dict]:
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(f"{query} stock")
           + "&hl=en-IN&gl=IN&ceid=IN:en")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
    except Exception as e:
        print(f"    (news fetch failed: {e})")
        return []
    try:
        root = ET.fromstring(data)
    except Exception:
        return []
    out = []
    for item in root.iter("item"):
        title = item.findtext("title")
        if title:
            out.append({"title": title.strip(), "pubDate": item.findtext("pubDate")})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Sentiment backends
# ---------------------------------------------------------------------------
def _ensure_backend():
    global _FINBERT, _BACKEND
    if _BACKEND is not None:
        return
    try:
        from transformers import pipeline  # noqa
        _FINBERT = pipeline("text-classification", model="ProsusAI/finbert", top_k=None)
        _BACKEND = "finbert"
        return
    except Exception:
        pass
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # noqa
        _BACKEND = "vader"
        return
    except Exception:
        pass
    _BACKEND = "lexicon"


def _score_one(text: str) -> float:
    """Return sentiment in [-1, +1] for a single headline."""
    if _BACKEND == "finbert":
        scores = _FINBERT(text)[0]  # list of {label, score}
        d = {s["label"].lower(): s["score"] for s in scores}
        return float(d.get("positive", 0) - d.get("negative", 0))
    if _BACKEND == "vader":
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        if not hasattr(_score_one, "_an"):
            _score_one._an = SentimentIntensityAnalyzer()
        return float(_score_one._an.polarity_scores(text)["compound"])
    # lexicon fallback
    words = set(text.lower().replace(",", " ").replace(".", " ").split())
    pos, neg = len(words & _POS_WORDS), len(words & _NEG_WORDS)
    if pos == neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


def _label(score: float) -> str:
    if score >= 0.15:
        return "POSITIVE"
    if score <= -0.15:
        return "NEGATIVE"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def analyze_news(name: str, limit: int = 20) -> dict:
    _ensure_backend()
    heads = fetch_headlines(name, limit)
    if not heads:
        return {"backend": _BACKEND, "n": 0, "avg_score": 0.0,
                "label": "NO NEWS", "headlines": []}
    scored = []
    for h in heads:
        s = _score_one(h["title"])
        scored.append({"title": h["title"], "score": round(s, 3), "label": _label(s)})
    avg = sum(x["score"] for x in scored) / len(scored)
    pos = sum(1 for x in scored if x["label"] == "POSITIVE")
    neg = sum(1 for x in scored if x["label"] == "NEGATIVE")
    return {
        "backend": _BACKEND,
        "n": len(scored),
        "avg_score": round(avg, 3),
        "label": _label(avg),
        "positive": pos,
        "negative": neg,
        "neutral": len(scored) - pos - neg,
        "headlines": scored[:10],
    }
