"""Symbol resolution + shared constants (Yahoo Finance, free, no API key)."""

from __future__ import annotations

import yfinance as yf

NIFTY = "^NSEI"  # NIFTY 50 index (for relative strength / market trend)


def resolve_symbol(name: str) -> tuple[str, "yf.Ticker"]:
    """
    'TCS' -> working Yahoo ticker. Tries NSE (.NS) then BSE (.BO).
    Returns (resolved_symbol, Ticker). Raises ValueError if nothing found.
    """
    name = name.strip().upper()
    candidates = [name] if name.endswith((".NS", ".BO")) else [f"{name}.NS", f"{name}.BO"]
    for sym in candidates:
        tk = yf.Ticker(sym)
        try:
            if not tk.history(period="5d").empty:
                return sym, tk
        except Exception:
            continue
    raise ValueError(
        f"Could not find price data for '{name}'. "
        f"Use the NSE symbol, e.g. TCS, INFY, RELIANCE, HDFCBANK."
    )


def base_name(symbol: str) -> str:
    """'TCS.NS' -> 'TCS' (used for the per-stock output folder)."""
    return symbol.split(".")[0]
