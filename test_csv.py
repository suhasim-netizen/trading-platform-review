import pandas as pd

df = pd.read_csv('data/spy_2023_2026.csv', 
                 parse_dates=['Date'], index_col='Date')
df.columns = [c.lower() for c in df.columns]
df = df.sort_index()
print('Rows:', len(df))
print('Date range:', df.index[0], 'to', df.index[-1])
print(df[['close', 'volume']].head())
print(df[['close', 'volume']].tail())
