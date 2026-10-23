"""Data fetching and pie simulation, kept separate from the UI so it can be tested."""
from __future__ import annotations

import numpy as np
import pandas as pd
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # we report missing tickers ourselves


# ---------- data ----------

def search_assets(query: str, max_results: int = 10) -> list[dict]:
    """Search Yahoo Finance by name, ticker or ISIN (e.g. 'IE00BK5BQT80' or 'vanguard all world')."""
    try:
        quotes = yf.Search(query, max_results=max_results).quotes
    except Exception:
        return []
    out = []
    for q in quotes:
        if q.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND", "INDEX"):
            out.append({
                "symbol": q.get("symbol"),
                "name": q.get("longname") or q.get("shortname") or "",
                "exchange": q.get("exchDisp") or q.get("exchange") or "",
                "type": q.get("quoteType"),
            })
    return out


def asset_name(ticker: str) -> str:
    """The listing's name on Yahoo, for pies that arrive without names (short share links)."""
    hits = [h for h in search_assets(ticker, 5) if (h["symbol"] or "").upper() == ticker.upper()]
    return hits[0]["name"] if hits and hits[0]["name"] else ticker


# Preferred Yahoo exchange suffixes when a ticker comes without one (e.g. from Trading 212).
EXCHANGE_PREFERENCE = {
    "EUR": [".DE", ".AS", ".PA", ".MI", ".L", ".SW"],
    "GBP": [".L", ".DE", ".AS", ".PA", ".MI", ".SW"],
    "USD": [".L", ".DE", ".AS", ".SW", ".PA", ".MI"],
}


ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
# exchanges few European or US investors buy on; their listings go to the end of the results
RARE_EXCHANGES = (".MX", ".SG", ".XD", ".XC", ".CL", ".BA", ".SA", ".NE", ".VI", ".HM", ".DU", ".MU", ".BE")


def search_listings(query: str) -> list[dict]:
    """Search results with each listing's currency. For an ISIN, the same fund's other listings
    are added (Yahoo often returns only one of them), and junk entries named after the ISIN go."""
    hits = search_assets(query, 10)
    if ISIN.match(query.strip().upper()) and hits:
        name = hits[0]["name"].casefold()
        hits += [h for h in search_assets(hits[0]["name"], 15)
                 if h["name"].casefold() == name and h["symbol"] not in {x["symbol"] for x in hits}]
    hits = [h for h in hits if h["symbol"] and not ISIN.match(h["symbol"].split(".")[0].upper())]
    with ThreadPoolExecutor(8) as pool:  # one lookup per listing; in parallel they take about as long as one
        currencies = list(pool.map(get_currency, [h["symbol"] for h in hits]))
    return [dict(h, currency=c) for h, c in zip(hits, currencies)]


def rank_listings(hits: list[dict], base_ccy: str) -> list[dict]:
    """Funds (ETFs, ETCs) in the pie's currency first (a euro investor wants VWCE.DE, not VWRA.L); stocks keep
    Yahoo's order, which puts the home listing first (AAPL above AAPL.TO). Rare exchanges go last."""
    def key(item):
        i, h = item
        cur = {"GBP": "GBP", "GBp": "GBP", "GBX": "GBP"}.get(h.get("currency"), h.get("currency"))
        # Yahoo files ETCs (gold, commodities) as equities, so the name tells funds apart too
        fund = h["type"] == "ETF" or re.search(r"\b(ETC|ETN|UCITS)\b", h["name"], re.I)
        other_currency = bool(fund) and cur != base_ccy
        return (h["symbol"].upper().endswith(RARE_EXCHANGES), other_currency, i)
    return [h for _, h in sorted(enumerate(hits), key=key)]


def needs_suffix(ticker: str) -> bool:
    """European ETFs on Yahoo need an exchange suffix (VWRA -> VWRA.L)."""
    return "." not in ticker and "=" not in ticker and "^" not in ticker


def resolve_ticker(ticker: str, base_ccy: str = "EUR") -> list[dict]:
    """Candidate Yahoo symbols for a bare ticker, best first."""
    t = ticker.strip().upper()
    hits = [h for h in search_assets(t, 15) if h["symbol"] and h["symbol"].split(".")[0].upper() == t]
    pref = EXCHANGE_PREFERENCE.get(base_ccy.upper(), EXCHANGE_PREFERENCE["EUR"])

    def rank(h):
        # preferred exchanges first, then the exact bare listing (e.g. US AAPL),
        # then anything else (e.g. AAPL.TO, a Canadian depositary receipt)
        sym = h["symbol"].upper()
        suffix = sym[len(t):]
        return pref.index(suffix) if suffix in pref else len(pref) + (1 if suffix else 0)

    hits = sorted(hits, key=rank)
    if hits:
        return hits
    # Search found nothing: try the usual European listings directly and keep the ones with prices.
    cands = [t + suf for suf in pref]
    try:
        data = yf.download(cands, period="1mo", auto_adjust=True, progress=False, group_by="column")
        close = data["Close"] if data is not None and not data.empty else pd.DataFrame()
    except Exception:
        close = pd.DataFrame()
    return [{"symbol": c, "name": c, "exchange": c.split(".")[-1], "type": "ETF"}
            for c in cands if c in getattr(close, "columns", []) and close[c].notna().any()]


