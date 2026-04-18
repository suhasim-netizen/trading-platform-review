import yfinance as yf
spy = yf.Ticker('SPY')
hist = spy.history(start='2021-01-01', end='2024-01-01', auto_adjust=True)
print('Rows:', len(hist))
if len(hist) > 0:
    print(hist[['Close','Volume']].head())
else:
    print('EMPTY - yfinance failed')
