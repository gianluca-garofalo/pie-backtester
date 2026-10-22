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


def get_current_user(allow_guest: bool = True) -> dict[str, str] | None:
    """Return user info if authenticated via Streamlit native auth or session state."""
    # Check st.user (Streamlit >= 1.39) or st.experimental_user
    user_obj = getattr(st, "user", getattr(st, "experimental_user", None))
    if user_obj and getattr(user_obj, "is_logged_in", False):
        return {
            "email": getattr(user_obj, "email", "user@example.com"),
            "name": getattr(user_obj, "name", "User"),
            # namespaced so ids from other providers or the local guest can't collide
            "id": "google:" + str(getattr(user_obj, "sub", None) or getattr(user_obj, "email", "")),
        }

    # Check if a custom session user was set (e.g. for testing/local mode)
    if allow_guest and st.session_state.get("custom_user"):
        return st.session_state["custom_user"]

    return None


def render_auth_ui(allow_guest: bool = True) -> dict[str, str] | None:
    """Render the one-line account area in the sidebar: "<name> · Log out" or "Guest · Sign in with Google".

    allow_guest=False when pies are stored in a shared database: every guest has the
    same id, so guests would see and delete each other's pies.
    """
    user = get_current_user(allow_guest)
    privacy = ("Only the pies you save are stored: tickers, names, weights and settings. "
               "No brokerage credentials or financial accounts are ever accessed.")
    if not user and not is_auth_configured() and not allow_guest:
        # st.login() can only fail without secrets, so don't offer it
        st.warning("Google sign-in isn't set up, so pies can't be saved (see README).")
        return None
    with st.container(key="account", horizontal=True, vertical_alignment="center", gap="small"):
        if user:
            st.markdown(f"**{user.get('name') or user.get('email')}** ·", width="content")
            if st.button("Log out", key="logout_btn", type="tertiary", help=privacy):
                if st.session_state.get("custom_user") or not hasattr(st, "logout"):
                    st.session_state.pop("custom_user", None)
                    st.rerun()
                st.logout()
        elif not is_auth_configured():
            st.markdown("Not signed in ·", width="content")
            if st.button("Use guest account", key="guest_login_btn", type="tertiary",
                         help="Google sign-in isn't set up (see README), so pies are saved on this machine."):
                st.session_state["custom_user"] = dict(GUEST_USER)
                st.rerun()
        else:
            st.markdown("Guest ·", width="content")
            if st.button("Sign in with Google", key="login_btn", type="tertiary",
                         help="Save and manage your pies across devices. " + privacy):
                try:
                    st.login("google")
                except Exception as err:
                    st.session_state["auth_error"] = str(err)

    if st.session_state.get("auth_error"):
        st.warning(f"Google Auth error: {st.session_state['auth_error']}\n\n"
                   "Please check `.streamlit/secrets.toml` for `redirect_uri`, `cookie_secret`, "
                   "and `[auth.google]` settings (see README).")
        if allow_guest and st.button("Use guest account", key="guest_after_error_btn", type="tertiary"):
            st.session_state["custom_user"] = dict(GUEST_USER)
            st.session_state.pop("auth_error", None)
            st.rerun()
    return user
