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
    assert [r[0] for r in comparison_rows(app)] == ["All-World ETF", "60/40 Stocks & Bonds (editing)"]  # chip order
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


def start_choice(app):
    return app.page.get_by_role("radiogroup", name="When the pies start")


def test_late_listing_choice_card(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2015-01-01")
    # VWCE.DE lists in 2019, so by default every pie starts then: same days, same money, rankable
    expect(start_choice(app).get_by_role("radio", name="Start all pies on 29 Jul 2019")).to_be_checked()
    app.eventually(lambda: {r[0]: r[1] for r in comparison_rows(app)},
                   {"All-World ETF (editing)": "2019-07-29", "Tech Leaders": "2019-07-29"})
    expect(app.page.get_by_text("Every number and chart below covers 29 Jul 2019 – ")).to_be_visible()
    expect(app.page.get_by_text("VWCE.DE has prices from 29 Jul 2019")).to_be_visible()

    start_choice(app).get_by_text("Each pie from its own first price").click()
    app.wait()
    app.eventually(lambda: {r[0]: r[1] for r in comparison_rows(app)},
                   {"All-World ETF (editing)": "2019-07-29", "Tech Leaders": "2015-12-03"})

    start_choice(app).get_by_text("Start on 1 Jan 2015, holding cash until VWCE.DE lists").click()
    app.wait()
    app.eventually(lambda: {r[0]: r[1] for r in comparison_rows(app)},
                   {"All-World ETF (editing)": "2015-01-01", "Tech Leaders": "2015-01-01"})
    expect(start_choice(app).get_by_text("changes the strategy")).to_be_visible()
    expect(app.page.get_by_text("Started later, with the average value")).to_have_count(0)  # that rule is gone


def test_start_choice_is_kept_while_the_card_is_hidden(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2016-01-01")
    start_choice(app).get_by_text("Each pie from its own first price").click()
    app.wait()
    app.remove_pie("All-World ETF (editing)")  # nothing lists late now, so the card goes
    expect(start_choice(app)).to_have_count(0)
    app.load_example("All-World ETF")
    expect(start_choice(app).get_by_role("radio", name="Each pie from its own first price")).to_be_checked()


def test_a_pie_without_prices_in_the_period_says_why(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2018-01-01")
    app.set_date("To", "2019-01-01")
    expect(app.page.get_by_text("No prices in this period: VWCE.DE starts 29 Jul 2019")).to_be_visible()
    # the other pie still shows, over its own days
    expect(app.page.get_by_text("Every number and chart below covers 2 Jan 2018 – 31 Dec 2018")).to_be_visible()


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
    expect(app.page.get_by_text("'Tech Leaders' uses the comparison's settings: EUR, not its own USD")).to_be_visible(
        timeout=20_000)
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


def test_phone_layout(phone):
    phone.load_example("All-World ETF")
    phone.load_example("Tech Leaders")
    chart = phone.page.get_by_test_id("stPlotlyChart").nth(1)  # the Growth chart (the donut is first)
    expect(chart.locator(".legend")).to_have_count(1)  # a legend below instead of labels on the right
    expect(chart.locator(".annotation-text")).to_have_count(0)
    table = phone.page.get_by_test_id("stDataFrame").last
    table.scroll_into_view_if_needed()  # tables below the fold are drawn when they come into view
    phone.eventually(lambda: [h.strip() for h in table.locator("thead [role=columnheader]").all_text_contents()
                              if h.strip()], ["Pie", "Value", "Return", "Per year"])
    box = phone.page.get_by_role("button", name="Remove All-World ETF", exact=True).bounding_box()
    assert box["width"] >= 36 and box["height"] >= 36  # a finger-sized ✕
    scroller = table.locator(".dvn-scroller").first  # the table's scroll area: no sideways scroll needed
    assert scroller.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "the columns don't fit"
    phone.page.get_by_role("button", name="Share").click()
    share = phone.page.get_by_test_id("stPopoverBody")
    copy = share.frame_locator("iframe").locator("#b")
    expect(copy).to_have_text("Copy link")
    copy.click()  # a visible copy button, also on touch screens
    expect(copy).to_have_text("Copied ✓")


def test_an_unfinished_pie_that_cant_join_says_so(app):
    app.load_example("60/40 Stocks & Bonds")
    app.edit_weight(0, 30)  # 70%: can't be compared
    app.page.get_by_role("button", name="Examples").click()
    app.page.get_by_test_id("stPopoverBody").get_by_role("button", name="All-World ETF", exact=True).click()
    expect(app.page.get_by_text("'60/40 Stocks & Bonds' was closed: its weights add up to 70.00%")).to_be_visible(
        timeout=20_000)
    app.wait()
    assert app.chips() == ["All-World ETF (editing)"]
