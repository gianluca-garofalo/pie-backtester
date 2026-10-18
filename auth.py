"""Authentication helper module for Streamlit native auth and Supabase integration."""

from __future__ import annotations

import streamlit as st


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
        if hasattr(st, "logout"):
            if st.button("Log out", key="logout_btn"):
                st.logout()
        elif st.button("Log out", key="custom_logout_btn"):
            st.session_state.pop("custom_user", None)
            st.rerun()
    else:
        st.write("Sign in to save and manage your pies across devices.")
        if hasattr(st, "login"):
            try:
                if st.button("Sign in with Google", key="login_btn"):
                    st.login("google")
            except Exception:
                pass

    with st.expander("Privacy & Data Note"):
        st.caption("We only store pie configurations (tickers, names, and weights) that you explicitly save. "
                   "No brokerage credentials or personal financial accounts are ever accessed.")
    return user
