"""app.py with made-up prices (no network): start rules, Undo, saved state and escaping, run in-process with AppTest."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import engine
import storage

APP = str(Path(__file__).resolve().parents[1] / "app.py")
LISTED = {"OLD.DE": "2010-01-04", "NEW.DE": "2019-07-29", "MID.DE": "2012-01-02"}


def fake_load(tickers, start, end, base="EUR"):
    """Rising prices from each ticker's listing day; a ticker that isn't in LISTED has no prices."""
    missing = [t for t in tickers if t not in LISTED]
    if missing:
        raise ValueError("No prices found for " + ", ".join(missing) + ".")
    idx = pd.bdate_range("2010-01-04", date.today())
    df = pd.DataFrame({t: np.linspace(100, 200, len(idx)) for t in tickers}, index=idx)
    for t in tickers:
        df.loc[df.index < pd.Timestamp(LISTED[t]), t] = np.nan
    return df, {"currencies": {t: "EUR" for t in tickers}}


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no saved_pies.json or secrets from the checkout
    monkeypatch.setattr(engine, "load_prices", fake_load)


def app(pie, compare=(), name="Mix", **settings):
    at = AppTest.from_file(APP, default_timeout=60)
    s = at.session_state
    s["pie"] = [{"Ticker": t, "Name": t, "Weight %": w} for t, w in pie.items()]
    s["pie_name"] = name
    s["compare"] = [dict({"names": {}, "color": "#B86E00", "order": i + 1, "saved_ref": None}, **e)
                    for i, e in enumerate(compare)]
    s["period"] = "Custom"
    for k, v in settings.items():
        s[k] = v
    return at


def test_cash_with_an_asset_listing_after_to_says_why_instead_of_crashing():
    for compare in ([], [{"name": "Only old", "weights": {"OLD.DE": 100.0}}]):
        at = app({"OLD.DE": 50.0, "NEW.DE": 50.0}, compare, start_rule="cash",
                 start=date(2018, 1, 1), end=date(2019, 1, 1)).run()
        assert not at.exception, at.exception[0].message  # was a TypeError comparing None with a date
        assert len(at.radio)  # the choice card is still there to switch back


def test_undo_is_gone_after_a_copy():
    at = app({"OLD.DE": 100.0}, [{"name": "Other", "weights": {"MID.DE": 100.0}}],
             start=date(2015, 1, 1), end=date(2016, 1, 1)).run()
    at.button(key="remove_0").click().run()
    assert "undo" in at.session_state
    at.button(key="copy_own").click().run()
    assert "undo" not in at.session_state  # Undo would bring back "Other" and silently drop the copy
    assert [e["name"] for e in at.session_state.compare] == ["Mix (copy)"]


def test_deleting_a_saved_pie_unmarks_its_compared_card():
    saved = storage.LocalStorageBackend().save_pie({"name": "Kept", "assets": [{"ticker": "MID.DE", "weight": 100}]})
    ref = {"id": saved["id"], "key": ("Kept", (("MID.DE", 100.0),))}
    at = app({"OLD.DE": 100.0}, [{"name": "Kept", "weights": {"MID.DE": 100.0}, "saved_ref": ref}],
             start=date(2015, 1, 1), end=date(2016, 1, 1)).run()
    at.button(key=f"delete_saved_{saved['id']}").click().run()
    assert at.session_state.compare[0]["saved_ref"] is None  # it said "Saved" for a pie no longer stored


def test_names_and_tickers_from_links_stay_text_in_help_and_errors():
    crafted = "[x](http://e.com)"
    at = app({"OLD.DE": 60.0}, [{"name": "Other", "weights": {"MID.DE": 100.0}}], name=crafted,
             start=date(2015, 1, 1), end=date(2016, 1, 1)).run()
    assert "\\[x\\]" in at.button(key="edit_0").help  # "Finish '…' first": Markdown
    at = app({"[Y](http://e.com)": 100.0}, start=date(2015, 1, 1), end=date(2016, 1, 1)).run()
    assert any("\\[Y\\]" in e.value for e in at.error), [e.value for e in at.error]  # "Backtest failed: …"
