import pandas as pd
import pytest
import engine

def test_simulate_pie_even_split():
    # Construct sample daily prices for two assets over 5 days
    dates = pd.date_range("2023-01-01", periods=5, freq="D")
    prices = pd.DataFrame({
        "STOCK_A": [100.0, 105.0, 110.0, 108.0, 112.0],
        "STOCK_B": [50.0, 52.0, 54.0, 53.0, 55.0]
    }, index=dates)

    weights = {"STOCK_A": 50.0, "STOCK_B": 50.0}
    initial = 1000.0

    res = engine.simulate_pie(
        prices=prices,
        weights=weights,
        start="2023-01-01",
        initial=initial,
        monthly=0.0,
        rebalance="Never",
        before_listing="wait"
    )

    assert "values" in res
    assert "total" in res
    assert "twr" in res

    # Day 1 initial setup: 500 in A (5 units @ 100), 500 in B (10 units @ 50)
    # Day 5: A = 5 * 112 = 560; B = 10 * 55 = 550; total = 1110
    total_day5 = res["total"].iloc[-1]
    assert pytest.approx(total_day5, 0.01) == 1110.0

def test_metrics_calculation():
    dates = pd.date_range("2023-01-01", periods=3, freq="D")
    total = pd.Series([1000.0, 1050.0, 1100.0], index=dates)
    invested = pd.Series([1000.0, 1000.0, 1000.0], index=dates)
    twr = pd.Series([1.0, 1.05, 1.10], index=dates)
    daily_r = pd.Series([0.0, 0.05, 0.0476], index=dates)

    res = {
        "total": total,
        "invested": invested,
        "twr": twr,
        "daily_r": daily_r
    }

    m = engine.metrics(res)
    assert m["final_value"] == 1100.0
    assert m["invested"] == 1000.0
    assert m["profit"] == 100.0
    assert pytest.approx(m["twr_total"], 0.001) == 0.10


def _fake_search(symbols):
    return lambda q, max_results=10: [
        {"symbol": s, "name": s, "exchange": "", "type": "EQUITY"} for s in symbols
    ]


def test_resolve_ticker_keeps_exact_listing_over_foreign_ones(monkeypatch):
    # AAPL.TO is a Canadian depositary receipt, not the Apple share a bare "AAPL" means
    monkeypatch.setattr(engine, "search_assets", _fake_search(["AAPL.TO", "AAPL.MX", "AAPL"]))
    assert engine.resolve_ticker("AAPL", "USD")[0]["symbol"] == "AAPL"


def test_resolve_ticker_prefers_currency_exchange(monkeypatch):
    monkeypatch.setattr(engine, "search_assets", _fake_search(["VWRA.SW", "VWRA.L", "VWRA.AQ"]))
    assert [h["symbol"] for h in engine.resolve_ticker("VWRA", "USD")] == ["VWRA.L", "VWRA.SW", "VWRA.AQ"]


def test_rebase_starts_late_assets_at_their_first_price():
    dates = pd.date_range("2023-01-01", periods=4, freq="D")
    prices = pd.DataFrame({"OLD": [10.0, 11.0, 12.0, 13.0],
                           "NEW": [float("nan"), float("nan"), 50.0, 55.0]}, index=dates)
    rebased = engine.rebase(prices)
    assert rebased["OLD"].tolist() == pytest.approx([100.0, 110.0, 120.0, 130.0])
    assert rebased["NEW"].iloc[2:].tolist() == pytest.approx([100.0, 110.0])
    assert rebased["NEW"].iloc[:2].isna().all()


def test_load_prices_retries_tickers_yahoo_dropped(monkeypatch):
    dates = pd.date_range("2023-01-02", periods=3, freq="D")
    calls = []

    def fake_close_frame(tickers, start, end):
        calls.append(list(tickers))
        # the first batch download silently drops MSFT, as Yahoo sometimes does
        return pd.DataFrame({t: [1.0, 2.0, 3.0] for t in tickers if len(calls) > 1 or t != "MSFT"}, index=dates)

    monkeypatch.setattr(engine, "_close_frame", fake_close_frame)
    monkeypatch.setattr(engine, "get_currency", lambda t: "USD")
    prices, _ = engine.load_prices(["AAPL", "MSFT"], "2023-01-02", "2023-01-04", "USD")
    assert list(prices.columns) == ["AAPL", "MSFT"]
    assert calls == [["AAPL", "MSFT"], ["MSFT"]]


def _prices():
    dates = pd.date_range("2023-01-02", periods=6, freq="D")
    return pd.DataFrame({
        "OLD": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
        "NEW": [float("nan")] * 3 + [20.0, 22.0, 24.0],   # lists on day 4
        "FLAT": [5.0] * 6,
    }, index=dates)


def test_compare_pies_starts_every_pie_on_the_latest_common_date():
    res, start = engine.compare_pies(_prices(), {"A": {"OLD": 100}, "B": {"OLD": 50, "NEW": 50}},
                                     "2023-01-02", initial=1000)
    assert start == pd.Timestamp("2023-01-05")
    assert res["A"]["total"].index[0] == res["B"]["total"].index[0] == start
    # A is rebought on the common start, not carried over from the earlier run
    assert res["A"]["total"].iloc[0] == pytest.approx(1000)


def test_compare_pies_keeps_the_requested_start_when_everything_has_prices():
    res, start = engine.compare_pies(_prices(), {"A": {"OLD": 100}, "B": {"FLAT": 100}}, "2023-01-02", initial=1000)
    assert start == pd.Timestamp("2023-01-02")
    assert res["B"]["total"].iloc[-1] == pytest.approx(1000)


def test_comparison_table_has_one_row_per_pie():
    res, _ = engine.compare_pies(_prices(), {"Up": {"OLD": 100}, "Flat": {"FLAT": 100}}, "2023-01-02", initial=1000)
    table = engine.comparison_table(res)
    assert list(table["Pie"]) == ["Up", "Flat"]
    assert table.loc[0, "Final value"] == pytest.approx(1500)
    assert table.loc[0, "Return %"] == pytest.approx(50)
    assert table.loc[1, "Max drawdown %"] == pytest.approx(0)
