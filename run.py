"""
Entry point. Usage:
    python run.py TCS
    python run.py RELIANCE --interval weekly

All analysis code lives in src/. Outputs are written to output/<STOCK>/.
"""

import sys

# Windows consoles default to cp1252 and choke on emoji/unicode in the report.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.main import main

if __name__ == "__main__":
    main()
