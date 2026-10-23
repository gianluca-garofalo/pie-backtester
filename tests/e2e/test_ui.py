import json
from datetime import date
import re
import urllib.parse

import pytest
from playwright.sync_api import expect

from conftest import App
from storage import list_examples

EXAMPLES = {ex["name"]: ex for ex in list_examples()}
ROWS = {"Value now", "Return", "Per year", "Worst fall"}


def test_empty_page(app):
    expect(app.page.get_by_text("Start from an example")).to_have_count(0)  # examples live in the header menu
    expect(app.page.get_by_text("No pies yet. Pick one from Examples at the top, or start a new pie.")).to_be_visible()
    expect(app.page.get_by_role("button", name="New pie")).to_be_visible()
    expect(app.page.get_by_role("button", name="Run backtest")).to_have_count(0)  # results update by themselves
    expect(app.page.locator(".st-key-save_open button").first).to_be_disabled()


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_example_loads_settings_and_backtests(app, name):
    ex = EXAMPLES[name]
    app.load_example(name)

    assert app.tickers() == [a["ticker"] for a in ex["assets"]]
    # the plan bar reads the settings back
    expect(app.plan).to_contain_text(f"{ex['currency']} · rebalance {ex['rebalance'].lower()}")
    expect(app.plan).to_contain_text(f"{ex['monthly']:,.0f} every month")
    assert date_of(app, "From") == date.fromisoformat(ex["start"])

    assert not [a for a in app.alerts() if "failed" in a.lower() or "couldn't" in a.lower()], app.alerts()
    metrics = app.metrics()
    assert set(metrics) == ROWS
    put_in = re.search(r"on (\S+) put in", app.page.locator(".st-key-result_own").inner_text()).group(1)
    assert app.amount(put_in) > ex["initial"]  # monthly deposits
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
    assert not app.metrics()  # no silent swap to another listing
    expect(app.page.locator(".st-key-result_own")).to_contain_text("every ticker is found")
    editor = app.open_editor()
    expect(editor.get_by_text("have no exchange suffix")).to_be_visible()
    app.click("Fix tickers", root=editor)
    assert app.tickers() == ["VWRA.L"]
    app.apply()
    assert app.metrics()


def test_weight_column_is_visible_and_editable(app):
    app.load_example("60/40 Stocks & Bonds")
    app.open_editor()
    # long ETF names used to push the weights out of view
    assert app.rows()
    headers = app.grid.locator("thead [role=columnheader]").all_text_contents()
    assert headers[:3] == ["Ticker", "Weight %", "Lock"]

    app.edit_weight(0, 70, apply=False)
    assert float(app.rows()[0][1]) == 70
    editor = app.editor
    expect(editor.get_by_text("Total 110.00% · 10.00% too much")).to_be_visible()
    app.click("Split evenly", root=editor)
    assert [float(r[1]) for r in app.rows()] == [50, 50]
    expect(editor.get_by_text("Total 100% ✓")).to_be_visible()
    app.apply()
    assert app.metrics()  # back to 100%: results appear by themselves


def test_scale_to_100_keeps_the_proportions(app):
    app.load_example("60/40 Stocks & Bonds")
    app.edit_weight(0, 30, apply=False)  # 30 + 40 = 70%
    expect(app.editor.get_by_text("Total 70.00% · 30.00% left")).to_be_visible()
    app.click("Scale to 100%", root=app.editor)
    assert [float(r[1]) for r in app.rows()] == pytest.approx([42.86, 57.14])
    app.apply()
    assert app.metrics()


def test_add_assets_by_search(app):
    for query in ("IE00BK5BQT80", "EIMI.L"):  # an ISIN, then a ticker; the first opens a new pie
        app.search_add(query)
    assert len(app.rows()) == 2  # no empty "add row" line: assets only come from search
    # the search stays (clearing it during the rerun could wipe the next query); the button confirms instead
    expect(app.editor.get_by_role("button", name="Added ✓")).to_be_disabled()
    # the ISIN's first result is its euro listing (the pie is in EUR), not the London USD line
    assert app.tickers() == ["VWCE.DE", "EIMI.L"]
    assert [float(r[1]) for r in app.rows()] == [100, 0]  # the second gets what's left: nothing
    app.apply()
    assert app.cards() == ["My Pie"]

    app.remove_pie("My Pie")
    expect(app.page.get_by_text("No pies yet.")).to_be_visible()


