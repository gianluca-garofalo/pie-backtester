"""app.py wiring with Supabase configured, run in-process with Streamlit's AppTest (no browser, no network)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import storage

PUBLIC_PIE = {"id": "p-other", "name": "Someone's pie", "is_public": True, "owner_id": "google:999",
              "config": {"assets": [{"ticker": "VWCE.DE", "weight": 100.0}]}}


class Resp:
    status_code = 200
    text = ""

    def __init__(self, rows):
        self.rows = rows

    def json(self):
        return self.rows


APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(autouse=True)
def empty_workdir(tmp_path, monkeypatch):
    """No saved_pies.json or .streamlit/secrets.toml from the developer's checkout."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def requests_log(monkeypatch):
    log = []

    def get(url, params=None, **kw):
        log.append(("get", params))
        return Resp([PUBLIC_PIE])

    def delete(url, params=None, **kw):
        log.append(("delete", params))
        return Resp([])

    monkeypatch.setattr(storage.requests, "get", get)
    monkeypatch.setattr(storage.requests, "delete", delete)
    return log


def test_supabase_errors_are_shown_in_my_pies(monkeypatch):
    class Missing(Resp):
        status_code = 404

    monkeypatch.setattr(storage.requests, "get", lambda url, params=None, **kw: Missing([]))
    at = run_app(SUPABASE_URL="https://x.supabase.co", SUPABASE_SERVICE_KEY="service")
    assert any("Supabase answered with an error" in w.value and "migration" in w.value for w in at.warning)


def run_app(**secrets):
    at = AppTest.from_file(APP, default_timeout=30)
    for key, value in secrets.items():
        at.secrets[key] = value
    return at.run()


def labels(at):
    return [b.label for b in at.button]


def test_shared_storage_has_no_guest_account(requests_log):
    at = run_app(SUPABASE_URL="https://x.supabase.co", SUPABASE_SERVICE_KEY="service")
    assert "Use guest account" not in labels(at)
    assert any("can't be saved" in w.value for w in at.warning)
    # anonymous visitors only see public pies
    assert requests_log[0] == ("get", {"select": "*", "is_public": "eq.true"})


def test_anonymous_visitor_cannot_save_or_delete(requests_log):
    at = run_app(SUPABASE_URL="https://x.supabase.co", SUPABASE_SERVICE_KEY="service")
    at.button(key="ex_pop_0").click().run()  # an example pie, from the Examples menu
    assert at.session_state.pie
    assert at.button(key="save_open").disabled  # saving needs a signed-in user
    at.button(key="my_open_p-other").click().run()  # picking a pie opens it
    assert [a["Ticker"] for a in at.session_state.pie] == ["VWCE.DE"]
    keys = [b.key for b in at.button]
    assert "delete_saved_p-other" not in keys and "edit_saved_p-other" not in keys  # someone else's public pie


def test_old_anon_key_secret_falls_back_with_a_warning(requests_log):
    at = run_app(SUPABASE_URL="https://x.supabase.co", SUPABASE_KEY="anon")
    assert any("SUPABASE_SERVICE_KEY" in w.value for w in at.warning)
    assert "Use guest account" in labels(at)  # local storage, so the guest account is fine
    assert requests_log == []


def test_local_storage_keeps_the_guest_account(requests_log):
    at = run_app()
    assert "Use guest account" in labels(at)
    assert requests_log == []


def test_signed_in_owner_gets_delete_with_a_confirmation(requests_log, monkeypatch):
    # The owner-scoped delete request itself is tested in test_supabase.py: AppTest can't click inside
    # a dialog (dialogs rerun on their own), so the confirmed delete is covered by the browser tests.
    import auth

    own = dict(PUBLIC_PIE, id="p-mine", name="My pie", owner_id="google:123")
    monkeypatch.setattr(storage.requests, "get", lambda url, params=None, **kw: Resp([own]))
    monkeypatch.setattr(auth, "get_current_user",
                        lambda allow_guest=True: {"id": "google:123", "name": "Me", "email": "me@example.com"})
    at = run_app(SUPABASE_URL="https://x.supabase.co", SUPABASE_SERVICE_KEY="service")
    at.button(key="my_open_p-mine").click().run()
    at.button(key="delete_saved_p-mine").click().run()
    assert at.button(key="delete_confirm").label == "Delete"  # it asks first
    assert not any(method == "delete" for method, _ in requests_log)  # nothing deleted yet
