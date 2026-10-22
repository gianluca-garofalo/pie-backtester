**Prices.** Daily closing prices from Yahoo Finance, adjusted for dividends and splits, so dividends are reinvested. Each price is converted into the pie's currency with Yahoo's exchange rate for that day (London prices in pence are divided by 100). On days when one market is closed, its last price is carried forward. There are no fees, taxes or spreads, and shares can be fractional.

**Simulation.** On the first day with prices, the initial amount $I$ is split by the target weights $w_i$ and buys $I\,w_i / P_{i,t}$ units of each asset. From the next month on, the monthly deposit $M$ is split and bought the same way on the first trading day of each month. With rebalancing on, the whole value is split by $w_i$ again on the first trading day of each period. If you hold cash for assets that list later, their slice stays as cash (earning nothing) until their first price. The pie's value on day $t$ is $V_t = \sum_i u_{i,t}\,P_{i,t} + \text{cash}_t$, where $u_{i,t}$ is the number of units held.

| Number | Formula | In words |
|---|---|---|
| **Value now** | $V_T$ | what the pie is worth on the last day |
| **You put in** | $C_T = I + nM$ | the initial amount plus $n$ monthly deposits |
| **Gain** | $V_T - C_T$ | the value minus what you put in |
| **Return** (time-weighted) | $R = \prod_t (1 + r_t) - 1$, with $r_t = \dfrac{V_t - D_t}{V_{t-1}} - 1$ | daily growth with that day's deposit $D_t$ taken out, so it measures the pie, not the timing of your deposits |
| **Per year** (CAGR) | $(1 + R)^{1/Y} - 1$, with $Y = \text{days} / 365.25$ | the steady yearly rate that gives the same return; needs a year of data |
| **Worst fall** (max drawdown) | $\min_t \left( G_t / \max_{s \le t} G_s - 1 \right)$, with $G_t = \prod_{s \le t} (1 + r_s)$ | the largest drop from a previous high, measured on growth so deposits can't hide it |
| **Volatility** | $\sigma(r_t)\,\sqrt{252}$ | how much daily returns swing, scaled to a year of 252 trading days |
| **Price return** (by asset) | $P_{i,T} / P_{i,0} - 1$ | how the asset's price moved over the period |
| **Drift** (holdings) | $\dfrac{u_{i,T}\,P_{i,T}}{V_T} - w_i$ | how far an asset has moved from its target weight, in percentage points |
| **Gain** (holdings) | $\sum_t u_{i,t-1}\,(P_{i,t} - P_{i,t-1})$ | each day's price move times the units held; the assets' gains add up to the pie's gain |

Compared pies use the same settings, and each one starts on its own first day with prices.
