# Pie backtester

Build a Trading 212-style pie of ETFs and stocks, pick a start date, and see how it would have developed until today (or any end date).

## Features

- **Curated Example Pies**: Quickly load popular strategies like All-World ETF, 60/40 Stocks & Bonds, Three-Fund Portfolio, Dividend Focus, and Tech Leaders.
- **Compare Pies**: Loading another pie keeps the previous one on the charts, so you can compare up to 5 pies on the same settings: overlaid value and drawdown charts, a table of returns, CAGR, drawdown and volatility, and a picker to see each pie's allocation.
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

1. **Load or Create a Pie**: Pick an example under **Examples** at the top, open a saved pie or a `.json` file from **My pies**, or click **New pie** and search by ISIN, ticker or name (e.g. `VWCE.DE`, `EUNA.DE`, `AAPL`).
2. **Edit it**: **Edit** on a pie's card opens the editor. The live total shows how much is left; "Split evenly" and "Scale to 100%" leave locked rows alone, and "Paste a list" takes rows copied from a spreadsheet. Nothing changes on the page until **Apply**.
3. **Pick the period and the plan**: The period bar at the top (1Y to Max, or your own dates) is the only place time is set. **Edit plan** sets the currency, initial amount, monthly deposit and rebalancing.
4. **See the Results**: Each pie gets a card with its value, gain on money put in, return, yearly growth and worst fall. The Growth, By asset and Holdings tabs follow below; zooming a chart is only for looking closer.
5. **Assets that list later**: When an asset has no prices yet at the start, a card under the dates says so and lets you choose: start every pie on the same later day (the default, so they can be ranked), each pie from its own first price, or hold cash until the asset lists.
6. **Check the maths**: the "How it's calculated" tab lists every formula ([docs/how-its-calculated.md](docs/how-its-calculated.md)).
7. **Compare**: Load another pie, and both show side by side, each in its own colour. **Copy** compares a version of a pie; **Remove** takes one away, with **Undo**.
8. **Share or Save**: Use **Share** (a link with the open pie and its settings) or **Save** at the top.

## Google sign-in and cloud storage (optional)

Without this, the app saves pies in `saved_pies.json` on the machine running it, with an optional local guest account.

Sign-in uses Streamlit's built-in Google login, and users are known as `google:<their Google id>`. Supabase is only a database: the Streamlit server talks to it with the secret key and limits every query to the signed-in user's pies plus public ones. Row-level security is on with no policies, so the public anon key can't read or write anything.

1. **Google:** in the [Google Cloud Console](https://console.cloud.google.com/), set up the OAuth consent screen (Google Auth Platform):
   - Audience: External.
   - Add yourself as a test user. While the app is in *Testing*, only test users can sign in.

   Then create an OAuth client of type *Web application*. Add `http://localhost:8501/oauth2callback` and your deployed URL plus `/oauth2callback` as authorized redirect URIs.
2. **Supabase:** create a project. Create the `pies` table from [`supabase/migrations/`](supabase/migrations/) in one of two ways:
   - **GitHub integration:** in **Project Settings → Integrations → GitHub**, set the working directory to `.`, turn on **Deploy to production**, and choose `main` as the production branch. The migration then runs on the next push to `main`.
   - **By hand:** paste the migration into the SQL Editor.

   Either way, it's safe to run on a project that already has the table.
3. **Secrets:** for local use, put these in `.streamlit/secrets.toml`, which is gitignored. On Streamlit Community Cloud, paste them under **App settings → Secrets**, with `redirect_uri` set to `https://your-app.streamlit.app/oauth2callback`.

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_KEY = "sb_secret_..."  # the secret or legacy service_role key; never the anon/publishable key

[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "a-long-random-string"   # e.g. python -c "import secrets; print(secrets.token_urlsafe(32))"

[auth.google]
client_id = "your-google-client-id"
client_secret = "your-google-client-secret"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

After changing secrets or requirements on Streamlit Cloud, use **Manage app → Reboot app**. To let other people sign in, click **Publish app** under *Audience* in the Google console.

With Supabase configured:
- Visitors who aren't signed in can browse and load public pies, but can't save.
- Signed-in users save their own pies, see their own and public pies, and can delete only their own.
- The local guest account is turned off, because every guest would share one account.

### Troubleshooting

| What you see | Cause and fix |
|---|---|
| "Google sign-in isn't set up" | A key is missing from `[auth]` or `[auth.google]`. All five above are needed. |
| "Internal server error" at `…/auth/login` | `httpx` isn't installed. `requirements.txt` must have `streamlit[auth]`; reboot the app after changing it. |
| "Bad request" (400) at `…/auth/login` | `server_metadata_url` is wrong. Copy it exactly as above, without a trailing slash. |
| Google says `redirect_uri_mismatch` | `redirect_uri` and the URI in the Google client must match exactly: `http`/`https`, port, no trailing slash. |
| Google says "Access blocked" | Your account isn't a test user, or the app isn't published yet. |
| "Supabase answered with an error … HTTP 404" | The `pies` table doesn't exist: deploy or run the migration. |
| "Supabase answered with an error … HTTP 401" | The key isn't the secret/service_role key. |
| A warning about `SUPABASE_KEY` | That's the old anon-key setting. Replace it with `SUPABASE_SERVICE_KEY`. |

The secret key bypasses row-level security, so only `storage.py` keeps users apart: every query is filtered by `owner_id`, and `tests/test_supabase.py` checks this. Keep that in mind when adding queries. To rotate the key, create a new one in Supabase, update the secrets, then delete the old one.

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
