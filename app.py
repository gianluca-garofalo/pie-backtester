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
import storage
import sharing
import auth

st.set_page_config(page_title="Pie backtester", page_icon="🥧", layout="wide")

PALETTE = ["#1F6F78", "#E0A526", "#5B4B8A", "#C8553D", "#3E8E5E", "#2E4057",
           "#B56576", "#7A9E9F", "#D98E04", "#4F5D75", "#8AA29E", "#9C6644"]
# one colour per pie, kept for as long as the pie is loaded (Okabe-Ito, colour-blind safe;
# same list as chartCategoricalColors in .streamlit/config.toml)
PIE_COLORS = ["#0072B2", "#B86E00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9"]

if "pie" not in st.session_state:
    st.session_state.pie = []  # list of {"Ticker", "Name", "Weight %"}
if "editor_version" not in st.session_state:
    st.session_state.editor_version = 0
if "fix_report" not in st.session_state:
    st.session_state.fix_report = None
if "verified_tickers" not in st.session_state:
    st.session_state.verified_tickers = set()  # bare tickers Yahoo knows as-is, e.g. AAPL
if "compare" not in st.session_state:
    st.session_state.compare = []  # other pies to compare with yours: {"name", "weights", "names", "color"}
st.session_state.setdefault("pie_name", "My Pie")  # name of the pie in the table
st.session_state.setdefault("own_color", PIE_COLORS[0])

MAX_COMPARED = 5  # pies in one comparison, including yours

CURRENCIES = ["EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN"]
# sidebar settings, keyed so a loaded pie can set them
for _key, _default in {"base_ccy": "EUR", "start": date(2020, 1, 1), "end": date.today(),
                       "initial": 1000.0, "monthly": 0.0, "rebalance": "Never",
                       "before_listing": "wait"}.items():
    st.session_state.setdefault(_key, _default)


def free_color(taken):
    """The first pie colour no loaded pie uses."""
    return next((c for c in PIE_COLORS if c not in taken), PIE_COLORS[len(taken) % len(PIE_COLORS)])


def pie_changed():
    """Call after changing st.session_state.pie from code (not from the table)."""
    st.session_state.editor_version += 1


def load_pie(cfg):
    """Replace the pie and the sidebar settings with a normalized pie config.

    The pie being replaced moves to the comparison (if it's complete and not the same pie),
    so loading several pies one after another compares them; ✕ removes one.
    """
    previous = {a["Ticker"]: float(a["Weight %"] or 0) for a in st.session_state.pie if float(a["Weight %"] or 0) > 0}
    loaded = {str(a["ticker"]).upper(): float(a["weight"]) for a in cfg.get("assets", []) if float(a["weight"]) > 0}
    if previous and abs(sum(previous.values()) - 100) <= 0.01 and previous != loaded:
        add_to_comparison({"name": st.session_state.pie_name,
                           "assets": [{"ticker": a["Ticker"], "weight": a["Weight %"], "name": a.get("Name")}
                                      for a in st.session_state.pie if a["Ticker"] in previous]},
                          color=st.session_state.own_color)
    st.session_state.compare = [e for e in st.session_state.compare if e["weights"] != loaded]
    st.session_state.own_color = free_color({e.get("color") for e in st.session_state.compare})
    st.session_state.pie_name = cfg.get("name") or "My Pie"
    st.session_state.pie = [
        {"Ticker": a["ticker"], "Name": a["name"], "Weight %": a["weight"]}
        for a in cfg.get("assets", [])
    ]
    st.session_state.fix_report = None
    # widgets are already drawn this run, so their new values are applied on the next one
    pending = {"initial": float(cfg.get("initial", 1000.0)), "monthly": float(cfg.get("monthly", 0.0))}
    if cfg.get("currency") in CURRENCIES:
        pending["base_ccy"] = cfg["currency"]
    if cfg.get("rebalance") in engine.REBALANCE_RULES:
        pending["rebalance"] = cfg["rebalance"]
    if cfg.get("before_listing") in engine.BEFORE_LISTING:
        pending["before_listing"] = cfg["before_listing"]
    for key in ("start", "end"):
        try:
            d = date.fromisoformat(str(cfg.get(key)))
        except ValueError:  # no end date means "up to date"; no start keeps the current one
            if key == "end":
                pending["end"] = date.today()
            continue
        pending[key] = min(d, date.today())
    st.session_state.pending_settings = pending
    pie_changed()