def test_an_added_asset_gets_the_rest_and_keeps_the_others(app):
    app.load_example("60/40 Stocks & Bonds")
    app.edit_weight(0, 50, apply=False)  # 50 + 40 = 90%
    app.search_add("EIMI.L")
    assert [float(r[1]) for r in app.rows()] == [50, 40, 10]
    expect(app.editor.get_by_text("Total 100% ✓")).to_be_visible()


def test_save_load_delete(app):
    app.load_example("Three-Fund Portfolio")
    app.save_pie("E2E save test")
    expect(app.page.get_by_text("Saved pie 'E2E save test'.")).to_be_visible()
    assert app.cards() == ["E2E save test"]

    app.remove_pie("E2E save test")
    app.open_saved("E2E save test")  # picking it opens it
    assert app.tickers() == [a["ticker"] for a in EXAMPLES["Three-Fund Portfolio"]["assets"]]
    assert app.cards() == ["E2E save test"]

    dialog = app.edit_saved("E2E save test")
    dialog.get_by_label("Pie name").fill("E2E renamed")
    dialog.get_by_text("Make public").click()
    dialog.get_by_role("button", name="Save changes").click()
    app.wait()
    expect(app.page.get_by_text("Updated 'E2E renamed' (public).")).to_be_visible()
    assert app.cards() == ["E2E renamed"]  # the open pie follows the new name

    app.delete_saved("E2E renamed")
    expect(app.page.get_by_text("Deleted 'E2E renamed'.")).to_be_visible()
    expect(app.open_my_pies().get_by_role("button", name="E2E renamed", exact=True)).to_have_count(0)


def test_export_then_import(app, tmp_path):
    app.load_example("All-World ETF")
    app.set_plan(initial=2500)
    exported = json.loads(open(app.download()).read())
    assert exported["name"] == "All-World ETF"
    assert exported["initial"] == 2500.0 and exported["monthly"] == 100.0

    path = tmp_path / "pie.json"
    path.write_text(json.dumps(dict(exported, name="Imported", initial=777.0)))
    app.remove_pie("All-World ETF")
    app.upload(path)  # opens without another click
    assert app.tickers() == ["VWCE.DE"]
    expect(app.plan).to_contain_text("777 to start")
    assert app.cards() == ["Imported"]


def test_share_link_restores_pie_and_settings(app):
    app.load_example("Tech Leaders")
    app.set_plan(initial=4321)
    app.page.get_by_role("button", name="Share").click()
    link = app.page.get_by_test_id("stPopoverBody").get_by_test_id("stCode").inner_text().strip()
    assert link.startswith(app.url)
    expect(app.page.get_by_test_id("stPopoverBody").locator("iframe")).to_have_count(0)  # copy on hover here
    assert link.split("?", 1)[1] == "p=Tech+Leaders~USD~2020-01-01~~4321~100~Q~w~QDVE.DE:50,AAPL:25,MSFT:25"

    app.page.goto(link)
    app.wait()
    assert app.tickers() == ["QDVE.DE", "AAPL", "MSFT"]
    assert app.rows()[1][3] == "Apple Inc."  # names left out of the link are looked up again
    expect(app.plan).to_contain_text("$4,321 to start")
    expect(app.plan).to_contain_text("USD")


def test_older_long_share_links_still_open(app):
    import sharing
    app.open("?pie=" + sharing.encode_pie_to_query_param(EXAMPLES["60/40 Stocks & Bonds"]))
    assert app.tickers() == [a["ticker"] for a in EXAMPLES["60/40 Stocks & Bonds"]["assets"]]


def test_broken_share_link_says_so(app):
    app.open("?pie=not-a-real-pie")
    expect(app.page.get_by_text("This share link can't be opened: it's damaged.")).to_be_visible()
    expect(app.page.get_by_text("No pies yet.")).to_be_visible()


