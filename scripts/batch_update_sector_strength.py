# -*- coding: utf-8 -*-
"""
batch_update_sector_strength.py — 批量计算板块强度因子并写入 factor_values

数据源：
  - stock_list 表: ts_code → industry 映射
  - daily_prices 表: 全市场日线 (ts_code, trade_date, close, pct_chg, amount)

逻辑：
  每个交易日按行业分组，计算板块收益中位数 + 板块宽度 + 成交额排名，
  合成板块强度并映射回个股，写入 factor_values.sector_strength
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import numpy as np
import pandas as pd
from src.sector_factor import SectorFactor

DB = "db/stock_data.db"

def main():
    t0 = time.time()
    conn = sqlite3.connect(DB)

    # 1. 加载股票行业分类
    print("1. 加载 stock_list 行业分类...")
    stock_info = pd.read_sql("SELECT ts_code, industry FROM stock_list", conn)
    stock_info = stock_info.dropna(subset=["industry"])
    stock_info = stock_info[stock_info["industry"] != ""].copy()
    print(f"   {len(stock_info)} 只有行业分类")

    # 2. 加载最近 2 年的日线数据
    print("2. 加载 daily_prices...")
    df = pd.read_sql("""
        SELECT ts_code, trade_date, close, pct_chg, amount
        FROM daily_prices
        WHERE trade_date >= '20240901'
        ORDER BY trade_date
    """, conn)
    print(f"   {len(df)} 行, {df['trade_date'].nunique()} 个交易日")

    # 3. 按交易日计算板块强度
    print("3. 计算板块强度...")
    sf = SectorFactor()
    results = []

    dates = sorted(df["trade_date"].unique())
    n_dates = len(dates)
    for i, dt in enumerate(dates):
        if (i + 1) % 50 == 0:
            print(f"   进度: {i+1}/{n_dates} ({(i+1)/n_dates*100:.0f}%)")

        day_df = df[df["trade_date"] == dt]
        if len(day_df) < 100:
            continue

        strength = sf.compute_sector_strength(day_df, stock_info)
        if len(strength) > 0:
            tmp = strength.reset_index()
            tmp.columns = ["ts_code", "sector_strength"]
            tmp["trade_date"] = dt
            results.append(tmp)

    print(f"   合并结果...")
    all_data = pd.concat(results, ignore_index=True)
    all_data = all_data.replace([np.inf, -np.inf], np.nan)
    all_data = all_data.dropna(subset=["sector_strength"])
    print(f"   {len(all_data)} 行板块强度数据")

    # 4. 批量更新 factor_values
    print("4. 写入 factor_values.sector_strength...")
    rows = [(r["sector_strength"], r["ts_code"], r["trade_date"]) for _, r in all_data.iterrows()]
    conn.executemany(
        "UPDATE factor_values SET sector_strength = ? WHERE stock_code = ? AND trade_date = ?",
        rows
    )
    conn.commit()
    conn.close()

    elapsed = time.time() - t0
    updated = len(rows)
    print(f"\n✅ 完成! 耗时 {elapsed:.1f}s, 更新 {updated} 行")

    # 验证
    conn2 = sqlite3.connect(DB)
    r = conn2.execute("SELECT COUNT(*) FROM factor_values WHERE sector_strength IS NOT NULL").fetchone()
    print(f"   factor_values.sector_strength 非空行数: {r[0]}")
    # 样本
    sample = conn2.execute("""
        SELECT trade_date, stock_code, sector_strength
        FROM factor_values
        WHERE sector_strength IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT 5
    """).fetchall()
    print("   样本:")
    for s in sample:
        print(f"     {s[0]} {s[1]} = {s[2]:.4f}")
    conn2.close()

if __name__ == "__main__":
    main()
