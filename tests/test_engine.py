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
