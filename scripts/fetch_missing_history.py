# -*- coding: utf-8 -*-
"""
fetch_missing_history.py —— 自动查找并补齐 20251231 到 20260519 期间的缺失日线和基础指标数据
"""

import os
import sys
import json
import time
import sqlite3
import pandas as pd
import tushare as ts

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "db", "stock_data.db")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

class RateLimiter:
    def __init__(self, qps=6):
        self.interval = 1.0 / qps
        self.last_call = time.time()

    def wait(self):
        now = time.time()
        elapsed = now - self.last_call
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_call = time.time()

limiter = RateLimiter(qps=6.5)

def load_tushare_token():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"❌ 未找到配置文件: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    token = config.get("api", {}).get("tushare_token", "")
    if not token:
        raise ValueError("❌ config.json 中未找到 api.tushare_token")
    return token

def main():
    print("=" * 60)
    print("🚀 启动历史缺失数据补齐任务 (Tushare)")
    print("=" * 60)

    # 1. 初始化 Tushare
    try:
        token = load_tushare_token()
        ts.set_token(token)
        pro = ts.pro_api()
    except Exception as e:
        print(f"❌ 载入 Tushare Token 失败: {e}")
        return

    # 2. 连接数据库
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()

    # 3. 自动识别在 20251115 到 20260519 期间记录数不足 4000 的交易日
    query_dates = """
        SELECT cal_date FROM trade_cal
        WHERE is_open = 1 AND cal_date BETWEEN '20251115' AND '20260519'
        AND cal_date NOT IN (
            SELECT trade_date FROM daily_prices GROUP BY trade_date HAVING COUNT(*) >= 4000
        )
        ORDER BY cal_date;
    """
    cursor.execute(query_dates)
    missing_dates = [row[0] for row in cursor.fetchall()]

    print(f"ℹ️ 检测到 {len(missing_dates)} 个交易日数据不全或缺失。")
    if not missing_dates:
        print("✅ 没有需要补齐的交易日数据。")
        conn.close()
        return

    # 4. 开始分步拉取与写入
    for idx, d in enumerate(missing_dates):
        print(f"\n[{idx+1}/{len(missing_dates)}] 正在补齐交易日: {d}")
        
        # 4.1 拉取 daily_prices 和 adj_factor 并进行合并
        df_daily = None
        df_adj = None
        
        # 拉取日线价格
        for retry in range(5):
            try:
                limiter.wait()
                df_daily = pro.daily(trade_date=d)
                break
            except Exception as e:
                print(f"   ⚠️ daily 拉取失败重试 {retry+1}/5: {e}")
                time.sleep(2 ** retry)
                
        # 拉取复权因子
        for retry in range(5):
            try:
                limiter.wait()
                df_adj = pro.adj_factor(trade_date=d)
                break
            except Exception as e:
                print(f"   ⚠️ adj_factor 拉取失败重试 {retry+1}/5: {e}")
                time.sleep(2 ** retry)

        # 拉取 daily_basic
        df_basic = None
        for retry in range(5):
            try:
                limiter.wait()
                df_basic = pro.daily_basic(trade_date=d)
                break
            except Exception as e:
                print(f"   ⚠️ daily_basic 拉取失败重试 {retry+1}/5: {e}")
                time.sleep(2 ** retry)

        if df_daily is None or df_daily.empty or df_basic is None or df_basic.empty:
            print(f"   ❌ 交易日 {d} 数据拉取失败，跳过此日期。")
            continue

        # 合并 daily_prices 和 adj_factor
        if df_adj is not None and not df_adj.empty:
            df_daily_merged = pd.merge(df_daily, df_adj[["ts_code", "adj_factor"]], on="ts_code", how="left")
        else:
            df_daily_merged = df_daily.copy()
            df_daily_merged["adj_factor"] = None

        # 写入数据库
        try:
            # 清理该日期可能存在的旧记录以保证幂等
            cursor.execute("DELETE FROM daily_prices WHERE trade_date = ?", (d,))
            cursor.execute("DELETE FROM daily_basic WHERE trade_date = ?", (d,))
            
            # 写入
            df_daily_merged.to_sql("daily_prices", conn, if_exists="append", index=False)
            
            # 过滤 daily_basic 列
            cols_basic = ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_share", "float_share", "free_share", "total_mv", "circ_mv"]
            df_basic_clean = df_basic[[c for c in cols_basic if c in df_basic.columns]]
            df_basic_clean.to_sql("daily_basic", conn, if_exists="append", index=False)
            
            conn.commit()
            print(f"   ✅ 写入 daily_prices ({len(df_daily_merged)}行) & daily_basic ({len(df_basic_clean)}行) 成功")
        except Exception as e:
            conn.rollback()
            print(f"   ❌ 写入数据库失败: {e}")

    # 5. 执行全局 adj_factor 安全修复
    print("\n" + "=" * 60)
    print("🛠️ 正在执行全局 adj_factor 安全修复...")
    try:
        # 使用 stk_factor 修复 daily_prices 中任何由于 incremental 拉取导致的 NULL adj_factor
        cursor.execute("""
            UPDATE daily_prices
            SET adj_factor = (
                SELECT adj_factor FROM stk_factor 
                WHERE stk_factor.ts_code = daily_prices.ts_code 
                  AND stk_factor.trade_date = daily_prices.trade_date
            )
            WHERE adj_factor IS NULL;
        """)
        conn.commit()
        print(f"✅ 全局 adj_factor 修复完成，受影响行数: {cursor.rowcount}")
    except Exception as e:
        conn.rollback()
        print(f"❌ 运行全局 adj_factor 修复失败: {e}")

    conn.close()
    print("=" * 60)
    print("🎉 历史数据补齐及清洗任务全部完成！")

if __name__ == "__main__":
    main()
