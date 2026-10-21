from playwright.sync_api import expect


def comparison_rows(app):
    return app.rows(app.page.get_by_test_id("stDataFrame").last)


def test_loading_another_pie_keeps_the_previous_one(app):
    app.load_example("All-World ETF")
    expect(app.page.get_by_role("heading", name="Comparison")).to_have_count(0)

    app.load_example("60/40 Stocks & Bonds")
    expect(app.page.get_by_text("'All-World ETF' is in the comparison")).to_be_visible()
    assert [r[0] for r in comparison_rows(app)] == ["60/40 Stocks & Bonds (editing)", "All-World ETF"]
    assert app.metrics()  # tiles are for the pie being edited

    app.click("✕ All-World ETF")
    expect(app.page.get_by_role("heading", name="Comparison")).to_have_count(0)
    assert app.metrics()


def test_reloading_the_same_pie_does_not_duplicate_it(app):
    app.load_example("All-World ETF")
    app.click("Load example")
    expect(app.page.get_by_role("heading", name="Comparison")).to_have_count(0)


def test_snapshot_of_your_own_pie(app):
    app.load_example("Tech Leaders")
    app.click("Duplicate")
    rows = comparison_rows(app)
    assert [r[0] for r in rows] == ["Tech Leaders (editing)", "Tech Leaders"]
    assert rows[0][1:] == rows[1][1:]  # an untouched copy performs exactly like your pie

    app.edit_weight(0, 70)  # weights now add up to 120%
    expect(app.page.get_by_text("Your pie appears here once")).to_be_visible()
    expect(app.page.get_by_role("heading", name="Compared pies")).to_be_visible()


def test_pie_selector_switches_the_allocation_donut(app):
    app.load_example("All-World ETF")
    app.load_example("Tech Leaders")
    picker = app.page.get_by_role("radiogroup", name="Show allocation of")
    expect(picker.get_by_role("radio", name="Tech Leaders (editing)")).to_be_checked()
    picker.get_by_role("radio", name="All-World ETF").click()
    app.wait()
    donut = app.page.get_by_test_id("stPlotlyChart").first
    expect(donut).to_contain_text("VWCE.DE")
    expect(donut).not_to_contain_text("QDVE.DE")


def test_compared_pies_share_the_sidebar_settings(app):
    app.load_example("All-World ETF")
    app.load_example("Three-Fund Portfolio")
    app.set_number("Initial investment (EUR)", 5000)
    app.set_number("Monthly deposit (EUR)", 0)
    # columns: Pie, From, Final value, Invested
    app.eventually(lambda: {float(r[3]) for r in comparison_rows(app)}, {5000.0})


def test_a_pie_with_later_assets_starts_later(app):
    app.load_example("Tech Leaders")
    app.load_example("All-World ETF")
    app.set_date("Start date", "2015-01-01")
    app.eventually(lambda: {r[0]: r[1] for r in comparison_rows(app)},
                   {"All-World ETF (editing)": "2019-07-29", "Tech Leaders": "2015-12-03"})
    expect(app.page.get_by_text("'Tech Leaders' starts on 2015-12-03")).to_be_visible()


def test_every_loaded_pie_can_be_removed(app):
    # two examples loaded one after the other: both get a ✕, including the one being edited
    app.load_example("All-World ETF")
    app.load_example("60/40 Stocks & Bonds")
    expect(app.page.get_by_role("button", name="✕ 60/40 Stocks & Bonds (editing)")).to_be_visible()
    expect(app.page.get_by_role("button", name="✕ All-World ETF")).to_be_visible()

    app.click("✕ 60/40 Stocks & Bonds (editing)")
    # the other pie opens in the editor, keeping the sidebar settings
    assert app.tickers() == ["VWCE.DE"]
    expect(app.sidebar.get_by_label("Pie name")).to_have_value("All-World ETF")
    expect(app.page.get_by_role("heading", name="Comparison")).to_have_count(0)
    assert app.metrics()


def test_loading_a_compared_pie_opens_it_instead_of_duplicating(app):
    app.load_example("All-World ETF")
    app.load_example("60/40 Stocks & Bonds")
    app.load_example("All-World ETF")
    app.eventually(lambda: [r[0] for r in comparison_rows(app)],
                   ["All-World ETF (editing)", "60/40 Stocks & Bonds"])
