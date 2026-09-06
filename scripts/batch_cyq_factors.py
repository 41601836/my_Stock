# -*- coding: utf-8 -*-
"""
batch_cyq_factors.py — 批量计算 CYQ 筹码因子并写入 factor_values

性能优化版：使用 sliding_window_view + 3D 向量化，~0.1s/股
5500 只股票 ≈ 10 分钟（原版 >15 分钟未完成）
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import numpy as np
import pandas as pd
from src.cyq_model import CYQModel

DB = "db/stock_data.db"

def main():
    t0 = time.time()
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA cache_size = -200000")  # 200MB cache

    # 1. 获取所有股票代码
    print("1. 获取股票列表...")
    codes = pd.read_sql("SELECT DISTINCT ts_code FROM daily_prices ORDER BY ts_code", conn)["ts_code"].tolist()
    print(f"   {len(codes)} 只股票")

    # 2. 检查 factor_values 表是否有 CYQ 列
    cols = [c[1] for c in conn.execute("PRAGMA table_info(factor_values)").fetchall()]
    cyq_cols = [c for c in cols if c.startswith("cyq_")]
    print(f"   factor_values CYQ 列: {cyq_cols}")

    if not cyq_cols:
        print("   添加 CYQ 列...")
        for col in ["cyq_profit_ratio_60d", "cyq_upper_pressure_60d",
                     "cyq_chip_concentration_60d", "cyq_avg_cost_dev_60d"]:
            conn.execute(f"ALTER TABLE factor_values ADD COLUMN {col} REAL")
        conn.commit()
        print("   列已添加")

    # 3. 批量计算
    print("2. 批量计算 CYQ 因子...")
    model = CYQModel(window=60, n_bins=30)
    batch_size = 200
    total_rows = 0
    failed = 0

    # 创建临时表用于批量 JOIN 更新
    conn.execute("""
        CREATE TEMP TABLE IF NOT EXISTS tmp_cyq_update (
            stock_code TEXT,
            trade_date TEXT,
            cyq_profit REAL,
            cyq_pressure REAL,
            cyq_concentration REAL,
            cyq_avg_cost_dev REAL
        )
    """)
    conn.commit()

    for batch_start in range(0, len(codes), batch_size):
        batch_end = min(batch_start + batch_size, len(codes))
        batch_codes = codes[batch_start:batch_end]
        elapsed = time.time() - t0
        pct = batch_end / len(codes) * 100
        print(f"   [{batch_end}/{len(codes)}] {pct:.0f}% ({elapsed:.0f}s) rows={total_rows}")

        # 加载这批股票的日线数据
        placeholders = ",".join(["?"] * len(batch_codes))
        df = pd.read_sql(f"""
            SELECT d.ts_code, d.trade_date, d.high, d.low, d.close, d.vol, d.amount,
                   b.turnover_rate
            FROM daily_prices d
            JOIN daily_basic b ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.ts_code IN ({placeholders})
            ORDER BY d.ts_code, d.trade_date
        """, conn, params=batch_codes)

        if df.empty:
            failed += len(batch_codes)
            continue

        # 逐股票计算
        rows = []
        for code, group in df.groupby("ts_code", sort=False):
            group = group.sort_values("trade_date")
            try:
                res = model.compute_rolling(group)
                dev = (group["close"].values - res["cyq_avg_cost"].values) / res["cyq_avg_cost"].values

                for i in range(len(group)):
                    pr = res.iloc[i]["cyq_profit_ratio"]
                    if np.isnan(pr):
                        continue
                    rows.append((
                        code, group.iloc[i]["trade_date"],
                        float(pr), float(res.iloc[i]["cyq_upper_pressure"]),
                        float(res.iloc[i]["cyq_chip_concentration"]),
                        float(dev[i]) if not np.isnan(dev[i]) else None
                    ))
            except Exception:
                failed += 1
                continue

        # 写入临时表，再 JOIN 更新（比逐行 UPDATE 快 100x）
        if rows:
            conn.execute("DELETE FROM tmp_cyq_update")
            conn.executemany(
                "INSERT INTO tmp_cyq_update VALUES (?, ?, ?, ?, ?, ?)",
                rows
            )
            conn.execute("""
                UPDATE factor_values
                SET cyq_profit_ratio_60d = t.cyq_profit,
                    cyq_upper_pressure_60d = t.cyq_pressure,
                    cyq_chip_concentration_60d = t.cyq_concentration,
                    cyq_avg_cost_dev_60d = t.cyq_avg_cost_dev
                FROM tmp_cyq_update t
                WHERE factor_values.stock_code = t.stock_code
                  AND factor_values.trade_date = t.trade_date
            """)
            conn.commit()
            total_rows += len(rows)

    conn.close()
    elapsed = time.time() - t0
    print(f"\n✅ 完成! 耗时 {elapsed:.0f}s, 更新 {total_rows} 行, 失败 {failed} 股")

    # 验证
    conn2 = sqlite3.connect(DB)
    r = conn2.execute("SELECT COUNT(*) FROM factor_values WHERE cyq_chip_concentration_60d IS NOT NULL").fetchone()
    print(f"   factor_values.cyq_chip_concentration_60d 非空: {r[0]}")

    sample = conn2.execute("""
        SELECT trade_date, stock_code, cyq_profit_ratio_60d, cyq_chip_concentration_60d, cyq_upper_pressure_60d
        FROM factor_values
        WHERE cyq_chip_concentration_60d IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT 5
    """).fetchall()
    print("   样本:")
    for s in sample:
        print(f"     {s[0]} {s[1]} profit={s[2]:.4f} conc={s[3]:.4f} pressure={s[4]:.4f}")
    conn2.close()

if __name__ == "__main__":
    main()
