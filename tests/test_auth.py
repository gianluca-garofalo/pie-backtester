import streamlit as st
import auth


def test_get_current_user_none():
    st.session_state.clear()
    if hasattr(st, "user"):
        # Reset mock st.user if needed
        delattr(st, "user")
    assert auth.get_current_user() is None


def test_get_current_user_custom():
    st.session_state["custom_user"] = {"email": "test@example.com", "name": "Tester", "id": "123"}
    user = auth.get_current_user()
    assert user is not None
    assert user["email"] == "test@example.com"


def test_get_current_user_st_user():
    st.session_state.clear()

    class MockUser:
        is_logged_in = True
        email = "user@example.com"
        name = "Google User"
        sub = "google_sub_123"

    st.user = MockUser()
    user = auth.get_current_user()
    assert user is not None
    assert user["email"] == "user@example.com"
    assert user["name"] == "Google User"
    assert user["id"] == "google:google_sub_123"
    delattr(st, "user")


def test_is_auth_configured_false_when_empty():
    st.secrets._secrets = {}
    assert auth.is_auth_configured() is False


def test_is_auth_configured_false_when_incomplete():
    st.secrets._secrets = {
        "auth": {
            "redirect_uri": "http://localhost:8501/oauth2callback",
            "google": {
                "client_id": "cid",
                "client_secret": "csec"
                # missing server_metadata_url and cookie_secret
            }
        }
    }
    assert auth.is_auth_configured() is False


def test_is_auth_configured_true():
    st.secrets._secrets = {
        "auth": {
            "redirect_uri": "http://localhost:8501/oauth2callback",
            "cookie_secret": "mycookie_secret",
            "google": {
                "client_id": "cid",
                "client_secret": "csec",
                "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration"
            }
        }
    }
    assert auth.is_auth_configured() is True
