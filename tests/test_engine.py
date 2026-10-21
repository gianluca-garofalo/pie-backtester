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
