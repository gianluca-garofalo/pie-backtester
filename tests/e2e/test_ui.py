import json
import re
import urllib.parse

import pytest
from playwright.sync_api import expect

from storage import list_examples

EXAMPLES = {ex["name"]: ex for ex in list_examples()}
TILES = {"Value now", "You put in", "Return", "Per year", "Worst fall"}


def test_empty_page(app):
    expect(app.page.get_by_text("Start from an example")).to_have_count(0)  # examples live in the header menu
    expect(app.page.get_by_text("Your pie is empty. Pick one from Examples at the top")).to_be_visible()
    expect(app.page.get_by_role("button", name="Run backtest")).to_have_count(0)  # results update by themselves
    expect(app.page.get_by_role("button", name="Save", exact=True)).to_be_disabled()


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_example_loads_settings_and_backtests(app, name):
    ex = EXAMPLES[name]
    app.load_example(name)

    assert app.tickers() == [a["ticker"] for a in ex["assets"]]
    expect(app.page.get_by_role("combobox", name="Currency")).to_have_value(ex["currency"])
    expect(app.page.get_by_role("radiogroup", name="Rebalance to target").get_by_role("radio", checked=True)).to_have_text(
        {"Never": "Never", "Monthly": "Month", "Quarterly": "Quarter", "Yearly": "Year"}[ex["rebalance"]])
    expect(app.page.get_by_role("spinbutton", name="Monthly")).to_have_value(f"{ex['monthly']:.0f}")
    expect(app.page.get_by_text(f"/month · {ex['start'][:7]}")).to_be_visible()  # the settings summary line

    assert not [a for a in app.alerts() if "failed" in a.lower() or "couldn't" in a.lower()], app.alerts()
    metrics = app.metrics()
    assert set(metrics) == TILES
    assert app.amount(metrics["You put in"]) > ex["initial"]  # monthly deposits
    for tab in ("By asset", "Holdings", "Growth"):
        app.page.get_by_role("tab", name=tab).click()
    expect(app.page.get_by_test_id("stPlotlyChart").first).to_be_visible()


def test_us_stocks_keep_their_us_listing(app):
    app.load_example("Tech Leaders")
    # AAPL and MSFT are real listings, so they're confirmed silently and the backtest runs
    assert app.tickers() == ["QDVE.DE", "AAPL", "MSFT"]
    assert app.metrics()
    expect(app.page.get_by_text("have no exchange suffix")).to_have_count(0)


def test_ticker_that_would_change_needs_fix_tickers(app):
    # tickers can't be typed in any more; bare ones still arrive from files and links
    app.open("?p=Imported~EUR~2020-01-01~~1000~100~N~w~VWRA:100")
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
    expect(app.page.get_by_text("Total 110.00% · 10.00% too much")).to_be_visible()
    expect(app.page.get_by_text("The results appear here once")).to_be_visible()
    assert not app.metrics()

    app.click("Split evenly")
    assert [float(r[1]) for r in app.rows()] == [50, 50]
    expect(app.page.get_by_text("Total 100% ✓")).to_be_visible()
    assert app.metrics()  # back to 100%: results appear by themselves


def test_scale_to_100_keeps_the_proportions(app):
    app.load_example("60/40 Stocks & Bonds")
    app.edit_weight(0, 30)  # 30 + 40 = 70%
    expect(app.page.get_by_text("Total 70.00% · 30.00% left")).to_be_visible()
    app.click("Scale to 100%")
    expect(app.page.get_by_text("Scaled the weights from 70.00% to 100%.")).to_be_visible()
    assert [float(r[1]) for r in app.rows()] == pytest.approx([42.86, 57.14])
    assert app.metrics()


def test_add_assets_by_search(app):
    for query in ("IE00BK5BQT80", "EIMI.L"):  # an ISIN, then a ticker
        app.page.get_by_label("Search by name, ticker or ISIN").fill(query)
        app.page.keyboard.press("Enter")
        app.wait()
        app.click("Add to pie")
    assert len(app.rows()) == 2  # no empty "add row" line: assets only come from search
    expect(app.page.get_by_label("Search by name, ticker or ISIN")).to_have_value("")  # cleared after adding
    expect(app.page.get_by_role("button", name="Add to pie")).to_have_count(0)
    # the ISIN's first result is its euro listing (the pie is in EUR), not the London USD line
    assert app.tickers() == ["VWCE.DE", "EIMI.L"]
    assert [float(r[1]) for r in app.rows()] == [100, 0]  # the second gets what's left: nothing

    app.click("Clear pie")
    expect(app.page.get_by_text("Your pie is empty")).to_be_visible()


