import os
import pytest
from storage import validate_pie, normalize_pie, LocalStorageBackend

def test_validate_pie_valid():
    valid_data = {
        "version": 1,
        "name": "Test Pie",
        "currency": "EUR",
        "assets": [
            {"ticker": "VWCE.DE", "weight": 60.0},
            {"ticker": "AGGH.DE", "weight": 40.0}
        ]
    }
    is_valid, msg = validate_pie(valid_data)
    assert is_valid is True
    assert msg == ""

def test_validate_pie_legacy():
    legacy_data = {
        "pie": [
            {"Ticker": "VWCE.DE", "Name": "Vanguard FTSE All-World", "Weight %": 50.0},
            {"Ticker": "IWDA.AS", "Name": "iShares Core MSCI World", "Weight %": 50.0}
        ],
        "currency": "USD"
    }
    is_valid, msg = validate_pie(legacy_data)
    assert is_valid is True
    assert msg == ""

def test_validate_pie_invalid_weights():
    invalid_data = {
        "version": 1,
        "assets": [
            {"ticker": "VWCE.DE", "weight": 50.0},
            {"ticker": "AGGH.DE", "weight": 40.0}
        ]
    }
    is_valid, msg = validate_pie(invalid_data)
    assert is_valid is False
    assert "must sum to 100%" in msg

def test_normalize_pie():
    data = {
        "name": "  My Pie  ",
        "currency": "eur",
        "assets": [
            {"ticker": "vwce.de ", "weight": 100.0}
        ]
    }
    norm = normalize_pie(data)
    assert norm["version"] == 1
    assert norm["name"] == "My Pie"
    assert norm["currency"] == "EUR"
    assert norm["assets"][0]["ticker"] == "VWCE.DE"
    assert norm["assets"][0]["weight"] == 100.0

def test_local_storage_crud(tmp_path):
    test_file = str(tmp_path / "test_pies.json")
    storage = LocalStorageBackend(filepath=test_file)

    assert storage.list_pies() == []

    pie_data = {
        "name": "Sample Pie",
        "currency": "EUR",
        "assets": [{"ticker": "AAPL", "weight": 100.0}]
    }
    saved = storage.save_pie(pie_data)
    pie_id = saved["id"]

    listed = storage.list_pies()
    assert len(listed) == 1
    assert listed[0]["id"] == pie_id
    assert listed[0]["name"] == "Sample Pie"

    retrieved = storage.get_pie(pie_id)
    assert retrieved is not None
    assert retrieved["name"] == "Sample Pie"

    deleted = storage.delete_pie(pie_id)
    assert deleted is True
    assert storage.get_pie(pie_id) is None
    assert storage.list_pies() == []


def test_validate_pie_rejects_nan_weight():
    data = {"assets": [{"ticker": "VWCE.DE", "weight": float("nan")}, {"ticker": "EUNA.DE", "weight": 100.0}]}
    is_valid, msg = validate_pie(data)
    assert is_valid is False
    assert "VWCE.DE" in msg


def test_validate_pie_legacy_bad_weight_is_invalid_not_an_exception():
    is_valid, msg = validate_pie({"pie": [{"Ticker": "VWCE.DE", "Weight %": "lots"}]})
    assert is_valid is False


def test_normalize_pie_null_name_falls_back_to_ticker():
    norm = normalize_pie({"assets": [{"ticker": "vwce.de", "weight": 100.0, "name": None}]})
    assert norm["assets"][0]["name"] == "VWCE.DE"



def test_local_rename_and_publish(tmp_path):
    store = LocalStorageBackend(filepath=str(tmp_path / "pies.json"))
    saved = store.save_pie({"name": "Old", "assets": [{"ticker": "VWCE.DE", "weight": 100.0}]})
    assert store.update_pie(saved["id"], name="  New name ")
    assert store.update_pie(saved["id"], is_public=True)
    pie = store.get_pie(saved["id"])
    assert (pie["name"], pie["is_public"]) == ("New name", True)
    assert not store.update_pie(saved["id"], name="  ")  # an empty name is refused
    assert not store.update_pie("no-such-id", name="X")


def test_local_overwrite_keeps_the_id(tmp_path):
    store = LocalStorageBackend(filepath=str(tmp_path / "pies.json"))
    saved = store.save_pie({"name": "Mine", "assets": [{"ticker": "VWCE.DE", "weight": 100.0}]})
    store.overwrite_pie(saved["id"], {"name": "Mine", "assets": [{"ticker": "EUNA.DE", "weight": 100.0}]})
    assert [p["assets"][0]["ticker"] for p in store.list_pies()] == ["EUNA.DE"]  # replaced, not added


@pytest.mark.parametrize("bad", ["lots", [], {}, "nan", float("inf"), True, False])
def test_amounts_must_be_numbers(bad):
    pie = {"initial": bad, "assets": [{"ticker": "AAPL", "weight": 100}]}
    ok, err = validate_pie(pie)
    assert not ok and "'initial' must be a number" in err
    ok, err = validate_pie(dict(pie, initial=None, monthly=bad))
    assert not ok and "'monthly' must be a number" in err
    assert validate_pie(dict(pie, initial="1000"))[0]  # numbers as text are fine, like weights


def test_thirds_add_up():
    # 33.33 * 3 is 99.99000000000001 in floating point, just past a plain 0.01 tolerance
    assert validate_pie({"assets": [{"ticker": t, "weight": 33.33} for t in ("A", "B", "C")]})[0]
    assert not validate_pie({"assets": [{"ticker": t, "weight": 33.3} for t in ("A", "B", "C")]})[0]  # 99.9


def test_names_ignore_case_and_spacing():
    from storage import clean_name, same_name
    assert clean_name("  [P6]   Tech  ") == "[P6] Tech"
    assert same_name("[P6]  Tech", "[p6] tech ")
    assert not same_name("Tech", "Tech 2")
    assert normalize_pie({"name": " My   pie ", "assets": [{"ticker": "A", "weight": 100}]})["name"] == "My pie"


@pytest.mark.parametrize("field, value, message", [
    ("monthly", -100, "can't be negative"), ("initial", 1e308, "too large"),
    ("currency", "XYZ", "Unknown currency"), ("rebalance", "Daily", "Unknown rebalance"),
    ("before_listing", "maybe", "Unknown before_listing"), ("start", "yesterday", "must be a date"),
])
def test_settings_that_make_no_sense_are_refused(field, value, message):
    ok, err = validate_pie({field: value, "assets": [{"ticker": "AAPL", "weight": 100}]})
    assert not ok and message in err


def test_storage_settings_match_the_engine():
    import engine
    from storage import BEFORE_LISTING_OPTIONS, REBALANCE_OPTIONS
    assert tuple(engine.REBALANCE_RULES) == REBALANCE_OPTIONS
    assert tuple(engine.BEFORE_LISTING) == BEFORE_LISTING_OPTIONS


def test_an_unfinished_pie_can_be_opened_but_not_saved():
    pie = {"assets": [{"ticker": "A", "weight": 50}, {"ticker": "B", "weight": 20}]}  # 70%
    assert not validate_pie(pie)[0]
    assert validate_pie(pie, whole=False)[0]
    assert sum(a["weight"] for a in normalize_pie(pie, whole=False)["assets"]) == 70


def test_a_weight_of_true_is_refused():
    assert not validate_pie({"assets": [{"ticker": "A", "weight": True}]}, whole=False)[0]
