"""Authentication helper module for Streamlit native auth and Supabase integration."""

from __future__ import annotations

import streamlit as st

GUEST_USER = {"email": "guest@local.dev", "name": "Local Guest", "id": "local_guest_user"}


def is_auth_configured(provider: str = "google") -> bool:
    """Check if all required auth secrets for provider are present in st.secrets."""
    try:
        auth_sec = st.secrets.get("auth", {})
        if not auth_sec or "redirect_uri" not in auth_sec or "cookie_secret" not in auth_sec:
            return False
        provider_sec = auth_sec.get(provider, {})
        if not provider_sec:
            return False
        required_keys = ["client_id", "client_secret", "server_metadata_url"]
        return all(key in provider_sec for key in required_keys)
    except Exception:
        return False


def get_current_user() -> dict[str, str] | None:
    """Return user info if authenticated via Streamlit native auth or session state."""
    # Check st.user (Streamlit >= 1.39) or st.experimental_user
    user_obj = getattr(st, "user", getattr(st, "experimental_user", None))
    if user_obj and getattr(user_obj, "is_logged_in", False):
        return {
            "email": getattr(user_obj, "email", "user@example.com"),
            "name": getattr(user_obj, "name", "User"),
            "id": getattr(user_obj, "sub", getattr(user_obj, "email", "user_id"))
        }

    # Check if a custom session user was set (e.g. for testing/local mode)
    if st.session_state.get("custom_user"):
        return st.session_state["custom_user"]

    return None


def render_auth_ui() -> dict[str, str] | None:
    """Render Login / Logout UI in the sidebar."""
    user = get_current_user()
    if user:
        st.write(f"Logged in as **{user.get('name') or user.get('email')}**")
        if hasattr(st, "logout") and not st.session_state.get("custom_user"):
            if st.button("Log out", key="logout_btn", width="stretch"):
                st.logout()
        else:
            if st.button("Log out", key="custom_logout_btn", width="stretch"):
                st.session_state.pop("custom_user", None)
                st.rerun()
    elif not is_auth_configured():
        # st.login() can only fail without secrets, so don't offer it
        st.caption("Google sign-in isn't set up (see README). Pies are saved on this machine.")
        if st.button("Use Local Guest Account", key="guest_login_btn", width="stretch"):
            st.session_state["custom_user"] = dict(GUEST_USER)
            st.rerun()
    else:
        st.caption("Sign in to save and manage your pies across devices.")
        if st.button("Sign in with Google", key="login_btn", type="primary", width="stretch"):
            if hasattr(st, "login"):
                try:
                    st.login("google")
                except Exception as err:
                    st.session_state["auth_error"] = str(err)
            else:
                st.session_state["auth_error"] = "Streamlit native auth is not supported in this version."

        if st.session_state.get("auth_error"):
            st.warning(f"Google Auth error: {st.session_state['auth_error']}\n\n"
                       "Please check `.streamlit/secrets.toml` for `redirect_uri`, `cookie_secret`, "
                       "and `[auth.google]` settings (see README).")
            if st.button("Use Local Guest Account", key="guest_login_btn", width="stretch"):
                st.session_state["custom_user"] = dict(GUEST_USER)
                st.session_state.pop("auth_error", None)
                st.rerun()

    with st.expander("Privacy & Data Note"):
        st.caption("We only store pie configurations (tickers, names, and weights) that you explicitly save. "
                   "No brokerage credentials or personal financial accounts are ever accessed.")
    return user