def close_open_pie():
    """✕ on the pie being edited: drop it and open the most recently compared pie instead."""
    if not st.session_state.compare:
        st.session_state.pie = []
    else:
        e = st.session_state.compare.pop()
        st.session_state.pie = [{"Ticker": t, "Name": e.get("names", {}).get(t, t), "Weight %": w}
                                for t, w in e["weights"].items()]
        st.session_state.pie_name = e["name"]
        st.session_state.own_color = e.get("color") or st.session_state.own_color
    st.session_state.fix_report = None
    pie_changed()


def open_compared(i):
    """Click on a compared pie: it opens in the table, and the pie being edited takes its place."""
    e = st.session_state.compare[i]
    current = {a["Ticker"]: float(a["Weight %"] or 0) for a in st.session_state.pie if float(a["Weight %"] or 0) > 0}
    if current:
        st.session_state.compare[i] = {
            "name": st.session_state.pie_name, "weights": current, "color": st.session_state.own_color,
            "names": {a["Ticker"]: a.get("Name") or a["Ticker"] for a in st.session_state.pie if a["Ticker"] in current}}
    else:
        st.session_state.compare.pop(i)
    st.session_state.pie = [{"Ticker": t, "Name": e.get("names", {}).get(t, t), "Weight %": w}
                            for t, w in e["weights"].items()]
    st.session_state.pie_name = e["name"]
    st.session_state.own_color = e.get("color") or st.session_state.own_color
    st.session_state.fix_report = None
    pie_changed()


def scale_to_100():
    """Keep the proportions, make the weights add up to exactly 100%."""
    total = sum(float(a["Weight %"] or 0) for a in st.session_state.pie)
    for a in st.session_state.pie:
        a["Weight %"] = round(float(a["Weight %"] or 0) * 100 / total, 2)
    biggest = max(st.session_state.pie, key=lambda a: a["Weight %"])
    biggest["Weight %"] = round(biggest["Weight %"] + 100 - sum(a["Weight %"] for a in st.session_state.pie), 2)
    st.toast(f"Scaled the weights from {total:.2f}% to 100%.")
    pie_changed()


def shades(color, n):
    """n shades of one colour, darkest first: the slices of a pie's donut."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    out = []
    for i in range(n):
        f = 0.7 * i / max(n - 1, 1)  # mix in up to 70% white
        out.append("#%02x%02x%02x" % tuple(round(c + (255 - c) * f) for c in (r, g, b)))
    return out


def flash(kind, msg):
    """Show a message after the st.rerun() that usually follows."""
    st.session_state.flash = (kind, msg)


# Check for share link in query params on initial load
if "loaded_query_pie" not in st.session_state:
    st.session_state.loaded_query_pie = True
    qp_pie = st.query_params.get("pie")
    if qp_pie:
        decoded = sharing.decode_pie_from_query_param(qp_pie)
        if decoded:
            load_pie(decoded)
        else:
            flash("error", "This share link is invalid or damaged, so no pie was loaded.")

for _key, _value in st.session_state.pop("pending_settings", {}).items():
    st.session_state[_key] = _value


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


def is_bare(ticker):
    """A ticker without exchange suffix that we haven't confirmed Yahoo knows as-is."""
    return engine.needs_suffix(ticker) and ticker not in st.session_state.verified_tickers


def fix_tickers(ccy):
    """Add exchange suffixes to bare tickers, e.g. Trading 212's VWRA -> VWRA.L."""
    changed, unresolved = [], []
    for a in st.session_state.pie:
        t = str(a["Ticker"]).strip().upper()
        if not is_bare(t):
            continue
        hits = cached_resolve(t, ccy)
        if not hits:
            unresolved.append(t)
            continue
        best = hits[0]
        if best["symbol"].upper() == t:  # a real listing without suffix, e.g. US stocks
            st.session_state.verified_tickers.add(t)
            continue
        changed.append((t, best["symbol"], best["name"], best["exchange"],
                        [h["symbol"] for h in hits[1:4]]))
        a["Ticker"], a["Name"] = best["symbol"], best["name"] or best["symbol"]
    st.session_state.fix_report = (changed, unresolved)
    pie_changed()


@st.cache_data(ttl=3600, show_spinner=False)
def cached_ticker_prices(ticker, start, end, base):
    return engine.load_prices([ticker], start, end, base)


def prices_for(tickers, start, end, base):
    """Prices in the base currency, cached per ticker so adding a pie only downloads its new tickers."""
    frames, currencies = [], {}
    for t in dict.fromkeys(tickers):
        prices, info = cached_ticker_prices(t, start, end, base)
        frames.append(prices)
        currencies.update(info["currencies"])
    # exchanges trade on different days; carry each price forward like a single download would
    return pd.concat(frames, axis=1).sort_index().ffill(), {"currencies": currencies}