def test_dates_before_2010_are_allowed(app):
    app.set_date("From", "2005-03-01")
    field = app.page.get_by_role("group", name="From")
    expect(field).not_to_have_attribute("aria-invalid", "true")
    app.load_example("Tech Leaders")  # loading an example sets its own start date
    app.set_date("From", "2005-03-01")
    # QDVE.DE lists in 2015, so the pie would start then; or it holds that slice as cash from 2005
    expect(app.page.get_by_role("radio", name="Start on 3 Dec 2015")).to_be_checked()
    app.page.get_by_role("radiogroup", name="When the pies start").get_by_text(
        "Start on 1 Mar 2005, holding cash until QDVE.DE lists").click()
    app.wait()
    assert app.metrics(), app.alerts()
    expect(app.page.get_by_text("Every number and chart below covers 1 Mar 2005 – ")).to_be_visible()


def test_results_wait_for_valid_settings(app):
    app.load_example("All-World ETF")
    dialog = app.set_plan(initial=0, monthly=0, apply=False)  # nothing to invest can't be applied
    expect(dialog.get_by_text("Set an initial investment or a monthly deposit.")).to_be_visible()
    expect(dialog.get_by_role("button", name="Apply")).to_be_disabled()
    app.page.keyboard.press("Escape")
    expect(app.page.get_by_test_id("stDialog")).to_have_count(0)
    expect(app.plan).to_contain_text("€1,000 to start")  # unchanged

    app.set_date("From", "2026-01-01")
    app.set_date("To", "2025-01-01")
    expect(app.page.get_by_text("The start date must be before the end date.")).to_be_visible()
    assert not app.metrics()

    # examples have no end date, which means "up to date"
    app.load_example("All-World ETF")
    expect(app.page.get_by_text("The start date must be before the end date.")).to_have_count(0)
    assert app.metrics()


def period(app):
    return app.page.locator(".st-key-period_pick")


def date_of(app, label):
    parts = [app.page.get_by_role("spinbutton", name=f"{p}, {label}").get_attribute("aria-valuenow")
             for p in ("year", "month", "day")]
    return date(*map(int, parts))


def test_period_presets_set_the_dates(app):
    before = date_of(app, "From")
    period(app).get_by_role("radio", name="Max", exact=True).click()  # no pie yet: nothing to go back to
    app.wait()
    assert date_of(app, "From") == before
    period(app).get_by_role("radio", name="1Y", exact=True).click()
    app.wait()
    today = date.today()
    assert date_of(app, "From") == (today.replace(year=today.year - 1) if (today.month, today.day) != (2, 29)
                                    else date(today.year - 1, 2, 28))
    assert date_of(app, "To") == today
    app.set_date("From", "2019-05-06")  # a date typed by hand makes the period Custom
    expect(period(app).get_by_role("radio", name="Custom", exact=True)).to_be_checked()
    assert date_of(app, "From") == date(2019, 5, 6)


def test_growth_chart_controls(app):
    app.load_example("All-World ETF")
    tabs = app.page.get_by_test_id("stTabs")
    expect(tabs.get_by_role("radio", name="1Y", exact=True)).to_have_count(0)  # time is set only by the Period
    tabs.get_by_role("radio", name="Log", exact=True).click()  # segmented controls are radio buttons
    app.wait()
    expect(tabs.get_by_text("Double-click to zoom back out. Zooming changes no numbers")).to_be_visible()
    expect(app.page.get_by_role("button", name="Reset zoom")).to_have_count(0)  # double-click does it
    assert app.metrics()
    expect(app.page.get_by_test_id("stPlotlyChart").first).to_be_visible()


def test_guest_account_without_google_config(app):
    account = app.page.locator(".st-key-account")
    expect(account.get_by_role("button", name="Sign in with Google")).to_have_count(0)
    app.click("Use guest account", root=account)
    expect(account.get_by_text("Local Guest ·")).to_be_visible()
    app.click("Log out", root=account)
    expect(account.get_by_role("button", name="Use guest account")).to_be_visible()


