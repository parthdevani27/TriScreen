"""Shared visual theme for all sections (Stocks / Mutual Funds / IPO).

Palette = validated data-viz reference (dark surface). Import the constants and
call inject_css() ONCE in the entrypoint (streamlit_app.py) — never in a page.
"""

from __future__ import annotations

import streamlit as st

# --- surface/ink roles: FLIP with the active theme (set by apply_theme each run) ---
_DARK = dict(PAGE="#0d0d0d", SURFACE="#1a1a19", INK="#ffffff", INK_2="#c3c2b7",
             GRID="#2c2c2a", BASELINE="#383835", BORDER="rgba(255,255,255,0.10)")
_LIGHT = dict(PAGE="#f7f7f5", SURFACE="#ffffff", INK="#0b0b0b", INK_2="#52514e",
              GRID="#e6e5df", BASELINE="#c3c2b7", BORDER="rgba(11,11,11,0.12)")

# initialised to dark; apply_theme() reassigns these module globals each run.
PAGE     = _DARK["PAGE"]
SURFACE  = _DARK["SURFACE"]
INK      = _DARK["INK"]
INK_2    = _DARK["INK_2"]
GRID     = _DARK["GRID"]
BASELINE = _DARK["BASELINE"]
BORDER   = _DARK["BORDER"]
MODE            = "dark"
PLOTLY_TEMPLATE = "plotly_dark"

# --- muted + series/status colours: CONSTANT across light & dark (read on both) ---
MUTED     = "#898781"
BLUE      = "#3987e5"   # series-1
VIOLET    = "#9085e9"   # series-5
AQUA      = "#199e70"   # series-2
GOOD      = "#0ca30c"
WARNING   = "#e0930a"   # amber that reads on white AND dark
CRITICAL  = "#d03b3b"
SERIOUS   = "#ec835a"


def apply_theme() -> str:
    """Read the active native theme (Settings menu / system) and flip the module's
    surface/ink palette to match. Call in the entrypoint BEFORE inject_css() and
    BEFORE pg.run() — pages re-import these constants each run, so they pick up the
    current values. Returns the active mode."""
    global PAGE, SURFACE, INK, INK_2, GRID, BASELINE, BORDER, MODE, PLOTLY_TEMPLATE
    mode = "dark"
    try:
        t = getattr(st.context, "theme", None)
        typ = getattr(t, "type", None) if t is not None else None
        if typ in ("light", "dark"):
            mode = typ
    except Exception:
        pass
    p = _LIGHT if mode == "light" else _DARK
    PAGE, SURFACE, INK, INK_2, GRID, BASELINE, BORDER = (
        p["PAGE"], p["SURFACE"], p["INK"], p["INK_2"], p["GRID"], p["BASELINE"], p["BORDER"])
    MODE = mode
    PLOTLY_TEMPLATE = "plotly_white" if mode == "light" else "plotly_dark"
    return mode

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
  /* keep the ⚙ menu visible — it's the only path to Settings → Theme (Light/Dark) */
  footer {{ visibility: hidden; }}
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

  /* ---------- sidebar: minimal & clean (bg owned by config secondaryBackground) ---------- */
  section[data-testid="stSidebar"] {{ border-right:1px solid {BORDER}; }}
  section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding-top:1.1rem; }}
  /* turn "### Screen …" headers into quiet section labels */
  section[data-testid="stSidebar"] h1,
  section[data-testid="stSidebar"] h2,
  section[data-testid="stSidebar"] h3 {{
    font-size:.72rem; text-transform:uppercase; letter-spacing:.09em;
    color:{MUTED}; font-weight:700; margin:0 0 .5rem 0; }}
  section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap:.7rem; }}
  section[data-testid="stSidebar"] label {{ font-size:.82rem; color:{INK_2}; }}
  section[data-testid="stSidebar"] .disclaimer {{ font-size:.72rem; margin-top:.5rem; }}

  /* ---------- account chip (inside the sidebar-top account popover) ---------- */
  .acct {{ display:flex; align-items:center; gap:.6rem; padding:.1rem 0 .6rem; }}
  .acct-av {{ width:32px; height:32px; border-radius:50%; flex:0 0 auto;
              background:{BLUE}22; color:{BLUE}; display:flex; align-items:center;
              justify-content:center; font-weight:700; font-size:.9rem; }}
  .acct-meta {{ min-width:0; }}
  .acct-name {{ color:{INK}; font-size:.82rem; font-weight:600;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .acct-mail {{ color:{MUTED}; font-size:.72rem;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}

  /* ---------- responsive: tablet ---------- */
  @media (min-width:641px) and (max-width:1024px) {{
    .block-container {{ padding-left:1.2rem; padding-right:1.2rem; }}
    .app-title {{ font-size:1.7rem; }}
    .tile {{ padding:.9rem 1rem; }}
    .tile .v {{ font-size:1.6rem; }}
  }}
  /* ---------- responsive: mobile ---------- */
  @media (max-width:640px) {{
    .block-container {{ padding-left:.8rem; padding-right:.8rem; padding-top:.9rem; }}
    .app-title {{ font-size:1.45rem; }}
    .app-sub {{ font-size:.85rem; }}
    .tile {{ padding:.7rem .85rem; border-radius:12px; }}
    .tile .k {{ font-size:.68rem; }}
    .tile .v {{ font-size:1.35rem; }}
    .crit-row {{ padding:.5rem .6rem; }}
    .crit-lab {{ font-size:.85rem; }}
    .plan {{ padding:.9rem 1rem; }}
    .badge {{ font-size:.72rem; }}
  }}
</style>
""", unsafe_allow_html=True)
