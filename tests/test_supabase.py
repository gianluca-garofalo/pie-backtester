"""SupabaseStorageBackend against a fake PostgREST: owner scoping is enforced by our code."""
import pytest

import storage

PIE = {"name": "Mine", "assets": [{"ticker": "VWCE.DE", "weight": 100.0}]}


class Resp:
    def __init__(self, status_code=200, rows=None):
        self.status_code, self._rows, self.text = status_code, rows if rows is not None else [], ""

    def json(self):
        return self._rows


@pytest.fixture
def calls(monkeypatch):
    """Record every request; answer with whatever the test queued in calls.replies."""
    class Log(list):
        replies = None

    log = Log()
    log.replies = []

    def fake(method):
        def send(url, params=None, json=None, headers=None, timeout=None):
            log.append({"method": method, "url": url, "params": params or {}, "json": json, "headers": headers})
            return log.replies.pop(0) if log.replies else Resp()
        return send

    for method in ("get", "post", "delete", "patch"):
        monkeypatch.setattr(storage.requests, method, fake(method))
    return log


@pytest.fixture
def db():
    return storage.SupabaseStorageBackend(url="https://x.supabase.co/", key="service-key")


def test_list_without_user_shows_only_public_pies(db, calls):
    db.list_pies()
    assert calls[0]["params"]["is_public"] == "eq.true"
    assert "or" not in calls[0]["params"]


def test_list_with_user_shows_public_and_own_pies(db, calls):
    db.list_pies(user_id="google:123")
    assert calls[0]["params"]["or"] == '(is_public.eq.true,owner_id.eq."google:123")'


def test_owner_id_is_quoted_inside_filters(db, calls):
    db.list_pies(user_id='evil",is_public.eq.false')
    assert calls[0]["params"]["or"] == '(is_public.eq.true,owner_id.eq."evil\\",is_public.eq.false")'


def test_listed_pies_keep_their_owner(db, calls):
    calls.replies.append(Resp(rows=[{"id": "p1", "name": "Mine", "is_public": False,
                                     "owner_id": "google:123", "config": dict(PIE)}]))
    [pie] = db.list_pies(user_id="google:123")
    assert pie["owner_id"] == "google:123" and pie["id"] == "p1"


def test_save_requires_a_signed_in_user(db, calls):
    with pytest.raises(ValueError, match="Sign in"):
        db.save_pie(PIE)
    assert calls == []


def test_save_inserts_with_owner(db, calls):
    calls.replies += [Resp(rows=[]), Resp(201, rows=[{"id": "p1", "config": dict(PIE)}])]
    db.save_pie(PIE, user_id="google:123")
    insert = calls[-1]
    assert insert["method"] == "post"
    assert insert["json"]["owner_id"] == "google:123"


def test_save_counts_only_own_pies_for_the_limit(db, calls):
    own = [{"id": f"p{i}", "owner_id": "google:123", "config": dict(PIE)} for i in range(storage.MAX_PIES_PER_USER)]
    calls.replies.append(Resp(rows=own))
    with pytest.raises(ValueError, match="limit"):
        db.save_pie(PIE, user_id="google:123")
    assert calls[0]["params"]["owner_id"] == "eq.google:123"


def test_delete_is_scoped_to_the_owner(db, calls):
    calls.replies.append(Resp(rows=[{"id": "p1"}]))
    assert db.delete_pie("p1", user_id="google:123") is True
    assert calls[0]["params"] == {"id": "eq.p1", "owner_id": "eq.google:123"}


def test_delete_of_someone_elses_pie_reports_failure(db, calls):
    calls.replies.append(Resp(rows=[]))  # PostgREST deletes nothing and still answers 200
    assert db.delete_pie("p1", user_id="google:999") is False


def test_delete_without_user_does_nothing(db, calls):
    assert db.delete_pie("p1") is False
    assert calls == []


def test_requests_use_the_service_key(db, calls):
    db.list_pies()
    assert calls[0]["headers"]["Authorization"] == "Bearer service-key"
    assert calls[0]["url"] == "https://x.supabase.co/rest/v1/pies"


def test_save_raises_when_supabase_rejects_it(db, calls):
    calls.replies += [Resp(rows=[]), Resp(401)]
    with pytest.raises(RuntimeError, match="401"):
        db.save_pie(PIE, user_id="google:123")


def test_new_style_secret_keys_go_only_in_the_apikey_header(calls):
    # sb_secret_... keys are not JWTs; Supabase reads them from the apikey header
    storage.SupabaseStorageBackend(url="https://x.supabase.co", key="sb_secret_abc").list_pies()
    assert calls[0]["headers"]["apikey"] == "sb_secret_abc"
    assert "Authorization" not in calls[0]["headers"]


def test_a_missing_table_is_reported_not_shown_as_no_pies(db, calls):
    calls.replies.append(Resp(404))
    assert db.list_pies(user_id="google:123") == []
    assert "404" in db.last_error and "migration" in db.last_error


def test_a_wrong_key_is_reported(db, calls):
    calls.replies.append(Resp(401))
    db.list_pies()
    assert "service_role" in db.last_error


def test_a_successful_read_clears_the_error(db, calls):
    calls.replies += [Resp(500), Resp(rows=[])]
    db.list_pies()
    assert db.last_error.startswith("HTTP 500")
    db.list_pies()
    assert db.last_error is None


def test_rename_and_publish_are_scoped_to_the_owner(db, calls):
    row = {"id": "p1", "owner_id": "google:123", "name": "Old", "config": PIE}
    calls.replies += [Resp(rows=[row]), Resp(rows=[dict(row, name="New")])]
    assert db.update_pie("p1", user_id="google:123", name=" New ", is_public=True)
    patch = calls[1]
    assert patch["method"] == "patch"
    assert patch["params"] == {"id": "eq.p1", "owner_id": "eq.google:123"}
    assert (patch["json"]["name"], patch["json"]["is_public"]) == ("New", True)
    assert (patch["json"]["config"]["name"], patch["json"]["config"]["is_public"]) == ("New", True)


def test_rename_of_someone_elses_pie_does_nothing(db, calls):
    calls.replies.append(Resp(rows=[]))  # the owner filter matches nothing
    assert not db.update_pie("p1", user_id="google:456", name="Mine now")
    assert [c["method"] for c in calls] == ["get"]


def test_update_needs_a_user_and_a_name(db, calls):
    assert not db.update_pie("p1", name="New")
    assert not db.update_pie("p1", user_id="google:123", name="   ")
    assert calls == []