def test_consecutive_weight_edits_all_stick(app):
    # each edit used to change the table's input, so the next edit was dropped once
    app.load_example("60/40 Stocks & Bonds")
    app.edit_weight(0, 70, apply=False)
    app.edit_weight(1, 30, apply=False)
    assert [float(r[1]) for r in app.rows()] == [70, 30]
    app.apply()
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
        button = app.page.get_by_role("button", name=name, exact=True).first  # the header's (cards have a Save too)
        expect(button).to_be_visible()  # the word is the accessible name
        expect(button.get_by_test_id("stIconMaterial").first).to_be_visible()  # popovers add an arrow icon after it


def test_amounts_keep_their_cents(app):
    app.load_example("All-World ETF")
    app.set_plan(monthly=10.12)
    expect(app.plan).to_contain_text("€10.12 every month")
    expect(app.open_plan().get_by_role("spinbutton", name="Monthly")).to_have_value("10.12")
    app.page.keyboard.press("Escape")
    app.set_plan(monthly=200)
    expect(app.plan).to_contain_text("€200 every month")  # no ".00" on whole amounts
    expect(app.open_plan().get_by_role("spinbutton", name="Monthly")).to_have_value("200")
    app.page.keyboard.press("Escape")


def test_a_broken_file_says_why(app, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"assets": []}')
    app.upload(path)
    expect(app.page.get_by_text("Could not load this file: Pie must contain at least one asset")).to_be_visible()
    expect(app.page.get_by_text("No pies yet.")).to_be_visible()


def test_saving_under_the_same_name_updates_the_pie(app):
    app.load_example("60/40 Stocks & Bonds")
    app.save_pie("E2E update test")
    app.edit_weight(0, 70, apply=False)
    app.edit_weight(1, 30)
    app.save_pie("E2E update test")
    expect(app.page.get_by_text("Updated pie 'E2E update test'.")).to_be_visible()
    expect(app.page.get_by_role("button", name="My pies (1)")).to_be_visible()  # updated, not copied

    app.remove_pie("E2E update test")
    app.open_saved("E2E update test")
    assert [float(r[1]) for r in app.rows()] == [70, 30]
    app.delete_saved("E2E update test")


def test_click_a_column_name_to_sort(app):
    app.load_example("Three-Fund Portfolio")  # SWRD.L, EIMI.L, EUNA.DE
    app.open_editor()
    app.rows()  # the grid is drawn
    app.grid.scroll_into_view_if_needed()  # the click is at screen coordinates
    box = app.grid.bounding_box()
    app.page.mouse.click(box["x"] + 70, box["y"] + 17)  # the Ticker header
    app.eventually(app.tickers, ["EIMI.L", "EUNA.DE", "SWRD.L"])


def test_a_file_with_text_for_an_amount_says_why(app, tmp_path):
    path = tmp_path / "lots.json"
    path.write_text(json.dumps({"name": "x", "initial": "lots", "assets": [{"ticker": "AAPL", "weight": 100}]}))
    app.upload(path)
    expect(app.page.get_by_text("Could not load this file: 'initial' must be a number")).to_be_visible()
    expect(app.page.get_by_test_id("stException")).to_have_count(0)  # no raw traceback


def test_share_carries_the_latest_edit(app):
    # the link used to be built before the table applied the edit, so it lagged one edit behind
    app.open("?p=60%2F40~EUR~2020-01-01~~1000~100~N~w~VWCE.DE:70,EUNA.DE:40")  # 110%
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
    app.edit_weight(0, 39.99, apply=False)
    assert float(app.rows()[0][1]) == 39.99  # used to become 39.9
    expect(app.editor.get_by_text("Total 79.99% · 20.01% left")).to_be_visible()


def test_a_crafted_name_shows_as_typed(app):
    # pie names come from links and files: no bold, links or maths in someone else's name
    name = "**Bold** [x](http://evil.example) $a$ ~b~"
    app.open("?p=" + urllib.parse.quote_plus(name + "~EUR~2020-01-01~~1000~100~N~w~VWCE.DE:100", safe="~:,.-"))
    chip = app.page.locator(".st-key-pie_card_own .card-name")
    expect(chip).to_contain_text(name)
    assert chip.locator("strong, a, .katex").count() == 0


