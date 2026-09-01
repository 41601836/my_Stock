# -*- coding: utf-8 -*-
"""复现 Jack 回测的基准截面: 检查 202604-202606 各周 future_return_5d 截面质量"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('db/stock_data.db')
q = "SELECT ts_code AS stock_code, trade_date, close, adj_factor FROM daily_prices WHERE trade_date >= '20260301'"
dp = pd.read_sql(q, conn)
dp['trade_date'] = dp['trade_date'].astype(str)
dp = dp.sort_values(['stock_code', 'trade_date']).reset_index(drop=True)
dp['close_adj'] = dp['close'] * dp['adj_factor']
dp['fr5'] = dp.groupby('stock_code')['close_adj'].shift(-5) / dp['close_adj'] - 1.0
dp['fr5'] = dp['fr5'].clip(-0.5, 0.8)

# 每周(每个trade_date)截面统计
g = dp.groupby('trade_date')['fr5']
stat = pd.DataFrame({
    'n': g.count(),
    'mean': g.mean(),
    'median': g.median(),
})
stat['clip80_pct'] = dp.assign(c=(dp.fr5 >= 0.799)).groupby('trade_date')['c'].mean() * 100
stat['clip50_pct'] = dp.assign(c=(dp.fr5 <= -0.499)).groupby('trade_date')['c'].mean() * 100
print(stat[stat.n > 0].tail(30).round(4).to_string())

# 查看最异常一天的构成
for d in ['20260515', '20260522', '20260626']:
    sub = dp[dp.trade_date == d].dropna(subset=['fr5'])
    if sub.empty:
        print(f'\n{d}: no data')
        continue
    print(f'\n=== {d}: n={len(sub)} mean={sub.fr5.mean():.4f} median={sub.fr5.median():.4f} ===')
    print('top6:', sub.nlargest(6, 'fr5')[['stock_code', 'close', 'adj_factor', 'fr5']].round(3).to_string(index=False))

# 数据行连续性: 抽查一只股票在5-6月的行间隔
one = dp[dp.stock_code == dp[dp.trade_date == '20260515'].stock_code.iloc[0]] if (dp.trade_date == '20260515').any() else None
conn.close()
