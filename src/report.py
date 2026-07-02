"""Render the positional (1-2 month) checklist report."""

from __future__ import annotations

_ICON = {"PASS": "[PASS]", "FAIL": "[fail]", "MANUAL": "[VERIFY]", "UNKNOWN": "[ ?  ]"}


def _fmt(d: dict) -> str:
    return "\n".join(f"  {k:<22}: {v}" for k, v in d.items())


def write_report(r: dict, path: str) -> None:
    L = "=" * 74
    fund = r["fundamentals"]
    sc = r["scorecard"]
    news = r.get("news")

    lines = [L]
    name = fund["identity"].get("name") or r["stock"]
    lines.append(f"  {name}  ({r['symbol']})   as of {r['as_of']}")
    lines.append("  POSITIONAL CHECKLIST  —  1 to 2 month horizon")
    lines.append("  (descriptive screen, NOT a guaranteed prediction — see disclaimer)")
    lines.append(L)

    lines.append("\n[PRICE]\n" + _fmt(fund["price"]))
    lines.append("\n[VALUATION]\n" + _fmt(fund["valuation"]))
    lines.append(f"\n[MARKET REGIME] NIFTY: {fund.get('market_regime')}")
    if fund.get("relative_strength"):
        lines.append("[RELATIVE STRENGTH 6m]\n" + _fmt(fund["relative_strength"]))
    eg = fund.get("earnings_growth", {})
    lines.append(f"[EARNINGS YoY] revenue {eg.get('revenue_yoy')}%  EPS {eg.get('eps_yoy')}%  "
                 f"(available={eg.get('available')})")
    lines.append(f"[NEXT EARNINGS] {fund.get('next_earnings_date')}")

    # The 10-criteria checklist grouped by category
    lines.append("\n" + L)
    lines.append("  10-CRITERIA CHECKLIST")
    lines.append(L)
    cur_group = None
    for c in sc["criteria"]:
        if c["group"] != cur_group:
            cur_group = c["group"]
            lines.append(f"\n  -- {cur_group} --")
        lines.append(f"  {_ICON[c['status']]} {c['id']}: {c['label']}")
        lines.append(f"          {c['detail']}")

    # Trade plan
    lines.append("\n" + L)
    lines.append("  TRADE PLAN")
    lines.append(L)
    lines.append(f"  Entry (current)   : {fund['price']['last']}")
    lines.append(f"  Stop-loss         : {sc['stop_price']}  ({sc['stop_dist_pct']}% below)")
    if sc["target_price"]:
        lines.append(f"  Target (resistance): {sc['target_price']}  (+{sc['upside_pct']}%)")
        lines.append(f"  Risk : Reward     : 1 : {sc['risk_reward']}")
    else:
        lines.append("  Target            : open upside (price at/above recent resistance)")

    # Verdict / probability matrix
    if news:
        lines.append(f"\n[NEWS SENTIMENT] {news.get('label')} (avg {news.get('avg_score')})")
    lines.append("\n" + L)
    lines.append(f"  SCORE: {sc['confirmed_score']}/10 confirmed"
                 + (f"  (+{len(sc['manual'])} manual to verify -> up to {sc['best_case_score']}/10)" if sc['manual'] else ""))
    lines.append(f"  PROBABILITY BAND: {sc['band']}")
    lines.append(f"  ACTION: {sc['action']}")
    if sc["manual"]:
        lines.append(f"  MUST VERIFY MANUALLY: {', '.join(sc['manual'])}  "
                     "(promoter pledge & institutional holding)")
    lines.append(L)

    # Honest disclaimer
    lines.append("\n  HOW TO READ THIS (please read):")
    lines.append("  - This screens for a 1-2 month positional setup (Minervini/CANSLIM style).")
    lines.append("  - The 75%/50-60% probabilities are the checklist's design targets, NOT")
    lines.append("    guarantees. Our own backtests show technical edges are modest — treat the")
    lines.append("    score as setup QUALITY, not a promise of profit.")
    lines.append("  - C7 (promoter pledge) & C8 (FII/DII) have no free data feed — verify them")
    lines.append("    manually before any conviction buy.")
    lines.append("  - ALWAYS use the stop-loss. Never risk more than 1-2% of capital per trade.")
    lines.append("  - Educational only — not investment advice.")
    lines.append(L)

    text = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
