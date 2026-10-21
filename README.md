# Pie backtester

Build a Trading 212-style pie of ETFs and stocks, pick a start date, and see how it would have developed until today (or any end date).

## Features

- **Curated Example Pies**: Quickly load popular strategies like All-World ETF, 60/40 Stocks & Bonds, Three-Fund Portfolio, Dividend Focus, and Tech Leaders.
- **Compare Pies**: Add example, saved or uploaded pies (or a snapshot of your own) to a comparison. Up to 5 pies are compared automatically on the same settings: overlaid value and drawdown charts plus a table of returns, CAGR, drawdown and volatility.
- **Share Links**: Share your pie setup instantly using compressed, URL-safe query parameters (`?pie=...`).
- **Save & Load**: Persist your custom pies locally or connect Supabase for cloud database storage.
- **Google Authentication**: Optional Google login via native Streamlit auth (`st.login("google")`).
- **Dividends & Rebalancing**: Daily price data adjusted for splits and dividends, with custom rebalancing intervals (Monthly, Quarterly, Yearly, or Never).

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501 in your browser.

## How to Use

1. **Load or Create a Pie**: Choose an example pie from the sidebar dropdown, upload a `.json` file, or search by ISIN, ticker, or name (e.g. `VWCE.DE`, `EUNA.DE`, `AAPL`) to add assets manually.
2. **Set Target Weights**: Ensure asset weights sum to 100% (or use the "Split evenly" button).
3. **Configure Simulation**: In the sidebar, set currency, initial amount, monthly contributions, and rebalancing rule.
4. **Run Backtest**: Click "Run backtest" to view performance charts, drawdowns, CAGR, and holdings breakdown.
5. **Compare**: Click "Add to comparison" under an example or saved pie, or "Add a copy to the comparison" under your pie. The comparison appears once there are two pies.
6. **Share or Save**: Copy the share link from the sidebar or save the pie to your account/local storage.

## Setup Supabase & Authentication (Optional)

For a full walkthrough, from creating the Google and Supabase accounts to deploying, see **[docs/CLOUD_SETUP.md](docs/CLOUD_SETUP.md)**.

Sign-in uses Streamlit's built-in Google login. Supabase is only a database: the Streamlit server talks to it with the service key and limits every query to the signed-in user. Create `.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_KEY = "your-supabase-service-role-key"  # server-side only, never put it in client code

[auth]
redirect_uri = "http://localhost:8501/oauth2callback"  # your deployed URL + /oauth2callback in production
cookie_secret = "a-long-random-string"

[auth.google]
client_id = "your-google-client-id"
client_secret = "your-google-client-secret"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

1. In Google Cloud Console, create an OAuth client of type "Web application" and add the `redirect_uri` above as an authorized redirect URI.
2. Run `schema.sql` in the Supabase SQL Editor. It creates the `pies` table, or upgrades the earlier one, with row-level security on and no policies, so the public anon key can't read or write pies.

With Supabase configured:
- Visitors who aren't signed in can browse and load public pies, but can't save.
- Signed-in users save their own pies, see their own and public pies, and can delete only their own.
- The local guest account is turned off, because every guest would share one account.

Without these secrets, the app runs in local storage mode using `saved_pies.json`, with an optional local guest account.

## Run Tests

```bash
python3 -m pytest                  # unit tests
```

Browser tests drive the real app in Chromium with Playwright. They need internet access for Yahoo Finance data:

```bash
pip install -r requirements-dev.txt
playwright install chromium
python3 -m pytest -m e2e
```

## Disclaimer

Not financial advice. Past performance is not indicative of future returns. This tool is for backtesting and educational purposes only.
