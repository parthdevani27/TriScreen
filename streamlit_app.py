"""Market Analysis — multi-section entrypoint (Stocks / Mutual Funds / IPO).

Run:  .venv/bin/streamlit run streamlit_app.py

This is the ONLY place that calls st.set_page_config() and injects the shared
CSS. Each section is a page script under views/, run by st.navigation.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Market Analysis", page_icon="📈",
                   layout="wide", initial_sidebar_state="expanded")

from components.theme import inject_css

inject_css()

stocks = st.Page("views/stocks.py", title="Stocks", icon=":material/trending_up:", default=True)
funds = st.Page("views/mutual_funds.py", title="Mutual Funds", icon=":material/account_balance:")
ipo = st.Page("views/ipo.py", title="IPO", icon=":material/upcoming:")

pg = st.navigation({"Screeners": [stocks, funds], "Coming soon": [ipo]}, position="top")
pg.run()
