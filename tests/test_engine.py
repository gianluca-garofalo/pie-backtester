import numpy as np
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


def test_per_asset_gains_add_up_to_the_pies_gain():
    dates = pd.date_range("2023-01-02", periods=70, freq="D")
    prices = pd.DataFrame({"UP": [100 + i for i in range(70)],
                           "DOWN": [50 - i * 0.2 for i in range(70)]}, index=dates, dtype=float)
    res = engine.simulate_pie(prices, {"UP": 60, "DOWN": 40}, "2023-01-02", initial=1000, monthly=100,
                              rebalance="Monthly")
    table = engine.per_asset_table(res, {"UP": 60, "DOWN": 40}, {"UP": "Up", "DOWN": "Down"})
    gain = res["total"].iloc[-1] - res["invested"].iloc[-1]
    assert table["Gain"].sum() == pytest.approx(gain)
    assert table.set_index("Ticker").loc["UP", "Gain"] > 0 > table.set_index("Ticker").loc["DOWN", "Gain"]
    assert table["Drift"].tolist() == pytest.approx((table["Current %"] - table["Target %"]).tolist())
    assert len(table.loc[0, "History"]) > 1


def test_asset_name_takes_the_exact_listing(monkeypatch):
    monkeypatch.setattr(engine, "search_assets", lambda q, n=10: [
        {"symbol": "AAPL.TO", "name": "Apple CDR"}, {"symbol": "AAPL", "name": "Apple Inc."}])
    assert engine.asset_name("aapl") == "Apple Inc."
    monkeypatch.setattr(engine, "search_assets", lambda q, n=10: [])
    assert engine.asset_name("ZZZZ") == "ZZZZ"  # no match: the ticker stands in for the name


@pytest.mark.parametrize("x, text", [
    (950, "€950"), (0.5, "€0.50"), (99.999, "€100"), (12_345, "€12.3k"), (999_000, "€999k"), (5_000_000, "€5M"), (1_254_000, "€1.25M"),
    (2_500_000_000, "€2.5B"), (-6_300, "−€6.3k"),
])
def test_money_compact(x, text):
    assert engine.money(x, "EUR", compact=True) == text


def test_money_full_and_other_currencies():
    assert engine.money(5_000_000, "EUR") == "€5,000,000.00"
    assert engine.money(1_500, "SEK", compact=True) == "1.5k SEK"


def _hit(symbol, name="Vanguard FTSE All-World", type_="ETF", exchange="X"):
    return {"symbol": symbol, "name": name, "exchange": exchange, "type": type_}


def test_isin_search_adds_the_funds_other_listings_and_drops_junk(monkeypatch):
    def search(q, n=10):
        if q == "IE00BK5BQT80":
            return [_hit("VWRA.L"), _hit("IE00BK5BQT80.SG", type_="MUTUALFUND")]
        return [_hit("VWCE.DE"), _hit("VWRA.L"), _hit("VHVE.L", name="Vanguard FTSE Developed World")]
    monkeypatch.setattr(engine, "search_assets", search)
    monkeypatch.setattr(engine, "get_currency", lambda t: {"VWCE.DE": "EUR"}.get(t, "USD"))
    hits = engine.search_listings("IE00BK5BQT80")
    assert [(h["symbol"], h["currency"]) for h in hits] == [("VWRA.L", "USD"), ("VWCE.DE", "EUR")]


def test_rank_puts_etfs_in_the_pie_currency_first_and_keeps_stock_order():
    hits = [dict(_hit("VWRA.L"), currency="USD"), dict(_hit("VWCE.MX"), currency="EUR"),
            dict(_hit("VWCE.DE"), currency="EUR"), dict(_hit("SWRD.L"), currency="GBp"),
            dict(_hit("AAPL", type_="EQUITY"), currency="USD"), dict(_hit("APC.DE", type_="EQUITY"), currency="EUR")]
    assert [h["symbol"] for h in engine.rank_listings(hits, "EUR")] == \
        ["VWCE.DE", "AAPL", "APC.DE", "VWRA.L", "SWRD.L", "VWCE.MX"]  # a rare exchange goes last
    assert [h["symbol"] for h in engine.rank_listings(hits, "GBP")][0] == "SWRD.L"  # pence count as pounds


def test_etcs_count_as_funds_when_ranking():
    hits = [dict(_hit("IGLN.L", name="iShares Physical Gold ETC", type_="EQUITY"), currency="USD"),
            dict(_hit("EGLN.L", name="iShares Physical Gold ETC", type_="EQUITY"), currency="EUR")]
    assert [h["symbol"] for h in engine.rank_listings(hits, "EUR")] == ["EGLN.L", "IGLN.L"]


