import json

from playwright.sync_api import expect


def comparison_rows(app):
    return app.rows(app.page.get_by_test_id("stDataFrame").last)


def test_loading_another_pie_keeps_the_previous_one(app):
    app.load_example("All-World ETF")
    expect(app.page.get_by_role("heading", name="Compared pies")).to_have_count(0)

    app.load_example("60/40 Stocks & Bonds")
    assert app.chips() == ["All-World ETF", "60/40 Stocks & Bonds (editing)"]  # in the order they were loaded
    expect(app.page.get_by_test_id("stAlert")).to_have_count(0)  # no banner about it
    assert [r[0] for r in comparison_rows(app)] == ["60/40 Stocks & Bonds (editing)", "All-World ETF"]
    assert app.metrics()  # tiles are for the pie being edited

    app.remove_pie("All-World ETF")
    expect(app.page.get_by_role("heading", name="Compared pies")).to_have_count(0)
    assert app.metrics()


def test_reloading_the_same_pie_does_not_duplicate_it(app):
    app.load_example("All-World ETF")
    app.load_example("All-World ETF")
    assert app.chips() == ["All-World ETF (editing)"]


def test_snapshot_of_your_own_pie(app):
    app.load_example("Tech Leaders")
    app.click("Compare a copy")
    rows = comparison_rows(app)
    assert [r[0] for r in rows] == ["Tech Leaders (editing)", "Tech Leaders (copy)"]
    assert rows[0][1:] == rows[1][1:]  # an untouched copy performs exactly like your pie
    app.page.get_by_role("button", name="Compare a copy").click()  # again: nothing new to compare
    expect(app.page.get_by_text("This pie is already in the comparison as 'Tech Leaders (copy)'.")).to_be_visible()
    app.wait()

    app.edit_weight(0, 70)  # weights now add up to 120%
    expect(app.page.get_by_text("Your pie appears here once")).to_be_visible()


def test_a_copy_keeps_the_fund_names(app):
    app.load_example("Tech Leaders")
    app.click("Compare a copy")
    app.click("Split evenly")  # make the two differ, so switching keeps both
    app.open_pie("Tech Leaders (copy)")
    assert [r[2] for r in app.rows()] == ["iShares S&P 500 Information Technology Sector UCITS ETF",
                                          "Apple Inc.", "Microsoft Corporation"]  # were the tickers


def test_clicking_a_compared_pie_opens_it(app):
    app.load_example("All-World ETF")
    app.load_example("Tech Leaders")
    app.open_pie("All-World ETF")
    assert app.tickers() == ["VWCE.DE"]
    assert app.chips() == ["All-World ETF (editing)", "Tech Leaders"]
    expect(app.page.get_by_test_id("stPlotlyChart").first).to_contain_text("VWCE.DE")  # the donut


def test_compared_pies_share_the_sidebar_settings(app):
    app.load_example("All-World ETF")
    app.load_example("Three-Fund Portfolio")
    app.set_number("Initial", 5000)
    app.set_number("Monthly", 0)
    expect(app.page.get_by_text("Every pie had €5,000.00 put in.")).to_be_visible()


def test_a_pie_with_later_assets_starts_later(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2015-01-01")
    app.eventually(lambda: {r[0]: r[1] for r in comparison_rows(app)},
                   {"All-World ETF (editing)": "2019-07-29", "Tech Leaders": "2015-12-03"})
    expect(app.page.get_by_text("'Tech Leaders' starts on 2015-12-03")).to_be_visible()
    # All-World lists later than Tech Leaders, so it starts with Tech Leaders' value on that day
    expect(app.page.get_by_text("'All-World ETF (editing)' starts on 2019-07-29 (VWCE.DE has no earlier prices) with $")).to_be_visible()
    expect(app.page.get_by_text("Every pie had")).to_be_visible()  # the same amount put in
    # the tiles say which pie they're about
    expect(app.page.get_by_text("(the pie you're editing)")).to_be_visible()


def test_every_loaded_pie_can_be_removed(app):
    # two examples loaded one after the other: both get a ✕, including the one being edited
    app.load_example("All-World ETF")
    app.load_example("60/40 Stocks & Bonds")
    app.remove_pie("60/40 Stocks & Bonds (editing)")
    # the other pie opens in the editor, keeping the sidebar settings
    assert app.tickers() == ["VWCE.DE"]
    assert app.chips() == ["All-World ETF (editing)"]
    expect(app.page.get_by_role("heading", name="Compared pies")).to_have_count(0)
    assert app.metrics()


def test_loading_a_compared_pie_opens_it_instead_of_duplicating(app):
    app.load_example("All-World ETF")
    app.load_example("60/40 Stocks & Bonds")
    app.load_example("All-World ETF")
    assert app.chips() == ["All-World ETF (editing)", "60/40 Stocks & Bonds"]


def test_a_pie_added_to_a_comparison_keeps_the_settings(app):
    app.load_example("All-World ETF")  # EUR, never rebalanced
    app.page.get_by_role("button", name="Examples").click()
    app.page.get_by_test_id("stPopoverBody").get_by_role("button", name="Tech Leaders", exact=True).click()
    # saved with USD and quarterly rebalancing; the note is a toast, gone after a few seconds, so look right away
    expect(app.page.get_by_text("Kept your settings. 'Tech Leaders' was saved with USD")).to_be_visible(timeout=20_000)
    app.wait()
    expect(app.page.get_by_role("combobox", name="Currency")).to_have_value("EUR")
    expect(app.page.get_by_role("radiogroup", name="Rebalance to target")
           .get_by_role("radio", checked=True)).to_have_text("Never")


def test_a_sixth_pie_is_refused_without_losing_one(app, tmp_path):
    names = ["All-World ETF", "Dividend Focus", "60/40 Stocks & Bonds", "Tech Leaders", "Three-Fund Portfolio"]
    for name in names:
        app.load_example(name)
    before = app.chips()
    assert len(before) == 5
    path = tmp_path / "sixth.json"
    path.write_text(json.dumps({"name": "Sixth", "assets": [{"ticker": "EIMI.L", "weight": 100}]}))
    app.open_sidebar_section("Import / export JSON")
    app.sidebar.locator("input[type=file]").set_input_files(path)
    app.wait()
    expect(app.page.get_by_text("Remove one with ✕ first, then open 'Sixth'.")).to_be_visible()
    assert app.chips() == before  # the pie being edited used to be dropped here


def test_chips_keep_their_place_when_switching(app):
    for name in ("All-World ETF", "Tech Leaders", "60/40 Stocks & Bonds"):
        app.load_example(name)
    assert app.chips() == ["All-World ETF", "Tech Leaders", "60/40 Stocks & Bonds (editing)"]
    app.open_pie("All-World ETF")
    assert app.chips() == ["All-World ETF (editing)", "Tech Leaders", "60/40 Stocks & Bonds"]
    app.open_pie("Tech Leaders")
    assert app.chips() == ["All-World ETF", "Tech Leaders (editing)", "60/40 Stocks & Bonds"]
