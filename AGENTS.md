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
- Sidebar settings are keyed widgets (`base_ccy`, `start`, `end`, `initial`, `monthly`, `rebalance`, `before_listing`, `save_pie_name_input`). Change them only through `load_pie()`, which applies them on the next rerun through `pending_settings`.
- Show messages that must survive a `st.rerun()` with `flash(kind, msg)`.
- Load prices with `prices_for()`, which caches each ticker separately, so the single backtest and the comparison reuse downloads. Every pie, yours and the compared ones, is simulated by `cached_backtest`, cached per pie, so unrelated reruns don't re-simulate. Each pie starts on its first day with prices within the sidebar dates.
- Sign-in and storage: `st.login` (Google) identifies users as `google:<sub>`. Supabase is a database used only from the server with the service key, so `SupabaseStorageBackend` must filter every query by `owner_id`; RLS is not the safety net. Never offer the guest account when storage is shared.
- Commits: never add `Co-Authored-By:` or `Claude-Session:` trailers.
- Claude state stays in this repo. Memory goes in `.claude/memory/` (set by `autoMemoryDirectory` in the gitignored `.claude/settings.local.json`; Claude Code ignores that key in the committed settings), plans in `.claude/plans/`, and progress in `.claude/LEDGER.md`. Update the ledger before pausing.

## Things that are easy to get wrong

- Yahoo sometimes drops a ticker from a batch download. `load_prices` retries the missing ones once, so don't treat one failed run as a bad ticker.
- Yahoo tickers: European ETFs need an exchange suffix (`VWCE.DE`). US stocks don't (`AAPL`). `resolve_ticker` must rank the exact bare listing above foreign ones such as `AAPL.TO`, which is a Canadian depositary receipt.
- `st.date_input` defaults to a lower bound 10 years back, so always pass `min_value`.
- Streamlit 1.66 DOM, for E2E tests: selects are react-aria comboboxes (`get_by_role("combobox", name=label)`). The pie table is a canvas grid, so read it through its hidden `table` and edit by clicking coordinates, then Enter, then typing. Dates commit on blur, not on Tab. Wait for reruns with `stApp[data-test-script-state=notRunning]`.
