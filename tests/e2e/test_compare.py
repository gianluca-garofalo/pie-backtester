from playwright.sync_api import expect


def comparison_rows(app):
    return app.rows(app.page.get_by_test_id("stDataFrame").last)


def test_loading_another_pie_keeps_the_previous_one(app):
    app.load_example("All-World ETF")
    expect(app.page.get_by_role("heading", name="Compared pies")).to_have_count(0)

    app.load_example("60/40 Stocks & Bonds")
    assert app.chips() == ["60/40 Stocks & Bonds (editing)", "All-World ETF"]
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
    assert [r[0] for r in rows] == ["Tech Leaders (editing)", "Tech Leaders"]
    assert rows[0][1:] == rows[1][1:]  # an untouched copy performs exactly like your pie

    app.edit_weight(0, 70)  # weights now add up to 120%
    expect(app.page.get_by_text("Your pie appears here once")).to_be_visible()


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
    expect(app.page.get_by_text("'All-World ETF (editing)' starts on 2019-07-29 (VWCE.DE has no earlier prices) with €")).to_be_visible()
    expect(app.page.get_by_text("Every pie had")).to_be_visible()  # the same amount put in


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
