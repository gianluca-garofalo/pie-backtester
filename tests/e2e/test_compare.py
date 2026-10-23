import json

from playwright.sync_api import expect


def copy_pie(app, name):
    app.card(name).get_by_role("button", name="Copy", exact=True).click()
    app.wait()


def test_loading_another_pie_keeps_the_previous_one(app):
    app.load_example("All-World ETF")
    assert app.cards() == ["All-World ETF"]

    app.load_example("60/40 Stocks & Bonds")
    assert app.cards() == ["All-World ETF", "60/40 Stocks & Bonds"]  # in the order they were loaded
    assert app.editing() == "60/40 Stocks & Bonds"
    expect(app.page.get_by_test_id("stAlert")).to_have_count(0)  # no banner about it
    assert app.results("All-World ETF") and app.results("60/40 Stocks & Bonds")  # a results card each

    app.remove_pie("All-World ETF")
    assert app.cards() == ["60/40 Stocks & Bonds"]
    assert app.metrics()


def test_reloading_the_same_pie_does_not_duplicate_it(app):
    app.load_example("All-World ETF")
    app.load_example("All-World ETF")
    assert app.cards() == ["All-World ETF"]


def test_snapshot_of_your_own_pie(app):
    app.load_example("Tech Leaders")
    copy_pie(app, "Tech Leaders")
    assert app.cards() == ["Tech Leaders", "Tech Leaders (copy)"]
    assert app.results("Tech Leaders") == app.results("Tech Leaders (copy)")  # an untouched copy performs the same
    copy_pie(app, "Tech Leaders")  # again: nothing new to compare
    expect(app.page.get_by_text("This pie is already in the comparison as 'Tech Leaders (copy)'.")).to_be_visible()
    app.wait()

    app.edit_weight(0, 70, apply=False)  # weights now add up to 120%: Apply waits, and says why
    expect(app.editor.get_by_role("button", name="Apply")).to_be_disabled()
    expect(app.editor.get_by_text("Apply needs the weights to add up to 100%")).to_be_visible()


def test_a_copy_keeps_the_fund_names(app):
    app.load_example("Tech Leaders")
    copy_pie(app, "Tech Leaders")
    app.click("Split evenly", root=app.open_editor())  # make the two differ, so switching keeps both
    app.apply()
    app.open_pie("Tech Leaders (copy)")
    assert [r[3] for r in app.rows()] == ["iShares S&P 500 Information Technology Sector UCITS ETF",
                                          "Apple Inc.", "Microsoft Corporation"]  # were the tickers


def test_clicking_a_compared_pie_opens_it(app):
    app.load_example("All-World ETF")
    app.load_example("Tech Leaders")
    app.open_pie("All-World ETF")
    assert app.tickers() == ["VWCE.DE"]
    assert app.cards() == ["All-World ETF", "Tech Leaders"]
    assert app.editing() == "All-World ETF"
    expect(app.card("All-World ETF").get_by_test_id("stPlotlyChart")).to_contain_text("VWCE.DE")  # its donut


def test_compared_pies_share_the_plan(app):
    app.load_example("All-World ETF")
    app.load_example("Three-Fund Portfolio")
    app.set_plan(initial=5000, monthly=0)
    expect(app.plan).to_contain_text("€5,000 to start · no monthly deposits")
    expect(app.page.get_by_text("€5k put in each")).to_be_visible()


def test_results_cards_mark_the_best(app):
    for name in ("All-World ETF", "60/40 Stocks & Bonds", "Tech Leaders"):
        app.load_example(name)
    app.set_date("From", "2018-01-01")
    for name in app.cards():  # the shared window: VWCE.DE lists on 29 Jul 2019
        assert app.window(name).startswith("29 Jul 2019 – "), app.window(name)
    expect(app.page.locator(".st-key-best_own_value")).to_have_text("best")  # Tech Leaders grew the most
    expect(app.page.locator("[class*='st-key-best_']")).to_have_count(4)  # one per row


