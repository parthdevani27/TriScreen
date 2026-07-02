# TriScreen

An honest, evidence-first screener for the Indian market — **three tools in one**:

- 📈 **Stocks** — positional setup (backtested technicals + risk) & fundamental quality
- 📊 **Mutual Funds** — 12-point equity-fund checklist (rolling returns, alpha, Sharpe, downside capture)
- 🚀 **IPO** — Mainboard & SME: a computed *listing-gain* read (subscription · GMP · anchor · valuation) plus a *long-term* checklist

Every tool splits what it can **compute** from free data vs what needs **manual review** — it screens and scores setup quality & risk, it does not predict profit.

## Run

```bash
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Paste tickers / fund names / an IPO name → get a ranked, honest verdict.

## Data

Free, unofficial, no-SLA sources (Yahoo Finance, mfapi.in, Kuvera, NSE, investorgain). Verify before acting.

---

> Educational only — **not financial advice**. Always confirm the details yourself and use a stop-loss.
