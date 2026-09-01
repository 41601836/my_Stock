# -*- coding: utf-8 -*-
"""stock_list 表补 pinyin_full/pinyin_simp 列并全量生成拼音数据"""
import re
import sqlite3
from pypinyin import lazy_pinyin

DB_PATH = "/Users/lyu/Documents/my_Stock/db/stock_data.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 1. 补列（若不存在）
cur.execute("PRAGMA table_info(stock_list)")
cols = [r[1] for r in cur.fetchall()]
if "pinyin_full" not in cols:
    cur.execute("ALTER TABLE stock_list ADD COLUMN pinyin_full TEXT")
if "pinyin_simp" not in cols:
    cur.execute("ALTER TABLE stock_list ADD COLUMN pinyin_simp TEXT")

# 2. 读取全部股票
cur.execute("SELECT ts_code, name FROM stock_list")
rows = cur.fetchall()
print(f"待处理: {len(rows)} 只")

# 3. 生成拼音
han_re = re.compile(r"[\u4e00-\u9fff]+")
alnum_re = re.compile(r"[A-Za-z0-9]+")

updates = []
skipped = 0
for ts_code, name in rows:
    if not name:
        skipped += 1
        continue
    hans = "".join(han_re.findall(name))      # 汉字部分（自动去掉 *ST/ST/退 等标记）
    latins = "".join(alnum_re.findall(name))  # 原有字母/数字（如 TCL、C 前缀、GQY）
    if not hans and not latins:
        skipped += 1
        continue
    try:
        if hans:
            pys = lazy_pinyin(hans)                       # 全拼音节列表（处理常用多音字）
            full = latins.lower() + "".join(pys)
            simp = latins.lower() + "".join(p[0] for p in pys)
        else:
            full = simp = latins.lower()
    except Exception:
        skipped += 1
        continue
    updates.append((full, simp, ts_code))

# 4. 一次性写回
cur.executemany("UPDATE stock_list SET pinyin_full=?, pinyin_simp=? WHERE ts_code=?", updates)
conn.commit()

# 5. 抽样验证
print(f"写入: {len(updates)} 条, 跳过: {skipped}")
for kw in ["600519.SH", "300159.SZ", "688111.SH", "000651.SZ", "002415.SZ", "300059.SZ"]:
    cur.execute("SELECT ts_code, name, pinyin_full, pinyin_simp FROM stock_list WHERE ts_code=?", (kw,))
    r = cur.fetchone()
    if r:
        print(f"  {r[0]} {r[1]}: full={r[2]} simp={r[3]}")
conn.close()
