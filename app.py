"""Pie backtester — build a Trading 212-style pie and see how it would have developed.

Run with:  streamlit run app.py
"""
import json
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import engine

st.set_page_config(page_title="Pie backtester", page_icon="🥧", layout="wide")

PALETTE = ["#1F6F78", "#E0A526", "#5B4B8A", "#C8553D", "#3E8E5E", "#2E4057",
           "#B56576", "#7A9E9F", "#D98E04", "#4F5D75", "#8AA29E", "#9C6644"]

if "pie" not in st.session_state:
    st.session_state.pie = []  # list of {"Ticker", "Name", "Weight %"}
if "results" not in st.session_state:
    st.session_state.results = None
if "editor_version" not in st.session_state:
    st.session_state.editor_version = 0
if "fix_report" not in st.session_state:
    st.session_state.fix_report = None


def pie_changed():
    """Call after changing st.session_state.pie from code (not from the table)."""
    st.session_state.editor_version += 1
    st.session_state.results = None


def add_asset(symbol: str, name: str):
    if any(a["Ticker"] == symbol for a in st.session_state.pie):
        st.toast(f"{symbol} is already in the pie")
        return
    st.session_state.pie.append({"Ticker": symbol, "Name": name, "Weight %": 0.0})
    split_evenly()
    pie_changed()


def split_evenly():
    n = len(st.session_state.pie)
    if n:
        base = round(100 / n, 2)
        for a in st.session_state.pie:
            a["Weight %"] = base
        st.session_state.pie[-1]["Weight %"] = round(100 - base * (n - 1), 2)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(q):
    return engine.search_assets(q)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_resolve(t, ccy):
    return engine.resolve_ticker(t, ccy)


def fix_tickers(ccy):
    """Add exchange suffixes to bare tickers, e.g. Trading 212's VWRA -> VWRA.L."""
    changed, unresolved = [], []
    for a in st.session_state.pie:
        t = str(a["Ticker"]).strip().upper()
        if not engine.needs_suffix(t):
            continue
        hits = cached_resolve(t, ccy)
        if hits:
            best = hits[0]
            changed.append((t, best["symbol"], best["name"], best["exchange"],
                            [h["symbol"] for h in hits[1:4]]))
            a["Ticker"], a["Name"] = best["symbol"], best["name"] or best["symbol"]
        else:
            unresolved.append(t)
    st.session_state.fix_report = (changed, unresolved)
    pie_changed()


@st.cache_data(ttl=3600, show_spinner=False)
def cached_prices(tickers, start, end, base):
    return engine.load_prices(list(tickers), start, end, base)


def fmt_money(x, ccy):
    return f"{x:,.2f} {ccy}"


# ---------------- sidebar: settings ----------------
with st.sidebar:
    st.header("Settings")
    base_ccy = st.selectbox("Pie currency", ["EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN"])
    start = st.date_input("Start date", value=date(2020, 1, 1), max_value=date.today())
    end = st.date_input("End date", value=date.today(), max_value=date.today())
    initial = st.number_input(f"Initial investment ({base_ccy})", min_value=0.0, value=1000.0, step=100.0)
    monthly = st.number_input(f"Monthly deposit ({base_ccy})", min_value=0.0, value=0.0, step=50.0,
                              help="Invested on the first trading day of each month, split by target weights.")
    rebalance = st.selectbox("Rebalance to target", list(engine.REBALANCE_RULES.keys()),
                             help="Trading 212 pies don't rebalance automatically, so 'Never' matches them.")
    before_listing = st.radio("Assets younger than the start date", list(engine.BEFORE_LISTING),
                              format_func=engine.BEFORE_LISTING.get,
                              help="If one ETF launched later (e.g. in 2025), 'wait' shortens the whole backtest. "
                                   "'Cash' keeps the full period and buys that ETF once it lists.")

    st.divider()
    st.subheader("Save or load a pie")
    pie_json = json.dumps({"pie": st.session_state.pie, "currency": base_ccy}, indent=2)
    st.download_button("Download pie (.json)", pie_json, file_name="my_pie.json", mime="application/json",
                       disabled=not st.session_state.pie)
    uploaded = st.file_uploader("Load pie", type="json", label_visibility="collapsed")
    if uploaded is not None and st.button("Load this pie"):
        st.session_state.pie = json.load(uploaded).get("pie", [])
        st.session_state.fix_report = None
        pie_changed()
        st.rerun()

