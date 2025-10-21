# FakeoutScreener
Introducing a Streamlit dashboard to filter out Indian stocks which have created fake breakouts in current week.

# Futures & Options Stock Screener

## What This Screener Shows ❓

The Futures & Options stocks are selected using **Weekly OHLC** analysis. The following filters are applied by default:

- **Weekly Fakeout Signals**: LONG/SHORT signals based on price behavior.
- **Monthly Movers**: Stocks that show a ±3% threshold to avoid consolidating stocks.

### Signal Explanation
In the following week, when the price retraces and closes below or above the prior week's high/low, a fakeout is signaled.

### Additional Features
- Additional filters can be applied on the Screener page.

### Data Format
- The **Datetime** column is standardized to the format: **YYYY-MM-DD**.
- Numeric values are rounded to **3** decimals.

### Data Update
- Data is updated on a daily basis at **12:00 IST** after market close.
