# -*- coding: utf-8 -*-
"""定位 daily_prices 尾部数据伪影: 重复行 / 复权因子跳变 / close 序列"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('db/stock_data.db')

# 1) 重复行检查
dup = pd.read_sql("""
    SELECT ts_code, trade_date, COUNT(*) AS c
    FROM daily_prices WHERE trade_date >= '20260501'
    GROUP BY ts_code, trade_date HAVING c > 1 LIMIT 10
""", conn)
print('duplicate (ts_code,trade_date) rows:', len(dup))
if len(dup):
    print(dup.to_string(index=False))

# 2) 000001.SZ 的 close / adj_factor 序列
one = pd.read_sql("""
    SELECT trade_date, close, adj_factor FROM daily_prices
    WHERE ts_code='000001.SZ' AND trade_date >= '20260510' AND trade_date <= '20260705'
    ORDER BY CAST(trade_date AS INTEGER)
""", conn)
one['close_adj'] = one['close'] * one['adj_factor']
print('\n000001.SZ 2026/05-06:')
print(one.to_string(index=False))

# 3) adj_factor 分布（最近 vs 稍早）
af = pd.read_sql("""
    SELECT trade_date, COUNT(*) n, SUM(adj_factor=1.0) n_af1, AVG(adj_factor) avg_af
    FROM daily_prices WHERE trade_date >= '20260401'
    GROUP BY trade_date ORDER BY CAST(trade_date AS INTEGER)
""", conn)
print('\nadj_factor=1.0 占比按日:')
print(af.tail(25).to_string(index=False))

conn.close()