# ---------------- main: build the pie ----------------
st.title("🥧 Pie backtester")
st.caption("Pick ETFs and stocks, set their weights, and see how the pie would have grown. "
           "Prices come from Yahoo Finance and include reinvested dividends.")

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Add assets")
    q = st.text_input("Search by name, ticker or ISIN",
                      placeholder="e.g. IE00BK5BQT80, Vanguard FTSE All-World, AAPL")
    if q:
        hits = cached_search(q)
        if not hits:
            st.info("No matches. Try the ticker with its exchange suffix, e.g. VWCE.DE, IWDA.AS, CSPX.L.")
        else:
            labels = [f"{h['symbol']} — {h['name']} ({h['exchange']}, {h['type']})" for h in hits]
            choice = st.selectbox("Results", range(len(hits)), format_func=lambda i: labels[i])
            if st.button("Add to pie", type="primary"):
                add_asset(hits[choice]["symbol"], hits[choice]["name"])
                st.rerun()

    with st.expander("Add a ticker directly"):
        c1, c2 = st.columns([2, 1])
        manual = c1.text_input("Yahoo ticker", placeholder="VWCE.DE")
        if c2.button("Add", width="stretch") and manual.strip():
            add_asset(manual.strip().upper(), manual.strip().upper())
            st.rerun()

    st.subheader("Your pie")
    if not st.session_state.pie:
        st.info("Your pie is empty. Search for an asset above to add the first slice.")
    else:
        edited = st.data_editor(
            pd.DataFrame(st.session_state.pie, columns=["Ticker", "Name", "Weight %"]),
            num_rows="dynamic", width="stretch", hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn(required=True,
                                                      help="Yahoo symbol with exchange suffix, e.g. VWRA.L or VECP.DE"),
                "Weight %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.5, format="%.2f"),
            },
            key=f"pie_editor_{st.session_state.editor_version}",
        )
        rows = edited.dropna(subset=["Ticker"]).fillna({"Weight %": 0.0, "Name": ""})
        rows["Ticker"] = rows["Ticker"].astype(str).str.strip().str.upper()
        st.session_state.pie = rows[rows["Ticker"] != ""].to_dict("records")
        total_w = sum(float(a["Weight %"] or 0) for a in st.session_state.pie)

        bare = [a["Ticker"] for a in st.session_state.pie if engine.needs_suffix(a["Ticker"])]
        c1, c2, c3 = st.columns(3)
        if c1.button("Fix tickers", width="stretch", disabled=not bare, type="primary" if bare else "secondary",
                     help="Look up the exchange suffix Yahoo needs, e.g. VWRA → VWRA.L"):
            with st.spinner("Looking up tickers…"):
                fix_tickers(base_ccy)
            st.rerun()
        if c2.button("Split evenly", width="stretch"):
            split_evenly()
            pie_changed()
            st.rerun()
        if c3.button("Clear pie", width="stretch"):
            st.session_state.pie, st.session_state.fix_report = [], None
            pie_changed()
            st.rerun()

        if bare:
            st.warning("These tickers have no exchange suffix, so Yahoo can't find them (or finds a "
                       "different security): " + ", ".join(bare) + ". Click 'Fix tickers'.")
        if st.session_state.fix_report:
            changed, unresolved = st.session_state.fix_report
            if changed:
                lines = [f"- **{old}** → `{new}` {name} ({exch})" +
                         (f" · other listings: {', '.join(alts)}" if alts else "")
                         for old, new, name, exch, alts in changed]
                st.success("Updated tickers. Check they're the listings you hold; "
                           "you can edit any ticker in the table.\n\n" + "\n".join(lines))
            if unresolved:
                st.error("Couldn't find " + ", ".join(unresolved) +
                         ". Search for them by ISIN above and replace them.")

        if abs(total_w - 100) > 0.01:
            st.warning(f"Weights add up to {total_w:.2f}%. They need to add up to 100%.")

with right:
    if st.session_state.pie:
        dfp = pd.DataFrame(st.session_state.pie)
        dfp = dfp[dfp["Weight %"] > 0]
        if not dfp.empty:
            fig = go.Figure(go.Pie(labels=dfp["Ticker"], values=dfp["Weight %"], hole=0.55,
                                   marker=dict(colors=PALETTE), sort=False,
                                   hovertext=dfp["Name"], hovertemplate="%{label}<br>%{hovertext}<br>%{value:.2f}%<extra></extra>"))
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340, showlegend=True,
                              annotations=[dict(text="Target", x=0.5, y=0.5, showarrow=False, font_size=16)])
            st.plotly_chart(fig)

# ---------------- run ----------------
pie = [a for a in st.session_state.pie if float(a["Weight %"] or 0) > 0]
ready = pie and abs(sum(float(a["Weight %"]) for a in pie) - 100) <= 0.01 and start < end
if st.button("Run backtest", type="primary", disabled=not ready, width="stretch"):
    if any(engine.needs_suffix(a["Ticker"]) for a in pie):
        with st.spinner("Adding exchange suffixes to your tickers…"):
            fix_tickers(base_ccy)
        st.session_state.autorun = True
        st.rerun()
    st.session_state.autorun = True
