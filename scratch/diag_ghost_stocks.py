# -*- coding: utf-8 -*-
"""诊断：推荐列表中「不存在的股票」的真实状态（用后可删）"""
import sqlite3

CODES = ["920427.BJ", "920227.BJ", "600610.SH", "600622.SH", "600604.SH",
         "600594.SH", "600641.SH", "600479.SH", "600881.SH", "600691.SH"]
conn = sqlite3.connect("db/stock_data.db")
cur = conn.cursor()

cur.execute("SELECT MAX(trade_date) FROM factor_values_evo")
fdate = str(cur.fetchone()[0])
cur.execute("SELECT MAX(trade_date) FROM daily_prices")
pdate = str(cur.fetchone()[0])
print(f"因子日: {fdate} | 行情日: {pdate}\n")

print(f"{'代码':<12}{'stock_list名称':<14}{'list_date':<11}{'因子日有行':<8}{'行情最后日':<11}{'行情日有当日K':<10}")
for c in CODES:
    cur.execute("SELECT name, list_date FROM stock_list WHERE ts_code=?", (c,))
    row = cur.fetchone()
    name, list_date = (row if row else ("❌ 不在stock_list", "—"))
    cur.execute("SELECT COUNT(*) FROM factor_values_evo WHERE ts_code=? AND trade_date=?", (c, fdate))
    has_f = cur.fetchone()[0]
    cur.execute("SELECT MAX(trade_date) FROM daily_prices WHERE ts_code=?", (c,))
    last_px = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM daily_prices WHERE ts_code=? AND trade_date=?", (c, pdate))
    has_today = cur.fetchone()[0]
    print(f"{c:<12}{name:<14}{str(list_date):<11}{has_f:<10}{str(last_px):<13}{has_today}")

conn.close()
