"""Pie backtester — build a Trading 212-style pie and see how it would have developed.

Run with:  streamlit run app.py
"""
import html
import json
import re
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

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
METHOD = (Path(__file__).parent / "docs" / "how-its-calculated.md").read_text()  # the "How it's calculated" tab

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


SETTING_WORDS = {  # how a pie's own settings are named in the note when it joins a comparison
    "base_ccy": str, "rebalance": lambda v: f"rebalance {v.lower()}", "start": lambda v: f"start {v}",
    "end": lambda v: f"end {v}", "initial": lambda v: f"{v:g} initial", "monthly": lambda v: f"{v:g}/month",
    "before_listing": lambda v: engine.BEFORE_LISTING[v].lower(),
}


def load_pie(cfg):
    """Replace the pie with a normalized pie config, and the sidebar settings with its own.

    The pie being replaced moves to the comparison (if it's complete and not the same pie),
    so loading several pies one after another compares them; ✕ removes one. All compared pies
    share the sidebar settings, so a pie added to a comparison keeps the current ones.
    Returns False, changing nothing, when the comparison has no room for the pie being replaced.
    """
    previous = {a["Ticker"]: float(a["Weight %"] or 0) for a in st.session_state.pie if float(a["Weight %"] or 0) > 0}
    loaded = {str(a["ticker"]).upper(): float(a["weight"]) for a in cfg.get("assets", []) if float(a["weight"]) > 0}
    others = [e for e in st.session_state.compare if e["weights"] != loaded]  # a compared pie that's opened leaves
    moving = (previous and storage.adds_up(sum(previous.values())) and previous != loaded
              and not any(e["weights"] == previous for e in others))
    if moving and len(others) >= MAX_COMPARED - 1:
        flash("warning", f"You can compare up to {MAX_COMPARED} pies, including the one you're editing. "
                         f"Remove one with ✕ first, then open '{md(cfg.get('name') or 'Pie')}'.")
        return False
    st.session_state.clear_saved_pick = True  # the saved-pies list stops showing the previous pick
    st.session_state.compare = others
    if moving:
        add_to_comparison({"name": st.session_state.pie_name,
                           "assets": [{"ticker": a["Ticker"], "weight": a["Weight %"], "name": a.get("Name")}
                                      for a in st.session_state.pie if a["Ticker"] in previous]},
                          color=st.session_state.own_color)
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
    if st.session_state.compare:
        # joining a comparison: keep the settings every compared pie uses, and say what this one had
        saved_with = [SETTING_WORDS[k](v) for k, v in pending.items() if st.session_state.get(k) != v]
        if saved_with:
            flash("toast", f"Kept your settings. '{md(st.session_state.pie_name)}' was saved with "
                           f"{', '.join(saved_with)}.")
    else:
        st.session_state.pending_settings = pending
    pie_changed()
    return True


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
        f = 0.5 * i / max(n - 1, 1)  # mix in up to 50% white, so the lightest still shows on white
        out.append("#%02x%02x%02x" % tuple(round(c + (255 - c) * f) for c in (r, g, b)))
    return out


MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|~<>$:])")  # ":" too, or "http://…" becomes a link


def md(text):
    """Text shown as typed in Markdown (labels, captions, messages): pie names come from people and
    links, so their * _ [ ] $ ~ must not turn into formatting, links or maths."""
    return MD_SPECIAL.sub(r"\\\1", str(text))


def flash(kind, msg):
    """Show a message after the st.rerun() that usually follows."""
    st.session_state.flash = (kind, msg)


def amount_format(key):
    """Number format for an amount field: "1000", or "10.12" once it has cents."""
    return "%.0f" if float(st.session_state[key]).is_integer() else "%.2f"


def side_label(text):
    """A small upper-case section heading in the sidebar."""
    st.html(f'<div class="side-label">{text}</div>')


# The sidebar needs some CSS to fit design A: four rebalance buttons side by side in 240px.
# It uses Streamlit's test ids, so check it after a Streamlit upgrade.
SIDEBAR_CSS = """<style>
.side-label{font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;opacity:.75}
.st-key-rebalance [role=radiogroup]{flex-wrap:nowrap}
.st-key-rebalance button{padding-left:0;padding-right:0;flex:1 1 0;min-width:0}
.st-key-initial button,.st-key-monthly button{display:none}  /* the +/- steppers */
[data-testid=stSidebar] [data-testid=stExpander] details{border:none;background:none}
[data-testid=stSidebar] [data-testid=stExpander] summary{padding:0;min-height:1.6rem}
[data-testid=stSidebar] [data-testid=stExpanderDetails]{padding-left:0;padding-right:0}
.st-key-account p{font-size:.875rem}
.st-key-account button p{text-decoration:underline}
</style>"""


