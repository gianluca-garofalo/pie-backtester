"""Pie backtester — build a Trading 212-style pie and see how it would have developed.

Run with:  streamlit run app.py
"""
import copy
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
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

import editing
import engine
import storage
import sharing
import auth

st.set_page_config(page_title="Pie backtester", page_icon="🥧", layout="wide")

PALETTE = ["#1F6F78", "#E0A526", "#5B4B8A", "#C8553D", "#3E8E5E", "#2E4057",
           "#B56576", "#7A9E9F", "#D98E04", "#4F5D75", "#8AA29E", "#9C6644"]
# one colour per pie, kept for as long as the pie is loaded (Okabe-Ito, colour-blind safe;
# same list as chartCategoricalColors in .streamlit/config.toml)
# Okabe-Ito-based; vermillion is last so it's rarely next to the orange (they were hard to tell apart)
PIE_COLORS = ["#0072B2", "#B86E00", "#009E73", "#AA4499", "#56B4E9", "#D55E00"]

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
# every pie keeps its place in the chip row: the pie being edited has own_order, compared ones "order"
st.session_state.setdefault("own_order", 0)
# the saved pie the open one came from, {"id", "key"}, to tell "Saved" from "Unsaved changes"; it moves
# with the pie in and out of the comparison (as "saved_ref" in compared pies)
st.session_state.setdefault("saved_ref", None)
st.session_state.setdefault("next_order", 1)


def pie_key(name, assets):
    """What "saved" compares: the name and the assets with their weights. Not the settings: in a
    comparison they're shared, so they'd differ from the saved pie's own without any edit."""
    return storage.clean_name(name), tuple(sorted((str(t).upper(), round(float(w), 2)) for t, w in assets))


def saved_ref_of(pie):
    """The saved_ref for a saved pie (as storage returns it)."""
    return {"id": pie["id"], "key": pie_key(pie["name"], [(a["ticker"], a["weight"]) for a in pie["assets"]])}


def new_order():
    """The place for a pie that's new on screen: after all the others."""
    st.session_state.next_order += 1
    return st.session_state.next_order - 1

MAX_COMPARED = 5  # pies in one comparison, including yours
METHOD = (Path(__file__).parent / "docs" / "how-its-calculated.md").read_text()  # the "How it's calculated" tab

CURRENCIES = storage.CURRENCIES
# settings (the period, the plan, the start rule), kept in session state so a loaded pie can set them
for _key, _default in {"base_ccy": "EUR", "start": date(2020, 1, 1), "end": date.today(),
                       "initial": 1000.0, "monthly": 0.0, "rebalance": "Never",
                       # how pies start when an asset lists after From (engine.START_RULES); kept in a plain key
                       # so the choice survives while its card isn't shown
                       "start_rule": "common",
                       # a preset (engine.PERIOD_PRESETS) keeps From/To in step with it, e.g. 5Y moves with today;
                       # dates picked by hand make it "Custom"
                       "period": "5Y"}.items():
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
    "start_rule": lambda v: "hold cash until assets list" if v == "cash" else "start when all assets have prices",
}


def load_pie(cfg):
    """Replace the pie with a normalized pie config, and the settings with its own.

    The pie being replaced moves to the comparison (if it's complete and not the same pie),
    so loading several pies one after another compares them; ✕ removes one. All compared pies
    share the settings, so a pie added to a comparison keeps the current ones.
    Returns False, changing nothing, when the comparison has no room for the pie being replaced.
    """
    previous = {a["Ticker"]: float(a["Weight %"] or 0) for a in st.session_state.pie if float(a["Weight %"] or 0) > 0}
    loaded = {str(a["ticker"]).upper(): float(a["weight"]) for a in cfg.get("assets", []) if float(a["weight"]) > 0}
    others = [e for e in st.session_state.compare if e["weights"] != loaded]  # a compared pie that's opened leaves
    moving = (previous and storage.adds_up(sum(previous.values())) and previous != loaded
              and not any(e["weights"] == previous for e in others))
    if moving and len(others) >= MAX_COMPARED - 1:
        flash("warning", f"You can compare up to {MAX_COMPARED} pies, including the one you're editing. "
                         f"Remove one first, then open '{md(cfg.get('name') or 'Pie')}'.")
        return False
    already = next((e for e in st.session_state.compare if e["weights"] == loaded), None)
    st.session_state.compare = others
    st.session_state.pop("undo", None)  # Undo is for the last change only
    if moving:
        add_to_comparison({"name": st.session_state.pie_name,
                           "assets": [{"ticker": a["Ticker"], "weight": a["Weight %"], "name": a.get("Name")}
                                      for a in st.session_state.pie if a["Ticker"] in previous]},
                          color=st.session_state.own_color, order=st.session_state.own_order,
                          saved_ref=st.session_state.saved_ref)
    elif previous and previous != loaded and not storage.adds_up(sum(previous.values())):
        flash("toast", f"'{md(st.session_state.pie_name)}' was closed: its weights add up to "
                       f"{sum(previous.values()):.2f}%, so it couldn't join the comparison.")
    st.session_state.saved_ref = already.get("saved_ref") if already else None  # callers that open a saved pie set it
    if moving or already:  # a new pie on screen goes last; a compared one that's opened keeps its place
        st.session_state.own_order = already["order"] if already and "order" in already else new_order()
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
        pending["start_rule"] = "cash" if cfg["before_listing"] == "cash" else "common"
    for key in ("start", "end"):
        try:
            d = date.fromisoformat(str(cfg.get(key)))
        except ValueError:  # no end date means "up to date"; no start keeps the current one
            if key == "end":
                pending["end"] = date.today()
            continue
        pending[key] = min(d, date.today())
    if "start" in pending:
        pending["period"] = "Custom"  # the pie's own dates
    if st.session_state.compare:
        # joining a comparison: keep the settings every compared pie uses, and say what this one had
        # "EUR, not its own USD": what's in use, then what the pie was saved with
        differ = [f"{SETTING_WORDS[k](st.session_state[k])}, not its own {SETTING_WORDS[k](v)}"
                  for k, v in pending.items()
                  if k in SETTING_WORDS and SETTING_WORDS[k](st.session_state[k]) != SETTING_WORDS[k](v)]
        if differ:
            flash("toast", f"'{md(st.session_state.pie_name)}' uses the comparison's settings: {md('; '.join(differ))}.")
    else:
        st.session_state.pending_settings = pending
    pie_changed()
    return True


UNDOABLE = ("pie", "pie_name", "own_color", "own_order", "saved_ref", "compare")  # what Remove can undo


def snapshot():
    """The loaded pies as they are, for Undo."""
    return copy.deepcopy({k: st.session_state[k] for k in UNDOABLE})


def restore(snap):
    for k, v in copy.deepcopy(snap).items():
        st.session_state[k] = v
    pie_changed()


def close_open_pie():
    """✕ on the pie being edited: drop it and open the most recently compared pie instead."""
    if not st.session_state.compare:
        st.session_state.pie = []
        st.session_state.saved_ref = None
    else:
        e = st.session_state.compare.pop()
        st.session_state.saved_ref = e.get("saved_ref")
        st.session_state.pie = [{"Ticker": t, "Name": e.get("names", {}).get(t, t), "Weight %": w}
                                for t, w in e["weights"].items()]
        st.session_state.pie_name = e["name"]
        st.session_state.own_color = e.get("color") or st.session_state.own_color
        st.session_state.own_order = e.get("order", st.session_state.own_order)
    st.session_state.fix_report = None
    pie_changed()


def open_compared(i):
    """Click on a compared pie: it opens in the table, and the pie being edited takes its place."""
    e = st.session_state.compare[i]
    st.session_state.pop("undo", None)
    current = {a["Ticker"]: float(a["Weight %"] or 0) for a in st.session_state.pie if float(a["Weight %"] or 0) > 0}
    if current:
        st.session_state.compare[i] = {
            "name": st.session_state.pie_name, "weights": current, "color": st.session_state.own_color,
            "order": st.session_state.own_order,  # the two swap places in the chip row
            "saved_ref": st.session_state.saved_ref,
            "names": {a["Ticker"]: a.get("Name") or a["Ticker"] for a in st.session_state.pie if a["Ticker"] in current}}
    else:
        st.session_state.compare.pop(i)
    st.session_state.pie = [{"Ticker": t, "Name": e.get("names", {}).get(t, t), "Weight %": w}
                            for t, w in e["weights"].items()]
    st.session_state.pie_name = e["name"]
    st.session_state.own_color = e.get("color") or st.session_state.own_color
    st.session_state.own_order = e.get("order", new_order())
    st.session_state.saved_ref = e.get("saved_ref")
    st.session_state.fix_report = None
    pie_changed()


