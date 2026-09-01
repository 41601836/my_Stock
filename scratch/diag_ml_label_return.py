# -*- coding: utf-8 -*-
"""临时诊断：标签档位 vs 实际 T+1 执行收益的单调性（验证 M5.2 结果自洽性，用后可删）"""
import sys, os, json
import numpy as np
import pandas as pd
import sqlite3

sys.path.insert(0, "/Users/lyu/Documents/my_Stock")
sys.path.insert(0, "/Users/lyu/Documents/my_Stock/web/backend")
os.chdir("/Users/lyu/Documents/my_Stock")
from config.paths import PATHS
DB = PATHS.database.stock_data
fwd = 5

meta = json.load(open("evo/datasets/ds_f5_b10.meta.json", encoding="utf-8"))
d = np.load("evo/datasets/ds_f5_b10.npz")
y, seg, date_idx, code_idx = d["y"], d["seg"], d["date_idx"], d["code_idx"]
dates, codes = meta["dates"], meta["codes"]

conn = sqlite3.connect(DB)
dp = pd.read_sql("SELECT ts_code, trade_date, close, adj_factor FROM daily_prices "
                 "WHERE trade_date >= (SELECT MIN(trade_date) FROM factor_values_evo)", conn)
conn.close()
dp["trade_date"] = dp["trade_date"].astype(str)
dp["close_adj"] = (dp["close"].astype(float) * dp["adj_factor"].fillna(1.0).astype(float)).astype(np.float32)
ca = dp.pivot_table(index="trade_date", columns="ts_code", values="close_adj", aggfunc="last").sort_index()
# T+1 执行口径
exec_ret = (ca.shift(-(fwd + 1)) / ca.shift(-1) - 1.0).astype(np.float32)
limit_up = (ca.pct_change(fill_method=None) >= 0.095)

rows = np.where(seg == 2)[0]
di_arr = date_idx[rows]
print("=" * 72)
print("测试段（20250701~20260831）标签档位 vs 实际 T+1 执行收益（剔除涨停不可买）")
print("=" * 72)
buckets = {i: [] for i in range(10)}
market_all = []
for di in np.unique(di_arr):
    m = di_arr == di
    dt = dates[di]
    if dt not in exec_ret.index:
        continue
    er = exec_ret.loc[dt].to_numpy()
    buyable = ~limit_up.loc[dt].to_numpy()
    yy = y[rows][m]
    cc = code_idx[rows][m]
    market_all.append(np.nanmean(er[buyable]))
    for lab in range(10):
        sel = (yy == lab) & buyable[cc]
        r = er[cc[sel]]
        r = r[~np.isnan(r)]
        if len(r):
            buckets[lab].append(r.mean())

print(f"{'档位':>4} | {'平均T+1收益/5日':>14} | 说明")
print("-" * 50)
for lab in range(10):
    v = np.mean(buckets[lab]) * 100
    tag = "（最高档）" if lab == 9 else ("（最低档）" if lab == 0 else "")
    print(f"{lab:>4} | {v:>13.2f}% | {tag}")
print("-" * 50)
print(f"全市场平均（buyable）: {np.mean(market_all)*100:.2f}%/5日")
mono = all(np.mean(buckets[i]) < np.mean(buckets[i + 1]) for i in range(9))
print(f"档位单调性（低→高递增）: {'PASS' if mono else 'FAIL'}")