# Check for share link in query params on initial load: ?p= (short) or ?pie= (older links)
if "loaded_query_pie" not in st.session_state:
    st.session_state.loaded_query_pie = True
    qp_short, qp_pie = st.query_params.get("p"), st.query_params.get("pie")
    if qp_short or qp_pie:
        decoded = sharing.decode_share_link(qp_short) if qp_short else sharing.decode_pie_from_query_param(qp_pie)
        if decoded:
            for a in decoded["assets"]:
                if a["name"] == a["ticker"]:  # short links leave names out
                    a["name"] = engine.asset_name(a["ticker"])
            load_pie(decoded)
        else:
            flash("error", "This share link is invalid or damaged, so no pie was loaded.")

for _key, _value in st.session_state.pop("pending_settings", {}).items():
    st.session_state[_key] = _value


def add_asset(symbol: str, name: str):
    if any(a["Ticker"] == symbol for a in st.session_state.pie):
        st.toast(f"{symbol} is already in the pie")
        return
    # the new asset gets what's left to reach 100%, so the weights already set stay as they are
    total = sum(float(a["Weight %"] or 0) for a in st.session_state.pie)
    st.session_state.pie.append({"Ticker": symbol, "Name": name, "Weight %": round(max(100.0 - total, 0.0), 2)})
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


EARLIEST = date(1970, 1, 1)  # the earliest start the sidebar allows


@st.cache_resource(show_spinner=False)
def price_store():
    """Each ticker's full price history in one base currency, downloaded once a day and shared by all
    visitors: {(ticker, base, day): (prices, currency)}. Date changes then need no download at all."""
    return {}


def prices_for(tickers, start, end, base):
    """Prices in the base currency up to `end`, from the store; missing tickers come in one download."""
    store, today = price_store(), date.today()
    tickers = list(dict.fromkeys(tickers))
    missing = [t for t in tickers if (t, base, today) not in store]
    if missing:
        prices, info = engine.load_prices(missing, EARLIEST, today, base)
        for key in [k for k in store if k[2] != today]:
            store.pop(key, None)  # yesterday's prices are out of date
        for t in missing:
            store[(t, base, today)] = (prices[[t]].dropna(), info["currencies"][t])
    frames = [store[(t, base, today)][0] for t in tickers]
    currencies = {t: store[(t, base, today)][1] for t in tickers}
    # exchanges trade on different days; carry each price forward like a single download would
    prices = pd.concat(frames, axis=1).sort_index().ffill()
    return prices.loc[:pd.Timestamp(end)], {"currencies": currencies}