def get_currency(ticker: str) -> str:
    try:
        cur = yf.Ticker(ticker).fast_info["currency"]
        return cur or "USD"
    except Exception:
        return "USD"


def _close_frame(tickers: list[str], start, end) -> pd.DataFrame:
    """Adjusted (dividends reinvested) daily closes, one column per ticker."""
    data = yf.download(tickers, start=start, end=end, auto_adjust=True,
                       progress=False, group_by="column", threads=True)
    if data is None or data.empty:
        return pd.DataFrame()
    close = data["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close


def load_prices(tickers: list[str], start, end, base_ccy: str = "EUR") -> tuple[pd.DataFrame, dict]:
    """Prices converted into base currency. Returns (prices, info) where info holds currencies."""
    end_excl = pd.Timestamp(end) + pd.Timedelta(days=1)  # yfinance end is exclusive
    # fetch a little earlier so the first day has a value after forward-filling
    fetch_start = pd.Timestamp(start) - pd.Timedelta(days=10)
    raw = _close_frame(tickers, fetch_start, end_excl)
    if raw.empty:
        bare = [t for t in tickers if needs_suffix(t)]
        hint = (" Tickers like " + ", ".join(bare) + " need an exchange suffix on Yahoo "
                "(e.g. VWRA.L, VECP.DE). Use 'Fix tickers' to look them up.") if bare else ""
        raise ValueError("No prices found for any asset." + hint)

    missing = [t for t in tickers if t not in raw.columns or raw[t].dropna().empty]
    if missing:  # batch downloads sometimes drop a ticker; ask for those once more
        retry = _close_frame(missing, fetch_start, end_excl)
        if not retry.empty:
            raw = raw.drop(columns=[c for c in retry.columns if c in raw.columns]).join(retry, how="outer")
        missing = [t for t in tickers if t not in raw.columns or raw[t].dropna().empty]
    if missing:
        bare = [t for t in missing if needs_suffix(t)]
        hint = (" Tickers like " + ", ".join(bare) + " need an exchange suffix on Yahoo "
                "(e.g. VWRA.L, VECP.DE). Use 'Fix tickers' to look them up.") if bare else ""
        raise ValueError("No prices found for " + ", ".join(missing) + "." + hint)

    currencies = {t: get_currency(t) for t in tickers}
    prices = pd.DataFrame(index=raw.index)
    fx_rates = {}  # one download per currency, however many tickers use it
    for t in tickers:
        s = raw[t].astype(float)
        cur = currencies[t]
        if cur in ("GBp", "GBX"):  # London quotes in pence
            s, cur = s / 100.0, "GBP"
        if cur.upper() != base_ccy.upper():
            if cur.upper() not in fx_rates:
                fx_rates[cur.upper()] = _close_frame([f"{cur.upper()}{base_ccy.upper()}=X"], fetch_start, end_excl)
            fx = fx_rates[cur.upper()]
            if fx.empty:
                raise ValueError(f"Could not load FX rate {cur}->{base_ccy}.")
            fx = fx.iloc[:, 0].reindex(s.index).ffill().bfill()
            s = s * fx
        prices[t] = s
    prices = prices.ffill()
    return prices, {"currencies": currencies}


# ---------- simulation ----------

REBALANCE_RULES = {"Never": None, "Monthly": "M", "Quarterly": "Q", "Yearly": "Y"}
BEFORE_LISTING = {
    "wait": "Start when all have prices",
    "cash": "Hold their slice as cash",
}


def _period_starts(index: pd.DatetimeIndex, freq: str | None) -> set:
    if freq is None:
        return set()
    s = pd.Series(index, index=index)
    firsts = s.groupby(index.to_period(freq)).first()
    return set(firsts.iloc[1:])  # skip the very first period (that's the initial buy)


PERIOD_PRESETS = ("1Y", "3Y", "5Y", "10Y", "Max")
# how compared pies start when an asset lists after From: all on the same day (the latest first price),
# each on its own first price, or all on From with a later asset's slice held as cash
START_RULES = ("common", "own", "cash")


def period_start(preset: str, today, earliest):
    """The From date a period preset sets: today minus n years (29 Feb becomes 28 Feb), or for Max the
    earliest price of any loaded asset. None when there's nothing to set (Max with no pie loaded)."""
    if preset == "Max":
        return earliest
    return (pd.Timestamp(today) - pd.DateOffset(years=int(preset[:-1]))).date()


def first_full_day(prices: pd.DataFrame, start):
    """The first day on or after start on which every column has a price, or None."""
    full = prices.loc[pd.Timestamp(start):].dropna(how="any")
    return full.index[0] if not full.empty else None


def start_days(first_days: dict, rule: str) -> dict:
    """The day each pie starts on: the latest first day for every pie with the common rule, otherwise
    each pie's own (with cash, that's From for every pie)."""
    if rule == "common" and first_days:
        latest = max(first_days.values())
        return {name: latest for name in first_days}
    return dict(first_days)


BEST = ("final_value", "twr_total", "cagr", "max_drawdown")  # higher is better, also for the (negative) worst fall


def best_marks(by_pie: dict[str, dict]) -> dict[str, set]:
    """For each pie, the metrics it's best at among the pies; nothing with fewer than two pies."""
    marks = {name: set() for name in by_pie}
    if len(by_pie) < 2:
        return marks
    for key in BEST:
        values = {n: m[key] for n, m in by_pie.items() if not pd.isna(m[key])}
        if values:
            marks[max(values, key=values.get)].add(key)
    return marks


def window_label(first, last) -> str:
    """'29 Jul 2019 – 23 Oct 2026 · 7.2 yrs', or '· 5 months' under a year."""
    first, last = pd.Timestamp(first), pd.Timestamp(last)
    years = (last - first).days / 365.25
    length = f"{years:.1f} yrs" if years >= 1 else f"{round(years * 12)} months"
    return f"{first.day} {first:%b %Y} – {last.day} {last:%b %Y} · {length}"


def first_price_dates(prices: pd.DataFrame, start) -> pd.Series:
    return prices.loc[pd.Timestamp(start):].apply(lambda s: s.first_valid_index())


def rebase(prices: pd.DataFrame, base: float = 100.0) -> pd.DataFrame:
    """Each column relative to its own first price, so late-listing assets still show up."""
    return prices / prices.bfill().iloc[0] * base


def simulate_pie(prices: pd.DataFrame, weights: dict[str, float], start, initial: float,
                 monthly: float = 0.0, rebalance: str = "Never", before_listing: str = "wait") -> dict:
    """Simulate a Trading 212-style pie.

    - Initial amount is split by target weights on the first trading day >= start.
    - Monthly contribution is invested on the first trading day of each month,
      split by target weights (like Trading 212 auto-invest).
    - Optional rebalancing back to target weights at the start of each period.
    - before_listing="cash": the pie starts on the first business day on or after start, even before
      any asset has a price; an asset without prices yet keeps its slice as cash (0% return) and
      buys in on its first trading day.
    - Fractional shares, no fees, dividends reinvested (adjusted prices).
    """
    w = pd.Series(weights, dtype=float)
    w = w / w.sum()
    px = prices[w.index].loc[pd.Timestamp(start):]
    px = px.dropna(how="any") if before_listing == "wait" else px.dropna(how="all")
    if px.empty:
        raise ValueError("No price data for these assets from the chosen start date.")
    if before_listing == "cash":  # all cash from the asked start until the first price
        px = px.reindex(px.index.union(pd.bdate_range(pd.Timestamp(start), px.index[0], inclusive="left")))

    idx = px.index
    month_starts = _period_starts(idx, "M")
    rebal_days = _period_starts(idx, REBALANCE_RULES[rebalance])

    units = pd.Series(0.0, index=w.index)
    cash = initial * w  # every slice starts as cash and buys in when it has a price
    invested = initial
    rows_units, rows_cash, rows_invested, flows = [], [], [], []

    for day in idx:
        p = px.loc[day]
        live = p.notna()
        flow = 0.0
        if day in rebal_days:
            total = float((units[live] * p[live]).sum() + cash.sum())
            units = pd.Series(0.0, index=w.index)
            cash = total * w
        if monthly > 0 and day in month_starts:
            cash = cash + monthly * w
            invested += monthly
            flow = monthly
        buy = live & (cash > 0)
        units[buy] += cash[buy] / p[buy]
        cash[buy] = 0.0
        rows_units.append(units.copy())
        rows_cash.append(cash.copy())
        rows_invested.append(invested)
        flows.append(flow)

    units_df = pd.DataFrame(rows_units, index=idx)
    cash_df = pd.DataFrame(rows_cash, index=idx)
    values = (units_df * px).fillna(0.0) + cash_df
    total = values.sum(axis=1)
    invested_s = pd.Series(rows_invested, index=idx)
    flows_s = pd.Series(flows, index=idx)

    # time-weighted return index (removes the effect of contributions)
    # No return while nothing is invested yet (initial 0, waiting for the first deposit): dividing by
    # a value of 0 gave inf, or -inf from a rounding remainder of a tiny deposit split three ways.
    prev = total.shift(1)
    daily_r = ((total - flows_s) / prev - 1).where(prev > 1e-9, 0.0)
    daily_r.iloc[0] = 0.0
    twr = (1 + daily_r).cumprod()

    return {
        "values": values, "total": total, "invested": invested_s,
        "twr": twr, "daily_r": daily_r, "units": units_df.iloc[-1], "units_daily": units_df, "prices": px,
    }


CURRENCY_SIGNS = {"EUR": "€", "USD": "$", "GBP": "£"}


def money(x: float, ccy: str, compact: bool = False) -> str:
    """€12,345.67, or short when compact (tiles and labels; tables keep full values):
    €950, €0.50, €12.3k, €5M, €1.25M, €2.5B."""
    sign = CURRENCY_SIGNS.get(ccy, "")
    text = f"{abs(x):,.2f}"
    if compact:
        # under 1,000 cents show when there are any: a €0.50 deposit isn't "€0"
        text = f"{abs(x):,.0f}" if round(abs(x), 2) == round(abs(x)) else f"{abs(x):,.2f}"
        for size, suffix, decimals in ((1e9, "B", 2), (1e6, "M", 2), (1e3, "k", 1)):
            if abs(x) >= size:
                text = f"{abs(x) / size:.{decimals}f}".rstrip("0").rstrip(".") + suffix
                break
    text = f"{sign}{text}" if sign else f"{text} {ccy}"
    return f"−{text}" if x < 0 else text


def value_on(earlier: list[dict], day) -> tuple[float, float]:
    """The average value and amount put in of earlier-starting pies on a day.

    A compared pie that starts later begins with this value, as if you had moved the money
    into it then, so every pie's line and "You put in" stay comparable.
    """
    values = [float(r["total"].asof(pd.Timestamp(day))) for r in earlier]
    invested = [float(r["invested"].asof(pd.Timestamp(day))) for r in earlier]
    return sum(values) / len(values), sum(invested) / len(invested)


def metrics(res: dict) -> dict:
    total, invested, twr, r = res["total"], res["invested"], res["twr"], res["daily_r"]
    years = max((total.index[-1] - total.index[0]).days / 365.25, 1e-9)
    dd = twr / twr.cummax() - 1
    return {
        "final_value": float(total.iloc[-1]),
        "invested": float(invested.iloc[-1]),
        "profit": float(total.iloc[-1] - invested.iloc[-1]),
        "twr_total": float(twr.iloc[-1] - 1),
        "cagr": float(twr.iloc[-1] ** (1 / years) - 1) if years >= 1 else np.nan,
        "volatility": float(r.iloc[1:].std() * np.sqrt(252)),
        "max_drawdown": float(dd.min()),
        "years": years,
    }


def comparison_table(results: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for name, res in results.items():
        m = metrics(res)
        rows.append({
            "Pie": name,
            "From": res["total"].index[0].date(),
            "Final value": m["final_value"],
            "Invested": m["invested"],
            "Return %": m["twr_total"] * 100,
            "CAGR %": m["cagr"] * 100,
            "Max drawdown %": m["max_drawdown"] * 100,
            "Volatility %": m["volatility"] * 100,
        })
    return pd.DataFrame(rows)


def per_asset_table(res: dict, weights: dict[str, float], names: dict[str, str]) -> pd.DataFrame:
    px = res["prices"]
    last_vals = res["values"].iloc[-1]
    w = pd.Series(weights, dtype=float)
    w = w / w.sum()
    # gain per asset: units held overnight times the next day's price move, so the gains add up to
    # the pie's value minus what was put in, whatever the deposits and rebalancing did
    daily_gain = (res["units_daily"].shift(1) * px.diff()).fillna(0.0)
    history = res["values"].resample("W").last()
    return pd.DataFrame({
        "Asset": [names.get(t, t) for t in w.index],
        "Ticker": w.index,
        "Target %": (w * 100).values,
        "Current %": (last_vals / last_vals.sum() * 100).reindex(w.index).values,
        "Value": last_vals.reindex(w.index).values,
        "Price return %": ((px.ffill().iloc[-1] / px.bfill().iloc[0] - 1) * 100).reindex(w.index).values,
        "Gain": daily_gain.sum().reindex(w.index).values,
        "Drift": ((last_vals / last_vals.sum() * 100).reindex(w.index) - w * 100).values,
        "History": [history[t].tolist() for t in w.index],
    })