def add_to_comparison(cfg, color=None):
    """Add a normalized pie config to the comparison list. Bare tickers get their Yahoo listing."""
    others = st.session_state.compare
    if len(others) >= MAX_COMPARED - 1:
        flash("warning", f"'{cfg.get('name') or 'Pie'}' wasn't kept: you can compare up to {MAX_COMPARED} "
                         "pies, including yours. Remove one with ✕ first.")
        return
    weights, names = {}, {}
    for a in cfg.get("assets", []):
        t = str(a["ticker"]).strip().upper()
        name = a.get("name") or t
        if is_bare(t) and (hits := cached_resolve(t, st.session_state.base_ccy)):
            if hits[0]["symbol"].upper() == t:
                st.session_state.verified_tickers.add(t)
            t = hits[0]["symbol"]
        weights[t] = weights.get(t, 0.0) + float(a["weight"])
        names.setdefault(t, name)
    weights = {t: w for t, w in weights.items() if w > 0}
    if any(e["weights"] == weights for e in others):
        return  # already compared
    taken = {e["name"] for e in others}
    name, n = cfg.get("name") or "Pie", 2
    while name in taken:
        name, n = f"{cfg.get('name') or 'Pie'} ({n})", n + 1
    color = color or free_color({e.get("color") for e in others} | {st.session_state.own_color})
    others.append({"name": name, "weights": weights, "names": {t: names[t] for t in weights}, "color": color})


@st.cache_data(ttl=3600, show_spinner=False)
def cached_backtest(assets, start, end, base, initial, monthly, rebalance, before_listing):
    """One pie, cached on its own so changing one pie or setting doesn't re-run the others.

    assets: ((ticker, weight), ...). Returns (result, {late ticker: first price date}, currencies).
    """
    weights = dict(assets)
    prices, info = prices_for(list(weights), start, end, base)
    res = engine.simulate_pie(prices, weights, start, initial, monthly, rebalance, before_listing)
    first = engine.first_price_dates(prices[list(weights)], start).dropna()
    late = {t: d.date() for t, d in first.items() if d.date() > start + pd.Timedelta(days=7)}
    return res, late, info["currencies"]


def pie_payload(name=None):
    """The current pie and settings in the shared pie schema (see storage.validate_pie)."""
    return {
        "version": 1,
        "name": name or st.session_state.pie_name,
        "currency": st.session_state.base_ccy,
        "assets": [
            {"ticker": a["Ticker"], "weight": float(a["Weight %"] or 0), "name": a.get("Name") or ""}
            for a in st.session_state.pie
        ],
        "start": st.session_state.start.isoformat(),
        # an end of "today" means "up to date" when the pie is loaded later
        "end": None if st.session_state.end >= date.today() else st.session_state.end.isoformat(),
        "initial": st.session_state.initial,
        "monthly": st.session_state.monthly,
        "rebalance": st.session_state.rebalance,
        "before_listing": st.session_state.before_listing,
    }


# Determine active storage backend
try:
    supabase_url = st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase", {}).get("url")
    # the server-side service key: the app itself scopes every query to the signed-in user
    supabase_key = st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("supabase", {}).get("service_key")
    legacy_anon_key = bool(st.secrets.get("SUPABASE_KEY") or st.secrets.get("supabase", {}).get("key"))
except Exception:
    supabase_url = supabase_key = None
    legacy_anon_key = False
active_storage = storage.get_storage(url=supabase_url, key=supabase_key)
shared_storage = isinstance(active_storage, storage.SupabaseStorageBackend)

CURRENCY_SIGNS = {"EUR": "€", "USD": "$", "GBP": "£"}


def money(x, ccy, compact=False):
    """€12,345.67, or €12.3k when compact (tiles and labels; tables keep full values)."""
    sign = CURRENCY_SIGNS.get(ccy, "")
    if compact and abs(x) >= 1000:
        text = f"{abs(x) / 1000:,.1f}k"
    else:
        text = f"{abs(x):,.0f}" if compact else f"{abs(x):,.2f}"
    text = f"{sign}{text}" if sign else f"{text} {ccy}"
    return f"−{text}" if x < 0 else text


@st.dialog("Save pie")
def save_dialog():
    name = st.text_input("Pie name", value=st.session_state.pie_name)
    is_pub = st.checkbox("Make public", value=False)
    if st.button("Save pie", type="primary", key="save_confirm"):
        try:
            saved = active_storage.save_pie(dict(pie_payload(name), is_public=is_pub), user_id=user_id)
            st.session_state.pie_name = saved["name"]
            flash("success", f"Saved pie '{saved['name']}'.")
            st.rerun()
        except Exception as ex:
            st.error(f"Failed to save pie: {ex}")


