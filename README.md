# NASDAQ Top 1,000 + All NSE — HHLL(44) Weekly Alert Screener

## Display rule
The dashboard displays a stock only if the HHLL(44) algorithm generates a new Buy, Strong Buy, Sell, or Strong Sell event on the **latest available weekly candle**. Historical signals are not carried forward into the current alert list. Each BUY/SELL list displays only the stock symbol and signal label.

## Universe
- NASDAQ: up to the top 1,000 eligible stocks ranked by market capitalization from Nasdaq's screener feed.
- NSE: equity symbols from the official NSE equity directory.

## Run
1. Install Python 3.10 or later.
2. Open a terminal in this folder and run `pip install -r requirements.txt`.
3. Run `streamlit run app.py` or double-click `run.bat` on Windows.

The scan downloads weekly OHLC data through Yahoo Finance. Data availability and exchange symbol mapping can affect coverage. A blank list means no latest-week alert was detected among successfully downloaded symbols; it does not mean the market has no possible setups.
