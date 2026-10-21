from playwright.sync_api import expect


def add_example_to_comparison(app, name):
    app.choose("Load example pie", name)
    app.page.locator(".st-key-cmp_example button").click()
    app.wait()


def comparison_rows(app):
    return app.rows(app.page.get_by_test_id("stDataFrame").last)


def test_comparison_appears_once_two_pies_are_added(app):
    add_example_to_comparison(app, "All-World ETF")
    expect(app.page.get_by_role("heading", name="Comparison")).to_be_visible()
    expect(app.page.get_by_text("Add another pie to compare")).to_be_visible()

    add_example_to_comparison(app, "60/40 Stocks & Bonds")
    assert [r[0] for r in comparison_rows(app)] == ["All-World ETF", "60/40 Stocks & Bonds"]
    expect(app.page.get_by_test_id("stPlotlyChart")).to_have_count(2)  # value + drawdown

    app.click("✕ 60/40 Stocks & Bonds")
    expect(app.page.get_by_text("Add another pie to compare")).to_be_visible()
    app.click("Clear comparison")
    expect(app.page.get_by_role("heading", name="Comparison")).to_have_count(0)


def test_your_pie_and_a_snapshot_of_it(app):
    app.load_example("Tech Leaders")
    app.click("Add a copy to the comparison")
    rows = comparison_rows(app)
    assert [r[0] for r in rows] == ["Your pie", "Tech Leaders"]
    assert rows[0][1:] == rows[1][1:]  # an untouched copy performs exactly like your pie

    app.edit_weight(0, 70)  # weights now add up to 120%
    expect(app.page.get_by_text("Your pie isn't included")).to_be_visible()
    expect(app.page.get_by_text("Add another pie to compare")).to_be_visible()


def test_compared_pies_share_the_sidebar_settings(app):
    add_example_to_comparison(app, "All-World ETF")
    add_example_to_comparison(app, "Three-Fund Portfolio")
    app.set_number("Initial investment (EUR)", 5000)
    app.set_number("Monthly deposit (EUR)", 0)
    assert {float(r[2]) for r in comparison_rows(app)} == {5000.0}
