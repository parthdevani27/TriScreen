# Deploy (public)

The app has no login gate — anyone with the URL can use it.

## Install + run
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy (Streamlit Community Cloud)
1. Push to a **GitHub repo**.
2. <https://share.streamlit.io> → **New app** → point at `streamlit_app.py`.

## Don'ts
- Don't put brokerage logins / account numbers / PII in the app — keep it to the public market data it already uses.