def test_an_added_asset_gets_the_rest_and_keeps_the_others(app):
    app.load_example("60/40 Stocks & Bonds")
    app.edit_weight(0, 50)  # 50 + 40 = 90%
    app.page.get_by_label("Search by name, ticker or ISIN").fill("EIMI.L")
    app.page.keyboard.press("Enter")
    app.wait()
    app.click("Add to pie")
    assert [float(r[1]) for r in app.rows()] == [50, 40, 10]
    expect(app.page.get_by_text("Total 100% ✓")).to_be_visible()


def test_save_load_delete(app):
    app.load_example("Three-Fund Portfolio")
    app.save_pie("E2E save test")
    expect(app.page.get_by_text("Saved pie 'E2E save test'.")).to_be_visible()
    assert app.chips() == ["E2E save test (editing)"]

    app.click("Clear pie")
    app.open_sidebar_section("Saved pies")
    app.choose("Saved pies", "E2E save test (3 assets)")  # picking it opens it
    assert app.tickers() == [a["ticker"] for a in EXAMPLES["Three-Fund Portfolio"]["assets"]]
    assert app.chips() == ["E2E save test (editing)"]

    app.click("Edit", root=app.sidebar, exact=True)
    dialog = app.page.get_by_role("dialog")
    dialog.get_by_label("Name").fill("E2E renamed")
    dialog.get_by_text("Public").click()
    dialog.get_by_role("button", name="Save changes").click()
    app.wait()
    expect(app.page.get_by_text("Updated 'E2E renamed' (public).")).to_be_visible()
    assert app.chips() == ["E2E renamed (editing)"]  # the open pie follows the new name

    app.click("Delete", root=app.sidebar, exact=True)
    expect(app.page.get_by_text("Deleted pie 'E2E renamed'.")).to_be_visible()
    expect(app.page.get_by_role("option", name="E2E renamed (3 assets)")).to_have_count(0)


def test_export_then_import(app, tmp_path):
    app.load_example("All-World ETF")
    app.set_number("Initial", 2500)
    app.open_sidebar_section("Import / export JSON")
    with app.page.expect_download() as dl:
        app.sidebar.get_by_role("button", name="Download pie (.json)").click()
    exported = json.loads(open(dl.value.path()).read())
    assert exported["name"] == "All-World ETF"
    assert exported["initial"] == 2500.0 and exported["monthly"] == 100.0

    path = tmp_path / "pie.json"
    path.write_text(json.dumps(dict(exported, name="Imported", initial=777.0)))
    app.click("Clear pie")
    app.sidebar.locator("input[type=file]").set_input_files(path)  # opens without another click
    app.wait()
    assert app.tickers() == ["VWCE.DE"]
    expect(app.page.get_by_role("spinbutton", name="Initial")).to_have_value("777")
    assert app.chips() == ["Imported (editing)"]


def test_share_link_restores_pie_and_settings(app):
    app.load_example("Tech Leaders")
    app.set_number("Initial", 4321)
    app.page.get_by_role("button", name="Share").click()
    link = app.page.get_by_test_id("stPopoverBody").get_by_test_id("stCode").inner_text().strip()
    assert link.startswith(app.url)
    app.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    app.page.get_by_test_id("stPopoverBody").frame_locator("iframe").locator("#b").click()  # Copy link
    assert app.page.evaluate("navigator.clipboard.readText()") == link
    assert link.split("?", 1)[1] == "p=Tech+Leaders~USD~2020-01-01~~4321~100~Q~w~QDVE.DE:50,AAPL:25,MSFT:25"

    app.page.goto(link)
    app.wait()
    assert app.tickers() == ["QDVE.DE", "AAPL", "MSFT"]
    assert app.rows()[1][2] == "Apple Inc."  # names left out of the link are looked up again
    expect(app.page.get_by_role("combobox", name="Currency")).to_have_value("USD")
    expect(app.page.get_by_role("spinbutton", name="Initial")).to_have_value("4321")


def test_older_long_share_links_still_open(app):
    import sharing
    app.open("?pie=" + sharing.encode_pie_to_query_param(EXAMPLES["60/40 Stocks & Bonds"]))
    assert app.tickers() == [a["ticker"] for a in EXAMPLES["60/40 Stocks & Bonds"]["assets"]]


def test_broken_share_link_says_so(app):
    app.open("?pie=not-a-real-pie")
    expect(app.page.get_by_text("This share link is invalid or damaged")).to_be_visible()
    expect(app.page.get_by_text("Your pie is empty")).to_be_visible()


def test_dates_before_2010_are_allowed(app):
    app.set_date("From", "2005-03-01")
    field = app.page.get_by_role("group", name="From")
    expect(field).not_to_have_attribute("aria-invalid", "true")
    app.load_example("Tech Leaders")  # loading an example sets its own start date
    app.set_date("From", "2005-03-01")
    # QDVE.DE lists in 2015, so the pie would start then; one click keeps the full period
    expect(app.page.get_by_text("This pie starts on 2015-12-03")).to_be_visible()
    app.click("Hold cash until they list")
    assert app.metrics(), app.alerts()
    expect(app.page.get_by_text("held as cash until their first price")).to_be_visible()
    expect(app.page.get_by_text("2005-03 to")).to_be_visible()


