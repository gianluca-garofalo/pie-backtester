import json

import pytest
from playwright.sync_api import expect

from storage import list_examples

EXAMPLES = {ex["name"]: ex for ex in list_examples()}


def test_empty_page(app):
    expect(app.page.get_by_text("Your pie is empty")).to_be_visible()
    expect(app.page.get_by_role("button", name="Run backtest")).to_have_count(0)  # results update by themselves
    expect(app.page.get_by_role("button", name="Download pie (.json)")).to_be_disabled()


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_example_loads_settings_and_backtests(app, name):
    ex = EXAMPLES[name]
    app.load_example(name)

    assert app.tickers() == [a["ticker"] for a in ex["assets"]]
    expect(app.page.get_by_role("combobox", name="Pie currency")).to_have_value(ex["currency"])
    expect(app.page.get_by_role("combobox", name="Rebalance to target")).to_have_value(ex["rebalance"])
    expect(app.page.get_by_role("spinbutton", name=f"Monthly deposit ({ex['currency']})")) \
        .to_have_value(f"{ex['monthly']:.2f}")

    assert not [a for a in app.alerts() if "failed" in a.lower() or "couldn't" in a.lower()], app.alerts()
    metrics = app.metrics()
    assert set(metrics) == {f"Value ({ex['currency']})", f"Invested ({ex['currency']})", "Return (time-weighted)",
                            "Yearly return (CAGR)", "Max drawdown"}
    assert float(metrics[f"Invested ({ex['currency']})"].replace(",", "")) > ex["initial"]  # monthly deposits
    for tab in ("By asset", "Drawdown", "Holdings", "Value"):
        app.page.get_by_role("tab", name=tab).click()
    expect(app.page.get_by_test_id("stPlotlyChart").first).to_be_visible()


def test_us_stocks_keep_their_us_listing(app):
    app.load_example("Tech Leaders")
    # AAPL and MSFT are real listings, so they're confirmed silently and the backtest runs
    assert app.tickers() == ["QDVE.DE", "AAPL", "MSFT"]
    assert app.metrics()
    expect(app.page.get_by_text("have no exchange suffix")).to_have_count(0)


def test_ticker_that_would_change_needs_fix_tickers(app):
    app.page.get_by_text("Add a ticker directly").click()
    app.page.get_by_label("Yahoo ticker").fill("vwra")
    app.click("Add", exact=True)
    expect(app.page.get_by_text("have no exchange suffix")).to_be_visible()
    assert not app.metrics()  # no silent swap to another listing
    app.click("Fix tickers")
    assert app.tickers() == ["VWRA.L"]
    assert app.metrics()


def test_weight_column_is_visible_and_editable(app):
    app.load_example("60/40 Stocks & Bonds")
    # long ETF names used to push the weights out of view
    assert app.rows()
    headers = app.grid.locator("thead [role=columnheader]").all_text_contents()
    assert headers[:2] == ["Ticker", "Weight %"]

    app.edit_weight(0, 70)
    assert float(app.rows()[0][1]) == 70
    expect(app.page.get_by_text("Weights add up to 110.00%")).to_be_visible()
    assert not app.metrics()

    app.click("Split evenly")
    assert [float(r[1]) for r in app.rows()] == [50, 50]
    assert app.metrics()  # back to 100%: results appear by themselves


def test_add_asset_by_search_and_directly(app):
    app.page.get_by_label("Search by name, ticker or ISIN").fill("IE00BK5BQT80")
    app.page.keyboard.press("Enter")
    app.wait()
    app.click("Add to pie")
    assert len(app.rows()) == 1

    app.page.get_by_text("Add a ticker directly").click()
    app.page.get_by_label("Yahoo ticker").fill("eimi.l")
    app.click("Add", exact=True)
    assert app.tickers()[-1] == "EIMI.L"
    assert [float(r[1]) for r in app.rows()] == [50, 50]

    app.click("Clear pie")
    expect(app.page.get_by_text("Your pie is empty")).to_be_visible()


