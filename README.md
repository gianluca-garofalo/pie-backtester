# Pie backtester

Build a Trading 212-style pie of ETFs and stocks, pick a start date, and see how it would have developed until today (or any end date).

## Features

- **Curated Example Pies**: Quickly load popular strategies like All-World ETF, 60/40 Stocks & Bonds, Three-Fund Portfolio, Dividend Focus, and Tech Leaders.
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
5. **Share or Save**: Copy the share link from the sidebar or save the pie to your account/local storage.

## Setup Supabase & Authentication (Optional)

To enable cloud storage and Google authentication, create `.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-supabase-anon-key"

[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "your-random-cookie-secret-key"

[auth.google]
client_id = "your-google-client-id"
client_secret = "your-google-client-secret"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

Then run `schema.sql` in your Supabase SQL Editor to set up the `pies` table and Row Level Security (RLS) policies.

If secrets are not provided, the app runs out-of-the-box in local storage mode using `saved_pies.json`.

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
