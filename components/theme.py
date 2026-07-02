"""Shared visual theme for all sections (Stocks / Mutual Funds / IPO).

Palette = validated data-viz reference (dark surface). Import the constants and
call inject_css() ONCE in the entrypoint (streamlit_app.py) — never in a page.
"""

from __future__ import annotations

import streamlit as st

# --- palette ---
SURFACE   = "#1a1a19"
PAGE      = "#0d0d0d"
INK       = "#ffffff"
INK_2     = "#c3c2b7"
MUTED     = "#898781"
GRID      = "#2c2c2a"
BASELINE  = "#383835"
BORDER    = "rgba(255,255,255,0.10)"
BLUE      = "#3987e5"   # series-1
VIOLET    = "#9085e9"   # series-5
AQUA      = "#199e70"   # series-2
GOOD      = "#0ca30c"
WARNING   = "#fab219"
CRITICAL  = "#d03b3b"
SERIOUS   = "#ec835a"

# --- verdict styles (shared shape across sections) ---
VERDICT_STYLE = {
    # stocks
    "STRONG SETUP": (GOOD, "✅"),
    "WATCH":        (WARNING, "⚠️"),
    "AVOID":        (CRITICAL, "⛔"),
    # mutual funds
    "STRONG":       (GOOD, "✅"),
    "DECENT":       (BLUE, "◆"),
    "WEAK":         (WARNING, "⚠️"),
    "POOR":         (CRITICAL, "⛔"),
    "UNTESTED":     (MUTED, "•"),
    # ipo (listing-gain verdict)
    "APPLY":        (GOOD, "✅"),
    "NEUTRAL":      (BLUE, "◆"),
    # shared
    "ERROR":        (MUTED, "•"),
}

QUALITY_COLOR = {"Strong": GOOD, "Mixed": WARNING, "Weak": CRITICAL}

# status chip colours used by check grids in both sections
STATUS_COLOR = {"PASS": GOOD, "GOOD": GOOD, "OK": BLUE, "CAUTION": WARNING,
                "WARN": WARNING, "MANUAL": WARNING, "FAIL": CRITICAL,
                "BAD": CRITICAL, "UNKNOWN": MUTED, "NA": MUTED, "N/A": MUTED}


def inject_css():
    st.markdown(f"""
<style>
  .stApp {{ background: {PAGE}; }}
  #MainMenu, footer {{ visibility: hidden; }}
  .block-container {{ padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1400px; }}

  .app-title {{ font-size: 2rem; font-weight: 700; color: {INK}; letter-spacing:-0.02em; margin:0; }}
  .app-sub   {{ color: {MUTED}; font-size: .95rem; margin: .25rem 0 0 0; }}

  .tile {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px;
    padding: 1.1rem 1.25rem; }}
  .tile .k {{ color: {MUTED}; font-size: .78rem; text-transform: uppercase; letter-spacing:.06em; }}
  .tile .v {{ color: {INK}; font-size: 1.9rem; font-weight: 700; line-height: 1.1; margin-top:.2rem;
             font-variant-numeric: tabular-nums; }}

  .badge {{ display:inline-flex; align-items:center; gap:.35rem; padding:.22rem .6rem;
            border-radius: 999px; font-weight:700; font-size:.8rem;
            border:1px solid {BORDER}; }}

  .crit-row {{ display:flex; align-items:flex-start; gap:.6rem; padding:.55rem .75rem;
               border-radius:10px; background:{SURFACE}; border:1px solid {BORDER}; margin-bottom:.4rem; }}
  .crit-id  {{ color:{MUTED}; font-weight:700; font-size:.8rem; min-width:2.2rem; padding-top:.05rem;
               font-variant-numeric: tabular-nums; }}
  .crit-lab {{ color:{INK}; font-weight:600; font-size:.9rem; }}
  .crit-det {{ color:{INK_2}; font-size:.8rem; margin-top:.1rem; }}
  .crit-st  {{ font-weight:700; font-size:.78rem; padding:.1rem .5rem; border-radius:6px; white-space:nowrap; }}

  .plan {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:14px; padding:1.1rem 1.25rem; }}
  .plan .row {{ display:flex; justify-content:space-between; padding:.4rem 0;
               border-bottom:1px solid {GRID}; }}
  .plan .row:last-child {{ border-bottom:none; }}
  .plan .lab {{ color:{MUTED}; font-size:.85rem; }}
  .plan .val {{ color:{INK}; font-weight:700; font-variant-numeric: tabular-nums; }}

  .disclaimer {{ color:{MUTED}; font-size:.75rem; line-height:1.5;
                 border-left:2px solid {BASELINE}; padding-left:.7rem; margin-top:1rem; }}

  div[data-testid="stDataFrame"] {{ border:1px solid {BORDER}; border-radius:12px; }}
  section[data-testid="stSidebar"] {{ background:{SURFACE}; border-right:1px solid {BORDER}; }}
</style>
""", unsafe_allow_html=True)
