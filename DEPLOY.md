# Deploy with Google login (invite-only)

The app is gated by **Google sign-in + an email allow-list** (`components/auth.py`).
- No password is ever stored — Google verifies identity; your app only receives a verified email.
- The gate is **fail-closed**: only emails in `allowed_emails` get in. Everyone else is stopped.
- **Locally with no `.streamlit/secrets.toml`, the app runs ungated** (convenient for dev). The gate turns on only once an `[auth]` block exists in secrets.

## 1. Create a Google OAuth client (one time)
1. Go to <https://console.cloud.google.com> → create/select a project.
2. **APIs & Services → OAuth consent screen** → User type **External** → fill app name + your email.
   - Add yourself and any allowed users under **Test users**, and **leave the app in "Testing"** — this is a *second* gate: only listed test users can even complete Google login.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID** → type **Web application**.
   - **Authorized redirect URIs** → add both:
     - `http://localhost:8501/oauth2callback` (local)
     - `https://<your-app-url>/oauth2callback` (after you know your deployed URL — must match exactly)
4. Copy the **Client ID** and **Client secret**.

## 2. Configure secrets
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # this real file is git-ignored
python -c "import secrets; print(secrets.token_hex(32))"      # paste as cookie_secret
```
Fill `client_id`, `client_secret`, `cookie_secret`, and `allowed_emails` in `.streamlit/secrets.toml`.

## 3. Install + run
```bash
pip install "streamlit[auth]"        # or: pip install -r requirements.txt
streamlit run streamlit_app.py
```
You should see the **"Log in with Google"** screen; an approved account gets in, others are blocked.

## 4. Deploy (Streamlit Community Cloud)
1. Push to a **GitHub repo** (private repo recommended).
2. <https://share.streamlit.io> → **New app** → point at `streamlit_app.py`.
3. **App settings → Secrets** → paste the entire contents of your `secrets.toml` (do **not** commit the file).
4. Note the deployed URL, then:
   - update `redirect_uri` in the app's Secrets to `https://<your-app-url>/oauth2callback`, and
   - add that same URL to the Google OAuth client's **Authorized redirect URIs**.
5. (Optional, strongest) also set the app itself to **private** in *App settings → Sharing* for a platform-level gate on top.

## Managing access
- **Add someone:** add their email to `allowed_emails` (and to Google **Test users** if the consent screen is still in Testing).
- **Remove someone:** delete their email from `allowed_emails` — takes effect on their next action.

## Don'ts
- Don't commit `.streamlit/secrets.toml` (already git-ignored).
- Don't put brokerage logins / account numbers / PII in the app — keep it to the public market data it already uses.
- Don't remove the `allowed_emails` check — Google login alone authenticates *any* Google account.
