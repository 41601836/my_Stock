# -*- coding: utf-8 -*-
"""测试数据完整性闸门: 用当前 daily_prices 构造 df_aligned, 验证闸门行为"""
import sys, os
sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.abspath('web/backend'))

# 直接导入 _common 模块文件, 绕过 services/__init__.py 的聚合导入 (后者依赖 3.10+ 语法)
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "_common", os.path.abspath("web/backend/services/_common.py")
)
_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_common)
get_data_integrity_cfg = _common.get_data_integrity_cfg
check_data_integrity = _common.check_data_integrity
import sqlite3
import pandas as pd

# 模拟 validator 的 df_aligned 构造
conn = sqlite3.connect('db/stock_data.db')
df_prices = pd.read_sql(
    "SELECT ts_code AS stock_code, trade_date, close, adj_factor FROM daily_prices "
    "WHERE trade_date >= '20260601'", conn
)
conn.close()
df_prices['trade_date'] = df_prices['trade_date'].astype(str)
df_prices = df_prices.sort_values(['stock_code', 'trade_date']).reset_index(drop=True)
df_prices['close_adj'] = df_prices['close'] * df_prices['adj_factor']
df_prices['future_return_5d'] = df_prices.groupby('stock_code')['close_adj'].shift(-5) / df_prices['close_adj'] - 1.0
df_prices['future_return_5d'] = df_prices['future_return_5d'].clip(-0.5, 0.8)
df_aligned = df_prices.dropna(subset=['future_return_5d']).reset_index(drop=True)

print('df_aligned shape:', df_aligned.shape)
print('columns:', list(df_aligned.columns)[:8])

cfg = get_data_integrity_cfg()
print('cfg:', cfg)

result = check_data_integrity(df_aligned, cfg)
print('\n--- result ---')
print('passed:', result['passed'])
print('summary:', result['summary'])
print('violations count:', len(result['violations']))
if result['violations']:
    print('\nall violations:')
    for v in result['violations']:
        print(' ', v)
    # 按闸门分组统计
    from collections import Counter
    gates = Counter(v['gate'] for v in result['violations'])
    print('\nby gate:', dict(gates))