def test_rename_cannot_take_another_pies_name(app):
    app.load_example("All-World ETF")
    app.save_pie("E2E dup A")
    app.load_example("Tech Leaders")
    app.save_pie("E2E dup B")
    dialog = app.edit_saved("E2E dup B")
    dialog.get_by_label("Pie name").fill("e2e  DUP a")  # same name to a person: case and spaces differ
    dialog.get_by_label("Pie name").press("Enter")
    app.wait()
    expect(dialog.get_by_text("You already have a pie called 'E2E dup A'. Pick another name.")).to_be_visible()
    expect(dialog.get_by_role("button", name="Save changes")).to_be_disabled()
    app.page.keyboard.press("Escape")
    expect(app.page.get_by_test_id("stDialog")).to_have_count(0)
    app.delete_saved("E2E dup B")  # tidy up
    app.delete_saved("E2E dup A")


def test_an_asset_already_in_the_pie_cant_be_added_again(app):
    app.load_example("Tech Leaders")
    app.search("AAPL")
    expect(app.editor.get_by_role("button", name="Added ✓")).to_be_disabled()
    assert app.tickers() == ["QDVE.DE", "AAPL", "MSFT"]


def test_value_now_shows_the_gain_on_money_put_in(app):
    app.load_example("All-World ETF")
    card = app.page.locator(".st-key-result_own")
    expect(card).to_contain_text(re.compile(r"gain \([+−-]\d+%\) on €[\d.,]+k? put in"))  # the gain on money put in
    expect(card).to_contain_text("time-weighted")


def test_a_us_listing_picked_from_search_is_kept(app):
    # a euro pie used to flag NASDAQ's ASML as "no exchange suffix" and swap it for ASML.AS
    app.search_add("ASML")  # the first result: ASML on NASDAQ
    assert app.tickers() == ["ASML"]
    expect(app.editor.get_by_text("have no exchange suffix")).to_have_count(0)
    app.apply()
    assert app.metrics()  # results show without "Fix tickers"


def test_a_start_date_in_the_future_says_so(app):
    app.load_example("All-World ETF")
    app.set_date("From", f"{date.today().year + 1}-01-01")
    expect(app.page.get_by_text("The start date is in the future. Pick a date up to today.")).to_be_visible()
    assert not app.metrics()  # no stale results from the old dates


def test_a_downloaded_unfinished_pie_opens_again(app, tmp_path):
    app.open("?p=Unfinished~EUR~2020-01-01~~1000~100~N~w~VWCE.DE:30,EUNA.DE:40")  # 30 + 40 = 70%
    path = tmp_path / "unfinished.json"
    path.write_text(open(app.download()).read())
    app.remove_pie("Unfinished")
    app.upload(path)
    app.open_editor()
    assert [float(r[1]) for r in app.rows()] == [30, 40]  # used to say the weights must sum to 100%
    expect(app.editor.get_by_text("Total 70.00% · 30.00% left")).to_be_visible()


def test_a_very_long_name_keeps_the_card_name_on_one_line(app):
    app.open("?p=" + "L" * 300 + "~USD~2020-01-01~~1000~0~N~w~AAPL:50,MSFT:50")
    name = app.page.locator(".st-key-pie_card_own .card-name").bounding_box()
    assert name["height"] < 30  # one line, cut with "…"
    assert app.page.locator(".st-key-pie_card_own").bounding_box()["width"] < 700  # not stretched across the page


def test_links_say_why_they_cant_open_and_unfinished_ones_open(app):
    app.open("?p=Mine~XYZ~2020-01-01~~1000~100~N~w~VWCE.DE:100")
    expect(app.page.get_by_text("This share link can't be opened: unknown currency 'XYZ'")).to_be_visible()
    app.open("?p=Mine~EUR~2020-01-01~~1000~100~N~w~VWCE.DE:60,EUNA.DE:30")  # 90%: opens, ready to fix
    assert app.tickers() == ["VWCE.DE", "EUNA.DE"]
    expect(app.open_editor().get_by_text("Total 90.00% · 10.00% left")).to_be_visible()


def test_charts_have_a_text_alternative(app):
    app.load_example("All-World ETF")
    text = app.page.locator(".sr-only").first.inner_text()
    assert text.startswith("Growth chart: All-World ETF ends at €") and "you put in €" in text