def readable(color):
    """A pie colour as shown on the page. On the dark theme it's lightened until it has 4.5:1 contrast on
    the dark background (the blue was 3.7:1); the light theme shows it as it is."""
    if (getattr(st.context.theme, "type", None) or "light") != "dark":
        return color
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    for f in (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6):  # mix in white, a step at a time
        c = tuple(round(v + (255 - v) * f) for v in (r, g, b))
        lum = sum(w * ((x / 255) / 12.92 if x / 255 <= 0.03928 else ((x / 255 + 0.055) / 1.055) ** 2.4)
                  for w, x in zip((0.2126, 0.7152, 0.0722), c))
        if (lum + 0.05) / (0.0067 + 0.05) >= 4.5:  # 0.0067: the luminance of Streamlit's dark background
            break
    return "#%02x%02x%02x" % c


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


def screen_reader_text(text):
    """A sentence only screen readers hear, e.g. what a chart shows (Plotly charts are unnamed images)."""
    st.html(f'<p class="sr-only">{html.escape(text)}</p>')


def flash(kind, msg):
    """Show a message after the st.rerun() that usually follows. Several can queue up."""
    st.session_state.setdefault("flashes", []).append((kind, msg))


def copy_button(text, label="Copy link"):
    """A button that copies text to the clipboard, for phones: the code block's own copy icon only shows
    on hover. A component frame may write to the clipboard."""
    dark = (getattr(st.context.theme, "type", None) or "light") == "dark"
    fg, border = ("#fafafa", "rgba(250,250,250,.3)") if dark else ("#31333f", "rgba(49,51,63,.25)")
    components.html(f"""
<button id="b" style="font:15px 'Source Sans Pro',sans-serif;color:{fg};background:transparent;
  border:1px solid {border};border-radius:8px;padding:6px 14px;cursor:pointer">{html.escape(label)}</button>
<script>
const b = document.getElementById("b"), text = {json.dumps(text)};
b.onclick = () => {{
  // the hidden-textarea copy works straight away during the click; the clipboard API can wait on a
  // permission prompt, so it's only the fallback
  const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t);
  t.select(); const ok = document.execCommand("copy"); t.remove();
  if (!ok && navigator.clipboard) navigator.clipboard.writeText(text).catch(() => {{}});
  b.textContent = "Copied ✓"; setTimeout(() => b.textContent = {json.dumps(label)}, 2000);
}};
</script>""", height=44)


def on_phone():
    """Whether the visitor is on a phone. Streamlit doesn't tell the app the screen width, but phone
    browsers say "Mobi" in their user agent."""
    return "Mobi" in (st.context.headers.get("User-Agent") or "")


def money_column(ccy):
    """A table column format for amounts: €1,234.56 for euros and dollars, thousands separators otherwise."""
    return {"EUR": "euro", "USD": "dollar"}.get(ccy, "localized")


def signed_pct(v):
    """+12.3% or −4.5%, with a real minus sign like the rest of the app (not a hyphen)."""
    return f"{v:+.1f}%".replace("-", "−")


def amount_format(key):
    """Number format for an amount field: "1000", or "10.12" once it has cents."""
    return "%.0f" if float(st.session_state[key]).is_integer() else "%.2f"


# Page-wide CSS. Some rules use Streamlit's test ids and st-key classes, so check them after a Streamlit upgrade.
PAGE_CSS = """<style>
.st-key-plan_initial button,.st-key-plan_monthly button{display:none}  /* the +/- steppers */
.st-key-account p{font-size:.875rem}
.st-key-account button p{text-decoration:underline}
.card-name{font-weight:700;font-size:1.05rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.big-number{font-size:1.9rem;font-weight:700;line-height:1.2}
@media (pointer:coarse){[class*='st-key-pie_card_'] button{min-width:36px;min-height:36px}}  /* finger-sized */
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
/* secondary text at 78% of the text colour (about 6:1 on white, still fine in dark mode); Streamlit's
   own grey was about 3.5:1, under the 4.5:1 that WCAG asks for */
[data-testid=stCaptionContainer],input::placeholder,textarea::placeholder{
  color:inherit !important;opacity:.78}
</style>"""


# Check for share link in query params on initial load: ?p= (short) or ?pie= (older links)
if "loaded_query_pie" not in st.session_state:
    st.session_state.loaded_query_pie = True
    qp_short, qp_pie = st.query_params.get("p"), st.query_params.get("pie")
    if qp_short or qp_pie:
        if qp_short:
            decoded, why = sharing.read_share_link(qp_short)
        else:  # older links
            decoded, why = sharing.decode_pie_from_query_param(qp_pie), "it's damaged"
        if decoded:
            for a in decoded["assets"]:
                if a["name"] == a["ticker"]:  # short links leave names out
                    a["name"] = engine.asset_name(a["ticker"])
            load_pie(decoded)
        else:
            flash("error", f"This share link can't be opened: {md(why)}. No pie was loaded.")

for _key, _value in st.session_state.pop("pending_settings", {}).items():
    st.session_state[_key] = _value


def draft_changed():
    """Call after changing st.session_state.draft from code (not from the editor's table)."""
    st.session_state.draft_version = st.session_state.get("draft_version", 0) + 1


def add_to_draft(symbol, name):
    """"Add to pie" in the editor. The search box isn't cleared: clearing it during the rerun could wipe what
    someone starts typing next. The button turns into "Added ✓" instead, and a toast confirms."""
    if any(a["Ticker"] == symbol for a in st.session_state.draft):
        st.toast(f"{md(symbol)} is already in the pie.")
        return
    # it came from search, so Yahoo knows it as-is: ASML on NASDAQ is a real listing, even though a
    # euro pie's suffix check would prefer ASML.AS
    st.session_state.verified_tickers.add(symbol)
    # the new asset gets what's left to reach 100%, so the weights already set stay as they are
    st.session_state.draft = editing.with_added(st.session_state.draft, symbol, name)
    draft_changed()
    st.toast(f"Added {md(symbol)}.")


def change_draft(operation):
    """Scale to 100% or Split evenly on the editor's rows; locked rows keep their weight."""
    st.session_state.draft = operation(st.session_state.draft)
    draft_changed()


def paste_rows(found, replace):
    """Pasted (symbol, name, weight) rows replace the editor's rows, or are added to them (a ticker that's
    already there gets the pasted weight)."""
    rows = [] if replace else [dict(r) for r in st.session_state.draft]
    for symbol, name, weight in found:
        st.session_state.verified_tickers.add(symbol)
        same = next((r for r in rows if r["Ticker"] == symbol), None)
        if same:
            same["Weight %"] = weight
        else:
            rows.append({"Ticker": symbol, "Name": name, "Weight %": weight, "Lock": False})
    st.session_state.draft = rows
    st.session_state.draft_paste = ""
    draft_changed()


@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(q):
    return engine.search_listings(q)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_resolve(t, ccy):
    return engine.resolve_ticker(t, ccy)


def is_bare(ticker):
    """A ticker without exchange suffix that we haven't confirmed Yahoo knows as-is."""
    return engine.needs_suffix(ticker) and ticker not in st.session_state.verified_tickers


@st.cache_data(ttl=3600, show_spinner=False)
def find_listing(ticker, ccy):
    """The Yahoo listing for a pasted ticker, (symbol, name), or None: the exact symbol first (VWCE.DE, AAPL),
    then a bare ticker's usual European listing (VWRA -> VWRA.L)."""
    exact = [h for h in engine.search_assets(ticker, 10) if (h["symbol"] or "").upper() == ticker]
    if exact:
        return exact[0]["symbol"], exact[0]["name"] or ticker
    hits = engine.resolve_ticker(ticker, ccy) if engine.needs_suffix(ticker) else []
    return (hits[0]["symbol"], hits[0]["name"] or hits[0]["symbol"]) if hits else None


def fix_tickers(ccy):
    """Add exchange suffixes to the editor's bare tickers, e.g. Trading 212's VWRA -> VWRA.L."""
    changed, unresolved = [], []
    for a in st.session_state.draft:
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
    draft_changed()


EARLIEST = date(1970, 1, 1)  # the earliest start the From field allows


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