# ---------------- sidebar: settings first, then your pies, then the account ----------------
with st.sidebar:
    settings_box, pies_box, account_box = st.container(), st.container(), st.container()

with account_box:
    st.divider()
    if supabase_url and legacy_anon_key and not supabase_key:
        st.warning("`SUPABASE_KEY` (the anon key) is no longer used. Set `SUPABASE_SERVICE_KEY` "
                   "to store pies in Supabase (see README). Pies are saved on this machine for now.")
    current_user = auth.render_auth_ui(allow_guest=not shared_storage)
    user_id = current_user.get("id") if current_user else None

with settings_box:
    st.subheader("Backtest settings")
    base_ccy = st.selectbox("Pie currency", CURRENCIES, key="base_ccy")
    # Streamlit's default lower bound is only ten years back
    start = st.date_input("Start date", min_value=date(1970, 1, 1), max_value=date.today(), key="start")
    end = st.date_input("End date", min_value=date(1970, 1, 1), max_value=date.today(), key="end")
    if start >= end:
        st.warning("The start date must be before the end date.")
    c_init, c_month = st.columns(2)
    initial = c_init.number_input(f"Initial ({base_ccy})", min_value=0.0, step=100.0, key="initial")
    monthly = c_month.number_input(f"Monthly ({base_ccy})", min_value=0.0, step=50.0, key="monthly",
                                   help="Invested on the first trading day of each month, split by target weights.")
    if initial == 0 and monthly == 0:
        st.warning("Set an initial investment or a monthly deposit.")
    # four options don't fit on one line in the sidebar, so a dropdown rather than buttons
    rebalance = st.selectbox("Rebalance to target", list(engine.REBALANCE_RULES), key="rebalance",
                             help="Trading 212 pies don't rebalance automatically, so 'Never' matches them.")
    before_listing = st.radio("Assets that list later", list(engine.BEFORE_LISTING),
                              format_func=engine.BEFORE_LISTING.get, key="before_listing",
                              help="If one ETF launched later (e.g. in 2025), 'wait' shortens the whole backtest. "
                                   "'Cash' keeps the full period and buys that ETF once it lists.")

pie_data_raw = pie_payload() if st.session_state.pie else None
examples = storage.list_examples()

with pies_box:
    st.divider()
    with st.expander("Saved pies"):
        saved_pies = active_storage.list_pies(user_id=user_id)
        if saved_pies:
            def is_mine(p):
                return not shared_storage or p.get("owner_id") == user_id

            sp_names = [f"{p['name']} ({len(p['assets'])} assets)" + ("" if is_mine(p) else " · public")
                        for p in saved_pies]
            sel_sp_idx = st.selectbox("Saved pies", range(len(sp_names)), format_func=lambda i: sp_names[i],
                                      label_visibility="collapsed")
            target_sp = saved_pies[sel_sp_idx]
            c_load, c_del = st.columns(2)
            if c_load.button("Load saved pie", width="stretch"):
                load_pie(target_sp)
                st.rerun()
            if is_mine(target_sp) and c_del.button("Delete pie", width="stretch"):
                if active_storage.delete_pie(target_sp["id"], user_id=user_id):
                    flash("success", f"Deleted pie '{target_sp['name']}'.")
                    st.rerun()
                st.error(f"Could not delete pie '{target_sp['name']}'.")
        else:
            st.caption("No saved pies yet. Use Save at the top to keep a pie.")

    with st.expander("Import / export JSON"):
        if pie_data_raw:
            try:
                norm_export = storage.normalize_pie(pie_data_raw)
                norm_export.pop("id")  # a fresh id is assigned when the file is saved somewhere
                pie_json = json.dumps(norm_export, indent=2)
            except Exception:
                pie_json = json.dumps(pie_data_raw, indent=2)
        else:
            pie_json = ""
        st.download_button("Download pie (.json)", pie_json, file_name="my_pie.json", mime="application/json",
                           disabled=not st.session_state.pie)
        uploaded = st.file_uploader("Load pie", type="json", label_visibility="collapsed")
        if uploaded is not None and st.button("Load this pie"):
            try:
                uploaded.seek(0)
                raw_content = json.load(uploaded)
                is_valid, err = storage.validate_pie(raw_content)
                if not is_valid:
                    st.error(f"Invalid pie file: {err}")
                else:
                    load_pie(storage.normalize_pie(raw_content))
                    st.rerun()
            except Exception as e:
                st.error(f"Could not load pie file: {e}")

