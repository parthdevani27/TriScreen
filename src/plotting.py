"""Chart rendering (candlesticks + EMAs + S/R zones + volume)."""

from __future__ import annotations

import pandas as pd

# Force a non-interactive backend BEFORE mplfinance (which imports pyplot) loads.
# These charts are saved straight to PNG and never shown in a GUI; Agg also lets
# the parallel screener batch render on worker threads without the macOS GUI
# backend crashing ("Cannot create a GUI FigureManager outside the main thread").
try:
    import matplotlib
    matplotlib.use("Agg")
except Exception:
    pass


def save_analysis_chart(df: pd.DataFrame, sr: dict, symbol: str, out_png: str,
                        bars: int = 300) -> bool:
    try:
        import mplfinance as mpf
    except ImportError:
        print("(!) mplfinance missing - skipping chart. pip install mplfinance")
        return False

    plot_df = df.tail(bars)
    aps = [
        mpf.make_addplot(plot_df["EMA20"], color="blue", width=0.8),
        mpf.make_addplot(plot_df["EMA50"], color="orange", width=0.8),
    ]
    if plot_df["EMA200"].notna().any():
        aps.append(mpf.make_addplot(plot_df["EMA200"], color="red", width=0.8))

    # Horizontal lines for nearest support/resistance
    hlines = []
    if sr.get("nearest_support"):
        hlines.append(sr["nearest_support"]["level"])
    if sr.get("nearest_resistance"):
        hlines.append(sr["nearest_resistance"]["level"])

    kwargs = dict(
        type="candle", style="yahoo",
        title=f"{symbol}  EMA20=blue 50=orange 200=red",
        ylabel="Price", volume=True, addplot=aps,
        figratio=(16, 9), figscale=1.4,
        savefig=dict(fname=out_png, dpi=130, bbox_inches="tight"),
    )
    if hlines:
        kwargs["hlines"] = dict(hlines=hlines, colors=["green", "purple"][:len(hlines)],
                                linestyle="--", linewidths=0.9)
    mpf.plot(plot_df, **kwargs)
    return True