def add_to_comparison(cfg, color=None, order=None, saved_ref=None):
    """Add a normalized pie config to the comparison list. Bare tickers get their Yahoo listing."""
    others = st.session_state.compare
    if len(others) >= MAX_COMPARED - 1:
        flash("warning", f"'{md(cfg.get('name') or 'Pie')}' wasn't kept: you can compare up to {MAX_COMPARED} "
                         "pies, including yours. Remove one first.")
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
    if same := next((e for e in others if e["weights"] == weights), None):
        flash("toast", f"This pie is already in the comparison as '{md(same['name'])}'.")
        return
    taken = {e["name"] for e in others}
    base = cfg.get("name") or "Pie"
    name, n = base, 2
    while name in taken:  # "X (2)", or "X (copy 2)" for copies
        name = f"{base[:-1]} {n})" if base.endswith(" (copy)") else f"{base} ({n})"
        n += 1
    color = color or free_color({e.get("color") for e in others} | {st.session_state.own_color})
    others.append({"name": name, "weights": weights, "names": {t: names[t] for t in weights}, "color": color,
                   "order": new_order() if order is None else order, "saved_ref": saved_ref})


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
        "before_listing": "cash" if st.session_state.start_rule == "cash" else "wait",
    }


def loaded_tickers():
    """Every ticker of every loaded pie: the open one and the compared ones."""
    own = [a["Ticker"] for a in st.session_state.pie if float(a["Weight %"] or 0) > 0]
    return list(dict.fromkeys(own + [t for e in st.session_state.compare for t in e["weights"]]))


def earliest_price():
    """The first day any loaded asset has a price (the Max period), or None with no pie."""
    tickers = [t for t in loaded_tickers() if not is_bare(t)]
    try:
        prices, _ = prices_for(tickers, EARLIEST, date.today(), st.session_state.base_ccy) if tickers else (None, None)
    except Exception:  # a ticker without prices: the results say so
        return None
    firsts = prices.apply(lambda col: col.first_valid_index()).dropna() if prices is not None else []
    return min(firsts).date() if len(firsts) else None


def pick_period():
    st.session_state.period = st.session_state.period_pick


def custom_period():
    st.session_state.period = "Custom"


# a preset keeps the dates in step with it (5Y moves with today, Max with the loaded pies); set before the
# date fields are drawn
if st.session_state.period != "Custom":
    _from = engine.period_start(st.session_state.period, date.today(),
                                earliest_price() if st.session_state.period == "Max" else None)
    if _from:
        st.session_state.start = _from
    st.session_state.end = date.today()


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


PUBLIC_HELP = "Public pies are listed for everyone who opens the app, signed in or not."  # Save and Edit say the same


def my_saved_pie(name):
    """Your saved pie with this name, if any: saving under it updates that pie instead of adding a copy."""
    mine = [p for p in active_storage.list_pies(user_id=user_id)
            if not shared_storage or p.get("owner_id") == user_id]
    return next((p for p in mine if storage.same_name(p["name"], name)), None)


def save_open_pie(name, is_public=None):
    """Save the open pie as `name`, updating your saved pie of that name. is_public None keeps that pie's
    setting (private for a new one). Returns (saved pie, whether it updated one)."""
    same = my_saved_pie(name)
    payload = dict(pie_payload(name.strip()),
                   is_public=bool(same and same.get("is_public")) if is_public is None else is_public)
    if same:
        saved = active_storage.overwrite_pie(same["id"], payload, user_id=user_id)
    else:
        saved = active_storage.save_pie(payload, user_id=user_id)
    st.session_state.pie_name = saved["name"]
    st.session_state.saved_ref = saved_ref_of(saved)
    return saved, bool(same)


@st.dialog("Save pie")
def save_dialog():
    name = st.text_input("Pie name", value=st.session_state.pie_name, max_chars=storage.MAX_NAME_LENGTH)
    same = my_saved_pie(name)
    is_pub = st.checkbox("Make public", value=bool(same and same.get("is_public")), help=PUBLIC_HELP)
    if same:
        st.caption(f"You already have a saved pie called '{md(same['name'])}'. Saving updates it. "
                   "To keep both, change the name.")
    if st.button("Update pie" if same else "Save pie", type="primary", key="save_confirm",
                 disabled=not name.strip()):
        try:
            saved, updated = save_open_pie(name, is_pub)
            flash("success", f"{'Updated' if updated else 'Saved'} pie '{md(saved['name'])}'.")
            st.rerun()
        except Exception as ex:
            st.error(f"Failed to save pie: {ex}")


@st.dialog("Edit saved pie")
def edit_dialog(pie):
    """Rename a saved pie, or make it public or private."""
    name = st.text_input("Pie name", value=pie["name"], max_chars=storage.MAX_NAME_LENGTH)
    is_pub = st.checkbox("Make public", value=bool(pie.get("is_public")), help=PUBLIC_HELP)
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
            ref = st.session_state.saved_ref
            if ref and ref["id"] == pie["id"]:  # renamed, still saved
                st.session_state.saved_ref = {"id": ref["id"], "key": (storage.clean_name(name), ref["key"][1])}
            flash("success", f"Updated '{md(storage.clean_name(name))}'" + (" (public)." if is_pub else "."))
            st.rerun()
        st.error(f"Could not update pie '{md(pie['name'])}'.")


def delete_saved(pie):
    """Delete a saved pie at once; Undo saves it again, with the same id."""
    if not active_storage.delete_pie(pie["id"], user_id=user_id):
        flash("error", f"Could not delete pie '{md(pie['name'])}'.")
        return
    was_open = (st.session_state.saved_ref or {}).get("id") == pie["id"]
    if was_open:
        st.session_state.saved_ref = None  # still open, but no longer saved
    st.session_state.undo = {"label": f"Deleted '{pie['name']}'.", "kind": "delete",
                             "data": {"pie": pie, "was_open": was_open}}


def undo_last():
    u = st.session_state.pop("undo")
    if u["kind"] == "remove":
        restore(u["data"])
        return
    try:
        saved = active_storage.save_pie(u["data"]["pie"], user_id=user_id)
        if u["data"]["was_open"]:
            st.session_state.saved_ref = saved_ref_of(saved)
    except Exception as e:
        flash("error", f"Could not bring back '{md(u['data']['pie']['name'])}': {e}")


# ---------------- the account, on one line at the top (there's no sidebar) ----------------
st.html(PAGE_CSS)
if supabase_url and legacy_anon_key and not supabase_key:
    st.warning("`SUPABASE_KEY` (the anon key) is no longer used. Set `SUPABASE_SERVICE_KEY` "
               "to store pies in Supabase (see README). Pies are saved on this machine for now.")
with st.container(horizontal=True, horizontal_alignment="right"):
    current_user = auth.render_auth_ui(allow_guest=not shared_storage)
user_id = current_user.get("id") if current_user else None

# the money settings are plain keys, changed only through the Plan dialog (or a loaded pie)
base_ccy, initial, monthly, rebalance = (st.session_state[k] for k in ("base_ccy", "initial", "monthly", "rebalance"))


def plan_amount(x):
    """€1,000 or €10.12: cents only when there are any."""
    text = money(x, base_ccy)
    return text.replace(".00", "") if round(x, 2) == round(x) else text


@st.dialog("Plan")
def plan_dialog():
    """The money settings, with their own fields: nothing changes until Apply."""
    ccy = st.selectbox("Currency", CURRENCIES, key="plan_ccy")
    # the currency shows as an icon in the field when Material has one, otherwise in the label
    ccy_icon = CURRENCY_ICONS.get(ccy)
    ccy_label = "" if ccy_icon else f" ({ccy})"
    # whole amounts without ".00", but cents stay visible when there are any (10.12)
    new_initial = st.number_input(f"Initial{ccy_label}", min_value=0.0, max_value=storage.MAX_AMOUNT, step=100.0,
                                  format=amount_format("plan_initial"), icon=ccy_icon, key="plan_initial")
    new_monthly = st.number_input(f"Monthly{ccy_label}", min_value=0.0, max_value=storage.MAX_AMOUNT, step=50.0,
                                  format=amount_format("plan_monthly"), icon=ccy_icon, key="plan_monthly")
    st.segmented_control("Rebalance to target", list(engine.REBALANCE_RULES), required=True,
                         format_func=REBALANCE_LABELS.get, width="stretch", key="plan_rebalance")
    nothing = new_initial == 0 and new_monthly == 0
    if nothing:
        st.caption("Set an initial investment or a monthly deposit.")
    if st.button("Apply", type="primary", key="plan_apply", disabled=nothing):
        st.session_state.pending_settings = {k: st.session_state[f"plan_{k}"] for k in ("initial", "monthly", "rebalance")}
        st.session_state.pending_settings["base_ccy"] = st.session_state.plan_ccy
        st.rerun()


examples = storage.list_examples()

# ---------------- header: title and actions ----------------
saved_pies = active_storage.list_pies(user_id=user_id)
head, actions = st.columns([3, 2], vertical_alignment="bottom")
with head.container(horizontal=True, vertical_alignment="center"):
    st.title("Pie backtester", width="content")
    # a new key after opening a pie draws a fresh, closed menu (as for Examples)
    my_pies = st.popover(f"My pies ({len(saved_pies)})", key=f"my_pies_{st.session_state.setdefault('my_pies_round', 0)}",
                         on_change="rerun")