# ---------------- header: title, settings summary, actions ----------------
head, actions = st.columns([3, 2], vertical_alignment="bottom")
head.title("Pie backtester")
summary_slot = head.empty()  # filled once the results know the last price date
with actions.container(horizontal=True, horizontal_alignment="right"):
    if st.session_state.pop("close_examples", False):
        st.session_state.examples_pop = False  # close it once a pie is loaded
    with st.popover("Examples", key="examples_pop", on_change="rerun"):
        for i, ex in enumerate(examples):
            if st.button(ex["name"], key=f"ex_pop_{i}", width="stretch"):
                load_pie(ex)
                st.session_state.close_examples = True
                st.rerun()
    can_save = bool(st.session_state.pie) and not (shared_storage and not user_id)
    if st.button("Save", key="save_open", disabled=not can_save,
                 help=None if can_save or not st.session_state.pie else "Sign in to save pies."):
        save_dialog()
    with st.popover("Share", disabled=not pie_data_raw):
        try:
            if not pie_data_raw:
                raise ValueError("build a pie first")
            encoded_param = sharing.encode_pie_to_query_param(pie_data_raw)
            if len(encoded_param) > sharing.MAX_SHARE_URL_PARAM_LEN:
                st.warning("Pie configuration is too large for a URL share link. Use 'Download pie (.json)' instead.")
            else:
                st.code(f"{st.context.url or ''}?pie={encoded_param}", language=None, wrap_lines=True)
                st.caption("Copy this link to share your pie and its settings.")
        except Exception as e:
            st.caption(f"Cannot generate share link: {e}")

if "flash" in st.session_state:
    _kind, _msg = st.session_state.pop("flash")
    getattr(st, _kind)(_msg)

OWN = f"{st.session_state.pie_name or 'My Pie'} (editing)"  # the pie in the table

if not st.session_state.pie and not st.session_state.compare:
    # empty page: one click to a full result
    st.markdown("**Start from an example**")
    with st.container(horizontal=True):
        for i, ex in enumerate(examples):
            if st.button(ex["name"], key=f"ex_pill_{i}"):
                load_pie(ex)
                st.rerun()
    st.caption("or build your own:")

strip = st.container()  # the pie chips; filled after the table so they see this run's edits

