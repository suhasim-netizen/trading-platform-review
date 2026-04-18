import pandas as pd
import os

tickers = ['avgo', 'lly', 'tsm', 'gev', 'lasr', 'lite', 'cohr', 'sndk', 'strl']
data_dir = 'data'

for ticker in tickers:
    path = os.path.join(data_dir, f'{ticker}_2023_2026.csv')
    if os.path.exists(path):
        df = pd.read_csv(path)
        print(f'{ticker.upper()}: {len(df)} rows, columns: {list(df.columns)}')
    else:
        print(f'{ticker.upper()}: MISSING - download from stooq.com')
