"""Access gate — Google login (Streamlit native OIDC) + email allow-list.

Design:
  - ENABLED only when an [auth] block exists in .streamlit/secrets.toml, so local
    `streamlit run` (and AppTest) run UNGATED with no secrets present.
  - On deploy: set [auth] + allowed_emails in secrets → every visitor must sign in
    with an approved Google account before anything renders.
  - FAIL-CLOSED: if auth is configured but allowed_emails is empty/missing, access
    is DENIED (never "allow everyone") — OIDC authenticates any Google account, so
    the allow-list is the real gate.

Docs: https://docs.streamlit.io/develop/concepts/connections/authentication
"""

from __future__ import annotations

import streamlit as st


def _auth_configured() -> bool:
    try:
        return "auth" in st.secrets
    except Exception:          # no secrets.toml at all → local/dev
        return False


def require_login() -> None:
    """Call once in the entrypoint, after set_page_config/inject_css and BEFORE
    st.navigation. Halts (st.stop) unless the visitor is a logged-in, allow-listed
    Google account."""
    if not _auth_configured():
        return  # ungated local/dev

    # 1) Authentication
    if not st.user.is_logged_in:
        st.markdown("## 🔒 This dashboard is private")
        st.write("Sign in with an approved Google account to continue.")
        st.button("Log in with Google", type="primary", on_click=st.login)
        st.stop()

    # 2) Authorization (OIDC only proves WHO — we enforce WHETHER-ALLOWED here)
    allowed = [e.strip().lower() for e in st.secrets.get("allowed_emails", []) if e]
    email = (getattr(st.user, "email", "") or "").lower()
    if not allowed:
        st.error("⚠️ Access denied: no `allowed_emails` configured. "
                 "The owner must add at least one email to secrets.")
        st.button("Log out", on_click=st.logout)
        st.stop()
    if email not in allowed:
        st.error(f"🚫 {st.user.email} is not on the access list for this app.")
        st.caption("Ask the owner to add your email, or sign in with an approved account.")
        st.button("Log out", on_click=st.logout)
        st.stop()

    # 3) Authorized — persistent logout in the sidebar
    with st.sidebar:
        st.caption(f"Signed in · {st.user.email}")
        st.button("Log out", on_click=st.logout, use_container_width=True, key="_logout")