# ---------------- your pie: search, table, total and the allocation donut ----------------
with st.container(border=True):
    left, right = st.columns([3, 2], gap="large")
    with left:
        c_search, c_ticker = st.columns([4, 1], vertical_alignment="bottom")
        q = c_search.text_input("Search by name, ticker or ISIN", label_visibility="collapsed",
                                placeholder="Search by name, ticker or ISIN, e.g. IE00BK5BQT80, AAPL")
        with c_ticker.popover("+ Ticker", width="stretch"):
            manual = st.text_input("Yahoo ticker", placeholder="VWCE.DE")
            if st.button("Add", width="stretch") and manual.strip():
                add_asset(manual.strip().upper(), manual.strip().upper())
                st.rerun()
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

        if not st.session_state.pie:
            st.info("Your pie is empty. Pick an example above or search for an asset.")
            total_w = 0.0
        else:
            # The table starts from a snapshot taken when the pie was last changed by code. Passing the
            # live pie instead would change the table's input after every edit, and Streamlit then
            # drops the next edit (it came back on the second try).
            if st.session_state.get("editor_base_version") != st.session_state.editor_version:
                st.session_state.editor_base = pd.DataFrame(st.session_state.pie,
                                                            columns=["Ticker", "Name", "Weight %"])
                st.session_state.editor_base_version = st.session_state.editor_version
            edited = st.data_editor(
                st.session_state.editor_base,
                num_rows="dynamic", width="stretch", hide_index=True,
                # weights first and narrow, so long ETF names can't push them out of view
                column_order=["Ticker", "Weight %", "Name"],
                column_config={
                    "Ticker": st.column_config.TextColumn(required=True, width="small",
                                                          help="Yahoo symbol with exchange suffix, e.g. VWRA.L or VECP.DE"),
                    "Weight %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.5,
                                                              format="%.2f", width="small"),
                    "Name": st.column_config.TextColumn(width="large"),
                },
                key=f"pie_editor_{st.session_state.editor_version}",
            )
            rows = edited.dropna(subset=["Ticker"]).fillna({"Weight %": 0.0, "Name": ""})
            rows["Ticker"] = rows["Ticker"].astype(str).str.strip().str.upper()
            st.session_state.pie = rows[rows["Ticker"] != ""].to_dict("records")
            total_w = sum(float(a["Weight %"] or 0) for a in st.session_state.pie)

            for t in {a["Ticker"] for a in st.session_state.pie if is_bare(a["Ticker"])}:
                hits = cached_resolve(t, base_ccy)
                if hits and hits[0]["symbol"].upper() == t:
                    st.session_state.verified_tickers.add(t)
            bare = [a["Ticker"] for a in st.session_state.pie if is_bare(a["Ticker"])]

            # the live total says why results are missing, before anyone looks for them
            if abs(total_w - 100) <= 0.01:
                st.markdown(":green[**Total 100% ✓**]")
            elif total_w < 100:
                st.markdown(f":orange[**Total {total_w:.2f}% · {100 - total_w:.2f}% left**]")
            else:
                st.markdown(f":orange[**Total {total_w:.2f}% · {total_w - 100:.2f}% too much**]")
            with st.container(horizontal=True, vertical_alignment="center"):
                if bare and st.button("Fix tickers", type="primary",
                                      help="Look up the exchange suffix Yahoo needs, e.g. VWRA → VWRA.L"):
                    with st.spinner("Looking up tickers…"):
                        fix_tickers(base_ccy)
                    st.rerun()
                if st.button("Split evenly"):
                    split_evenly()
                    pie_changed()
                    st.rerun()
                if st.button("Scale to 100%", disabled=abs(total_w - 100) <= 0.01 or total_w == 0):
                    scale_to_100()
                    st.rerun()
                if st.button("Compare a copy", disabled=abs(total_w - 100) > 0.01,
                             help="Adds a copy of this pie to the comparison, so you can change it and compare the two."):
                    add_to_comparison({"name": st.session_state.pie_name, "assets": [
                        {"ticker": a["Ticker"], "weight": a["Weight %"]} for a in st.session_state.pie]})
                    st.rerun()
                if st.button("Clear pie"):
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
            named = [a["Ticker"] for a in st.session_state.pie]
            dupes = sorted({t for t in named if named.count(t) > 1})
            if dupes:
                st.warning("These tickers are in the pie more than once: " + ", ".join(dupes) +
                           ". Merge them into one row.")

    with right:
        dfp = pd.DataFrame(st.session_state.pie, columns=["Ticker", "Name", "Weight %"])
        dfp = dfp[dfp["Weight %"] > 0]
        if not dfp.empty:
            st.markdown("**Allocation**")
            fig = go.Figure(go.Pie(labels=dfp["Ticker"], values=dfp["Weight %"], hole=0.55, sort=False,
                                   marker=dict(colors=shades(st.session_state.own_color, len(dfp)),
                                               line=dict(color="#ffffff", width=2)),
                                   hovertext=dfp["Name"],
                                   hovertemplate="%{label}<br>%{hovertext}<br>%{value:.2f}%<extra></extra>"))
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=300, showlegend=True,
                              annotations=[dict(text="Target", x=0.5, y=0.5, showarrow=False, font_size=16)])
            st.plotly_chart(fig)

# ---------------- the pie strip: one chip per loaded pie, in its colour ----------------
own_complete = bool(st.session_state.pie) and abs(total_w - 100) <= 0.01
chips = ([("own", OWN, st.session_state.own_color)] if st.session_state.pie else []) + \
    [(str(i), e["name"], e.get("color") or "#8a8d96") for i, e in enumerate(st.session_state.compare)]
with strip:
    if chips:
        # Streamlit buttons can't be coloured, so each chip's container gets a small CSS rule
        st.html("<style>" + "".join(
            f".st-key-chip_{k}{{border-color:{c} !important;border-radius:999px !important;padding:0 10px !important}}"
            f".st-key-chip_name_{k} p::before{{content:'●';color:{c};margin-right:6px}}"
            for k, _, c in chips) + ".st-key-chip_name_own p{font-weight:700}</style>")
        with st.container(horizontal=True, vertical_alignment="center"):
            for k, name, c in chips:
                with st.container(key=f"chip_{k}", border=True, horizontal=True, width="content",
                                  vertical_alignment="center", gap=None):
                    if k == "own":
                        st.button(name, key="chip_name_own", type="tertiary", help="The pie in the table below")
                    elif st.button(name, key=f"chip_name_{k}", type="tertiary", disabled=not own_complete,
                                   help="Edit this pie" if own_complete else
                                   "Finish the pie you're editing (weights at 100%) before switching"):
                        open_compared(int(k))
                        st.rerun()
                    if st.button("✕", key=f"chip_x_{k}", type="tertiary", help=f"Remove {name}"):
                        if k == "own":
                            close_open_pie()
                        else:
                            st.session_state.compare.pop(int(k))
                        st.rerun()
            st.caption(f"{len(chips)} of {MAX_COMPARED}" + (" · click a pie to edit it" if len(chips) > 1 else ""))
            if st.session_state.compare and st.button("Clear comparison", type="tertiary"):
                st.session_state.compare = []
                st.rerun()

