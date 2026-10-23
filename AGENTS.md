# Pie backtester: agent guide

A Streamlit app that backtests a Trading 212-style pie of ETFs and stocks using Yahoo Finance data.

## Layout

- `app.py`: the Streamlit UI (one script that reruns on every interaction)
- `engine.py`: data loading (yfinance), ticker resolution, simulation, metrics. Contains no UI code.
- `editing.py`: what the pie editor does to its rows (lock-aware split and scale, adding an asset). Contains no UI code.
- `storage.py`: pie schema (`validate_pie` / `normalize_pie`), local JSON backend, Supabase backend
- `sharing.py`: `?pie=` share-link encoding (zlib + urlsafe base64)
- `auth.py`: Streamlit native Google auth, plus a local guest account (local storage only)
- `examples/*.json`: example pies, including their settings (currency, start, monthly, rebalance)
- `tests/`: unit tests (`test_app.py` runs `app.py` in-process with Streamlit's `AppTest`). `tests/e2e/`: Playwright browser tests.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/playwright install chromium
.venv/bin/streamlit run app.py                # http://localhost:8501
.venv/bin/python -m pytest                    # unit tests only (what CI runs)
.venv/bin/python -m pytest -m e2e             # browser tests: starts the app itself, needs internet
```

## Conventions

- Keep logic that can be tested out of `app.py` and in `engine.py`, `editing.py`, `storage.py` or `sharing.py`, with unit tests.
- The page follows `.claude/designs/round-2026-10-23/B-workspace.png` plus C's late-listing choice card (the user's pick, 2026-10-23): Period → Plan → Pies → Results → charts, with no sidebar. "My pies" and the account are in the header.
- Settings live in session state: `start`/`end` (the period bar's date fields), `period` (a preset in `engine.PERIOD_PRESETS`, or "Custom"; a preset keeps the dates in step. Max is the user's definition: the earliest day a pie has prices for all its assets; with several pies, the earliest of those days, whatever the start rule (`engine.max_start`). Not the earliest price of any one asset: that gave 1980 for Apple. Not the pies' shared start either: that hid the start choice), `base_ccy`/`initial`/`monthly`/`rebalance` (plain keys, edited in the Plan dialog through its own `plan_*` fields) and `start_rule` (`engine.START_RULES`: common start, each its own, or cash). Change them through `load_pie()`, `pending_settings` (applied on the next rerun) or a widget's `on_change`. A setting whose widget isn't always drawn (`period`, `start_rule`) is a plain key that its widget (`period_pick`, `start_rule_pick`) is re-seeded from each run, so the choice survives while the widget is hidden. Saved pies and links still carry `before_listing` ("cash" when `start_rule` is cash, else "wait"). The open pie's name and colour live in `pie_name` and `own_color`.
- Each loaded pie has a fixed colour from `PIE_COLORS` (Okabe-Ito; also in `.streamlit/config.toml`). It's assigned when the pie is loaded and used for its card (top border and dot), chart lines and donut shades (`shades()`). Keep the donut for allocations, one per pie card: the user chose it over bar charts. Its slices are shades of the pie's colour (at most 50% white) with the ticker and weight written next to each slice, so no legend is needed.
- Pies are edited in a dialog (`editor_body`, opened by `start_editing()`, with `source=` a compared pie's index): it works on a copy, `draft`, and the page changes only on Apply (`apply_draft()`), including which pie is open; a card's Save on a compared pie (`save_source`) likewise swaps only when saved. Closing either dialog leaves the page as it was. Its table starts from `draft_base`, a snapshot that only changes on `draft_changed()`; passing the live rows makes Streamlit drop every other edit. Inside the dialog, rerun with `st.rerun(scope="fragment")` or a widget callback; a plain `st.rerun()` closes it.
- Pies are often matched by their weights (`load_pie`, `add_to_comparison`), and a copy has the same weights as its source: `add_to_comparison(source=…)` lets a pie's own copy through, `duplicate_ok=True` lets the open pie move aside next to its copy.
- The editor applies only a finished pie (weights at 100%, every ticker found, each once); unfinished pies still arrive from links and files and open, with the reason on their card.
- Compared pies: by default every pie starts on the latest of their first full-price days (`engine.start_days`), so they get the same deposits and can be ranked (`engine.best_marks`). The choice card under the dates offers each pie's own start (no "best" marks) or cash until listing. There's no averaged start value any more.
- Buttons: icon + word for Save, Share, Examples and downloads (`icon=":material/…:"`). Words only for sign-in, destructive and app-specific actions (Edit, Copy, Remove, New pie, Undo). The user chose this; don't make buttons icon-only.
- `PAGE_CSS` is emitted twice, on the page and inside the editor dialog: while the dialog reruns on its own, the page's style element stopped applying (toasts went back over the header). `PAGE_CSS` and `card_css()` in `app.py` style the cards through `st-key-*` classes and Streamlit's test ids, so check the page after upgrading Streamlit.
- Remove, Delete and Clear comparison act at once and offer Undo (`snapshot()` / `undo_last()`); there's no confirmation dialog.
- Examples live only in the header menu: the user removed the example buttons from the empty page.
- `docs/how-its-calculated.md` is shown in the "How it's calculated" tab. Update it whenever a formula in `engine.py` changes.
- Format money with `money(x, ccy, compact)` (in `engine.py`). Pie names and tickers come from links and files, so they're text: pass them through `md()` before Markdown, button labels, captions or messages (it also breaks bare `http://` and `www.` auto-links), and through `html.escape` before Plotly labels, legends and `st.html`.
- Show messages that must survive a `st.rerun()` with `flash(kind, msg)` (they queue, so several can show); `flash("toast", msg)` for a toast (a plain `st.toast` before `st.rerun()` is lost).
- Each pie card says Saved / Unsaved changes / Not saved yet by comparing `pie_key()` (name and assets, not the settings) with `saved_ref`. Set `saved_ref` whenever a pie is opened from or saved to storage; it travels with a pie in and out of the comparison.
- Pie colours shown as text or lines go through `readable()`, which lightens them on the dark theme to 4.5:1.
- Phones: Streamlit doesn't tell the app the screen width, so `on_phone()` checks the user agent. Phone-only layout (one card per pie with its results inside, a legend above the Growth chart instead of end labels, no Plotly toolbar) goes through it; touch-only CSS uses `@media (pointer:coarse)`.
- Load prices with `prices_for()`. It keeps each ticker's full history for the day in `price_store()` (shared by all visitors) and cuts it to the period, so date changes download nothing and a pie only fetches its new tickers, in one request. Every pie, yours and the compared ones, is simulated by `cached_backtest`, cached per pie, so unrelated reruns don't re-simulate. Each pie's start day comes from the start rule above.
- Sign-in and storage: `st.login` (Google) identifies users as `google:<sub>`. Supabase is a database used only from the server with the service key, so `SupabaseStorageBackend` must filter every query by `owner_id`; RLS is not the safety net. Never offer the guest account when storage is shared.
- Commits: never add `Co-Authored-By:` or `Claude-Session:` trailers.
- Claude state stays in this repo. Memory goes in `.claude/memory/` (set by `autoMemoryDirectory` in the gitignored `.claude/settings.local.json`; Claude Code ignores that key in the committed settings), plans in `.claude/plans/`, and progress in `.claude/LEDGER.md` (gitignored, local only). Update the ledger before pausing.

## Skills in this repo

- `.claude/skills/proposing-design-options/` shows the user design options as pictures. It covers research, parallel design directions, same-state mockups rendered to PNG with `render_mockups.py`, and the choice and its record. To use it in other projects, copy the folder to `~/.claude/skills/` (all projects) or to another project's `.claude/skills/`.

## Things that are easy to get wrong

- Yahoo sometimes drops a ticker from a batch download. `load_prices` retries the missing ones once, so don't treat one failed run as a bad ticker.
- Yahoo tickers: European ETFs need an exchange suffix (`VWCE.DE`). US stocks don't (`AAPL`). `resolve_ticker` must rank the exact bare listing above foreign ones such as `AAPL.TO`, which is a Canadian depositary receipt.
- `st.date_input` defaults to a lower bound 10 years back, so always pass `min_value`.
- Streamlit drops a button click when the next request (e.g. a new search) arrives within some 50 ms of it. No person is that fast (0 of 10 lost at a 300 ms pace); don't chase it again.
- A widget whose value the app writes (the From/To dates under a preset) can echo its old value back after a quick next click, and its `on_change` then fires as if the person had typed it. `custom_period()` ignores dates in `preset_dates`, the ones presets wrote lately.
- Sign-in needs `streamlit[auth]` in `requirements.txt`. With `authlib` alone, `httpx` is missing and `st.login` fails with a 500 at `/auth/login`. The secrets aren't the cause.
- Streamlit 1.66 DOM, for E2E tests: selects are react-aria comboboxes (`get_by_role("combobox", name=label)`). The pie table is a canvas grid, so read it through its hidden `table` and edit by double-clicking the cell's coordinates, then typing (in a dialog, Enter and Escape go to the grid's hidden table). Dates commit on blur, not on Tab. Wait for reruns with `stApp[data-test-script-state=notRunning]`. Find dialogs by test id `stDialog`: popovers have role "dialog" too. A dialog opened from inside a popover sits under it, so close the popover first (bump its key) and open the dialog on the next run.