def is_mine(p):
    return not shared_storage or p.get("owner_id") == user_id


with my_pies:
    if getattr(active_storage, "last_error", None):
        st.warning(f"Supabase answered with an error, so saved pies can't be shown: {active_storage.last_error}.")
    for p in saved_pies:
        with st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"saved_row_{p['id']}"):
            # picking a pie opens it, like picking a file
            if st.button(md(p["name"]), key=f"my_open_{p['id']}", type="tertiary", width="stretch"):
                if load_pie(p):
                    st.session_state.saved_ref = saved_ref_of(p)
                st.session_state.my_pies_round += 1  # closes the menu
                st.rerun()
            st.caption(f"{len(p['assets'])} asset{'' if len(p['assets']) == 1 else 's'}"
                       + ("" if is_mine(p) else " · public"), width="content")
            if is_mine(p):
                # the menu closes first, or it stays on top of the dialog; no tooltips: they stayed on screen
                if st.button("Edit", key=f"edit_saved_{p['id']}"):
                    st.session_state.saved_dialog = p
                    st.session_state.my_pies_round += 1
                    st.rerun()
                if st.button("Delete", key=f"delete_saved_{p['id']}"):  # at once: Undo shows on the page
                    delete_saved(p)
                    st.session_state.my_pies_round += 1
                    st.rerun()
    if not saved_pies:
        st.caption("No saved pies yet. Use Save to keep a pie.")
    st.divider()
    export_slot = st.empty()  # filled after the share link, with the open pie
    uploaded = st.file_uploader("Import a pie (.json)", type="json")
    if uploaded is not None:
        # opens as soon as it's picked; file_id keeps it from opening again on every rerun
        try:
            uploaded.seek(0)
            raw_content = json.load(uploaded)
            # a downloaded unfinished pie (not at 100%) opens too: the editor's total line takes over
            is_valid, err = storage.validate_pie(raw_content, whole=False)
        except Exception as e:
            is_valid, err = False, f"it isn't valid JSON ({e})"
        if not is_valid:
            st.error(f"Could not load this file: {err}")
        elif st.session_state.get("loaded_file_id") != uploaded.file_id:
            st.session_state.loaded_file_id = uploaded.file_id
            load_pie(storage.normalize_pie(raw_content, whole=False))
            st.session_state.my_pies_round += 1
            st.rerun()

if "saved_dialog" in st.session_state:  # Edit in My pies, now that the menu is closed
    edit_dialog(st.session_state.pop("saved_dialog"))

with actions.container(horizontal=True, horizontal_alignment="right"):
    # A new key after each pick draws a fresh, closed menu. Forcing the old one's state closed instead
    # raced with a quick next click on Examples, which then needed a second click.
    examples_round = st.session_state.setdefault("examples_round", 0)
    with st.popover("Examples", icon=":material/auto_awesome:", key=f"examples_pop_{examples_round}",
                    on_change="rerun"):
        for i, ex in enumerate(examples):
            if st.button(md(ex["name"]), key=f"ex_pop_{i}", width="stretch"):
                load_pie(ex)
                st.session_state.examples_round += 1  # closes the menu
                st.rerun()
    can_save = bool(st.session_state.pie) and not (shared_storage and not user_id)
    if st.button("Save", icon=":material/save:", key="save_open", disabled=not can_save,
                 help=None if can_save or not st.session_state.pie else "Sign in to save pies."):
        save_dialog()
    share_pop = st.popover("Share", icon=":material/share:", disabled=not st.session_state.pie)

for _kind, _msg in st.session_state.pop("flashes", []):
    getattr(st, _kind)(_msg)

OWN = f"{st.session_state.pie_name or 'My Pie'} (editing)"  # the pie in the table

# ---------------- period: the only place time is set ----------------
with st.container(border=True, key="period"):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.session_state.period_pick = st.session_state.period
        st.segmented_control("Period", engine.PERIOD_PRESETS + ("Custom",), key="period_pick", required=True,
                             on_change=pick_period)
        # Streamlit's default lower bound is only ten years back
        # No max_value: a future date would turn the field red and silently keep the old value (and the old
        # results). Any date is taken, and the checks below say what's wrong. An end after today means "up to date".
        start = st.date_input("From", min_value=date(1970, 1, 1), max_value=date(2100, 1, 1), key="start",
                              format="YYYY-MM-DD", on_change=custom_period, width=160)
        end = st.date_input("To", min_value=date(1970, 1, 1), max_value=date(2100, 1, 1), key="end",
                            format="YYYY-MM-DD", on_change=custom_period, width=160)
    if start > date.today():
        st.warning("The start date is in the future. Pick a date up to today.")
    elif start >= end:
        st.warning("The start date must be before the end date.")
    period_detail = st.container()  # the coverage strip, the late-listing choice and the window sentence

# ---------------- plan: the money settings in one sentence ----------------
with st.container(border=True, key="plan", horizontal=True, vertical_alignment="center"):
    st.markdown(f"**Plan** &nbsp; " + md(
        f"{plan_amount(initial)} to start · "
        + (f"{plan_amount(monthly)} every month" if monthly else "no monthly deposits")
        + f" · {base_ccy} · rebalance {rebalance.lower()}"), width="stretch")
    if st.button("Edit plan"):
        for k in ("initial", "monthly", "rebalance"):
            st.session_state[f"plan_{k}"] = st.session_state[k]
        st.session_state.plan_ccy = base_ccy
        plan_dialog()

pies_slot = st.container()  # the pie cards; filled after the table and the results, so they show this run's

# ---------------- the open pie: changed only in the editor dialog ----------------
total_w = sum(float(a["Weight %"] or 0) for a in st.session_state.pie)
for _t in {a["Ticker"] for a in st.session_state.pie if is_bare(a["Ticker"])}:
    _hits = cached_resolve(_t, base_ccy)
    if _hits and _hits[0]["symbol"].upper() == _t:  # a real listing without suffix, e.g. a US stock
        st.session_state.verified_tickers.add(_t)


def start_editing(new=False):
    """Open the editor on a copy of the open pie (or an empty one): nothing changes until Apply."""
    st.session_state.draft = [] if new else [
        {"Ticker": a["Ticker"], "Name": a.get("Name") or a["Ticker"], "Weight %": float(a["Weight %"] or 0),
         "Lock": bool(a.get("Lock"))} for a in st.session_state.pie]
    st.session_state.draft_name = "My Pie" if new else st.session_state.pie_name
    st.session_state.draft_new = new
    st.session_state.draft_q = st.session_state.draft_paste = ""
    st.session_state.fix_report = None
    draft_changed()
    st.session_state.open_editor = True  # the dialog opens on the next run, over the updated page
    st.rerun()


def apply_draft():
    """The editor's rows and name become the open pie; a new pie joins the comparison like a loaded one.
    False when there's no room for it."""
    name = storage.clean_name(st.session_state.draft_name) or "My Pie"
    rows = [dict(r) for r in st.session_state.draft]
    st.session_state.pop("undo", None)
    if not st.session_state.draft_new:
        st.session_state.pie, st.session_state.pie_name = rows, name
        pie_changed()
        return True
    settings = {k: v for k, v in pie_payload().items() if k in ("currency", "initial", "monthly", "rebalance",
                                                                 "before_listing", "start", "end")}
    ok = load_pie(dict(settings, name=name, assets=[
        {"ticker": r["Ticker"], "weight": float(r["Weight %"] or 0), "name": r["Name"] or r["Ticker"]} for r in rows]))
    st.session_state.get("pending_settings", {}).pop("period", None)  # same dates: the period preset stays
    return ok


