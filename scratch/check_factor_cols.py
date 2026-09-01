# -*- coding: utf-8 -*-
"""检查 factor_values 列名 + pkl 权重键 + agent/strategies 目录"""
import sqlite3
import pickle
import os

DB_PATH = "/Users/lyu/Documents/my_Stock/db/stock_data.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("PRAGMA table_info(factor_values)")
cols = [r[1] for r in cur.fetchall()]
print("factor_values 列:", cols)
conn.close()

def load(p):
    if os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    return None

for name, p in [("WEIGHTS", "/Users/lyu/Documents/my_Stock/models/factor_weights.pkl"),
                ("BULL", "/Users/lyu/Documents/my_Stock/models/bull_factor_weights.pkl")]:
    d = load(p)
    print(f"{name} {os.path.basename(p)}:", d)

sdir = "/Users/lyu/Documents/my_Stock/agent/strategies"
if os.path.isdir(sdir):
    print("strategies 目录:", os.listdir(sdir))
    for f in os.listdir(sdir):
        if f.endswith(".yaml"):
            fp = os.path.join(sdir, f)
            with open(fp, encoding="utf-8") as fh:
                content = fh.read()
            print(f"--- {f} 前 30 行 ---")
            print("\n".join(content.splitlines()[:30]))
