import auth

def test_get_current_user_none():
    import streamlit as st
    st.session_state.clear()
    assert auth.get_current_user() is None

def test_get_current_user_custom():
    import streamlit as st
    st.session_state["custom_user"] = {"email": "test@example.com", "name": "Tester", "id": "123"}
    user = auth.get_current_user()
    assert user is not None
    assert user["email"] == "test@example.com"

def test_is_auth_configured():
    assert auth.is_auth_configured() in (True, False)