def test_each_card_says_whether_the_pie_is_saved(app):
    app.load_example("60/40 Stocks & Bonds")
    status = app.page.locator(".st-key-status_own")
    expect(status).to_have_text("Not saved yet")
    app.save_pie("E2E status")
    expect(status).to_have_text("Saved")
    app.edit_weight(0, 70, apply=False)
    app.edit_weight(1, 30)
    expect(status).to_have_text("Unsaved changes")
    app.save_pie("E2E status")  # updates it
    expect(status).to_have_text("Saved")
    app.delete_saved("E2E status")
    expect(status).to_have_text("Not saved yet")  # still open, no longer saved


def test_editor_applies_only_on_apply(app):
    app.load_example("60/40 Stocks & Bonds")
    before = app.results()
    app.edit_weight(0, 50, apply=False)
    app.edit_weight(1, 50, apply=False)
    app.close_editor()  # ✕ or Escape: nothing changes
    assert app.results() == before
    assert [float(r[1]) for r in app.rows()] == [60, 40]  # the next edit starts from the pie again
    app.edit_weight(0, 50, apply=False)
    app.edit_weight(1, 50, apply=False)
    app.click("Discard changes", root=app.editor)
    assert app.results() == before
    app.edit_weight(0, 50, apply=False)
    app.edit_weight(1, 50)  # and Apply
    assert app.results() != before


def test_locked_rows_are_kept_by_split(app):
    app.load_example("Three-Fund Portfolio")
    app.edit_weight(0, 70, apply=False)
    box = app.grid.bounding_box()
    app.page.mouse.click(box["x"] + 250, box["y"] + 35 + 17)  # the first row's Lock box
    app.wait()
    app.click("Split evenly", root=app.editor)
    assert [float(r[1]) for r in app.rows()] == [70, 15, 15]


def test_no_sidebar(app):
    app.load_example("All-World ETF")
    expect(app.page.get_by_test_id("stSidebar")).to_have_count(0)  # one page, the same on phones
    expect(app.page.get_by_role("button", name=re.compile(r"^My pies \(\d+\)$"))).to_be_visible()


def test_delete_can_be_undone(app):
    app.load_example("All-World ETF")
    app.save_pie("E2E undo")
    app.delete_saved("E2E undo")
    expect(app.page.get_by_text("Deleted 'E2E undo'.")).to_be_visible()
    expect(app.page.locator(".st-key-status_own")).to_have_text("Not saved yet")
    app.click("Undo")
    expect(app.saved_row("E2E undo")).to_have_count(1)  # back in My pies
    expect(app.page.locator(".st-key-status_own")).to_have_text("Saved")  # and the open pie is saved again
    app.delete_saved("E2E undo")


def test_the_editor_says_before_replacing_another_saved_pie(app):
    app.load_example("All-World ETF")
    app.save_pie("E2E taken")
    app.load_example("Tech Leaders")
    editor = app.open_editor()
    name = editor.get_by_role("textbox", name="Pie name")
    name.fill("E2E taken")
    name.press("Enter")
    app.wait()
    expect(editor.get_by_text("You already have a saved pie called 'E2E taken'")).to_be_visible()
    expect(editor.get_by_role("button", name="Replace in My pies")).to_be_visible()  # not a silent overwrite
    app.close_editor()
    app.delete_saved("E2E taken")


def test_a_compared_pie_with_changes_isnt_shown_as_saved(app):
    app.load_example("60/40 Stocks & Bonds")
    app.save_pie("E2E stale")
    app.edit_weight(0, 50, apply=False)
    app.edit_weight(1, 50)  # changed and applied, not saved
    app.open_saved("E2E stale")  # the saved version opens; the changed one moves to the comparison
    statuses = app.page.locator("[class*='st-key-status_']").all_inner_texts()  # two cards with one name
    assert sorted(statuses) == ["Saved", "Unsaved changes"], statuses
    app.delete_saved("E2E stale")