def test_results_wait_for_valid_settings(app):
    app.load_example("All-World ETF")
    app.set_number("Initial", 0)
    app.set_number("Monthly", 0)
    expect(app.page.get_by_text("Set an initial investment or a monthly deposit.")).to_be_visible()
    assert not app.metrics()

    app.set_number("Monthly", 100)
    app.set_date("From", "2026-01-01")
    app.set_date("To", "2025-01-01")
    expect(app.page.get_by_text("The start date must be before the end date.")).to_be_visible()
    assert not app.metrics()

    # examples have no end date, which means "up to date"
    app.load_example("All-World ETF")
    expect(app.page.get_by_text("The start date must be before the end date.")).to_have_count(0)
    assert app.metrics()


def test_growth_chart_controls(app):
    app.load_example("All-World ETF")
    for option in ("Log", "1Y"):  # segmented controls are radio buttons
        app.page.get_by_role("radio", name=option, exact=True).click()
        app.wait()
    assert app.metrics()
    expect(app.page.get_by_test_id("stPlotlyChart").first).to_be_visible()


def test_guest_account_without_google_config(app):
    expect(app.sidebar.get_by_role("button", name="Sign in with Google")).to_have_count(0)
    app.click("Use guest account", root=app.sidebar)
    expect(app.sidebar.get_by_text("Local Guest ·")).to_be_visible()
    app.click("Log out", root=app.sidebar)
    expect(app.sidebar.get_by_role("button", name="Use guest account")).to_be_visible()


def test_consecutive_weight_edits_all_stick(app):
    # each edit used to change the table's input, so the next edit was dropped once
    app.load_example("60/40 Stocks & Bonds")
    app.edit_weight(0, 70)
    app.edit_weight(1, 30)
    assert [float(r[1]) for r in app.rows()] == [70, 30]
    assert app.metrics()


def test_how_its_calculated_tab(app):
    app.load_example("All-World ETF")
    app.page.get_by_role("tab", name="How it's calculated").click()
    panel = app.page.get_by_role("tabpanel", name="How it's calculated")
    expect(panel.get_by_text("Return", exact=True)).to_be_visible()
    expect(panel.locator(".katex").first).to_be_visible()  # the formulas render as maths, not as $…$


def test_standard_actions_have_icons_and_words(app):
    app.load_example("All-World ETF")
    for name in ("Examples", "Save", "Share"):
        button = app.page.get_by_role("button", name=name, exact=True)
        expect(button).to_be_visible()  # the word is the accessible name
        expect(button.get_by_test_id("stIconMaterial").first).to_be_visible()  # popovers add an arrow icon after it


def test_amounts_keep_their_cents(app):
    app.load_example("All-World ETF")
    app.set_number("Monthly", 10.12)
    expect(app.page.get_by_role("spinbutton", name="Monthly")).to_have_value("10.12")
    app.set_number("Monthly", 200)
    expect(app.page.get_by_role("spinbutton", name="Monthly")).to_have_value("200")  # no ".00" on whole amounts


def test_a_broken_file_says_why(app, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"assets": []}')
    app.open_sidebar_section("Import / export JSON")
    app.sidebar.locator("input[type=file]").set_input_files(path)
    app.wait()
    expect(app.sidebar.get_by_text("Could not load this file: Pie must contain at least one asset")).to_be_visible()
    expect(app.page.get_by_text("Your pie is empty")).to_be_visible()


def test_saving_under_the_same_name_updates_the_pie(app):
    app.load_example("60/40 Stocks & Bonds")
    app.save_pie("E2E update test")
    app.edit_weight(0, 70)
    app.edit_weight(1, 30)
    app.save_pie("E2E update test")
    expect(app.page.get_by_text("Updated pie 'E2E update test'.")).to_be_visible()
    app.open_sidebar_section("Saved pies")
    expect(app.sidebar.get_by_text("Saved pies (1)")).to_be_visible()  # updated, not copied

    app.click("Clear pie")
    app.choose("Saved pies", "E2E update test (2 assets)")
    assert [float(r[1]) for r in app.rows()] == [70, 30]
    app.click("Delete", root=app.sidebar, exact=True)


def test_click_a_column_name_to_sort(app):
    app.load_example("Three-Fund Portfolio")  # SWRD.L, EIMI.L, EUNA.DE
    box = app.grid.bounding_box()
    app.page.mouse.click(box["x"] + 70, box["y"] + 17)  # the Ticker header
    app.eventually(app.tickers, ["EIMI.L", "EUNA.DE", "SWRD.L"])


