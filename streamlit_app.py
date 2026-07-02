"""Market Analysis — multi-section entrypoint (Stocks / Mutual Funds / IPO).

Run:  .venv/bin/streamlit run streamlit_app.py

This is the ONLY place that calls st.set_page_config() and injects the shared
CSS. Each section is a page script under views/, run by st.navigation.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Market Analysis", page_icon="📈",
                   layout="wide", initial_sidebar_state="expanded")

from components.theme import inject_css, apply_theme
from components.auth import require_login, render_account

apply_theme()      # flip palette to the active light/dark theme (⚙ Settings menu) — before CSS + pages
inject_css()
require_login()    # Google login + email allow-list (no-op locally without [auth] secrets)
render_account()   # account chip + logout at top of sidebar (before pages, so it always renders)

stocks = st.Page("views/stocks.py", title="Stocks", icon=":material/trending_up:", default=True)
funds = st.Page("views/mutual_funds.py", title="Mutual Funds", icon=":material/account_balance:")
ipo = st.Page("views/ipo.py", title="IPO", icon=":material/rocket_launch:")

pg = st.navigation({"Screeners": [stocks, funds, ipo]}, position="top")
pg.run()