# ---------------- results ----------------
# Results update by themselves: no run button. Your pie is shown once it's valid, next to any compared pies.
pie = [a for a in st.session_state.pie if float(a["Weight %"] or 0) > 0]
tickers = [a["Ticker"] for a in pie]
own_ready = bool(pie and abs(sum(float(a["Weight %"]) for a in pie) - 100) <= 0.01
                 and len(set(tickers)) == len(tickers) and not any(is_bare(t) for t in tickers))
settings_ok = start < end and (initial > 0 or monthly > 0)
names = {a["Ticker"]: a.get("Name") or a["Ticker"] for a in pie}
entries = ([(OWN, tuple((a["Ticker"], float(a["Weight %"])) for a in pie))] if own_ready else []) + \
    [(e["name"], tuple(e["weights"].items())) for e in st.session_state.compare]

results, late, currencies = {}, {}, {}
if settings_ok and entries:
    with st.spinner("Loading prices and simulating…"):
        for name, assets in entries:
            try:
                results[name], late[name], cur = cached_backtest(assets, start, end, base_ccy, initial, monthly,
                                                                 rebalance, before_listing)
                currencies.update(cur)
            except Exception as e:
                if name == OWN:
                    st.error(f"Backtest failed: {e}")
                else:
                    st.warning(f"'{name}' is left out: {e}")

own = results.get(OWN)

# one line that says what every number below assumes
summary = (f"{money(initial, base_ccy, True)} + {money(monthly, base_ccy, True)}/month · "
           f"{start:%Y-%m} to {end:%Y-%m} · rebalance {rebalance.lower()} · {base_ccy}")
if results:
    last_price = max(r["total"].index[-1] for r in results.values())
    summary += f" · prices to {last_price:%d %b %Y}"
