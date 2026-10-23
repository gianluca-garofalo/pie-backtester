# Pie backtester: agent guide

A Streamlit app that backtests a Trading 212-style pie of ETFs and stocks using Yahoo Finance data.

## Layout

- `app.py`: the Streamlit UI (one script that reruns on every interaction)
- `engine.py`: data loading (yfinance), ticker resolution, simulation, metrics. Contains no UI code.
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

- Keep logic that can be tested out of `app.py` and in `engine.py`, `storage.py` or `sharing.py`, with unit tests.
- Sidebar settings are keyed widgets (`base_ccy`, `start`, `end`, `initial`, `monthly`, `rebalance`, `before_listing`). Change them only through `load_pie()` or `pending_settings`, which is applied on the next rerun. The open pie's name and colour live in `pie_name` and `own_color`, not in widgets.
- Each loaded pie has a fixed colour from `PIE_COLORS` (Okabe-Ito; also in `.streamlit/config.toml`). It's assigned when the pie is loaded and used for its chip, chart lines, table name and donut shades (`shades()`). Keep the donut for allocations: the user chose it over bar charts. Its slices are shades of the pie's colour (at most 50% white) with the ticker and weight written next to each slice, so no legend is needed.
- The pie table starts from `editor_base`, a snapshot that only changes on `pie_changed()`. Passing the live pie makes Streamlit drop every other edit.
- Buttons: icon + word for Save, Share, Examples and downloads (`icon=":material/…:"`). Words only for sign-in, destructive and app-specific actions. Only the ✕ on each pie chip is icon-only; its label "Remove <pie>" is hidden with CSS so screen readers still read it. The user chose this; don't make more buttons icon-only.
- The sidebar follows `.claude/designs/A-refined.png`, except that every setting has its own row (the user's choice, see `.claude/designs/sidebar-pairs-vs-stacked.png`). `SIDEBAR_CSS` in `app.py` fits the four rebalance buttons on one line and relies on Streamlit's test ids, so check the sidebar after upgrading Streamlit. The user chose the compact version: no `?` tooltips on the settings, a one-line account area, and no pie picker above the donut. They tried the alternatives and reverted.
- Examples live only in the header menu: the user removed the example buttons from the empty page.
- `docs/how-its-calculated.md` is shown in the "How it's calculated" tab. Update it whenever a formula in `engine.py` changes.
- Format money with `money(x, ccy, compact)` (in `engine.py`). Pass pie names and any text with `$` through `md()` before Markdown, button labels, captions or messages, or names turn into formatting, links or maths. Use `html.escape` for Plotly labels.
- Show messages that must survive a `st.rerun()` with `flash(kind, msg)`; `flash("toast", msg)` for a toast (a plain `st.toast` before `st.rerun()` is lost).
- Phones: Streamlit doesn't tell the app the screen width, so `on_phone()` checks the user agent. Phone-only layout (legend instead of end labels, fewer table columns) goes through it; touch-only CSS uses `@media (pointer:coarse)`.
- Load prices with `prices_for()`. It keeps each ticker's full history for the day in `price_store()` (shared by all visitors) and cuts it to the sidebar dates, so date changes download nothing and a pie only fetches its new tickers, in one request. Every pie, yours and the compared ones, is simulated by `cached_backtest`, cached per pie, so unrelated reruns don't re-simulate. Each pie starts on its first day with prices within the sidebar dates.
- Sign-in and storage: `st.login` (Google) identifies users as `google:<sub>`. Supabase is a database used only from the server with the service key, so `SupabaseStorageBackend` must filter every query by `owner_id`; RLS is not the safety net. Never offer the guest account when storage is shared.
- Commits: never add `Co-Authored-By:` or `Claude-Session:` trailers.
- Claude state stays in this repo. Memory goes in `.claude/memory/` (set by `autoMemoryDirectory` in the gitignored `.claude/settings.local.json`; Claude Code ignores that key in the committed settings), plans in `.claude/plans/`, and progress in `.claude/LEDGER.md` (gitignored, local only). Update the ledger before pausing.

## Skills in this repo

- `.claude/skills/proposing-design-options/` shows the user design options as pictures. It covers research, parallel design directions, same-state mockups rendered to PNG with `render_mockups.py`, and the choice and its record. To use it in other projects, copy the folder to `~/.claude/skills/` (all projects) or to another project's `.claude/skills/`.

## Things that are easy to get wrong

- Yahoo sometimes drops a ticker from a batch download. `load_prices` retries the missing ones once, so don't treat one failed run as a bad ticker.
- Yahoo tickers: European ETFs need an exchange suffix (`VWCE.DE`). US stocks don't (`AAPL`). `resolve_ticker` must rank the exact bare listing above foreign ones such as `AAPL.TO`, which is a Canadian depositary receipt.
- `st.date_input` defaults to a lower bound 10 years back, so always pass `min_value`.
- Sign-in needs `streamlit[auth]` in `requirements.txt`. With `authlib` alone, `httpx` is missing and `st.login` fails with a 500 at `/auth/login`. The secrets aren't the cause.
- Streamlit 1.66 DOM, for E2E tests: selects are react-aria comboboxes (`get_by_role("combobox", name=label)`). The pie table is a canvas grid, so read it through its hidden `table` and edit by clicking coordinates, then Enter, then typing. Dates commit on blur, not on Tab. Wait for reruns with `stApp[data-test-script-state=notRunning]`.
