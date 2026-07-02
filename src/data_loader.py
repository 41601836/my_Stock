# -*- coding: utf-8 -*-
"""
data_loader.py —— 数据加载与处理模块 (修正版)
========================================
1. 从中性化因子 CSV 自动导入因子 IC 数据至 sqlite 数据库。
2. 从数据库中加载中性化因子 IC 时间序列数据。
3. 从 stock_data.db 加载并计算生成全市场等权指数，同时获取每日上涨家数占比。
"""

import os
import sqlite3
import yaml
import pandas as pd
import numpy as np

def load_config(config_path="config/market_regime.yaml"):
    """
    加载配置文件
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"⚠️ [Loader] 未找到配置文件: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config

def init_factor_db(db_path, csv_source):
    """
    初始化因子数据库，如果 factor_ic_neutral 表不存在，则从 CSV 导入。
    """
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='factor_ic_neutral';")
    table_exists = cursor.fetchone()
    
    if not table_exists:
        print(f"ℹ️ [Loader] 数据库 {db_path} 中未检测到 factor_ic_neutral 表，开始导入...")
        if not os.path.exists(csv_source):
            conn.close()
            raise FileNotFoundError(f"❌ [Loader] 未找到因子数据源 CSV 文件: {csv_source}")
        
        # 读取 CSV 并导入
        df = pd.read_csv(csv_source)
        df["trade_date"] = df["trade_date"].astype(str)
        df.to_sql("factor_ic_neutral", conn, if_exists="replace", index=False)
        print(f"✅ [Loader] 成功导入因子 IC 数据，条数: {len(df)}")
    else:
        cursor.execute("SELECT COUNT(*) FROM factor_ic_neutral;")
        count = cursor.fetchone()[0]
        print(f"ℹ️ [Loader] 因子 IC 数据已存在，包含记录 {count} 条。")
        
    conn.close()

def load_neutral_factors(db_path):
    """
    从 sqlite 中加载中性化因子数据
    """
    conn = sqlite3.connect(db_path)
    query = "SELECT * FROM factor_ic_neutral ORDER BY trade_date"
    df = pd.read_sql(query, conn)
    conn.close()
    df["trade_date"] = df["trade_date"].astype(str)
    return df

def load_benchmark_data(stock_data_db_path, benchmark_code="equal_weight"):
    """
    加载全市场等权指数。
    执行高效 SQLite 聚合，计算每日的平均收益率 pct_chg 与上涨家数占比 up_ratio。
    """
    if not os.path.exists(stock_data_db_path):
        raise FileNotFoundError(f"❌ [Loader] 未找到日线数据库: {stock_data_db_path}")
        
    conn = sqlite3.connect(stock_data_db_path)
    
    print("ℹ️ [Loader] 正在计算全市场等权指数每日点数及上涨家数占比...")
    # 高效 SQL 分组聚合：计算每日收益率均值，以及 (pct_chg > 0) 的股票数量占比
    query = """
        SELECT 
            trade_date,
            AVG(pct_chg) AS avg_pct_chg,
            SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(pct_chg) AS up_ratio
        FROM daily_prices 
        WHERE pct_chg IS NOT NULL 
        GROUP BY trade_date 
        ORDER BY trade_date
    """
    
    df_eq = pd.read_sql(query, conn)
    df_eq["trade_date"] = df_eq["trade_date"].astype(str)
    
    # 累积计算等权指数收盘点数，初始设为 1000
    df_eq["pct_chg_ratio"] = df_eq["avg_pct_chg"] / 100.0
    df_eq["close"] = 1000.0 * (1.0 + df_eq["pct_chg_ratio"]).cumprod()
    
    # 丰富 OHLC 结构，令其等于收盘价，以便走势图计算
    df_eq["open"] = df_eq["close"]
    df_eq["high"] = df_eq["close"]
    df_eq["low"] = df_eq["close"]
    
    # 重命名列以符合标准基准命名
    df_eq = df_eq.rename(columns={"avg_pct_chg": "pct_chg"})
    
    # 整理列顺序
    df_benchmark = df_eq[["trade_date", "open", "high", "low", "close", "pct_chg", "up_ratio"]]
    print(f"✅ [Loader] 全市场等权指数生成成功，共计: {len(df_benchmark)} 个交易日")
    
    conn.close()
    return df_benchmark

if __name__ == "__main__":
    # 测试数据加载器
    config = load_config()
    db_cfg = config["database"]
    
    print("\n--- 测试因子数据库初始化 ---")
    init_factor_db(db_cfg["market_data_db"], db_cfg["factor_ic_csv_source"])
    
    print("\n--- 测试全市场等权指数及 up_ratio 加载 ---")
    df_eq = load_benchmark_data(db_cfg["stock_data_db"], "equal_weight")
    print(df_eq.head(5))