def test_no_infinite_return_before_the_first_deposit():
    # initial 0 and a tiny deposit split three ways: the first return used to be -inf
    days = pd.bdate_range("2020-01-01", "2020-04-30")
    prices = pd.DataFrame({t: np.linspace(10, 12, len(days)) * k for t, k in (("A", 1), ("B", 3), ("C", 7))},
                          index=days)
    res = engine.simulate_pie(prices, {"A": 33.33, "B": 33.33, "C": 33.34}, "2020-01-01", 0, 0.5)
    m = engine.metrics(res)
    assert np.isfinite(res["daily_r"]).all()
    assert all(np.isfinite(m[k]) for k in ("twr_total", "max_drawdown", "volatility"))
    assert m["twr_total"] > 0  # the prices only rose


# ---------- periods, start days, best marks ----------

from datetime import date


def test_period_start_presets():
    today = date(2026, 10, 23)
    assert engine.period_start("1Y", today, None) == date(2025, 10, 23)
    assert engine.period_start("3Y", today, None) == date(2023, 10, 23)
    assert engine.period_start("10Y", today, None) == date(2016, 10, 23)
    assert engine.period_start("5Y", date(2024, 2, 29), None) == date(2019, 2, 28)
    assert engine.period_start("Max", today, date(2004, 3, 1)) == date(2004, 3, 1)
    assert engine.period_start("Max", today, None) is None  # no pie loaded: From stays as it is


def _late_prices():
    days = pd.bdate_range("2020-01-01", "2020-06-30")
    a = pd.Series(100.0, index=days)
    b = pd.Series(50.0, index=days).where(days >= "2020-03-02")  # lists later
    return pd.DataFrame({"A": a, "B": b})


def test_first_full_day_waits_for_every_column():
    prices = _late_prices()
    assert engine.first_full_day(prices, "2020-01-01") == pd.Timestamp("2020-03-02")
    assert engine.first_full_day(prices, "2020-04-04") == pd.Timestamp("2020-04-06")  # a Saturday → Monday
    assert engine.first_full_day(prices, "2021-01-01") is None


def test_start_days_common_and_own():
    days = {"a": pd.Timestamp("2018-01-02"), "b": pd.Timestamp("2019-07-29")}
    assert engine.start_days(days, "common") == {"a": pd.Timestamp("2019-07-29"), "b": pd.Timestamp("2019-07-29")}
    assert engine.start_days(days, "own") == days
    assert engine.start_days(days, "cash") == days


def test_best_marks_need_two_pies_and_skip_nan():
    m = {
        "x": {"final_value": 17.0, "twr_total": 1.35, "cagr": 0.126, "max_drawdown": -0.334},
        "y": {"final_value": 14.1, "twr_total": 0.75, "cagr": np.nan, "max_drawdown": -0.22},
        "z": {"final_value": 25.6, "twr_total": 4.15, "cagr": 0.254, "max_drawdown": -0.297},
    }
    assert engine.best_marks(m) == {"x": set(), "y": {"max_drawdown"}, "z": {"final_value", "twr_total", "cagr"}}
    assert engine.best_marks({"x": m["x"]}) == {"x": set()}


def test_window_label():
    assert engine.window_label(pd.Timestamp("2019-07-29"), pd.Timestamp("2026-10-23")) == \
        "29 Jul 2019 – 23 Oct 2026 · 7.2 yrs"
    assert engine.window_label(pd.Timestamp("2026-05-01"), pd.Timestamp("2026-10-23")) == \
        "1 May 2026 – 23 Oct 2026 · 6 months"


def test_cash_rule_holds_cash_from_the_asked_start():
    prices = _late_prices()[["B"]]
    res = engine.simulate_pie(prices, {"B": 100}, "2020-01-01", 1000, 100, before_listing="cash")
    assert res["total"].index[0] == pd.Timestamp("2020-01-01")
    before = res["total"].loc[:"2020-02-28"]
    assert before.loc[:"2020-01-31"].eq(1000).all() and before.loc["2020-02-03":].eq(1100).all()  # cash, flat
    assert res["invested"].iloc[-1] == 1000 + 100 * 5  # Feb–Jun deposits
    assert res["units"]["B"] == pytest.approx(1200 / 50 + 300 / 50)  # cash and the March deposit buy in on 2 Mar, then Apr–Jun
