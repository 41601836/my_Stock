# -*- coding: utf-8 -*-
"""diag_data_integrity2.py —— 污染扩散面取证（只读）"""
import sqlite3

conn = sqlite3.connect("file:db/stock_data.db?mode=ro", uri=True, timeout=30)
c = conn.cursor()

# 1) 0902 stk_factor 覆盖的 ts_code 分布特征（是否为字典序连续段=拉取中断）
r = c.execute("SELECT COUNT(DISTINCT ts_code), MIN(ts_code), MAX(ts_code) "
              "FROM stk_factor WHERE trade_date='20260902'").fetchone()
print(f"0902 stk_factor: {r[0]} 只, 范围 {r[1]} ~ {r[2]}")
r = c.execute("SELECT COUNT(*) FROM (SELECT DISTINCT ts_code FROM stk_factor "
              "WHERE trade_date='20260902') WHERE ts_code > '600000.SH'").fetchone()
print(f"  其中 ts_code > 600000.SH 的: {r[0]} 只 (若≈0 则是字典序前半段=拉取中断)")

# 2) EVO 层是否被污染
for t in ["factor_values_evo", "stock_tracker_evo", "recommendation_tracker", "stock_tracker"]:
    try:
        r = c.execute(f"SELECT MAX(trade_date) d, COUNT(*) n FROM {t}").fetchone()
        print(f"{t}: latest={r[0]} rows={r[1]}")
    except Exception as e:
        print(f"{t}: {e}")

# 3) 追踪表若已有 0902 记录，看推荐行是否包含失真股
try:
    rows = c.execute("SELECT trade_date, COUNT(*) FROM recommendation_tracker "
                     "WHERE trade_date='20260902' GROUP BY trade_date").fetchall()
    print(f"recommendation_tracker@0902: {rows}")
except Exception as e:
    print(f"recommendation_tracker 查询: {e}")

# 4) 0902 截面 return_10d / return_20d 失真量级
r = c.execute("SELECT SUM(CASE WHEN return_10d < -0.27 THEN 1 ELSE 0 END), "
              "SUM(CASE WHEN return_20d < -0.45 THEN 1 ELSE 0 END) "
              "FROM factor_values WHERE trade_date='20260902'").fetchone()
print(f"0902 截面: return_10d<-27%: {r[0]}  return_20d<-45%: {r[1]}")

# 5) 前一日 0901 截面是否健康（对照组）
r = c.execute("SELECT SUM(CASE WHEN return_5d < -0.27 THEN 1 ELSE 0 END), COUNT(*) "
              "FROM factor_values WHERE trade_date='20260901'").fetchone()
print(f"0901 对照截面: return_5d<-27%: {r[0]} / 总数 {r[1]}")

conn.close()
