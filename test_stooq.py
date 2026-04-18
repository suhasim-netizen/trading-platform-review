import pandas_datareader.data as web
from datetime import datetime

try:
    df = web.DataReader('spy.us', 'stooq',
        datetime(2021, 1, 1),
        datetime(2024, 1, 1))
    df = df.sort_index()
    df.columns = [c.lower() for c in df.columns]
    print('Rows:', len(df))
    print(df[['close', 'volume']].head())
except Exception as e:
    print('FAILED:', e)
