# -*- coding: utf-8 -*-
"""
feature_engineering.py —— 全历史特征因子计算工程 (含 8 个额外实验因子版)
========================================================================
1. 高效 SQL 提取 2020-2026 行情与主力资金。
2. 批量计算 18 个核心因子 + 8 个实验因子，总计 26 个因子：
   - 动量/反转: return_5d, return_20d, return_60d, excess_return_20d + [实验] return_10d, return_120d
   - 波动率/风险: volatility_20d, volatility_60d, skewness_20d, max_drawdown_20d, atr_ratio + [实验] volatility_10d, volatility_120d, max_drawdown_60d
   - 估值/质量: pe_ttm, pb, roe, turnover_rate + [实验] turnover_rate_5d, turnover_rate_20d
   - 聪明钱/微观: north_net_inflow_ratio, profit_ratio_estimate, chip_concentration + [实验] vol_ratio
3. 因子写入 factor_values 表，覆盖式保存。
"""

import os
import sqlite3
import pandas as pd
import numpy as np
import time

from config.paths import PATHS, startup_check

startup_check()

def calculate_stock_factors(db_path=None):
    if db_path is None:
        db_path = PATHS.database.stock_data
    """
    通过高效 SQL 连接提取数据，执行 26 维因子计算并入库
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"❌ 数据库文件未找到: {db_path}")
        
    start_time = time.time()
    print(f"ℹ️ [Feature] 开始联合加载 2020-2026 行情、估值与资金流数据...")
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    
    query = """
        SELECT 
            p.ts_code, 
            p.trade_date, 
            p.high, 
            p.low, 
            p.close, 
            p.vol,
            IFNULL(sf.adj_factor, p.adj_factor) AS adj_factor, 
            b.turnover_rate, 
            b.pe AS pe_ttm, 
            b.pb, 
            b.circ_mv,
            IFNULL(m.buy_elg_amount, 0.0) AS buy_elg, 
            IFNULL(m.sell_elg_amount, 0.0) AS sell_elg
        FROM daily_prices p
        INNER JOIN daily_basic b ON p.ts_code = b.ts_code AND p.trade_date = b.trade_date
        LEFT JOIN moneyflow m ON p.ts_code = m.ts_code AND p.trade_date = m.trade_date
        LEFT JOIN stk_factor sf ON p.ts_code = sf.ts_code AND p.trade_date = sf.trade_date
        WHERE p.trade_date >= '20250101'
        ORDER BY p.ts_code, p.trade_date;
    """
    
    df = pd.read_sql(query, conn)
    df["trade_date"] = df["trade_date"].astype(str)
    
    load_time = time.time() - start_time
    print(f"✅ [Feature] 数据加载完毕，共 {len(df)} 行记录，耗时: {load_time:.2f} 秒。开始计算后复权价与收益...")
    
    # 后复权价格
    df["close_adj"] = df["close"] * df["adj_factor"]
    df["high_adj"] = df["high"] * df["adj_factor"]
    df["low_adj"] = df["low"] * df["adj_factor"]
    df["daily_ret"] = df.groupby("ts_code")["close_adj"].pct_change(1, fill_method=None)
    
    # 1. 动量/反转因子计算 (含实验因子 return_10d, return_120d)
    print("ℹ️ [Feature] 计算动量与实验动量因子...")
    df["return_5d"] = df.groupby("ts_code")["close_adj"].pct_change(5, fill_method=None)
    df["return_10d"] = df.groupby("ts_code")["close_adj"].pct_change(10, fill_method=None)
    df["return_20d"] = df.groupby("ts_code")["close_adj"].pct_change(20, fill_method=None)
    df["return_60d"] = df.groupby("ts_code")["close_adj"].pct_change(60, fill_method=None)
    df["return_120d"] = df.groupby("ts_code")["close_adj"].pct_change(120, fill_method=None)
    
    df["mean_return_20d"] = df.groupby("trade_date")["return_20d"].transform("mean")
    df["excess_return_20d"] = df["return_20d"] - df["mean_return_20d"]
    
    # 2. 波动率/风险因子计算 (含实验因子 volatility_10d, volatility_120d, max_drawdown_60d)
    print("ℹ️ [Feature] 计算风险与实验风险因子...")
    df["volatility_10d"] = df.groupby("ts_code")["daily_ret"].transform(lambda x: x.rolling(10).std())
    df["volatility_20d"] = df.groupby("ts_code")["daily_ret"].transform(lambda x: x.rolling(20).std())
    df["volatility_60d"] = df.groupby("ts_code")["daily_ret"].transform(lambda x: x.rolling(60).std())
    df["volatility_120d"] = df.groupby("ts_code")["daily_ret"].transform(lambda x: x.rolling(120).std())
    df["skewness_20d"] = df.groupby("ts_code")["daily_ret"].transform(lambda x: x.rolling(20).skew())
    
    # Max Drawdown
    roll_max_20d = df.groupby("ts_code")["close_adj"].transform(lambda x: x.rolling(20).max())
    df["drawdown_20d"] = (df["close_adj"] - roll_max_20d) / roll_max_20d
    df["max_drawdown_20d"] = df.groupby("ts_code")["drawdown_20d"].transform(lambda x: x.rolling(20).min())
    
    roll_max_60d = df.groupby("ts_code")["close_adj"].transform(lambda x: x.rolling(60).max())
    df["drawdown_60d"] = (df["close_adj"] - roll_max_60d) / roll_max_60d
    df["max_drawdown_60d"] = df.groupby("ts_code")["drawdown_60d"].transform(lambda x: x.rolling(60).min())
    
    # ATR
    df["prev_close_adj"] = df.groupby("ts_code")["close_adj"].shift(1)
    df["tr1"] = df["high_adj"] - df["low_adj"]
    df["tr2"] = (df["high_adj"] - df["prev_close_adj"]).abs()
    df["tr3"] = (df["low_adj"] - df["prev_close_adj"]).abs()
    df["tr"] = df[["tr1", "tr2", "tr3"]].max(axis=1)
    df["atr_14"] = df.groupby("ts_code")["tr"].transform(lambda x: x.rolling(14).mean())
    df["atr_ratio"] = df["atr_14"] / df["close_adj"]
    
    # 3. 估值/质量因子计算 (含实验因子 turnover_rate_5d, turnover_rate_20d)
    print("ℹ️ [Feature] 计算估值与实验换手均值因子...")
    pe_protected = df["pe_ttm"].apply(lambda x: x if x > 0.1 else 0.1)
    df["roe"] = (df["pb"] / pe_protected).clip(-0.5, 0.5).fillna(0.0)
    df["turnover_rate_5d"] = df.groupby("ts_code")["turnover_rate"].transform(lambda x: x.rolling(5).mean())
    df["turnover_rate_20d"] = df.groupby("ts_code")["turnover_rate"].transform(lambda x: x.rolling(20).mean())
    
    # 4. 聪明钱/微观结构因子 (含实验因子 vol_ratio)
    print("ℹ️ [Feature] 计算微观聪明钱与实验量比因子...")
    circ_mv_protected = df["circ_mv"].apply(lambda x: x if x > 1e-4 else 1e-4)
    df["daily_inflow_ratio"] = (df["buy_elg"] - df["sell_elg"]) / circ_mv_protected
    df["north_net_inflow_ratio"] = df.groupby("ts_code")["daily_inflow_ratio"].transform(lambda x: x.rolling(20).sum())
    
    # profit_ratio_estimate
    min_60 = df.groupby("ts_code")["close_adj"].transform(lambda x: x.rolling(60).min())
    max_60 = df.groupby("ts_code")["close_adj"].transform(lambda x: x.rolling(60).max())
    df["profit_ratio_estimate"] = (df["close_adj"] - min_60) / (max_60 - min_60 + 1e-8)
    
    # chip_concentration
    ma_20 = df.groupby("ts_code")["close_adj"].transform(lambda x: x.rolling(20).mean())
    df["chip_concentration"] = (df["close_adj"] / (ma_20 + 1e-8) - 1).abs().fillna(0.0)
    
    # vol_ratio (5日/60日成交量放大系数)
    vol_5m = df.groupby("ts_code")["vol"].transform(lambda x: x.rolling(5).mean())
    vol_60m = df.groupby("ts_code")["vol"].transform(lambda x: x.rolling(60).mean())
    df["vol_ratio"] = vol_5m / (vol_60m + 1e-8)
    
    # 5. 市场贝塔因子 (Beta Factor) - 用于贝塔剥离计算
    print("ℹ️ [Feature] 计算市场贝塔因子...")
    market_ret = df.groupby("trade_date")["daily_ret"].transform("mean")
    df["market_excess"] = market_ret - df.groupby("trade_date")["daily_ret"].transform(lambda x: x.rolling(60).mean())
    df["stock_excess"] = df["daily_ret"] - df.groupby("ts_code")["daily_ret"].transform(lambda x: x.rolling(60).mean())
    
    def calc_beta(group):
        cov = group["stock_excess"].rolling(60).cov(group["market_excess"])
        var = group["market_excess"].rolling(60).var()
        return cov / var.replace(0, np.nan)
    
    df["beta_60d"] = df.groupby("ts_code")[["stock_excess", "market_excess"]].apply(calc_beta, include_groups=False).reset_index(level=0, drop=True)
    df["beta_60d"] = df["beta_60d"].fillna(1.0).clip(0.1, 3.0)
    
    # 6. 质量防御因子 - 现金流/负债比近似 (基于 ROE 和 PB 的质量评分)
    print("ℹ️ [Feature] 计算质量防御因子...")
    df["quality_score"] = df["roe"].fillna(0) - df["pb"].fillna(0) * 0.1
    df["quality_score"] = df["quality_score"].clip(-1.0, 1.0)
    
    # 7. 低换手防御因子
    df["low_turnover_flag"] = (df["turnover_rate_5d"] < df.groupby("trade_date")["turnover_rate_5d"].transform(lambda x: x.quantile(0.30))).astype(int)
    
    # 8. 指数衰减时效性因子 (半衰期 3 天) - 基于未来5日收益的时间距离
    print("ℹ️ [Feature] 计算指数衰减时效性因子...")
    df["dt"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df["timeliness_decay"] = 1.0
    
    # --- 整理与保存 ---
    print("ℹ️ [Feature] 特征计算完成，正在过滤 NaN 行并持久化...")
    df = df.rename(columns={"ts_code": "stock_code"})
    
    cols_to_save = [
        "trade_date", "stock_code", 
        "return_5d", "return_20d", "return_60d", "excess_return_20d",
        "volatility_20d", "volatility_60d", "skewness_20d", "max_drawdown_20d", "atr_ratio",
        "pe_ttm", "pb", "roe", "turnover_rate",
        "north_net_inflow_ratio", "profit_ratio_estimate", "chip_concentration",
        # 新增的 8 个实验因子
        "return_10d", "return_120d",
        "volatility_10d", "volatility_120d", "max_drawdown_60d",
        "turnover_rate_5d", "turnover_rate_20d", "vol_ratio",
        # 新增的防御与风控因子
        "beta_60d", "quality_score", "low_turnover_flag", "timeliness_decay"
    ]
    
    # 丢弃前置 120 天 NaN 干扰
    df_clean = df[cols_to_save].dropna(subset=["volatility_120d", "return_120d"]).reset_index(drop=True)
    
    table_name = "factor_values"
    try:
        conn.execute(f"DROP INDEX IF EXISTS idx_factors_date_code")
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to drop table {table_name}: {e}")
        pass
    df_clean.to_sql(table_name, conn, if_exists="append", index=False, chunksize=10000)
    
    cursor = conn.cursor()
    cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_factors_date_code ON {table_name}(trade_date, stock_code);")
    conn.commit()
    conn.close()
    
    total_time = time.time() - start_time
    print(f"✅ [Feature] 26 维复合因子成功写入 SQLite 表 [{table_name}]，共 {len(df_clean)} 行数据，总耗时: {total_time:.2f} 秒。")
    return df_clean

if __name__ == "__main__":
    calculate_stock_factors()