if st.session_state.pop("autorun", False):
    pie = [a for a in st.session_state.pie if float(a["Weight %"] or 0) > 0]
    still_bare = [a["Ticker"] for a in pie if engine.needs_suffix(a["Ticker"])]
    if still_bare:
        st.error("Couldn't find a listing for " + ", ".join(still_bare) +
                 ". Search for them by ISIN above, add the right listing and remove the old row.")
        st.stop()
    tickers = tuple(a["Ticker"] for a in pie)
    weights = {a["Ticker"]: float(a["Weight %"]) for a in pie}
    names = {a["Ticker"]: a.get("Name") or a["Ticker"] for a in pie}
    try:
        with st.spinner("Loading prices and simulating…"):
            prices, info = cached_prices(tickers, start, end, base_ccy)
            first_valid = engine.first_price_dates(prices[list(tickers)], start)
            res = engine.simulate_pie(prices, weights, start, initial, monthly, rebalance, before_listing)
        st.session_state.results = dict(res=res, weights=weights, names=names, info=info,
                                        first_valid=first_valid, ccy=base_ccy, start=start,
                                        before_listing=before_listing)
    except Exception as e:
        st.session_state.results = None
        st.error(f"Backtest failed: {e}")

# ---------------- results ----------------
R = st.session_state.results
if R:
    res, ccy = R["res"], R["ccy"]
    m = engine.metrics(res)
    actual_start = res["total"].index[0].date()
    fv = R["first_valid"].dropna()
    late = fv[fv.dt.date > R["start"] + pd.Timedelta(days=7)].sort_values(ascending=False)
    if len(late):
        listed = ", ".join(f"{t} ({d.date()})" for t, d in late.items())
        if R["before_listing"] == "wait":
            st.warning(f"The backtest starts on {actual_start}, not {R['start']}, because these assets "
                       f"have no earlier prices: {listed}. To use the full period, choose "
                       "'Hold … as cash' in the sidebar.")
        else:
            st.info(f"These assets were held as cash until their first price: {listed}.")

    st.divider()
    st.subheader(f"{actual_start} to {res['total'].index[-1].date()}")
    k = st.columns(5)
    k[0].metric("Value", fmt_money(m["final_value"], ccy), f"{m['profit']:+,.2f} {ccy}")
    k[1].metric("Invested", fmt_money(m["invested"], ccy))
    k[2].metric("Return (time-weighted)", f"{m['twr_total']*100:.1f}%",
                help="Performance of the pie itself, ignoring when deposits were made.")
    k[3].metric("Yearly return (CAGR)", "—" if pd.isna(m["cagr"]) else f"{m['cagr']*100:.1f}%")
    k[4].metric("Max drawdown", f"{m['max_drawdown']*100:.1f}%",
                help=f"Largest drop from a peak. Volatility: {m['volatility']*100:.1f}% a year.")

    tab1, tab2, tab3, tab4 = st.tabs(["Value", "By asset", "Drawdown", "Holdings"])
    with tab1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=res["total"].index, y=res["total"], name="Pie value",
                                 line=dict(color=PALETTE[0], width=2.5)))
        fig.add_trace(go.Scatter(x=res["invested"].index, y=res["invested"], name="Invested",
                                 line=dict(color="#888", dash="dot", shape="hv")))
        fig.update_layout(height=450, hovermode="x unified", yaxis_title=ccy,
                          margin=dict(t=20, b=20), legend=dict(orientation="h", y=1.08))
        st.plotly_chart(fig)
    with tab2:
        vals = res["values"].rename(columns=R["names"])
        fig = px.area(vals, color_discrete_sequence=PALETTE)
        fig.update_layout(height=450, hovermode="x unified", yaxis_title=ccy, legend_title="",
                          margin=dict(t=20, b=20))
        st.plotly_chart(fig)
        norm = (res["prices"] / res["prices"].iloc[0] * 100).rename(columns=R["names"])
        fig2 = px.line(norm, color_discrete_sequence=PALETTE, title="Each asset, rebased to 100")
        fig2.update_layout(height=380, hovermode="x unified", legend_title="", yaxis_title="")
        st.plotly_chart(fig2)
    with tab3:
        dd = (res["twr"] / res["twr"].cummax() - 1) * 100
        fig = go.Figure(go.Scatter(x=dd.index, y=dd, fill="tozeroy", line=dict(color="#C8553D")))
        fig.update_layout(height=380, yaxis_title="% below previous peak", margin=dict(t=20, b=20))
        st.plotly_chart(fig)
    with tab4:
        table = engine.per_asset_table(res, R["weights"], R["names"])
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "Target %": st.column_config.NumberColumn(format="%.1f"),
            "Current %": st.column_config.NumberColumn(format="%.1f"),
            "Value": st.column_config.NumberColumn(format=f"%.2f {ccy}"),
            "Price return %": st.column_config.NumberColumn(format="%.1f"),
        })
        st.caption("Currencies of the listings: " +
                   ", ".join(f"{t} {c}" for t, c in R["info"]["currencies"].items()) +
                   f". All values are converted to {ccy} with daily FX rates.")
        csv = pd.concat([res["values"], res["total"].rename("Total"),
                         res["invested"].rename("Invested")], axis=1).to_csv()
        st.download_button("Download daily values (.csv)", csv, "pie_history.csv", "text/csv")

    st.caption("Assumes fractional shares, no fees or taxes, and dividends reinvested. "
               "Past performance doesn't predict future returns.")