def test_cards_dont_repeat_the_start_choice(app):
    for name in ("All-World ETF", "Tech Leaders"):
        app.load_example(name)
    app.set_date("From", "2018-01-01")
    card = app.page.locator(".st-key-result_own")
    # the period sentence and the start choice above say it already
    expect(card).not_to_contain_text("with the other pies")
    expect(card).not_to_contain_text("On its own")
    start_choice(app).get_by_text("Each pie from its own first price").click()  # still switches the rule
    app.wait()
    assert app.window("Tech Leaders").startswith("2 Jan 2018 – ")
    expect(app.page.locator("[class*='st-key-best_']")).to_have_count(0)  # different periods aren't ranked

def start_choice(app):
    return app.page.get_by_role("radiogroup", name="When the pies start")


def test_late_listing_choice_card(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2015-01-01")
    # VWCE.DE lists in 2019, so by default every pie starts then: same days, same money, rankable
    expect(start_choice(app).get_by_role("radio", name="Start all pies on 29 Jul 2019")).to_be_checked()
    app.eventually(lambda: {n: app.window(n)[:11] for n in app.cards()},
                   {"Tech Leaders": "29 Jul 2019", "All-World ETF": "29 Jul 2019"})
    expect(app.page.get_by_text("Every number and chart below covers 29 Jul 2019 – ")).to_be_visible()
    expect(app.page.get_by_text("VWCE.DE has prices from 29 Jul 2019")).to_be_visible()

    start_choice(app).get_by_text("Each pie from its own first price").click()
    app.wait()
    app.eventually(lambda: {n: app.window(n)[:11] for n in app.cards()},
                   {"Tech Leaders": "3 Dec 2015 ", "All-World ETF": "29 Jul 2019"})

    start_choice(app).get_by_text("Start on 1 Jan 2015, holding cash until VWCE.DE lists").click()
    app.wait()
    app.eventually(lambda: {n: app.window(n)[:10] for n in app.cards()},
                   {"Tech Leaders": "1 Jan 2015", "All-World ETF": "1 Jan 2015"})
    expect(start_choice(app).get_by_text("changes the strategy")).to_be_visible()
    expect(app.page.get_by_text("Started later, with the average value")).to_have_count(0)  # that rule is gone


def test_start_choice_is_kept_when_nothing_lists_late(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2016-01-01")
    start_choice(app).get_by_text("Each pie from its own first price").click()
    app.wait()
    app.remove_pie("All-World ETF")  # nothing lists late now: the choice stays, with what each option means
    expect(start_choice(app).get_by_role("radio", name="Each pie from its own first price")).to_be_checked()
    app.load_example("All-World ETF")
    expect(start_choice(app).get_by_role("radio", name="Each pie from its own first price")).to_be_checked()


def test_the_period_bar_always_shows_everything(app):
    # parts that came and went with the period made it confusing
    app.load_example("All-World ETF")
    for preset in ("10Y", "5Y"):  # VWCE.DE lists in 2019: only 10Y starts before that
        app.page.locator(".st-key-period_pick").get_by_role("radio", name=preset, exact=True).click()
        app.wait()
        expect(start_choice(app).get_by_role("radio")).to_have_count(3)
        expect(app.page.get_by_text("Solid: the days the results use. Faded: ")).to_be_visible()
        expect(app.page.get_by_text("Dotted: an asset has no prices yet.")).to_be_visible()
    expect(start_choice(app)).to_contain_text("the same as the first option")  # at 5Y nothing waits as cash


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
    app.remove_pie("60/40 Stocks & Bonds")
    # the other pie opens in the editor, keeping the plan
    assert app.tickers() == ["VWCE.DE"]
    assert app.cards() == ["All-World ETF"] and app.editing() == "All-World ETF"
    assert app.metrics()


def test_loading_a_compared_pie_opens_it_instead_of_duplicating(app):
    app.load_example("All-World ETF")
    app.load_example("60/40 Stocks & Bonds")
    app.load_example("All-World ETF")
    assert app.cards() == ["All-World ETF", "60/40 Stocks & Bonds"]
    assert app.editing() == "All-World ETF"


def test_a_pie_added_to_a_comparison_keeps_the_settings(app):
    app.load_example("All-World ETF")  # EUR, never rebalanced
    app.load_example("Tech Leaders")  # saved with USD and quarterly rebalancing
    # said in the Plan bar, where the settings are, and it stays; a toast covered the header buttons
    expect(app.plan).to_contain_text("EUR · rebalance never")
    expect(app.plan).to_contain_text("'Tech Leaders' uses this plan, not its own: USD, rebalance quarterly")


def test_a_sixth_pie_is_refused_without_losing_one(app, tmp_path):
    names = ["All-World ETF", "Dividend Focus", "60/40 Stocks & Bonds", "Tech Leaders", "Three-Fund Portfolio"]
    for name in names:
        app.load_example(name)
    before = app.cards()
    assert len(before) == 5
    path = tmp_path / "sixth.json"
    path.write_text(json.dumps({"name": "Sixth", "assets": [{"ticker": "EIMI.L", "weight": 100}]}))
    app.upload(path)
    expect(app.page.get_by_text("Remove one first, then open 'Sixth'.")).to_be_visible()
    assert app.cards() == before  # the pie being edited used to be dropped here


def test_cards_keep_their_place_when_switching(app):
    order = ["All-World ETF", "Tech Leaders", "60/40 Stocks & Bonds"]
    for name in order:
        app.load_example(name)
    assert app.cards() == order and app.editing() == "60/40 Stocks & Bonds"
    app.open_pie("All-World ETF")
    assert app.cards() == order and app.editing() == "All-World ETF"
    app.open_pie("Tech Leaders")
    assert app.cards() == order and app.editing() == "Tech Leaders"


def test_phone_layout(phone):
    phone.load_example("All-World ETF")
    phone.load_example("Tech Leaders")
    chart = phone.page.locator(".st-key-growth")  # the Growth chart
    expect(chart.locator(".legend")).to_have_count(1)  # a legend instead of labels on the right
    expect(chart.locator(".annotation-text")).to_have_count(0)
    # one card per pie, with its donut and its results together
    for name in ("All-World ETF", "Tech Leaders"):
        card = phone.card(name)
        expect(card.get_by_test_id("stPlotlyChart")).to_have_count(1)
        expect(card.locator("[class*='st-key-result_']")).to_have_count(1)
    expect(phone.page.locator(".st-key-results")).to_have_count(0)  # no separate results row
    box = phone.card("All-World ETF").get_by_role("button", name="Remove", exact=True).bounding_box()
    assert box["width"] >= 36 and box["height"] >= 36  # finger-sized
    assert phone.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "sideways scroll"
    phone.page.get_by_role("button", name="Share").click()
    share = phone.page.get_by_test_id("stPopoverBody")
    copy = share.frame_locator("iframe").locator("#b")
    expect(copy).to_have_text("Copy link")
    copy.click()  # a visible copy button, also on touch screens
    expect(copy).to_have_text("Copied ✓")


def test_an_unfinished_pie_that_cant_join_says_so(app):
    app.open("?p=60%2F40+Stocks+%26+Bonds~EUR~2020-01-01~~1000~100~N~w~VWCE.DE:30,EUNA.DE:40")  # 70%: unfinished
    expect(app.page.locator(".st-key-result_own")).to_contain_text("once its weights add up to 100%")
    app.page.get_by_role("button", name="Examples").click()
    app.page.get_by_test_id("stPopoverBody").get_by_role("button", name="All-World ETF", exact=True).click()
    expect(app.page.get_by_text("'60/40 Stocks & Bonds' was closed: its weights add up to 70.00%")).to_be_visible(
        timeout=20_000)
    app.wait()
    assert app.cards() == ["All-World ETF"]


def test_remove_can_be_undone(app):
    for name in ("All-World ETF", "60/40 Stocks & Bonds", "Tech Leaders"):
        app.load_example(name)
    before = app.card_keys()
    colors = [app.card(n).evaluate("e => getComputedStyle(e).borderTopColor") for n in before]
    app.remove_pie("60/40 Stocks & Bonds")
    expect(app.page.get_by_text("Removed '60/40 Stocks & Bonds'.")).to_be_visible()
    app.remove_pie("Tech Leaders")  # the open one: another opens
    app.click("Undo")  # undoes the last removal
    assert app.cards() == ["All-World ETF", "Tech Leaders"] and app.editing() == "Tech Leaders"
    app.remove_pie("All-World ETF")
    app.click("Undo")
    assert app.cards() == ["All-World ETF", "Tech Leaders"]
    assert [app.card(n).evaluate("e => getComputedStyle(e).borderTopColor") for n in app.cards()] == \
        [colors[0], colors[2]]  # same colours as before


def test_a_long_name_doesnt_squeeze_the_coverage_strip(app):
    app.open("?p=" + "L" * 60 + "~EUR~2015-01-01~~1000~100~N~w~VWCE.DE:100")
    app.load_example("Tech Leaders")
    labels = app.page.locator(".st-key-period [data-testid=stPlotlyChart] .ytick text").all_text_contents()
    assert labels and max(len(t) for t in labels) <= 25, labels  # cut with "…"


def test_copy_works_on_any_card(app):
    app.load_example("All-World ETF")
    app.load_example("Tech Leaders")  # the open one; All-World is compared
    copy_pie(app, "All-World ETF")  # was refused: "already in the comparison as 'All-World ETF'"
    assert app.cards() == ["All-World ETF", "Tech Leaders", "All-World ETF (copy)"]


def test_loading_a_pie_after_a_copy_keeps_the_original(app):
    app.load_example("Tech Leaders")
    copy_pie(app, "Tech Leaders")
    app.load_example("All-World ETF")  # Tech Leaders moves to the comparison; it was dropped for its copy
    assert app.cards() == ["Tech Leaders", "Tech Leaders (copy)", "All-World ETF"]


def test_the_chart_scale_stays_as_picked(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2015-01-01")
    tabs = app.page.get_by_test_id("stTabs")
    tabs.get_by_role("radio", name="Linear", exact=True).click()
    app.wait()
    start_choice(app).get_by_text("Each pie from its own first price").click()  # a longer period: >10 years
    app.wait()
    expect(tabs.get_by_role("radio", name="Linear", exact=True)).to_be_checked()  # used to flip to Log


def test_why_other_pies_cant_be_edited_is_on_the_page(app, tmp_path):
    app.load_example("All-World ETF")
    path = tmp_path / "unfinished.json"
    path.write_text(json.dumps({"name": "Unfinished", "assets": [{"ticker": "EIMI.L", "weight": 70}]}))
    app.upload(path)  # opens at 70%; All-World stays compared
    expect(app.card("All-World ETF").get_by_role("button", name="Edit", exact=True)).to_be_disabled()
    expect(app.page.get_by_text("Finish 'Unfinished' (weights at 100%) to edit the other pies.")).to_be_visible()


def test_each_pie_has_its_own_put_in_line_when_starts_differ(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2015-01-01")
    start_choice(app).get_by_text("Each pie from its own first price").click()
    app.wait()
    text = app.page.locator(".sr-only", has_text="Growth chart").inner_text()
    assert "you put in" in text and "(Tech Leaders)" in text and "(All-World ETF)" in text, text


def test_result_rows_line_up_across_five_cards(app):
    for name in ["All-World ETF", "Dividend Focus", "60/40 Stocks & Bonds", "Tech Leaders", "Three-Fund Portfolio"]:
        app.load_example(name)
    for row in ("value", "return", "per_year", "worst_fall"):
        ys = [b["y"] for b in (el.bounding_box() for el in app.page.locator(f"[class*='st-key-val_'][class*='_{row}']").all())]
        assert len(ys) == 5 and max(ys) - min(ys) <= 2, (row, ys)


def test_looking_at_a_compared_pie_changes_nothing_until_apply(app):
    for name in ("All-World ETF", "60/40 Stocks & Bonds", "Tech Leaders"):
        app.load_example(name)
    app.remove_pie("All-World ETF")  # Undo is offered
    app.open_editor("60/40 Stocks & Bonds")  # just to look
    app.close_editor()
    assert app.editing() == "Tech Leaders"  # was switched to 60/40 already
    expect(app.page.get_by_role("button", name="Undo")).to_be_visible()  # and Undo was gone
    app.card("60/40 Stocks & Bonds").get_by_role("button", name="Save", exact=True).click()
    expect(app.page.get_by_test_id("stDialog").get_by_label("Pie name")).to_have_value("60/40 Stocks & Bonds")
    app.page.get_by_test_id("stDialog").get_by_role("button", name="Close").click()
    app.wait()
    assert app.editing() == "Tech Leaders"
    app.open_editor("60/40 Stocks & Bonds")  # editing it for real: it becomes the open pie on Apply
    app.edit_weight(0, 50, apply=False)
    app.edit_weight(1, 50)
    assert app.editing() == "60/40 Stocks & Bonds" and app.cards() == ["60/40 Stocks & Bonds", "Tech Leaders"]


def test_a_rename_cant_give_two_pies_one_name(app):
    app.load_example("All-World ETF")
    app.load_example("Tech Leaders")
    editor = app.open_editor()
    editor.get_by_role("textbox", name="Pie name").fill("All-World ETF")
    editor.get_by_role("textbox", name="Pie name").press("Enter")
    app.wait()
    app.apply()
    assert app.cards() == ["All-World ETF", "All-World ETF (2)"]  # one card showed the other's numbers


def test_the_coverage_strip_is_always_there(app):
    app.load_example("All-World ETF")
    strip = app.page.locator(".st-key-period").get_by_test_id("stPlotlyChart")
    for preset in ("10Y", "5Y", "1Y"):  # VWCE.DE lists in 2019: only 10Y starts before that
        app.page.locator(".st-key-period_pick").get_by_role("radio", name=preset, exact=True).click()
        app.wait()
        expect(strip).to_have_count(1)
        expect(app.page.get_by_text("Every number and chart below covers")).to_be_visible()


def test_max_goes_back_to_the_earliest_pie_and_keeps_the_choice(app):
    app.load_example("All-World ETF")
    app.load_example("Tech Leaders")  # AAPL has prices from 1980, but QDVE.DE from 2015 and VWCE.DE from 2019
    app.page.locator(".st-key-period_pick").get_by_role("radio", name="Max", exact=True).click()
    app.wait()
    assert app.page.get_by_role("spinbutton", name="year, From").get_attribute("aria-valuenow") == "2015"
    # VWCE.DE lists after that, so the start choice is there, as with 10Y
    expect(app.page.get_by_role("radiogroup", name="When the pies start")).to_be_visible()


def test_the_strip_shows_each_pies_own_history(app):
    app.load_example("All-World ETF")
    app.load_example("Tech Leaders")
    app.page.locator(".st-key-period_pick").get_by_role("radio", name="Max", exact=True).click()
    app.wait()  # the pies start together on 29 Jul 2019; Tech Leaders has every price from Dec 2015
    traces = app.page.locator(".st-key-period .js-plotly-plot").evaluate(
        "e => e.data.map(t => [t.name, String(t.x[0]).slice(0, 10)])")
    assert ["has prices, not used", "2015-12-03"] in traces, traces  # the bars showed only the shared days
    expect(app.page.get_by_text("Faded: the pie has prices, but the results don't use these days.")).to_be_visible()


def test_the_strip_shows_cash_days_apart(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2015-01-01")
    start_choice(app).get_by_text("Start on 1 Jan 2015, holding cash until VWCE.DE lists").click()
    app.wait()
    traces = app.page.locator(".st-key-period .js-plotly-plot").evaluate(
        "e => e.data.map(t => [t.name, String(t.x[0]).slice(0, 10), t.line.dash])")
    # All-World waits as cash from 1 Jan 2015 until VWCE.DE lists: it looked fully invested
    assert ["cash until listed", "2015-01-01", "dash"] in traces, traces
    expect(app.page.get_by_text("Dashed: the results use these days, but a slice waits as cash.")).to_be_visible()


def test_the_strip_starts_with_the_period(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("From", "2018-01-01")  # Tech Leaders has prices from Dec 2015: the strip still starts at From
    plot = app.page.locator(".st-key-period .js-plotly-plot")
    assert plot.evaluate("e => String(e.layout.xaxis.range[0]).slice(0, 10)") == "2018-01-01"
    expect(plot.get_by_text("From", exact=True)).to_have_count(0)  # no marker: the strip is the period
