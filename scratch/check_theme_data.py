# -*- coding: utf-8 -*-
"""数据严谨性核查：题材排行板块 前端合成字段 vs DB 真实数据"""
import sqlite3

conn = sqlite3.connect("file:db/stock_data.db?mode=ro", uri=True)
c = conn.cursor()

c.execute("SELECT MAX(trade_date) FROM daily_prices")
d = c.fetchone()[0]
print("latest_date =", d)

# 1) 元器件板块：前端符号法口径复算
c.execute("""
SELECT COUNT(*),
       CAST(SUM(dp.amount * CASE WHEN mf.net_mf_amount > 0 THEN 1 ELSE -1 END) AS FLOAT)/100000.0 AS net_yi,
       SUM(dp.amount)/100000.0 AS total_amt_yi
FROM moneyflow mf
JOIN stock_list s ON mf.ts_code = s.ts_code
JOIN daily_prices dp ON mf.ts_code = dp.ts_code AND mf.trade_date = dp.trade_date
WHERE mf.trade_date = ? AND s.industry LIKE '%元器件%'
""", (d,))
n, net_yi, tot = c.fetchone()
print(f"[1] 元器件: stocks={n}, 符号法净流入={net_yi:.2f}亿, 板块总成交={tot:.2f}亿")

# 2) 元器件真实主力净流入合计（万元→亿）
c.execute("""
SELECT SUM(mf.net_mf_amount)/10000.0
FROM moneyflow mf JOIN stock_list s ON mf.ts_code = s.ts_code
WHERE mf.trade_date = ? AND s.industry LIKE '%元器件%'
""", (d,))
print("[2] 元器件 真实net_mf合计 =", round(c.fetchone()[0], 2), "亿")

# 3) 全市场主力净流入 / 主力买入
c.execute("SELECT SUM(net_mf_amount)/10000.0, SUM(buy_lg_amount+buy_elg_amount)/10000.0 FROM moneyflow WHERE trade_date = ?", (d,))
r = c.fetchone()
print(f"[3] 全市场: net_mf合计={r[0]:.1f}亿, 主力买入合计={r[1]:.1f}亿")

# 4) 各板块符号法净流入 Top10（对齐前端排序）
c.execute("""
SELECT s.industry, COUNT(*) AS cnt,
       CAST(SUM(dp.amount * CASE WHEN mf.net_mf_amount > 0 THEN 1 ELSE -1 END) AS FLOAT)/100000.0 AS net_yi
FROM moneyflow mf
JOIN stock_list s ON mf.ts_code = s.ts_code
JOIN daily_prices dp ON mf.ts_code = dp.ts_code AND mf.trade_date = dp.trade_date
WHERE mf.trade_date = ? AND s.industry IS NOT NULL
GROUP BY s.industry HAVING cnt >= 5 ORDER BY net_yi DESC LIMIT 10
""", (d,))
print("[4] 板块符号法净流入 Top10（前端显示口径）:")
for name, cnt, ny in c.fetchall():
    short = name.split(" | ")[-1] if " | " in name else name
    print(f"    {short}: stocks={cnt}, net={ny:.2f}亿")

# 5) 涨停题材 hit_count Top5（hot_money 的 streak 公式输入）
c.execute("""
SELECT reason, COUNT(*) FROM limit_list_stocks
WHERE trade_date = (SELECT MAX(trade_date) FROM limit_list_stocks) AND reason IS NOT NULL
GROUP BY reason ORDER BY 2 DESC LIMIT 5
""")
print("[5] 涨停题材 hit_count Top5:", c.fetchall())

conn.close()