def test_undo_doesnt_bring_back_a_duplicate_name(app):
    app.load_example("All-World ETF")
    app.save_pie("E2E again")
    app.delete_saved("E2E again")
    app.save_pie("E2E again")  # saved once more, as a new pie: Undo goes, it would make a second one
    expect(app.page.get_by_role("button", name="Undo")).to_have_count(0)
    expect(app.saved_row("E2E again")).to_have_count(1)
    app.delete_saved("E2E again")


def test_urls_in_names_and_crafted_tickers_stay_text(app):
    # tickers arrive from links and files too, so they're text like names
    name = "p5 see http://e.com now"
    tickers = '<A HREF="http://e.com">AAPL</A>:50,<I>MSFT</I> $X$ **Y**:50'
    app.open("?p=" + urllib.parse.quote_plus(f"{name}~EUR~2020-01-01~~1000~0~N~w~{tickers}", safe="~:,"))
    app.remove_pie(name)  # the Undo note names it
    main = app.page.get_by_test_id("stMain")
    expect(main.get_by_text("Removed 'p5 see http")).to_be_visible()
    expect(main.locator("a[href*='e.com']")).to_have_count(0)  # was an auto-link
    app.click("Undo")
    donut = app.card(name).get_by_test_id("stPlotlyChart")
    expect(donut).to_contain_text("<I>MSFT</I>")
    editor = app.open_editor()
    expect(editor.locator(".katex, a[href*='e.com']")).to_have_count(0)
    expect(editor.get_by_test_id("stAlert").filter(has_text="no exchange suffix")).to_contain_text("<I>MSFT</I> $X$ **Y**")


def test_quick_adds_all_land(app):
    # five assets added one after another at a quick human pace all land. (With no pause at all, about 3 in
    # 10 runs lost one: Streamlit drops a click when the next search arrives within some 50 ms; nobody types
    # a ticker that fast.)
    for attempt in range(3):
        app.open()
        editor = app.open_editor()
        for t in ["AAPL", "MSFT", "NVDA", "GOOG", "TSLA"]:
            box = editor.get_by_role("textbox", name="Search by name, ticker or ISIN")
            box.click()
            box.fill(t)
            box.press("Enter")
            editor.get_by_role("button", name="Add to pie").click(timeout=60_000)
            app.page.wait_for_timeout(300)  # moving back to the search box
        app.wait()
        app.eventually(app.tickers, ["AAPL", "MSFT", "NVDA", "GOOG", "TSLA"])


