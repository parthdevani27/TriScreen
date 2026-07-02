"""
Orchestrator: python run.py <STOCK> [--interval daily|weekly|monthly]

Pipeline for the given stock:
  1. Download full price history (from the very start)
  2. Compute the full indicator set
  3. Support/Resistance zones + Fibonacci
  4. Candlestick + chart pattern detection
  5. Volume analysis + volume profile
  6. Fundamentals + relative strength + market trend
  7. Combined scorecard -> UP / SIDEWAYS / DOWN verdict
  8. Save EVERYTHING under output/<STOCK>/
"""

from __future__ import annotations

import argparse
import json
import os

from .common import base_name
from .data import (download_history, resample_ohlcv, detect_corporate_action_gap,
                   trim_partial_candle)
from .indicators import add_indicators
from .levels import support_resistance, fibonacci
from .candles import detect_candles, at_level
from .chart_patterns import detect_patterns
from .volume import analyze_volume, volume_profile
from .fundamentals import gather_fundamentals
from .scorecard import build_checklist as build_scorecard
from .plotting import save_analysis_chart
from .report import write_report
from .news import analyze_news

OUTPUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")


def analyze(name: str, interval: str = "daily", with_news: bool = True, as_of=None) -> dict:
    """Full analysis. If `as_of` (a datetime.date) is given and is BEFORE the last
    available session, the price series is truncated to <= as_of and every technical
    signal is computed point-in-time (as it would have looked then). Live fundamentals
    (.info) still reflect today — they can't be back-dated for free."""
    print(f"\n>>> Analyzing '{name}' ({interval}) ...")

    # 1. Data
    symbol, tk, daily_all = download_history(name)
    daily_all, partial_info = trim_partial_candle(daily_all)   # drop today's in-progress candle
    full_last = daily_all.index[-1].date()

    # point-in-time truncation (only when as_of is a genuine PAST date)
    is_pit = as_of is not None and as_of < full_last
    if is_pit:
        daily = daily_all[daily_all.index.date <= as_of]
        if len(daily) < 210:   # need enough history for SMA200 / 6-month RS
            raise ValueError(f"Not enough price history up to {as_of} for {symbol}")
    else:
        daily = daily_all
    eff_as_of = daily.index[-1].date()

    data_quality = detect_corporate_action_gap(daily)  # unadjusted demerger/spin-off guard
    data_quality.update(partial_info)
    df = add_indicators(resample_ohlcv(daily, interval))
    stock = base_name(symbol)
    out_dir = os.path.join(OUTPUT_ROOT, stock)
    os.makedirs(out_dir, exist_ok=True)
    print(f"    {symbol}: {len(df)} {interval} candles "
          f"{df.index[0].date()} -> {df.index[-1].date()}"
          f"{f' [point-in-time as of {eff_as_of}]' if is_pit else ''}")

    # 2-6. Analysis modules
    sr = support_resistance(df)
    fib = fibonacci(df)
    candles = detect_candles(df)
    for c in candles:  # tag whether each candle is at an S/R level
        c["at_level"] = at_level(float(df.loc[df.index[-1], "Close"]), sr)
    patterns = detect_patterns(df)
    vol = analyze_volume(df)
    vprofile = volume_profile(df)
    fund = gather_fundamentals(tk, df, as_of=eff_as_of if is_pit else None)

    # 6b. News + AI sentiment (live signal / risk flag)
    news = None
    if with_news:
        print("    fetching news + running FinBERT sentiment ...")
        news = analyze_news(name)

    # 7. 10-criteria positional checklist
    score = build_scorecard(df, fund, sr, vol, patterns, candles, news)

    result = {
        "symbol": symbol, "stock": stock, "interval": interval,
        "as_of": str(eff_as_of),
        "as_of_full": str(full_last),
        "is_point_in_time": is_pit,
        "data_quality": data_quality,
        "fundamentals": fund,
        "support_resistance": sr,
        "fibonacci": fib,
        "candlestick_patterns": candles,
        "chart_patterns": patterns,
        "volume_analysis": vol,
        "volume_profile": vprofile,
        "news": news,
        "scorecard": score,
    }

    # 8. Save outputs
    prefix = f"{stock}_{interval}"
    df.to_csv(os.path.join(out_dir, f"{prefix}_ohlcv.csv"))
    # In point-in-time mode also save the FULL series (up to today) so the deep-dive
    # chart can show what happened AFTER the analysis date.
    full_path = os.path.join(out_dir, f"{prefix}_ohlcv_full.csv")
    if is_pit:
        add_indicators(resample_ohlcv(daily_all, interval)).to_csv(full_path)
    elif os.path.exists(full_path):
        os.remove(full_path)   # stale from a previous PIT run — the normal CSV is now full
    try:
        df.to_parquet(os.path.join(out_dir, f"{prefix}_ohlcv.parquet"))
    except Exception as e:
        print(f"    (parquet skipped: {e})")

    with open(os.path.join(out_dir, f"{prefix}_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    save_analysis_chart(df, sr, symbol, os.path.join(out_dir, f"{prefix}_chart.png"))
    write_report(result, os.path.join(out_dir, f"{prefix}_report.txt"))

    print(f"    Saved all outputs -> {out_dir}")
    print(f"    SCORE: {score['confirmed_score']}/10 confirmed "
          f"(up to {score['best_case_score']}/10 with manual checks) "
          f"-> {score['band']}")
    print(f"    ACTION: {score['action']}\n")
    return result


def main():
    ap = argparse.ArgumentParser(description="Full stock analysis pipeline.")
    ap.add_argument("name", nargs="?", help="Stock name, e.g. TCS")
    ap.add_argument("--interval", choices=["daily", "weekly", "monthly"], default="daily")
    ap.add_argument("--no-news", action="store_true", help="Skip news/sentiment")
    args = ap.parse_args()
    name = args.name or input("Enter stock name (e.g. TCS): ")
    analyze(name, args.interval, with_news=not args.no_news)


if __name__ == "__main__":
    main()