def editor_body():
    """Search, the table (weights and locks), Scale and Split, a pasted list, and a preview. It reruns on its
    own; the page only changes on Apply."""
    if st.session_state.get("draft_base_version") != st.session_state.draft_version:
        # a snapshot, changed only by code: passing the live rows makes Streamlit drop the next edit
        st.session_state.draft_base = pd.DataFrame(st.session_state.draft,
                                                   columns=["Ticker", "Weight %", "Lock", "Name"]).astype({"Lock": bool})
        st.session_state.draft_base_version = st.session_state.draft_version
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.text_input("Pie name", key="draft_name", max_chars=storage.MAX_NAME_LENGTH)
        # assets come only from search (or a checked pasted list), so every ticker is a real Yahoo listing
        q = st.text_input("Search by name, ticker or ISIN", label_visibility="collapsed", key="draft_q",
                          placeholder="Search by name, ticker or ISIN, e.g. IE00BK5BQT80, AAPL").strip()
        if q:
            hits = cached_search(q)
            if not hits:
                st.info("No matches. Try the ticker with its exchange suffix, e.g. VWCE.DE, IWDA.AS, CSPX.L.")
            else:
                hits = engine.rank_listings(hits, base_ccy)
                labels = [f"{h['symbol']} — {h['name']} · {h['exchange']} · {h['currency']}"
                          + ("" if h["type"] in ("ETF", "EQUITY") else f" · {h['type'].lower()}") for h in hits]
                choice = st.selectbox("Results", range(len(hits)), format_func=lambda i: labels[i])
                # a callback with the listing bound now: a click that lands while the dialog is still redrawing
                # adds exactly what was shown
                added = any(a["Ticker"] == hits[choice]["symbol"] for a in st.session_state.draft)
                st.button("Added ✓" if added else "Add to pie", type="primary", disabled=added,
                          on_click=add_to_draft, args=(hits[choice]["symbol"], hits[choice]["name"]))
        if st.session_state.draft:
            edited = st.data_editor(
                st.session_state.draft_base,
                # "delete": rows can be removed but not typed in, and clicking a column name sorts the view
                num_rows="delete", disabled=["Ticker"], width="stretch", hide_index=True,
                # weights first and narrow, so long ETF names can't push them out of view
                column_order=["Ticker", "Weight %", "Lock", "Name"],
                column_config={
                    "Ticker": st.column_config.TextColumn(width="small", help="Yahoo symbol. Add assets with the search above."),
                    "Weight %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.01,
                                                              format="%.2f", width="small"),
                    "Lock": st.column_config.CheckboxColumn(
                        width="small", help="Scale to 100% and Split evenly leave a locked weight as it is"),
                    "Name": st.column_config.TextColumn(width="large"),
                },
                key=f"draft_editor_{st.session_state.draft_version}",
            )
            rows = edited.dropna(subset=["Ticker"]).fillna({"Weight %": 0.0, "Name": "", "Lock": False})
            rows["Ticker"] = rows["Ticker"].astype(str).str.strip().str.upper()
            st.session_state.draft = rows[rows["Ticker"] != ""].to_dict("records")
        else:
            st.caption("Search above to add assets, or paste a list below.")
        draft = st.session_state.draft
        total = sum(float(a["Weight %"] or 0) for a in draft)
        bare = [a["Ticker"] for a in draft if is_bare(a["Ticker"])]
        named = [a["Ticker"] for a in draft]
        dupes = sorted({t for t in named if named.count(t) > 1})
        if draft:
            # the live total says why results would be missing
            if storage.adds_up(total):
                st.markdown(":green[**Total 100% ✓**]")
            elif total < 100:
                st.markdown(f":orange[**Total {total:.2f}% · {100 - total:.2f}% left**]")
            else:
                st.markdown(f":orange[**Total {total:.2f}% · {total - 100:.2f}% too much**]")
            with st.container(horizontal=True, vertical_alignment="center"):
                if bare and st.button("Fix tickers", type="primary",
                                      help="Look up the exchange suffix Yahoo needs, e.g. VWRA → VWRA.L"):
                    with st.spinner("Looking up tickers…"):
                        fix_tickers(base_ccy)
                    st.rerun(scope="fragment")
                st.button("Scale to 100%", disabled=storage.adds_up(total) or total == 0,
                          on_click=change_draft, args=(editing.scale_to_100,))
                st.button("Split evenly", on_click=change_draft, args=(editing.split_evenly,))
            st.caption("Scale to 100% and Split evenly leave locked rows as they are.")
            if bare:
                st.warning("These tickers have no exchange suffix, so Yahoo can't find them (or finds a "
                           "different security): " + ", ".join(bare) + ". Click 'Fix tickers'.")
            if st.session_state.fix_report:
                changed, unresolved = st.session_state.fix_report
                if changed:
                    lines = [f"- **{old}** → `{new}` {name} ({exch})" +
                             (f" · other listings: {', '.join(alts)}" if alts else "")
                             for old, new, name, exch, alts in changed]
                    st.success("Updated tickers. Check they're the listings you hold.\n\n" + "\n".join(lines))
                if unresolved:
                    st.error("Couldn't find " + ", ".join(unresolved) +
                             ". Search for them by ISIN above and add them again.")
            if dupes:
                st.warning("These tickers are in the pie more than once: " + ", ".join(dupes) +
                           ". Delete one of the rows.")
        with st.expander("Paste a list"):
            text = st.text_area("One ticker and weight per line", key="draft_paste",
                                placeholder="VWCE.DE 60\nAGGH.L 40",
                                help="Rows copied from a spreadsheet work too: a ticker column and a weight column.")
            found = []
            if text.strip():
                pairs, unread = editing.parse_paste(text)
                preview = []
                with st.spinner("Looking up tickers…"):
                    for t, w in pairs:
                        hit = find_listing(t, base_ccy)
                        preview.append({"Pasted": t, "Listing": hit[0] if hit else "not found",
                                        "Name": hit[1] if hit else "", "Weight %": w})
                        if hit:
                            found.append((hit[0], hit[1], w))
                if preview:
                    st.dataframe(pd.DataFrame(preview), hide_index=True, width="stretch",
                                 column_config={"Weight %": st.column_config.NumberColumn(format="%.2f")})
                if unread:
                    st.caption("Couldn't read " + "; ".join(md(b) for b in unread) + ".")
            # always there: the list was only read once the box lost focus (or on Ctrl+Enter, which a browser
            # inside an editor may take), so typing showed nothing and offered nothing to press
            with st.container(horizontal=True):
                st.button("Check list", help="Looks up each ticker. Nothing changes until Replace rows or Add to rows.")
                st.button("Replace rows", disabled=not found, on_click=paste_rows, args=(found, True))
                st.button("Add to rows", disabled=not found, on_click=paste_rows, args=(found, False))
    with right:
        live = sorted([(a["Ticker"], a["Name"] or a["Ticker"], float(a["Weight %"] or 0)) for a in draft
                       if float(a["Weight %"] or 0) > 0], key=lambda r: -r[2])
        if live:
            st.markdown("**Allocation**")
            st.plotly_chart(donut(live, readable(st.session_state.own_color), 300), config={"displayModeBar": False})
        if live and storage.adds_up(total) and not bare and not dupes and settings_ok:
            try:
                res, _, _ = cached_backtest(tuple((t, w) for t, _, w in live), start, end, base_ccy, initial,
                                            monthly, rebalance, "cash" if rule == "cash" else "wait")
                m = engine.metrics(res)
                st.markdown("**Preview**")
                st.caption("On its own, " + engine.window_label(res["total"].index[0], res["total"].index[-1]))
                with st.container(horizontal=True):
                    st.metric("Value now", money(m["final_value"], base_ccy, True))
                    st.metric("Per year", "n/a" if pd.isna(m["cagr"]) else signed_pct(m["cagr"] * 100))
                    st.metric("Worst fall", f"{m['max_drawdown'] * 100:.1f}%".replace("-", "−"))
            except Exception as e:
                st.caption(f"No preview: {md(e)}")
        elif live:
            st.caption("The preview appears once the weights add up to 100% and every ticker is found.")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Discard changes"):
            st.rerun()
        can_save = (bool(draft) and storage.adds_up(total) and not bare and not dupes
                    and not (shared_storage and not user_id))
        if st.button("Save to My pies", icon=":material/save:", disabled=not can_save,
                     help="Sign in to save pies." if shared_storage and not user_id else None):
            if apply_draft():
                try:
                    saved, updated = save_open_pie(st.session_state.pie_name)
                    flash("success", f"{'Updated' if updated else 'Saved'} pie '{md(saved['name'])}'.")
                except Exception as ex:
                    flash("error", f"Failed to save pie: {ex}")
            st.rerun()
        if st.button("Apply", type="primary", disabled=st.session_state.draft_new and not draft):
            apply_draft()
            st.rerun()


pie_editor = st.dialog("Edit pie", width="large")(editor_body)
new_pie_editor = st.dialog("New pie", width="large")(editor_body)

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
            link = f"{st.context.url or ''}?p={encoded_param}"
            st.code(link, language=None, wrap_lines=True)  # its copy icon shows on hover
            if on_phone():  # no hover on a phone, so the icon never shows: a button instead
                copy_button(link)
            st.caption("The link has your pie and its settings.")
if share_ok:
    norm_export = storage.normalize_pie(pie_data_raw)
    norm_export.pop("id")  # a fresh id is assigned when the file is saved somewhere
    pie_json = json.dumps(norm_export, indent=2)
else:
    pie_json = json.dumps(pie_data_raw or {}, indent=2)  # an unfinished pie can still be kept as a file
