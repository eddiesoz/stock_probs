import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm

def run_analysis():
** ticker_input = input("\nEnter Stock Symbol: ").strip().upper()**
** ticker = ticker_input if ticker_input else "SPY"**
** print(f"\nFetching 10 years of data for {ticker}...")**
** data = yf.download(ticker, period='10y', interval='1d', progress=False)**
** if data.empty:**
** print("Error: No data found.")**
** return**
** returns = data['Close'].pct_change().dropna()**
** hist_5pct = (returns < -0.05).mean() * 100**
** ann_vol = returns.tail(252).std() * np.sqrt(252)**
** iv_prob = norm.cdf(-0.05, 0, ann_vol/np.sqrt(252)) * 100**
** final_prob = (hist_5pct * 0.7) + (iv_prob * 0.3)**
** print(f"\nRESULTS FOR {ticker}:")**
** print(f"Historical Frequency (>5% drop): {hist_5pct:.2f}%")**
** print(f"Market IV Expectation: {iv_prob:.2f}%")**
** print(f"FINAL BLENDED PROB: {final_prob:.2f}%")**

if name == 'main':
** run_analysis()**
