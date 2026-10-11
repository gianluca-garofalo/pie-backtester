# Pie backtester

Build a Trading 212-style pie of ETFs and stocks, pick a start date, and see how it would have developed until today (or any end date).

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Your browser opens at http://localhost:8501.

## How to use

1. Search by ISIN, name or ticker (e.g. `IE00BK5BQT80`, `Vanguard FTSE All-World`, `AAPL`) and add assets.
2. Set the weights in the table (they must add up to 100%), or use "Split evenly".
3. In the sidebar, choose currency, start/end date, initial amount, monthly deposit and rebalancing.
4. Click "Run backtest".

## Tips

- European ETFs are listed on several exchanges. Use the listing you actually buy, e.g. `VWCE.DE` (Xetra, EUR), `IWDA.AS` (Amsterdam, EUR), `CSPX.L` (London, USD).
- Prices are adjusted for dividends and splits, so accumulating and distributing ETFs are compared fairly.
- Assets in other currencies are converted with daily FX rates into the pie currency.
- If an asset launched after your start date, the simulation starts when all assets have data.
- Save a pie as JSON from the sidebar and load it again later.

## Assumptions

Fractional shares, no fees or taxes, monthly deposits on the first trading day of each month split by target weights (like Trading 212 auto-invest), rebalancing only if you turn it on.