summary_slot.caption(summary.replace("$", "\\$"))  # a bare $ would start Markdown maths
if results:
    st.divider()
    if own:
        res, ccy = own, base_ccy
        m = engine.metrics(res)
        actual_start = res["total"].index[0].date()
        if late[OWN]:
            listed = ", ".join(f"{t} ({d})" for t, d in sorted(late[OWN].items(), key=lambda x: x[1], reverse=True))
            if before_listing == "wait":
                st.warning(f"The backtest starts on {actual_start}, not {start}, because these assets "
                           f"have no earlier prices: {listed}. To use the full period, choose "
                           "'Hold … as cash' in the sidebar.")
            else:
                st.info(f"These assets were held as cash until their first price: {listed}.")
        st.subheader(f"{actual_start} to {res['total'].index[-1].date()}")
        k = st.columns(5)
        # currency goes in the label: five tiles side by side leave no room for it after the number
        k[0].metric(f"Value ({ccy})", f"{m['final_value']:,.2f}", f"{m['profit']:+,.2f}")
        k[1].metric(f"Invested ({ccy})", f"{m['invested']:,.2f}")
        k[2].metric("Return (time-weighted)", f"{m['twr_total']*100:.1f}%",
                    help="Performance of the pie itself, ignoring when deposits were made.")
        k[3].metric("Yearly return (CAGR)", "—" if pd.isna(m["cagr"]) else f"{m['cagr']*100:.1f}%")
        k[4].metric("Max drawdown", f"{m['max_drawdown']*100:.1f}%",
                    help=f"Largest drop from a peak. Volatility: {m['volatility']*100:.1f}% a year.")
    else:
        st.subheader("Compared pies")
        if st.session_state.pie:
            st.caption("Your pie appears here once its weights add up to 100% and its tickers are fixed.")

    # each pie keeps the colour of its chip in every chart and table
    colors = {OWN: st.session_state.own_color} | {e["name"]: e.get("color") or "#8a8d96"
                                                  for e in st.session_state.compare}
    tab_names = ["Value", "By asset", "Drawdown", "Holdings"] if own else ["Value", "Drawdown"]
    tabs = dict(zip(tab_names, st.tabs(tab_names)))
    with tabs["Value"]:
        fig = go.Figure()
        for name, r in results.items():
            fig.add_trace(go.Scatter(x=r["total"].index, y=r["total"], name=name,
                                     line=dict(color=colors[name], width=2.5 if name == OWN else 1.8)))
        first = own if own else next(iter(results.values()))
        fig.add_trace(go.Scatter(x=first["invested"].index, y=first["invested"], name="Invested",
                                 line=dict(color="#888", dash="dot", shape="hv")))
        fig.update_layout(height=450, hovermode="x unified", yaxis_title=base_ccy,
                          margin=dict(t=20, b=20), legend=dict(orientation="h", y=1.08))
        st.plotly_chart(fig)
        later = {n: r["total"].index[0].date() for n, r in results.items()
                 if n != OWN and r["total"].index[0].date() > start + pd.Timedelta(days=7)}
        for n, d in later.items():
            why = ", ".join(late[n]) if late[n] else "no earlier prices"
            st.caption(f"'{n}' starts on {d}: {why} {'has' if len(late[n]) == 1 else 'have'} no earlier prices."
                       if late[n] else f"'{n}' starts on {d}.")
    with tabs["Drawdown"]:
        fig = go.Figure()
        for name, r in results.items():
            dd = (r["twr"] / r["twr"].cummax() - 1) * 100
            fig.add_trace(go.Scatter(x=dd.index, y=dd, name=name, line=dict(color=colors[name]),
                                     fill="tozeroy" if len(results) == 1 else None))
        fig.update_layout(height=380, hovermode="x unified", yaxis_title="% below previous peak",
                          margin=dict(t=20, b=20), legend=dict(orientation="h", y=1.1),
                          showlegend=len(results) > 1)
        st.plotly_chart(fig)
    if own:
        weights = dict(entries[0][1])
        with tabs["By asset"]:
            vals = res["values"].rename(columns=names)
            fig = px.area(vals, color_discrete_sequence=PALETTE)
            fig.update_layout(height=450, hovermode="x unified", yaxis_title=ccy, legend_title="",
                              margin=dict(t=20, b=20))
            st.plotly_chart(fig)
            norm = engine.rebase(res["prices"]).rename(columns=names)
            fig2 = px.line(norm, color_discrete_sequence=PALETTE, title="Each asset, rebased to 100")
            fig2.update_layout(height=380, hovermode="x unified", legend_title="", yaxis_title="")
            st.plotly_chart(fig2)
        with tabs["Holdings"]:
            table = engine.per_asset_table(res, weights, names)
            st.dataframe(table, hide_index=True, width="stretch", column_config={
                "Target %": st.column_config.NumberColumn(format="%.1f"),
                "Current %": st.column_config.NumberColumn(format="%.1f"),
                "Value": st.column_config.NumberColumn(format=f"%.2f {ccy}"),
                "Price return %": st.column_config.NumberColumn(format="%.1f"),
            })
            st.caption("Currencies of the listings: " +
                       ", ".join(f"{t} {currencies.get(t, '?')}" for t in weights) +
                       f". All values are converted to {ccy} with daily FX rates.")
            csv = pd.concat([res["values"], res["total"].rename("Total"),
                             res["invested"].rename("Invested")], axis=1).to_csv()
            st.download_button("Download daily values (.csv)", csv, "pie_history.csv", "text/csv")
elif st.session_state.pie and not settings_ok:
    st.info("Fix the settings in the sidebar to see the backtest.")
elif st.session_state.pie and not own_ready:
    st.info("The results appear here once the weights add up to 100% and every ticker is found.")

# ---------------- comparison ----------------
if st.session_state.compare:
    st.divider()
    st.subheader("Compared pies")
    if len(results) > 1:
        st.dataframe(engine.comparison_table(results), hide_index=True, width="stretch", column_config={
            "From": st.column_config.DateColumn(help="Each pie starts on the first day it has prices"),
            "Final value": st.column_config.NumberColumn(f"Final value ({base_ccy})", format="%.2f"),
            "Invested": st.column_config.NumberColumn(f"Invested ({base_ccy})", format="%.2f"),
            "Return %": st.column_config.NumberColumn("Return % (time-weighted)", format="%.1f"),
            "CAGR %": st.column_config.NumberColumn(format="%.1f"),
            "Max drawdown %": st.column_config.NumberColumn(format="%.1f"),
            "Volatility %": st.column_config.NumberColumn(format="%.1f"),
        })
        st.caption("All pies use the sidebar settings: same currency, dates, deposits and rebalancing. "
                   "A pie whose assets list later starts later, so check the From column.")

if results:
    st.caption("Assumes fractional shares, no fees or taxes, and dividends reinvested. "
               "Disclaimer: Not financial advice. Past performance doesn't predict future returns.")