def test_a_file_with_text_for_an_amount_says_why(app, tmp_path):
    path = tmp_path / "lots.json"
    path.write_text(json.dumps({"name": "x", "initial": "lots", "assets": [{"ticker": "AAPL", "weight": 100}]}))
    app.open_sidebar_section("Import / export JSON")
    app.sidebar.locator("input[type=file]").set_input_files(path)
    app.wait()
    expect(app.sidebar.get_by_text("Could not load this file: 'initial' must be a number")).to_be_visible()
    expect(app.page.get_by_test_id("stException")).to_have_count(0)  # no raw traceback


def test_share_carries_the_latest_edit(app):
    # the link used to be built before the table applied the edit, so it lagged one edit behind
    app.load_example("60/40 Stocks & Bonds")
    app.edit_weight(0, 70)
    app.page.get_by_role("button", name="Share").click()
    body = app.page.get_by_test_id("stPopoverBody")
    expect(body.get_by_text("Can't share this pie yet: weights must sum to 100% (got 110.00%).")).to_be_visible()
    app.page.keyboard.press("Escape")
    app.edit_weight(1, 30)
    app.page.get_by_role("button", name="Share").click()
    link = app.page.get_by_test_id("stPopoverBody").get_by_test_id("stCode").inner_text().strip()
    assert link.endswith("VWCE.DE:70,EUNA.DE:30")


def test_weights_keep_two_decimals(app):
    app.load_example("60/40 Stocks & Bonds")
    app.edit_weight(0, 39.99)
    assert float(app.rows()[0][1]) == 39.99  # used to become 39.9
    expect(app.page.get_by_text("Total 79.99% · 20.01% left")).to_be_visible()


def test_a_crafted_name_shows_as_typed(app):
    # pie names come from links and files: no bold, links or maths in someone else's name
    name = "**Bold** [x](http://evil.example) $a$ ~b~"
    app.open("?p=" + urllib.parse.quote_plus(name + "~EUR~2020-01-01~~1000~100~N~w~VWCE.DE:100", safe="~:,.-"))
    chip = app.page.locator(".st-key-chip_name_own")
    expect(chip).to_contain_text(name)
    assert chip.locator("strong, a, .katex").count() == 0


def test_rename_cannot_take_another_pies_name(app):
    app.load_example("All-World ETF")
    app.save_pie("E2E dup A")
    app.load_example("Tech Leaders")
    app.save_pie("E2E dup B")
    app.open_sidebar_section("Saved pies")
    app.choose("Saved pies", "E2E dup B (3 assets)")
    app.click("Edit", root=app.sidebar, exact=True)
    dialog = app.page.get_by_role("dialog")
    dialog.get_by_label("Name").fill("e2e  DUP a")  # same name to a person: case and spaces differ
    dialog.get_by_label("Name").press("Enter")
    app.wait()
    expect(dialog.get_by_text("You already have a pie called 'E2E dup A'. Pick another name.")).to_be_visible()
    expect(dialog.get_by_role("button", name="Save changes")).to_be_disabled()
    app.page.keyboard.press("Escape")
    app.click("Delete", root=app.sidebar, exact=True)  # tidy up: B is still picked
    app.open_sidebar_section("Saved pies")
    app.choose("Saved pies", "E2E dup A (1 asset)")
    app.click("Delete", root=app.sidebar, exact=True)


def test_adding_an_asset_twice_says_so(app):
    app.load_example("Tech Leaders")
    app.page.get_by_label("Search by name, ticker or ISIN").fill("AAPL")
    app.page.keyboard.press("Enter")
    app.wait()
    app.click("Add to pie")
    expect(app.page.get_by_text("AAPL is already in the pie.")).to_be_visible()
    assert app.tickers() == ["QDVE.DE", "AAPL", "MSFT"]


def test_value_now_shows_the_gain_on_money_put_in(app):
    app.load_example("All-World ETF")
    tile = app.page.get_by_test_id("stMetric").filter(has_text="Value now")
    expect(tile).to_contain_text(re.compile(r"gain \([+−-]\d+%\)"))  # the gain on money put in
    expect(app.page.get_by_test_id("stMetric").filter(has_text="Return")).to_contain_text("the pie's own growth")


def test_a_us_listing_picked_from_search_is_kept(app):
    # a euro pie used to flag NASDAQ's ASML as "no exchange suffix" and swap it for ASML.AS
    app.page.get_by_label("Search by name, ticker or ISIN").fill("ASML")
    app.page.keyboard.press("Enter")
    app.wait()
    app.click("Add to pie")  # the first result: ASML on NASDAQ
    assert app.tickers() == ["ASML"]
    expect(app.page.get_by_text("have no exchange suffix")).to_have_count(0)
    assert app.metrics()  # results show without "Fix tickers"