def test_save_load_delete(app):
    app.load_example("Three-Fund Portfolio")
    app.sidebar.get_by_label("Pie name").fill("E2E save test")
    app.page.keyboard.press("Enter")
    app.wait()
    app.click("Save pie to account/storage", root=app.sidebar)
    expect(app.page.get_by_text("Saved pie 'E2E save test'.")).to_be_visible()

    app.click("Clear pie")
    app.choose("Saved pies", "E2E save test (3 assets)")
    app.click("Load saved pie", root=app.sidebar)
    assert app.tickers() == [a["ticker"] for a in EXAMPLES["Three-Fund Portfolio"]["assets"]]
    expect(app.sidebar.get_by_label("Pie name")).to_have_value("E2E save test")

    app.click("Delete pie", root=app.sidebar)
    expect(app.page.get_by_text("Deleted pie 'E2E save test'.")).to_be_visible()
    expect(app.page.get_by_role("option", name="E2E save test (3 assets)")).to_have_count(0)


def test_export_then_import(app, tmp_path):
    app.load_example("All-World ETF")
    app.set_number("Initial investment (EUR)", 2500)
    with app.page.expect_download() as dl:
        app.sidebar.get_by_role("button", name="Download pie (.json)").click()
    exported = json.loads(open(dl.value.path()).read())
    assert exported["name"] == "All-World ETF"
    assert exported["initial"] == 2500.0 and exported["monthly"] == 100.0

    path = tmp_path / "pie.json"
    path.write_text(json.dumps(dict(exported, name="Imported", initial=777.0)))
    app.click("Clear pie")
    app.sidebar.locator("input[type=file]").set_input_files(path)
    app.wait()
    app.click("Load this pie", root=app.sidebar)
    assert app.tickers() == ["VWCE.DE"]
    expect(app.page.get_by_role("spinbutton", name="Initial investment (EUR)")).to_have_value("777.00")
    expect(app.sidebar.get_by_label("Pie name")).to_have_value("Imported")


def test_share_link_restores_pie_and_settings(app):
    app.load_example("Tech Leaders")
    app.set_number("Initial investment (USD)", 4321)
    link = app.sidebar.get_by_test_id("stCode").inner_text().strip()
    assert link.startswith(app.url) and "?pie=" in link

    app.page.goto(link)
    app.wait()
    assert app.tickers() == ["QDVE.DE", "AAPL", "MSFT"]
    expect(app.page.get_by_role("combobox", name="Pie currency")).to_have_value("USD")
    expect(app.page.get_by_role("spinbutton", name="Initial investment (USD)")).to_have_value("4321.00")


def test_broken_share_link_says_so(app):
    app.open("?pie=not-a-real-pie")
    expect(app.page.get_by_text("This share link is invalid or damaged")).to_be_visible()
    expect(app.page.get_by_text("Your pie is empty")).to_be_visible()


def test_dates_before_2010_are_allowed(app):
    app.set_date("Start date", "2005-03-01")
    field = app.page.get_by_role("group", name="Start date")
    expect(field).not_to_have_attribute("aria-invalid", "true")
    app.load_example("Tech Leaders")  # loading an example sets its own start date
    app.set_date("Start date", "2005-03-01")
    app.page.get_by_text("Hold a not-yet-listed").click()
    app.wait()
    assert app.metrics(), app.alerts()
    expect(app.page.get_by_role("heading", name="2005-03-01 to")).to_be_visible()


def test_results_wait_for_valid_settings(app):
    app.load_example("All-World ETF")
    app.set_number("Initial investment (EUR)", 0)
    app.set_number("Monthly deposit (EUR)", 0)
    expect(app.page.get_by_text("Set an initial investment or a monthly deposit.")).to_be_visible()
    assert not app.metrics()

    app.set_number("Monthly deposit (EUR)", 100)
    app.set_date("Start date", "2026-01-01")
    app.set_date("End date", "2025-01-01")
    expect(app.page.get_by_text("The start date must be before the end date.")).to_be_visible()
    assert not app.metrics()

    # examples have no end date, which means "up to date"
    app.load_example("All-World ETF")
    expect(app.page.get_by_text("The start date must be before the end date.")).to_have_count(0)
    assert app.metrics()


def test_guest_account_without_google_config(app):
    expect(app.sidebar.get_by_role("button", name="Sign in with Google")).to_have_count(0)
    app.click("Use Local Guest Account", root=app.sidebar)
    expect(app.sidebar.get_by_text("Logged in as Local Guest")).to_be_visible()
    app.click("Log out", root=app.sidebar)
    expect(app.sidebar.get_by_role("button", name="Use Local Guest Account")).to_be_visible()