export_slot.download_button("Download pie (.json)", pie_json, icon=":material/download:", file_name="my_pie.json",
                            mime="application/json", disabled=not st.session_state.pie)

# ---------------- results ----------------
# Results update by themselves: no run button. Your pie is shown once it's valid, next to any compared pies.
pie = [a for a in st.session_state.pie if float(a["Weight %"] or 0) > 0]
tickers = [a["Ticker"] for a in pie]
own_ready = bool(pie and storage.adds_up(sum(float(a["Weight %"]) for a in pie))
                 and len(set(tickers)) == len(tickers) and not any(is_bare(t) for t in tickers))
settings_ok = start < end and start <= date.today() and (initial > 0 or monthly > 0)
names = {a["Ticker"]: a.get("Name") or a["Ticker"] for a in pie}
entries = ([(OWN, tuple((a["Ticker"], float(a["Weight %"])) for a in pie))] if own_ready else []) + \
    [(e["name"], tuple(e["weights"].items())) for e in st.session_state.compare]

results, late, currencies, first_full, no_window = {}, {}, {}, {}, {}
rule = st.session_state.start_rule
if settings_ok and entries:
    with st.spinner("Loading prices and simulating…"):
        # each pie's first day with every price in the period, and its assets that list after From
        for name, assets in entries:
            try:
                prices, info = prices_for([t for t, _ in assets], start, date.today(), base_ccy)
            except Exception as e:
                if name == OWN:
                    st.error(f"Backtest failed: {e}")
                else:
                    st.warning(f"'{md(name)}' is left out: {md(e)}")
                continue
            currencies.update(info["currencies"])
            firsts = prices.apply(lambda col: col.first_valid_index())
            late[name] = {t: d.date() for t, d in firsts.items() if d.date() > start + pd.Timedelta(days=7)}
            day = engine.first_full_day(prices.loc[:pd.Timestamp(end)], start)
            if day is None and rule != "cash":
                ticker, listed = max(firsts.items(), key=lambda x: x[1])
                no_window[name] = f"No prices in this period: {ticker} starts {listed.day} {listed:%b %Y}"
            else:
                first_full[name] = day
        days = (dict.fromkeys(first_full, pd.Timestamp(start)) if rule == "cash"
                else engine.start_days(first_full, "common" if rule == "common" and len(first_full) > 1 else "own"))
        for name, assets in entries:
            if name not in days:
                continue
            try:
                results[name], _, _ = cached_backtest(assets, days[name].date(), end, base_ccy, initial, monthly,
                                                      rebalance, "cash" if rule == "cash" else "wait")
            except Exception as e:
                if name == OWN:
                    st.error(f"Backtest failed: {e}")
                else:
                    st.warning(f"'{md(name)}' is left out: {md(e)}")

late = {n: t for n, t in late.items() if t}  # pies with an asset that lists after From
pie_colors = {OWN: readable(st.session_state.own_color)} | {e["name"]: readable(e.get("color") or "#8a8d96")
                                                           for e in st.session_state.compare}


def plain_name(n):
    return st.session_state.pie_name if n == OWN else n


def nice(d):
    return f"{d.day} {d:%b %Y}"


def months(a, b):
    return round((pd.Timestamp(b) - pd.Timestamp(a)).days / 30.44)


def coverage_figure(names):
    """One bar per pie: the period asked for (light), where an asset has no prices yet (dotted) and the days
    the results use (in the pie's colour)."""
    fig = go.Figure()
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    for n in names:
        label = html.escape(plain_name(n))
        fig.add_trace(go.Scatter(x=[t0, t1], y=[label] * 2, mode="lines",
                                 line=dict(color="rgba(138,141,150,.25)", width=10)))
        if n in late:
            ticker, listed = max(late[n].items(), key=lambda x: x[1])
            listed = pd.Timestamp(min(listed, end))
            fig.add_trace(go.Scatter(x=[t0, listed], y=[label] * 2, mode="lines",
                                     line=dict(color="#8a8d96", width=2, dash="dot")))
            fig.add_annotation(x=t0 + (listed - t0) / 2, y=label, yshift=11, showarrow=False,
                               text=f"no {html.escape(ticker)} prices yet", font=dict(size=10, color="#5f636e"))
        if n in results:
            fig.add_trace(go.Scatter(x=[results[n]["total"].index[0], t1], y=[label] * 2, mode="lines",
                                     line=dict(color=pie_colors[n], width=10)))
    fig.update_layout(height=44 + 30 * len(names), showlegend=False, margin=dict(l=0, r=10, t=6, b=22),
                      yaxis=dict(autorange="reversed"), xaxis=dict(range=[t0, t1]))
    return fig


def pick_start_rule():
    st.session_state.start_rule = st.session_state.start_rule_pick


with period_detail:
    place = {OWN: st.session_state.own_order} | {e["name"]: e.get("order", 0) for e in st.session_state.compare}
    shown_pies = sorted([n for n, _ in entries if n in late or n in results], key=place.get)  # the cards' order
    if late and shown_pies:
        screen_reader_text("Which days each pie has prices for: " + "; ".join(
            f"{plain_name(n)} from {nice(results[n]['total'].index[0])}" for n in shown_pies if n in results) + ".")
        st.plotly_chart(coverage_figure(shown_pies), config={"staticPlot": True})
    if results:
        last_day = max(r["total"].index[-1] for r in results.values())
        first_day = min(r["total"].index[0] for r in results.values())
        if rule == "own" and len(results) > 1 and late:
            sentence = (f"Each pie starts on its own first price, so their periods differ; prices to "
                        f"{nice(last_day)}.")
        else:
            sentence = f"Every number and chart below covers {engine.window_label(first_day, last_day)}."
        if late:
            ticker, listed = max(((t, d) for n in late for t, d in late[n].items()), key=lambda x: x[1])
            holders = [plain_name(n) for n in late if ticker in late[n]]
            sentence += (f" {ticker}'s slice is held as cash until {nice(listed)}." if rule == "cash" else
                         f" {' and '.join(holders)} can't start earlier: {ticker} has prices from {nice(listed)}.")
        st.markdown(md(sentence))
    if late:
        ticker, listed = max(((t, d) for n in late for t, d in late[n].items()), key=lambda x: x[1])
        several = len(entries) > 1
        options = ["common", "own", "cash"] if several else ["common", "cash"]
        common = max(first_full.values()) if first_full else None
        lost = max(((n, months(max(d, pd.Timestamp(start)), common)) for n, d in first_full.items()),
                   key=lambda x: x[1], default=(None, 0))
        labels = {
            "common": (f"Start all pies on {nice(common)}" if several else f"Start on {nice(common)}")
                      if common is not None else "Start when every asset has prices",
            "own": "Each pie from its own first price",
            "cash": f"Start on {nice(start)}, holding cash until {ticker} lists",
        }
        captions = {
            "common": ":green-badge[recommended] " + (
                "Same days, same deposits, so the pies can be ranked."
                + (f" {md(plain_name(lost[0]))} loses its first {lost[1]} months." if lost[1] >= 1 else "")
                if several else "The pie as you built it, over a shorter period."),
            "own": "Every pie shows its own dates, so they aren't ranked against each other.",
            "cash": f":orange-badge[changes the strategy] Its slice waits as cash, earning nothing, for "
                    f"{months(start, listed)} months.",
        }
        # the choice is kept in start_rule, so it survives while this card isn't shown
        st.session_state.start_rule_pick = rule if rule in options else "common"
        st.radio("When the pies start", options, key="start_rule_pick", format_func=labels.get,
                 captions=[captions[o] for o in options], label_visibility="collapsed", on_change=pick_start_rule)
own = results.get(OWN)

# ---------------- pies and their results, as cards side by side ----------------
phone = on_phone()
own_complete = bool(st.session_state.pie) and storage.adds_up(total_w)
card_keys = [k for _, k in sorted(([(st.session_state.own_order, "own")] if st.session_state.pie else [])
                                  + [(e.get("order", 0), str(i)) for i, e in enumerate(st.session_state.compare)])]
card_name = {k: OWN if k == "own" else st.session_state.compare[int(k)]["name"] for k in card_keys}
assets_of = dict(entries)
by_pie = {n: engine.metrics(r) for n, r in results.items()}
BEST_ROW = {"final_value": "value", "twr_total": "return", "cagr": "per_year", "max_drawdown": "worst_fall"}
# the rows each pie is best at; pies over different periods aren't ranked
marks = {n: {BEST_ROW[m] for m in ms} for n, ms in engine.best_marks(by_pie).items()} if rule != "own" or not late else {}
CARD_COLUMNS = 3  # a lone pie doesn't stretch across the page