def add_to_comparison(cfg, color=None):
    """Add a normalized pie config to the comparison list. Bare tickers get their Yahoo listing."""
    others = st.session_state.compare
    if len(others) >= MAX_COMPARED - 1:
        flash("warning", f"'{md(cfg.get('name') or 'Pie')}' wasn't kept: you can compare up to {MAX_COMPARED} "
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

CURRENCY_ICONS = {"EUR": ":material/euro:", "USD": ":material/attach_money:", "GBP": ":material/currency_pound:",
                  "CHF": ":material/currency_franc:"}
REBALANCE_LABELS = {"Never": "Never", "Monthly": "Month", "Quarterly": "Quarter", "Yearly": "Year"}


money = engine.money


@st.dialog("Save pie")
def save_dialog():
    name = st.text_input("Pie name", value=st.session_state.pie_name)
    # saving under the name of one of your saved pies updates it instead of adding a copy
    mine = [p for p in active_storage.list_pies(user_id=user_id)
            if not shared_storage or p.get("owner_id") == user_id]
    same = next((p for p in mine if storage.same_name(p["name"], name)), None)
    is_pub = st.checkbox("Make public", value=bool(same and same.get("is_public")))
    if same:
        st.caption(f"You already have a saved pie called '{md(same['name'])}'. Saving updates it. "
                   "To keep both, change the name.")
    if st.button("Update pie" if same else "Save pie", type="primary", key="save_confirm",
                 disabled=not name.strip()):
        try:
            payload = dict(pie_payload(name.strip()), is_public=is_pub)
            if same:
                saved = active_storage.overwrite_pie(same["id"], payload, user_id=user_id)
            else:
                saved = active_storage.save_pie(payload, user_id=user_id)
            st.session_state.pie_name = saved["name"]
            flash("success", f"{'Updated' if same else 'Saved'} pie '{md(saved['name'])}'.")
            st.rerun()
        except Exception as ex:
            st.error(f"Failed to save pie: {ex}")


@st.dialog("Edit saved pie")
def edit_dialog(pie):
    """Rename a saved pie, or make it public or private."""
    name = st.text_input("Name", value=pie["name"])
    is_pub = st.toggle("Public", value=bool(pie.get("is_public")),
                       help="Public pies are listed for everyone who opens the app, signed in or not.")
    # two of your pies can't share a name: saving under a name updates that pie
    taken = next((p for p in active_storage.list_pies(user_id=user_id)
                  if p["id"] != pie["id"] and (not shared_storage or p.get("owner_id") == user_id)
                  and storage.same_name(p["name"], name)), None)
    if taken:
        st.caption(f"You already have a pie called '{md(taken['name'])}'. Pick another name.")
    if st.button("Save changes", type="primary", key="edit_confirm", disabled=not name.strip() or bool(taken)):
        if active_storage.update_pie(pie["id"], user_id=user_id, name=name, is_public=is_pub):
            if st.session_state.pie_name == pie["name"]:  # the open pie came from this one
                st.session_state.pie_name = storage.clean_name(name)
            flash("success", f"Updated '{md(storage.clean_name(name))}'" + (" (public)." if is_pub else "."))
            st.rerun()
        st.error(f"Could not update pie '{md(pie['name'])}'.")


# ---------------- sidebar: settings first, then your pies, then the account ----------------
with st.sidebar:
    st.html(SIDEBAR_CSS)
    settings_box, pies_box, account_box = st.container(), st.container(), st.container()

with account_box:
    st.divider()
    if supabase_url and legacy_anon_key and not supabase_key:
        st.warning("`SUPABASE_KEY` (the anon key) is no longer used. Set `SUPABASE_SERVICE_KEY` "
                   "to store pies in Supabase (see README). Pies are saved on this machine for now.")
    current_user = auth.render_auth_ui(allow_guest=not shared_storage)
    user_id = current_user.get("id") if current_user else None

with settings_box:
    side_label("Backtest settings")
    base_ccy = st.selectbox("Currency", CURRENCIES, key="base_ccy")
    # Streamlit's default lower bound is only ten years back
    start = st.date_input("From", min_value=date(1970, 1, 1), max_value=date.today(), key="start",
                          format="YYYY-MM-DD")
    end = st.date_input("To", min_value=date(1970, 1, 1), max_value=date.today(), key="end",
                        format="YYYY-MM-DD")
    if start >= end:
        st.warning("The start date must be before the end date.")
    # the currency shows as an icon in the field when Material has one, otherwise in the label
    ccy_icon = CURRENCY_ICONS.get(base_ccy)
    ccy_label = "" if ccy_icon else f" ({base_ccy})"
    # whole amounts without ".00", but cents stay visible when there are any (10.12)
    initial = st.number_input(f"Initial{ccy_label}", min_value=0.0, step=100.0, format=amount_format("initial"),
                              icon=ccy_icon, key="initial")
    monthly = st.number_input(f"Monthly{ccy_label}", min_value=0.0, step=50.0, format=amount_format("monthly"),
                              icon=ccy_icon, key="monthly")
    if initial == 0 and monthly == 0:
        st.warning("Set an initial investment or a monthly deposit.")
    rebalance = st.segmented_control("Rebalance to target", list(engine.REBALANCE_RULES), required=True,
                                     format_func=REBALANCE_LABELS.get, width="stretch", key="rebalance")
    before_listing = st.radio("Assets that list later", list(engine.BEFORE_LISTING),
                              format_func=engine.BEFORE_LISTING.get, key="before_listing")

examples = storage.list_examples()

with pies_box:
    st.divider()
    side_label("My pies")
    saved_pies = active_storage.list_pies(user_id=user_id)
    if getattr(active_storage, "last_error", None):
        st.warning(f"Supabase answered with an error, so saved pies can't be shown: {active_storage.last_error}.")
    with st.expander(f"Saved pies ({len(saved_pies)})"):
        if saved_pies:
            def is_mine(p):
                return not shared_storage or p.get("owner_id") == user_id

            by_id = {p["id"]: p for p in saved_pies}
            if st.session_state.pop("clear_saved_pick", False):  # deleted, or another pie was opened
                st.session_state.saved_pick = st.session_state.opened_saved_id = None
            elif st.session_state.get("saved_pick") not in by_id:
                # a rename changes the option's label, and Streamlit then resets the box: keep the open pie
                opened = st.session_state.get("opened_saved_id")
                st.session_state.saved_pick = opened if opened in by_id else None
            # picking a pie opens it, like picking a file; Edit and Delete act on the picked pie
            picked = st.selectbox(
                "Saved pies", list(by_id), key="saved_pick", label_visibility="collapsed",
                placeholder="Pick a pie to open",
                format_func=lambda i: f"{by_id[i]['name']} ({len(by_id[i]['assets'])} "
                                      f"asset{'' if len(by_id[i]['assets']) == 1 else 's'})"
                                      + ("" if is_mine(by_id[i]) else " · public"))
            if picked and picked != st.session_state.get("opened_saved_id"):
                if load_pie(by_id[picked]):
                    st.session_state.opened_saved_id, st.session_state.clear_saved_pick = picked, False
                else:
                    st.session_state.clear_saved_pick = True  # not opened: don't show it as picked
                st.rerun()
            target_sp = by_id.get(picked)
            if target_sp and is_mine(target_sp):
                with st.container(horizontal=True, gap="small"):
                    if st.button("Edit", key="edit_saved", width="stretch", help="Rename, or make public"):
                        edit_dialog(target_sp)
                    if st.button("Delete", key="delete_saved", width="stretch"):
                        if active_storage.delete_pie(target_sp["id"], user_id=user_id):
                            st.session_state.clear_saved_pick = True
                            flash("success", f"Deleted pie '{md(target_sp['name'])}'.")
                            st.rerun()
                        st.error(f"Could not delete pie '{md(target_sp['name'])}'.")
        else:
            st.caption("No saved pies yet. Use Save at the top to keep a pie.")

    with st.expander("Import / export JSON"):
        export_slot = st.empty()  # filled after the pie table, so the file has this run's edits
        uploaded = st.file_uploader("Load pie", type="json", label_visibility="collapsed")
        if uploaded is not None:
            # opens as soon as it's picked; file_id keeps it from opening again on every rerun
            try:
                uploaded.seek(0)
                raw_content = json.load(uploaded)
                is_valid, err = storage.validate_pie(raw_content)
            except Exception as e:
                is_valid, err = False, f"it isn't valid JSON ({e})"
            if not is_valid:
                st.error(f"Could not load this file: {err}")
            elif st.session_state.get("loaded_file_id") != uploaded.file_id:
                st.session_state.loaded_file_id = uploaded.file_id
                load_pie(storage.normalize_pie(raw_content))
                st.rerun()

# ---------------- header: title, settings summary, actions ----------------
head, actions = st.columns([3, 2], vertical_alignment="bottom")
head.title("Pie backtester")
summary_slot = head.empty()  # filled once the results know the last price date
with actions.container(horizontal=True, horizontal_alignment="right"):
    if st.session_state.pop("close_examples", False):
        st.session_state.examples_pop = False  # close it once a pie is loaded
    with st.popover("Examples", icon=":material/auto_awesome:", key="examples_pop", on_change="rerun"):
        for i, ex in enumerate(examples):
            if st.button(md(ex["name"]), key=f"ex_pop_{i}", width="stretch"):
                load_pie(ex)
                st.session_state.close_examples = True
                st.rerun()
    can_save = bool(st.session_state.pie) and not (shared_storage and not user_id)
    if st.button("Save", icon=":material/save:", key="save_open", disabled=not can_save,
                 help=None if can_save or not st.session_state.pie else "Sign in to save pies."):
        save_dialog()
    share_pop = st.popover("Share", icon=":material/share:", disabled=not st.session_state.pie)

if "flash" in st.session_state:
    _kind, _msg = st.session_state.pop("flash")
    getattr(st, _kind)(_msg)

OWN = f"{st.session_state.pie_name or 'My Pie'} (editing)"  # the pie in the table

strip = st.container()  # the pie chips; filled after the table so they see this run's edits

# ---------------- your pie: search, table, total and the allocation donut ----------------
with st.container(border=True):
    left, right = st.columns([3, 2], gap="large")
    with left:
        # assets come only from search, so every ticker is a real Yahoo listing
        q = st.text_input("Search by name, ticker or ISIN", label_visibility="collapsed",
                          placeholder="Search by name, ticker or ISIN, e.g. IE00BK5BQT80, AAPL")
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
            st.info("Your pie is empty. Pick one from Examples at the top, or search for an asset.")
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
                # "delete": rows can be removed but not typed in, and clicking a column name sorts the view
                num_rows="delete", disabled=["Ticker"], width="stretch", hide_index=True,
                # weights first and narrow, so long ETF names can't push them out of view
                column_order=["Ticker", "Weight %", "Name"],
                column_config={
                    "Ticker": st.column_config.TextColumn(width="small", help="Yahoo symbol. Add assets with the search above."),
                    "Weight %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.01,
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
            if storage.adds_up(total_w):
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
                if st.button("Scale to 100%", disabled=storage.adds_up(total_w) or total_w == 0):
                    scale_to_100()
                    st.rerun()
                if st.button("Compare a copy", disabled=not storage.adds_up(total_w),
                             help="Adds a copy of this pie to the comparison, so you can change it and compare the two."):
                    add_to_comparison({"name": st.session_state.pie_name, "assets": [
                        {"ticker": a["Ticker"], "weight": a["Weight %"], "name": a.get("Name")}
                        for a in st.session_state.pie]})
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
        dfp = dfp[dfp["Weight %"] > 0].sort_values("Weight %", ascending=False, kind="stable")  # biggest slice first
        if not dfp.empty:
            st.markdown("**Allocation**")
            fig = go.Figure(go.Pie(labels=dfp["Ticker"], values=dfp["Weight %"], hole=0.55, sort=False,
                                   marker=dict(colors=shades(st.session_state.own_color, len(dfp)),
                                               line=dict(color="#ffffff", width=2)),
                                   hovertext=dfp["Name"],
                                   hovertemplate="%{label}<br>%{hovertext}<br>%{value:.2f}%<extra></extra>",
                                   # ticker and weight next to each slice: shades alone are hard to tell apart
                                   texttemplate="%{label}<br>%{value:.1~f}%", textposition="outside",
                                   automargin=True))
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=320, showlegend=False,
                              annotations=[dict(text="Target", x=0.5, y=0.5, showarrow=False, font_size=16)])
            st.plotly_chart(fig)

# ---------------- share link and file: built after the table, so they carry this run's edits ----------------
pie_data_raw = pie_payload() if st.session_state.pie else None
share_ok, share_err = storage.validate_pie(pie_data_raw) if pie_data_raw else (False, "build a pie first")
with share_pop:
    if not share_ok:
        st.caption(f"Can't share this pie yet: {share_err[0].lower() + share_err[1:]}.")
    else:
        encoded_param = sharing.encode_share_link(pie_data_raw)
        if len(encoded_param) > sharing.MAX_SHARE_URL_PARAM_LEN:
            st.warning("Pie configuration is too large for a URL share link. Use 'Download pie (.json)' instead.")
        else:
            st.code(f"{st.context.url or ''}?p={encoded_param}", language=None, wrap_lines=True)
            st.caption("Copy this link to share your pie and its settings.")
if share_ok:
    norm_export = storage.normalize_pie(pie_data_raw)
    norm_export.pop("id")  # a fresh id is assigned when the file is saved somewhere
    pie_json = json.dumps(norm_export, indent=2)
else:
    pie_json = json.dumps(pie_data_raw or {}, indent=2)  # an unfinished pie can still be kept as a file
export_slot.download_button("Download pie (.json)", pie_json, icon=":material/download:", file_name="my_pie.json",
                            mime="application/json", disabled=not st.session_state.pie)

# ---------------- the pie strip: one chip per loaded pie, in its colour ----------------
own_complete = bool(st.session_state.pie) and storage.adds_up(total_w)
chips = ([("own", OWN, st.session_state.own_color)] if st.session_state.pie else []) + \
    [(str(i), e["name"], e.get("color") or "#8a8d96") for i, e in enumerate(st.session_state.compare)]
with strip:
    if chips:
        # Streamlit buttons can't be coloured, so each chip's container gets a small CSS rule
        st.html("<style>" + "".join(
            f".st-key-chip_{k}{{border-color:{c} !important;border-radius:999px !important;padding:0 10px !important}}"
            f".st-key-chip_name_{k} p::before{{content:'●';color:{c};margin-right:6px}}"
            for k, _, c in chips) + ".st-key-chip_name_own p{font-weight:700}"
            # ✕ shows only its icon; the label stays for screen readers ("Remove <pie>")
            "[class*='st-key-chip_x_'] [data-testid=stMarkdownContainer]{position:absolute;width:1px;height:1px;"
            "overflow:hidden;clip-path:inset(50%);white-space:nowrap}</style>")
        with st.container(horizontal=True, vertical_alignment="center"):
            for k, name, c in chips:
                with st.container(key=f"chip_{k}", border=True, horizontal=True, width="content",
                                  vertical_alignment="center", gap=None):
                    if k == "own":
                        st.button(md(name), key="chip_name_own", type="tertiary", help="The pie in the table below")
                    elif st.button(md(name), key=f"chip_name_{k}", type="tertiary", disabled=not own_complete,
                                   help="Edit this pie" if own_complete else
                                   "Finish the pie you're editing (weights at 100%) before switching"):
                        open_compared(int(k))
                        st.rerun()
                    if st.button(f"Remove {md(name)}", key=f"chip_x_{k}", type="tertiary", icon=":material/close:",
                                 help=f"Remove {name}"):
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
own_ready = bool(pie and storage.adds_up(sum(float(a["Weight %"]) for a in pie))
                 and len(set(tickers)) == len(tickers) and not any(is_bare(t) for t in tickers))
settings_ok = start < end and (initial > 0 or monthly > 0)
names = {a["Ticker"]: a.get("Name") or a["Ticker"] for a in pie}
entries = ([(OWN, tuple((a["Ticker"], float(a["Weight %"])) for a in pie))] if own_ready else []) + \
    [(e["name"], tuple(e["weights"].items())) for e in st.session_state.compare]

results, late, currencies, joined = {}, {}, {}, {}
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
                    st.warning(f"'{md(name)}' is left out: {md(e)}")
        # A pie that starts later begins with the average value of the pies that started earlier, as if
        # the money had moved into it then, so the lines and "You put in" stay comparable. Its Return,
        # Per year and Worst fall still cover only its own period.
        first_day = {n: r["total"].index[0] for n, r in results.items()}
        assets_of = dict(entries)
        for name in sorted(results, key=first_day.get):
            earlier = [results[o] for o in results if first_day[o] + pd.Timedelta(days=7) < first_day[name]]
            if earlier:
                value, put_in = engine.value_on(earlier, first_day[name])
                value = round(value, 2)  # also keeps the cache key tidy
                res_j, _, _ = cached_backtest(assets_of[name], start, end, base_ccy, value, monthly,
                                              rebalance, before_listing)
                results[name] = dict(res_j, invested=res_j["invested"] + (put_in - value))
                joined[name] = (first_day[name].date(), value)

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
    # each pie keeps the colour of its chip in every chart and table
    colors = {OWN: st.session_state.own_color} | {e["name"]: e.get("color") or "#8a8d96"
                                                  for e in st.session_state.compare}
    if own:
        res, ccy = own, base_ccy
        m = engine.metrics(res)
        actual_start = res["total"].index[0].date()
        if late[OWN]:
            listed = ", ".join(f"{t} ({d})" for t, d in sorted(late[OWN].items(), key=lambda x: x[1], reverse=True))
            if before_listing == "wait":
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.warning(f"This pie starts on {actual_start}, not {start}, because these assets have no "
                               f"earlier prices: {listed}.")
                    if st.button("Hold cash until they list",
                                 help="Keep the full period: the slice of a later asset stays cash until it lists."):
                        st.session_state.pending_settings = {"before_listing": "cash"}
                        st.rerun()
            else:
                st.info(f"These assets were held as cash until their first price: {listed}.")

        dd_own = res["twr"] / res["twr"].cummax() - 1
        deposits = int((res["invested"].diff() > 0).sum())
        gain = m["profit"]
        with st.container(horizontal=True):
            st.metric("Value now", money(m["final_value"], ccy, True), border=True, height="stretch",
                      delta=f"{'-' if gain < 0 else '+'}{money(abs(gain), ccy, True)} {'loss' if gain < 0 else 'gain'}",
                      chart_data=res["total"].resample("W").last().tolist(), chart_type="area",
                      help=f"What the pie is worth on {res['total'].index[-1].date()}.")
            st.metric("You put in", money(m["invested"], ccy, True), border=True, height="stretch",
                      delta=f"{money(res['invested'].iloc[0], ccy, True)} + {deposits} deposits",
                      delta_color="off", delta_arrow="off")
            st.metric("Return", f"{m['twr_total'] * 100:+.1f}%", border=True, height="stretch",
                      delta="time-weighted", delta_color="off", delta_arrow="off",
                      help="How the pie itself performed, ignoring when the deposits were made.")
            st.metric("Per year", "—" if pd.isna(m["cagr"]) else f"{m['cagr'] * 100:+.1f}%", border=True, height="stretch",
                      delta="CAGR", delta_color="off", delta_arrow="off",
                      help="The average yearly growth of the pie (compound annual growth rate). Needs a year of data.")
            st.metric("Worst fall", f"{m['max_drawdown'] * 100:.1f}%".replace("-", "−"), border=True, height="stretch",
                      delta=f"lowest on {dd_own.idxmin().date()}", delta_color="off", delta_arrow="off",
                      help=f"The largest drop from a previous high. Volatility: {m['volatility'] * 100:.1f}% a year.")
    elif st.session_state.pie:
        st.caption("Your pie appears here once its weights add up to 100% and its tickers are fixed.")

    tab_names = (["Growth", "By asset", "Holdings"] if own else ["Growth"]) + ["How it's calculated"]
    tabs = dict(zip(tab_names, st.tabs(tab_names)))
    with tabs["Growth"]:
        years = max((r["total"].index[-1] - r["total"].index[0]).days for r in results.values()) / 365.25
        with st.container(horizontal=True, horizontal_alignment="right"):
            # log by default for long horizons: equal % moves then look equal
            scale = st.segmented_control("Scale", ["Linear", "Log"], default="Log" if years > 10 else "Linear",
                                         required=True, label_visibility="collapsed")
            span = st.segmented_control("Period", ["1Y", "5Y", "Max"], default="Max", required=True,
                                        label_visibility="collapsed")
        last_day = max(r["total"].index[-1] for r in results.values())
        since = last_day - pd.DateOffset(years=int(span[:-1])) if span != "Max" else pd.Timestamp.min

        def window(series):
            return series[series.index >= since]

        # every pie has the same amount put in (later ones join with it), so the earliest one draws it
        first = min(results.values(), key=lambda r: r["total"].index[0])
        lines = {name: window(r["total"]) for name, r in results.items()}
        invested = window(first["invested"])
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.74, 0.26], vertical_spacing=0.05)
        fig.add_trace(go.Scatter(x=invested.index, y=invested, name="You put in", hovertemplate="%{y:,.0f}",
                                 line=dict(color="#8a8d96", dash="dot", shape="hv")), row=1, col=1)
        for name, r in results.items():
            fig.add_trace(go.Scatter(x=lines[name].index, y=lines[name], name=html.escape(name), hovertemplate="%{y:,.0f}",
                                     line=dict(color=colors[name], width=2.6 if name == OWN else 1.8)),
                          row=1, col=1)
            dd = window((r["twr"] / r["twr"].cummax() - 1) * 100)
            fig.add_trace(go.Scatter(x=dd.index, y=dd, name=html.escape(name), showlegend=False, hovertemplate="%{y:.1f}%",
                                     line=dict(color=colors[name], width=1.2),
                                     fill="tozeroy" if len(results) == 1 else None), row=2, col=1)

        # names at the line ends instead of a legend, nudged apart so they don't overlap
        values = pd.concat(list(lines.values()) + [invested])
        lo, hi = max(values.min(), 1e-9) * 0.95, values.max() * 1.05
        if scale == "Log":
            lo, hi = np.log10(lo), np.log10(hi)
        ends = sorted([(n, s.iloc[-1], colors[n]) for n, s in lines.items()] +
                      [("You put in", invested.iloc[-1], "#5f636e")], key=lambda x: -x[1])
        y_prev = 1.08
        for name, value, color in ends:
            y = ((np.log10(value) if scale == "Log" else value) - lo) / (hi - lo)
            y = min(y, y_prev - 0.07)
            y_prev = y
            label = name.removesuffix(" (editing)")
            fig.add_annotation(x=1.005, y=y, xref="x domain", yref="y domain", xanchor="left", showarrow=False,
                               text=f"<b>{html.escape(label)}</b> {money(value, base_ccy, True)}", font=dict(color=color, size=12))
        fig.update_yaxes(type="log" if scale == "Log" else "linear", range=[lo, hi], title=base_ccy, row=1, col=1)
        fig.update_yaxes(title="% below high", row=2, col=1)
        fig.update_layout(height=560, hovermode="x unified", showlegend=False, margin=dict(t=10, b=10, r=190))
        st.plotly_chart(fig)
        for n, r in results.items():
            d = r["total"].index[0].date()
            if n in joined:
                why = (f" ({', '.join(late[n])} {'has' if len(late[n]) == 1 else 'have'} no earlier prices)"
                       if late[n] else "")
                st.caption(f"'{md(n)}' starts on {d}{why} with {md(money(joined[n][1], base_ccy))}: the average "
                           "value of the pies that started earlier, as if the money had moved into it then.")
            elif n != OWN and d > start + pd.Timedelta(days=7):
                st.caption(f"'{md(n)}' starts on {d}: {', '.join(late[n])} {'has' if len(late[n]) == 1 else 'have'} "
                           "no earlier prices." if late[n] else f"'{md(n)}' starts on {d}.")
        st.caption(f"Hypothetical backtest. Yahoo Finance prices with dividends reinvested, no fees or taxes, "
                   f"fractional shares, converted to {base_ccy}. Not financial advice: past performance doesn't "
                   "predict future returns.")
    with tabs["How it's calculated"]:
        st.markdown(METHOD)  # the formulas are LaTeX, so its $ signs are meant
    if own:
        weights = dict(entries[0][1])
        with tabs["By asset"]:
            vals = res["values"].rename(columns=names)
            fig = px.area(vals, color_discrete_sequence=shades(st.session_state.own_color, len(names)))
            fig.update_layout(height=450, hovermode="x unified", yaxis_title=ccy, legend_title="",
                              margin=dict(t=20, b=20))
            st.plotly_chart(fig)
            norm = engine.rebase(res["prices"]).rename(columns=names)
            fig2 = px.line(norm, color_discrete_sequence=PALETTE, title="Each asset, rebased to 100")
            fig2.update_layout(height=380, hovermode="x unified", legend_title="", yaxis_title="")
            st.plotly_chart(fig2)
        with tabs["Holdings"]:
            table = engine.per_asset_table(res, weights, names)
            st.dataframe(table, hide_index=True, width="stretch",
                         column_order=["Asset", "Ticker", "Target %", "Current %", "Drift", "Value", "Gain",
                                       "Price return %", "History"],
                         column_config={
                             "Target %": st.column_config.NumberColumn(format="%.1f"),
                             "Current %": st.column_config.NumberColumn(format="%.1f"),
                             "Drift": st.column_config.NumberColumn(
                                 format="%+.1f pp", help="Current weight minus target weight, in percentage points"),
                             "Value": st.column_config.NumberColumn(format=f"%.2f {ccy}"),
                             "Gain": st.column_config.NumberColumn(
                                 format=f"%+.2f {ccy}", help="What this asset added to the pie's gain"),
                             "Price return %": st.column_config.NumberColumn(format="%+.1f"),
                             "History": st.column_config.AreaChartColumn("Value over time"),
                         })
            st.caption("Currencies of the listings: " +
                       ", ".join(f"{t} {currencies.get(t, '?')}" for t in weights) +
                       f". All values are converted to {ccy} with daily FX rates.")
            csv = pd.concat([res["values"], res["total"].rename("Total"),
                             res["invested"].rename("Invested")], axis=1).to_csv()
            st.download_button("Download daily values (.csv)", csv, "pie_history.csv", "text/csv",
                               icon=":material/download:")