def test_quick_preset_clicks_end_on_the_last_one(app):
    # a preset's dates, sent back by the browser after a quick next click, counted as a date typed by hand
    # and turned the period into Custom (about 3 in 20 runs)
    import random
    app.load_example("All-World ETF")
    years = {"1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10}
    for _ in range(15):
        clicks = random.sample(list(years), 4)
        for p in clicks:
            period(app).get_by_role("radio", name=p, exact=True).click()
            app.page.wait_for_timeout(random.randint(20, 80))
        app.wait()
        expect(period(app).get_by_role("radio", name=clicks[-1], exact=True)).to_be_checked()
        today = date.today()
        assert date_of(app, "From") == date(today.year - years[clicks[-1]], today.month,
                                            min(today.day, 28) if today.month == 2 else today.day)


def contrast(fg, bg):
    """WCAG contrast of two "rgb(r, g, b)" colours."""
    def lum(c):
        r, g, b = (int(x) / 255 for x in re.findall(r"\d+", c)[:3])
        f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_primary_buttons_are_readable_in_the_dark_theme(browser, app_url):
    page = browser.new_page(color_scheme="dark", viewport={"width": 1400, "height": 1000})
    dark = App(page, app_url).open()
    dark.load_example("All-World ETF")
    apply = dark.open_plan().get_by_role("button", name="Apply")
    fg, bg = apply.evaluate("e => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor]")
    assert contrast(fg, bg) >= 4.5, (fg, bg)  # was 2.18:1
    page.close()


def test_period_presets_fit_a_small_phone(browser, playwright, app_url):
    device = {k: v for k, v in playwright.devices["iPhone SE"].items() if k != "default_browser_type"}  # 320+ px
    context = browser.new_context(**dict(device, viewport={"width": 360, "height": 740}))
    small = App(context.new_page(), app_url).open()
    for name in ("1Y", "3Y", "5Y", "10Y", "Max", "Custom"):
        box = small.page.locator(".st-key-period_pick").get_by_role("radio", name=name, exact=True).bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 360, name  # "Custom" was cut to "Cust"
    context.close()


def test_an_asset_at_zero_is_named_by_the_total(app):
    app.load_example("Tech Leaders")
    app.search_add("NVDA")  # the pie is at 100%, so NVDA gets 0%
    expect(app.editor.get_by_text("NVDA at 0%")).to_be_visible()  # "Total 100% ✓" alone hid it
    expect(app.editor.get_by_text("Double-click a weight to change it.")).to_be_visible()


def test_the_editor_on_a_phone(phone):
    phone.load_example("60/40 Stocks & Bonds")
    editor = phone.open_editor()
    box = editor.get_by_role("button", name="Apply").bounding_box()
    assert box["y"] + box["height"] <= 844, box  # reachable without scrolling past the whole editor


def test_toasts_dont_cover_the_header_buttons(app):
    app.load_example("Tech Leaders")
    app.search_add("NVDA")  # "Added NVDA." comes as a toast
    toast = app.page.get_by_test_id("stToast").first
    expect(toast).to_be_visible()
    t, b = toast.bounding_box(), app.page.get_by_role("button", name="Share").bounding_box()
    assert t["y"] > b["y"] + b["height"] or t["x"] + t["width"] < b["x"], (t, b)


def test_results_dim_while_the_app_is_busy(app):
    app.load_example("All-World ETF")
    dimmed = app.page.evaluate("""() => {
        const app = document.querySelector('[data-testid=stApp]');
        app.setAttribute('data-test-script-state', 'running');
        const r = document.querySelector('.st-key-results');
        return getComputedStyle(r).transitionDelay;
    }""")
    assert dimmed and dimmed != "0s"  # a busy cue, delayed so quick reruns don't flicker


def test_the_undo_note_is_announced(app):
    app.load_example("All-World ETF")
    app.load_example("Tech Leaders")
    app.remove_pie("All-World ETF")
    expect(app.page.locator(".st-key-undo_note [role=status]")).to_contain_text("Removed 'All-World ETF'.")


def test_results_show_exact_values_and_name_the_pie_in_the_tabs(app):
    app.load_example("All-World ETF")
    big = app.page.locator(".st-key-val_own_value .big-number")
    assert re.fullmatch(r"€[\d,]+\.\d\d", big.get_attribute("title")), big.get_attribute("title")  # exact on hover
    for tab in ("By asset", "Holdings"):
        app.page.get_by_role("tab", name=tab).click()
        expect(app.page.get_by_role("tabpanel", name=tab)).to_contain_text("All-World ETF · the open pie")


def test_save_from_a_card_and_my_pies_marks_it(app):
    app.load_example("All-World ETF")
    app.load_example("Tech Leaders")  # All-World is compared now
    app.card("All-World ETF").get_by_role("button", name="Save", exact=True).click()
    dialog = app.page.get_by_test_id("stDialog")
    expect(dialog.get_by_label("Pie name")).to_have_value("All-World ETF")  # the card's pie, not the last opened
    dialog.get_by_label("Pie name").fill("E2E card save")
    dialog.get_by_label("Pie name").press("Enter")
    app.wait()
    dialog.get_by_role("button", name=re.compile("^(Save|Update) pie$")).click()
    app.wait()
    expect(app.page.locator(".st-key-status_own")).to_have_text("Saved")  # it's the open pie now
    expect(app.saved_row("E2E card save")).to_contain_text("open")  # My pies marks it
    app.delete_saved("E2E card save")


def test_long_names_in_my_pies_are_cut(app):
    app.open("?p=" + "W" * 60 + "~EUR~2020-01-01~~1000~100~N~w~VWCE.DE:100")
    app.save_pie("E2E " + "W" * 50)
    name = app.saved_row("E2E " + "W" * 50).get_by_role("button").first.locator("p")
    assert name.bounding_box()["height"] < 30  # one line, cut with "…", instead of a row broken over lines
    app.delete_saved("E2E " + "W" * 50)