def card_rows(k):
    """(ticker, name, weight) of a card's pie, biggest first."""
    if k == "own":
        rows = [(a["Ticker"], a.get("Name") or a["Ticker"], float(a["Weight %"] or 0)) for a in st.session_state.pie]
    else:
        e = st.session_state.compare[int(k)]
        rows = [(t, e.get("names", {}).get(t, t), w) for t, w in e["weights"].items()]
    return sorted([r for r in rows if r[2] > 0], key=lambda r: -r[2])


def donut(rows, color, height):
    """The pie's target weights, in shades of its colour, with the ticker and weight next to each slice."""
    fig = go.Figure(go.Pie(labels=[r[0] for r in rows], values=[r[2] for r in rows], hole=0.55, sort=False,
                           marker=dict(colors=shades(color, len(rows)), line=dict(color="#ffffff", width=2)),
                           hovertext=[r[1] for r in rows],
                           hovertemplate="%{label}<br>%{hovertext}<br>%{value:.2f}%<extra></extra>",
                           # shades alone are hard to tell apart
                           texttemplate="%{label}<br>%{value:.1~f}%", textposition="outside", automargin=True))
    fig.update_layout(margin=dict(t=16, b=16, l=16, r=16), height=height, showlegend=False,
                      annotations=[dict(text="Target", x=0.5, y=0.5, showarrow=False, font_size=13)])
    return fig


def status_of(k):
    """Saved / Unsaved changes / Not saved yet, and the badge colour."""
    ref = st.session_state.saved_ref if k == "own" else st.session_state.compare[int(k)].get("saved_ref")
    if not ref:
        return "Not saved yet", "orange"
    if k != "own":
        return "Saved", "green"
    same = pie_key(st.session_state.pie_name, [(a["Ticker"], a["Weight %"] or 0) for a in st.session_state.pie])
    return ("Saved", "green") if same == ref["key"] else ("Unsaved changes", "orange")


def card_name_html(k):
    st.html(f'<div class="card-name">{html.escape(plain_name(card_name[k]))}</div>')


def pie_card(k):
    """A pie's card: name, saved state, actions and its donut (on a phone also its results)."""
    name, rows = card_name[k], card_rows(k)
    with st.container(border=True, key=f"pie_card_{k}"):
        card_name_html(k)
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            status, color = status_of(k)
            with st.container(key=f"status_{k}", width="content"):
                st.badge(status, color=color)
            st.caption(f"{len(rows)} asset{'' if len(rows) == 1 else 's'}")
        with st.container(horizontal=True, gap="small"):
            if st.button("Edit", key=f"edit_{k}", disabled=k != "own" and not own_complete,
                         help=None if k == "own" or own_complete else
                         f"Finish '{plain_name(OWN)}' first (weights at 100%), then edit this one"):
                if k != "own":
                    open_compared(int(k))
                start_editing()
            if st.button("Copy", key=f"copy_{k}", disabled=k == "own" and not own_complete,
                         help="Adds a copy to the comparison, so you can change it and compare the two"):
                add_to_comparison({"name": f"{plain_name(name)} (copy)",
                                   "assets": [{"ticker": t, "weight": w, "name": n} for t, n, w in rows]})
                st.rerun()
            if st.button("Remove", key=f"remove_{k}"):
                undo = {"label": f"Removed '{plain_name(name)}'.", "kind": "remove", "data": snapshot()}
                if k == "own":
                    close_open_pie()
                else:
                    st.session_state.compare.pop(int(k))
                st.session_state.undo = undo
                st.rerun()
        if rows:
            st.plotly_chart(donut(rows, readable(pie_colors[name]), 180 if phone else 240), key=f"donut_{k}",
                            config={"displayModeBar": False})
        else:
            st.caption("No assets yet: Edit to add some.")
        if phone:
            result_card(k)


def big(text):
    st.html(f'<div class="big-number">{html.escape(text)}</div>')


def result_row(k, row, label, sub, value, help_text):
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(f"{label}  \n:small[{sub}]", help=help_text, width="stretch")
        with st.container(key=f"val_{k}_{row}", width="content"):
            st.markdown(f"**{value}**")
        if row in marks.get(card_name[k], ()):
            with st.container(key=f"best_{k}_{row}", width="content"):
                st.badge("best", color="green")


def result_card(k):
    """A pie's results: value now and the gain on money put in, Return, Per year and Worst fall."""
    name = card_name[k]
    with st.container(border=not phone, key=f"result_{k}"):
        if not phone:
            card_name_html(k)
        res = results.get(name)
        if res is None:
            if name in no_window:
                st.caption(md(no_window[name]) + ".")
            elif k == "own" and not own_ready:
                st.caption("Results appear once its weights add up to 100% and every ticker is found.")
            else:
                st.caption("No results for this pie: see the message above.")
            return
        m, ccy = by_pie[name], base_ccy
        first_day, last_day = res["total"].index[0], res["total"].index[-1]
        with st.container(key=f"window_{k}"):
            st.caption(engine.window_label(first_day, last_day))
        st.caption("Value now", help=f"What the pie is worth on {nice(last_day)}. The gain is the value minus "
                                     "everything you put in; the percentage is the gain on the money you put in.")
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            with st.container(key=f"val_{k}_value", width="content"):
                big(money(m["final_value"], ccy, True))
            if "value" in marks.get(name, ()):
                with st.container(key=f"best_{k}_value", width="content"):
                    st.badge("best", color="green")
        gain = m["profit"]
        on_put_in = f" ({gain / m['invested'] * 100:+.0f}%)".replace("-", "−") if m["invested"] > 0 else ""
        deposits = int((res["invested"].diff() > 0).sum())
        st.caption(md(f"{'−' if gain < 0 else '+'}{money(abs(gain), ccy, True)} {'loss' if gain < 0 else 'gain'}"
                      f"{on_put_in} on {money(m['invested'], ccy, True)} put in"),
                   help=f"{money(res['invested'].iloc[0], ccy)} to start and {deposits} monthly deposits.")
        result_row(k, "return", "Return", "time-weighted", signed_pct(m["twr_total"] * 100),
                   "How the pie itself grew, as if all the money had been in from the start (time-weighted). "
                   "It's higher or lower than the gain on money put in because money added later had less time "
                   "to grow or fall.")
        short = pd.isna(m["cagr"])
        result_row(k, "per_year", "Per year", "needs a year of data" if short else "on average",
                   "n/a" if short else signed_pct(m["cagr"] * 100),
                   "The steady yearly growth that gives the same Return (compound annual growth rate, CAGR).")
        dd = res["twr"] / res["twr"].cummax() - 1
        result_row(k, "worst_fall", "Worst fall", f"lowest on {nice(dd.idxmin())}",
                   f"{m['max_drawdown'] * 100:.1f}%".replace("-", "−"),
                   f"The largest drop from a previous high. Volatility: {m['volatility'] * 100:.1f}% a year.")
        # why it starts later than From, and what the shared window cost it
        if rule != "cash" and first_day > pd.Timestamp(start) + pd.Timedelta(days=7):
            own_late = late.get(name, {})
            if own_late and max(own_late.values()) >= first_day.date() - pd.Timedelta(days=7):
                ticker = max(own_late, key=own_late.get)
                st.caption(md(f"Starts {nice(first_day)}: {ticker} listed then."))
            else:
                st.caption(md(f"Starts {nice(first_day)}, with the other pies."))
        own_day = first_full.get(name)
        if rule == "common" and own_day is not None and own_day + pd.Timedelta(days=7) < first_day:
            alone, _, _ = cached_backtest(assets_of[name], own_day.date(), end, base_ccy, initial, monthly,
                                          rebalance, "wait")
            a = engine.metrics(alone)
            per_year = "" if pd.isna(a["cagr"]) else f", {signed_pct(a['cagr'] * 100)}/yr"
            st.caption(md(f"On its own, from {nice(alone['total'].index[0])}: "
                          f"{money(a['final_value'], ccy, True)}{per_year}"))
            if st.button("Each from its own start", key=f"own_start_{k}", type="tertiary"):
                st.session_state.start_rule = "own"
                st.rerun()


def card_css():
    """Each card's colour: a top border and a dot before its name."""
    rules = "".join(
        # on a phone the results are inside the pie's card, which already has the border
        f".st-key-pie_card_{k}{'' if phone else f',.st-key-result_{k}'}"
        f"{{border-top:4px solid {pie_colors[card_name[k]]} !important}}"
        f".st-key-pie_card_{k} .card-name::before,.st-key-result_{k} .card-name::before"
        f"{{content:'●';content:'●' / '';color:{pie_colors[card_name[k]]};margin-right:6px}}"
        for k in card_keys)
    st.html(f"<style>{rules}</style>")


