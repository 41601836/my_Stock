# -*- coding: utf-8 -*-
"""
batch_update_fast_factors.py — 批量计算快因子并写入 factor_values 表
跳过 CYQ（太慢），只跑 overnight/intraday + Amihud + GK/Parkinson + turnover/volume 高阶
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import numpy as np
import pandas as pd
from src.feature_engineering import (
    calc_overnight_intraday_factors,
    calc_liquidity_higher_order_factors,
    calc_gk_volatility,
)

DB = "db/stock_data.db"

def main():
    t0 = time.time()
    conn = sqlite3.connect(DB)

    # 1. 加载最近 2 年的日线数据
    print("1. 加载日线数据...")
    df = pd.read_sql("""
        SELECT ts_code, trade_date, open, high, low, close, vol, amount
        FROM daily_prices
        WHERE trade_date >= '20240901'
        ORDER BY ts_code, trade_date
    """, conn)
    print(f"   {len(df)} 行, {df['ts_code'].nunique()} 只股票")

    # 2. 加载 turnover_rate 从 factor_values
    print("2. 加载 turnover_rate...")
    fv = pd.read_sql("""
        SELECT stock_code, trade_date, turnover_rate
        FROM factor_values
        WHERE trade_date >= '20240901'
    """, conn)
    fv = fv.rename(columns={"stock_code": "ts_code"})
    df = df.merge(fv, on=["ts_code", "trade_date"], how="left")
    df["turnover_rate"] = df["turnover_rate"].fillna(0)

    # 3. 按股票分组计算因子
    print("3. 计算快因子...")
    results = []
    stocks = df["ts_code"].unique()
    n = len(stocks)
    for i, code in enumerate(stocks):
        if (i + 1) % 500 == 0:
            print(f"   进度: {i+1}/{n} ({(i+1)/n*100:.0f}%)")
        sub = df[df["ts_code"] == code].sort_values("trade_date").copy()
        if len(sub) < 25:
            continue

        # 隔夜/日内
        r1 = calc_overnight_intraday_factors(sub)
        # Amihud + 成交额高阶
        r2 = calc_liquidity_higher_order_factors(sub)
        # GK/Parkinson
        r3 = calc_gk_volatility(sub)

        out = pd.concat([r1, r2, r3], axis=1)
        out["ts_code"] = code
        out["trade_date"] = sub["trade_date"].values
        results.append(out.reset_index(drop=True))

    print(f"   合并结果...")
    all_factors = pd.concat(results, ignore_index=True)
    print(f"   {len(all_factors)} 行因子值")

    # 4. 写入 factor_values 表
    print("4. 写入 factor_values 表...")
    factor_cols = [
        "overnight_return_5d", "intraday_return_5d", "overnight_intraday_gap_5d",
        "amihud_illiq_20d", "turnover_volatility_20d", "volume_skewness_20d",
        "amount_volatility_20d", "gk_volatility_20d", "parkinson_volatility_20d",
    ]

    # 用 executemany 批量 UPDATE
    all_factors = all_factors.replace([np.inf, -np.inf], np.nan)
    rows = []
    for _, r in all_factors.iterrows():
        vals = [r[c] if pd.notna(r[c]) else None for c in factor_cols]
        vals.extend([r["ts_code"], r["trade_date"]])
        rows.append(vals)

    set_clause = ", ".join([f"{c} = ?" for c in factor_cols])
    sql = f"UPDATE factor_values SET {set_clause} WHERE stock_code = ? AND trade_date = ?"

    print(f"   批量 UPDATE {len(rows)} 行...")
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()

    elapsed = time.time() - t0
    print(f"\n✅ 完成! 耗时 {elapsed:.1f}s")
    print(f"   更新 {len(rows)} 行 × {len(factor_cols)} 列")

if __name__ == "__main__":
    main()