elif st.session_state.pie and not settings_ok:
    st.info("Fix the settings in the sidebar to see the backtest.")
elif st.session_state.pie and not own_ready:
    st.info("The results appear here once the weights add up to 100% and every ticker is found.")

# ---------------- comparison table ----------------
if st.session_state.compare and len(results) > 1:
    st.subheader("Compared pies")
    table = engine.comparison_table(results)
    same_invested = table["Invested"].round(2).nunique() == 1
    shown = table[["Pie", "From", "Final value", "Return %", "CAGR %", "Max drawdown %", "Volatility %"]
                  + ([] if same_invested else ["Invested"])]
    best = {"Final value": "max", "Return %": "max", "CAGR %": "max", "Max drawdown %": "max", "Volatility %": "min"}

    def emphasis(df):
        """Each pie's name in its colour; the best value in each column in bold."""
        css = pd.DataFrame("", index=df.index, columns=df.columns)
        for col, how in best.items():
            if df[col].notna().any():
                css.loc[getattr(df[col], f"idx{how}")(), col] = "font-weight: 700"
        css["Pie"] = [f"color: {colors.get(n, '#8a8d96')}; font-weight: 600" for n in df["Pie"]]
        return css

    pct = lambda v: "—" if pd.isna(v) else f"{v:+.1f}%"  # noqa: E731
    st.dataframe(
        shown.style.apply(emphasis, axis=None).format({
            "Final value": lambda v: money(v, base_ccy), "Invested": lambda v: money(v, base_ccy),
            "Return %": pct, "CAGR %": pct,
            "Max drawdown %": lambda v: f"{v:.1f}%".replace("-", "−"), "Volatility %": "{:.1f}%"}),
        hide_index=True, width="stretch", column_config={
            "From": st.column_config.DateColumn(help="Each pie starts on the first day it has prices"),
            "Final value": "Value", "Return %": st.column_config.Column("Return", help="Time-weighted"),
            "CAGR %": st.column_config.Column("Per year", help="CAGR"),
            "Max drawdown %": st.column_config.Column("Worst fall", help="Largest drop from a previous high"),
            "Volatility %": st.column_config.Column("Volatility", help="How much it swings, per year"),
        })
    st.caption("Bold: best in the column." +
               (f" Every pie had {money(table['Invested'].iloc[0], base_ccy)} put in." if same_invested else "") +
               " All pies use the sidebar settings; a pie whose assets list later starts later (see From).")
