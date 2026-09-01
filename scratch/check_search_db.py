# -*- coding: utf-8 -*-
"""验证 search_stock 的 SQL 与 stock_list 表结构"""
import sqlite3
import sys

DB_PATH = "/Users/lyu/Documents/my_Stock/db/stock_data.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 1. 表结构
cur.execute("PRAGMA table_info(stock_list)")
cols = [r[1] for r in cur.fetchall()]
print("stock_list 列:", cols)

# 2. 行数
cur.execute("SELECT COUNT(*) FROM stock_list")
print("总行数:", cur.fetchone()[0])

# 3. LIKE 查询测试
cur.execute("SELECT ts_code, name FROM stock_list WHERE ts_code LIKE '%300159%' LIMIT 5")
print("LIKE 300159:", cur.fetchall())

# 4. 模拟完整 search_stock 查询（含拼音列）
try:
    cur.execute("""
        SELECT ts_code, name, industry, market, list_date,
               pinyin_full, pinyin_simp
        FROM stock_list
        WHERE ts_code LIKE ?
           OR name LIKE ?
           OR pinyin_full LIKE ?
           OR pinyin_simp LIKE ?
        LIMIT 15
    """, ("%300159%", "%300159%", "%300159%", "%300159%"))
    rows = cur.fetchall()
    print("完整查询结果数:", len(rows))
    for r in rows[:3]:
        print("  ", r[:2])
except Exception as e:
    print("完整查询报错:", e)

conn.close()
