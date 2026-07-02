"""DEPRECATED entrypoint — the app is now multi-section (Stocks / Mutual Funds / IPO).

Canonical launch:  streamlit run streamlit_app.py

This shim forwards to the new entrypoint so the old command keeps working.
"""

import runpy

runpy.run_path("streamlit_app.py", run_name="__main__")