with pies_slot:
    if "undo" in st.session_state:  # what the last Remove or Delete did, and a way back
        with st.container(horizontal=True, vertical_alignment="center", key="undo_note"):
            st.caption(md(st.session_state.undo["label"]), width="content")
            if st.button("Undo", key="undo_button", type="tertiary"):
                undo_last()
                st.rerun()
    if not card_keys:
        # no example buttons here: examples live in the header menu
        st.info("No pies yet. Pick one from Examples at the top, or start a new pie.")
        if st.button("New pie"):
            start_editing(new=True)
    else:
        card_css()
        with st.container(horizontal=True, vertical_alignment="bottom"):
            st.subheader("Pies", anchor=False, width="content")
            st.caption(f"{len(card_keys)} of {MAX_COMPARED} · the donuts show target weights", width="stretch")
            if st.button("New pie", type="tertiary", disabled=len(card_keys) >= MAX_COMPARED,
                         help=None if len(card_keys) < MAX_COMPARED else f"Up to {MAX_COMPARED} pies: remove one first"):
                start_editing(new=True)
            if st.session_state.compare and st.button("Clear comparison", type="tertiary"):
                st.session_state.undo = {"label": "Cleared the comparison.", "kind": "remove", "data": snapshot()}
                st.session_state.compare = []
                st.rerun()
        if phone:
            for k in card_keys:
                pie_card(k)
        else:
            for start_at in range(0, len(card_keys), MAX_COMPARED):
                row = card_keys[start_at:start_at + MAX_COMPARED]
                for col, k in zip(st.columns(max(len(row), CARD_COLUMNS)), row):
                    with col:
                        pie_card(k)

if st.session_state.pop("open_editor", False):
    (new_pie_editor if st.session_state.draft_new else pie_editor)()

if card_keys and not phone:  # on a phone each pie's results are in its card
    st.divider()
    with st.container(key="results"):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            st.subheader("Results", anchor=False, width="content")
            if results and (rule != "own" or not late):
                some = next(iter(results.values()))
                st.caption(md(f"{engine.window_label(some['total'].index[0], some['total'].index[-1])} · "
                              f"{money(by_pie[next(iter(results))]['invested'], base_ccy, True)} put in each"),
                           width="stretch")
        for col, k in zip(st.columns(max(len(card_keys), CARD_COLUMNS)), card_keys):
            with col:
                result_card(k)

if results:
    st.divider()
    # each pie keeps the colour of its card in every chart
    colors = pie_colors
    if own:
        res, ccy = own, base_ccy
    tab_names = (["Growth", "By asset", "Holdings"] if own else ["Growth"]) + ["How it's calculated"]
    tabs = dict(zip(tab_names, st.tabs(tab_names)))
    with tabs["Growth"]:
        years = max((r["total"].index[-1] - r["total"].index[0]).days for r in results.values()) / 365.25
        with st.container(horizontal=True, vertical_alignment="center"):
            # log by default for long horizons: equal % moves then look equal
            scale = st.segmented_control("Scale", ["Linear", "Log"], default="Log" if years > 10 else "Linear",
                                         required=True, label_visibility="collapsed")
            # time is set only by the Period at the top; zooming is for looking closer
            st.caption("Drag across the chart to look closer. Zooming changes no numbers: they follow the "
                       "Period above.", width="stretch")
            if st.button("Reset zoom"):
                st.session_state.zoom_round = st.session_state.get("zoom_round", 0) + 1  # a fresh chart

        # every pie has the same amount put in (later ones join with it), so the earliest one draws it
        first = min(results.values(), key=lambda r: r["total"].index[0])
        lines = {name: r["total"] for name, r in results.items()}
        invested = first["invested"]
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.74, 0.26], vertical_spacing=0.05)
        fig.add_trace(go.Scatter(x=invested.index, y=invested, name="You put in", hovertemplate="%{y:,.0f}",
                                 line=dict(color="#8a8d96", dash="dot", shape="hv")), row=1, col=1)
        for name, r in results.items():
            fig.add_trace(go.Scatter(x=lines[name].index, y=lines[name], name=html.escape(plain_name(name)), hovertemplate="%{y:,.0f}",
                                     line=dict(color=colors[name], width=2.6 if name == OWN else 1.8)),
                          row=1, col=1)
            dd = (r["twr"] / r["twr"].cummax() - 1) * 100
            fig.add_trace(go.Scatter(x=dd.index, y=dd, name=html.escape(plain_name(name)), showlegend=False, hovertemplate="%{y:.1f}%",
                                     line=dict(color=colors[name], width=1.2),
                                     fill="tozeroy" if len(results) == 1 else None), row=2, col=1)

        # names at the line ends instead of a legend, nudged apart so they don't overlap; on a phone those
        # labels would take half the width, so a legend below the chart takes their place
        phone = on_phone()
        values = pd.concat(list(lines.values()) + [invested])
        lo, hi = max(values.min(), 1e-9) * 0.95, values.max() * 1.05
        if scale == "Log":
            lo, hi = np.log10(lo), np.log10(hi)
        ends = sorted([(n, s.iloc[-1], colors[n]) for n, s in lines.items()] +
                      [("You put in", invested.iloc[-1], readable("#5f636e"))], key=lambda x: -x[1])
        y_prev = 1.08
        for name, value, color in ([] if phone else ends):
            y = ((np.log10(value) if scale == "Log" else value) - lo) / (hi - lo)
            y = min(y, y_prev - 0.07)
            y_prev = y
            label = name.removesuffix(" (editing)")
            fig.add_annotation(x=1.005, y=y, xref="x domain", yref="y domain", xanchor="left", showarrow=False,
                               text=f"<b>{html.escape(label)}</b> {money(value, base_ccy, True)}", font=dict(color=color, size=12))
        fig.update_yaxes(type="log" if scale == "Log" else "linear", range=[lo, hi], title=base_ccy, row=1, col=1)
        fig.update_yaxes(title="% below high", row=2, col=1)
        fig.update_layout(height=560, hovermode="x unified", showlegend=phone, margin=dict(t=60 if phone else 10, b=10, r=10 if phone else 190),
                          legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, title=None))  # above the chart
        screen_reader_text("Growth chart: " + "; ".join(
            f"{n.removesuffix(' (editing)')} ends at {money(v, base_ccy, True)}" for n, v, _ in ends
            if n != "You put in") + f"; you put in {money(invested.iloc[-1], base_ccy, True)}.")
        st.plotly_chart(fig, key=f"growth_{st.session_state.get('zoom_round', 0)}",
                        config={"displayModeBar": False} if phone else {})
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
                              margin=dict(t=20, b=20),
                              legend=dict(orientation="h", y=-0.15) if on_phone() else {})
            screen_reader_text("Value of each asset now: " + "; ".join(
                f"{n}: {money(v, ccy, True)}" for n, v in vals.iloc[-1].items()) + ".")
            st.plotly_chart(fig, config={"displayModeBar": False} if phone else {})
            norm = engine.rebase(res["prices"]).rename(columns=names)
            fig2 = px.line(norm, color_discrete_sequence=PALETTE, title="Each asset, rebased to 100")
            fig2.update_layout(height=380, hovermode="x unified", legend_title="", yaxis_title="",
                               legend=dict(orientation="h", y=-0.2) if on_phone() else {})
            st.plotly_chart(fig2, config={"displayModeBar": False} if phone else {})
        with tabs["Holdings"]:
            table = engine.per_asset_table(res, weights, names)
            st.dataframe(table, hide_index=True, width="stretch",
                         column_order=(["Ticker", "Current %", "Value", "Gain"] if on_phone() else
                                       ["Asset", "Ticker", "Target %", "Current %", "Drift", "Value", "Gain",
                                        "Price return %", "History"]),
                         column_config={
                             "Target %": st.column_config.NumberColumn(format="%.1f"),
                             "Current %": st.column_config.NumberColumn(format="%.1f"),
                             "Drift": st.column_config.NumberColumn(
                                 format="%+.1f pp", help="Current weight minus target weight, in percentage points"),
                             "Value": st.column_config.NumberColumn(
                                 f"Value ({ccy})" if money_column(ccy) == "localized" else "Value",
                                 format=money_column(ccy)),
                             "Gain": st.column_config.NumberColumn(
                                 f"Gain ({ccy})" if money_column(ccy) == "localized" else "Gain",
                                 format=money_column(ccy), help="What this asset added to the pie's gain"),
                             "Price return %": st.column_config.NumberColumn(
                                 "Price change since start", format="%+.1f%%",
                                 help="How the asset's price moved over the period: not the return on the money put "
                                      "into it, which depends on when the deposits came in"),
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
    st.info("Fix the period or the plan above to see the backtest.")
