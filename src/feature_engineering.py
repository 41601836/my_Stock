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
            -- adj_factor 三级兜底：
            -- 1) 优先 stk_factor.adj_factor（每日官方后复权因子，主数据）；
            -- 2) 回退 daily_prices.adj_factor（种子表自带，通常全 NULL，已兼容处理）；
            -- 3) 终极回退 1.0（stk_factor 某交易日漏采全市场，如 20260825 仅 10 行时，
            --    用 1.0 = 不复权，保证 close_adj 不会因单个交易日而向下污染后续 20 个交易日的
            --    rolling(20) 波动率 / 收益指标，避免 5500+ 个股全部被 dropna 误删）。
            COALESCE(sf.adj_factor, p.adj_factor, 1.0) AS adj_factor,
            IFNULL(b.turnover_rate, 0.0) AS turnover_rate,
            IFNULL(b.pe, 0.0)             AS pe_ttm,
            IFNULL(b.pb, 0.0)             AS pb,
            IFNULL(b.circ_mv, 0.0)        AS circ_mv,
            IFNULL(m.buy_elg_amount, 0.0) AS buy_elg, 
            IFNULL(m.sell_elg_amount, 0.0) AS sell_elg
        FROM daily_prices p
        INNER JOIN daily_basic b ON p.ts_code = b.ts_code AND p.trade_date = b.trade_date
        LEFT JOIN moneyflow m ON p.ts_code = m.ts_code AND p.trade_date = m.trade_date
        LEFT JOIN stk_factor sf ON p.ts_code = sf.ts_code AND p.trade_date = sf.trade_date
        WHERE p.trade_date >= '20200101'
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
    print("ℹ️ [Feature] 高效计算风险与实验风险因子...")
    gb = df.groupby("ts_code")
    
    df["volatility_10d"] = gb["daily_ret"].rolling(10).std().to_numpy()
    df["volatility_20d"] = gb["daily_ret"].rolling(20).std().to_numpy()
    df["volatility_60d"] = gb["daily_ret"].rolling(60).std().to_numpy()
    df["volatility_120d"] = gb["daily_ret"].rolling(120).std().to_numpy()
    df["skewness_20d"] = gb["daily_ret"].rolling(20).skew().to_numpy()
    
    # Max Drawdown
    roll_max_20d = gb["close_adj"].rolling(20).max().to_numpy()
    df["drawdown_20d"] = (df["close_adj"] - roll_max_20d) / roll_max_20d
    df["max_drawdown_20d"] = gb["drawdown_20d"].rolling(20).min().to_numpy()
    
    roll_max_60d = gb["close_adj"].rolling(60).max().to_numpy()
    df["drawdown_60d"] = (df["close_adj"] - roll_max_60d) / roll_max_60d
    df["max_drawdown_60d"] = gb["drawdown_60d"].rolling(60).min().to_numpy()
    
    # ATR
    df["prev_close_adj"] = gb["close_adj"].shift(1)
    df["tr1"] = df["high_adj"] - df["low_adj"]
    df["tr2"] = (df["high_adj"] - df["prev_close_adj"]).abs()
    df["tr3"] = (df["low_adj"] - df["prev_close_adj"]).abs()
    df["tr"] = df[["tr1", "tr2", "tr3"]].max(axis=1)
    df["atr_14"] = gb["tr"].rolling(14).mean().to_numpy()
    df["atr_ratio"] = df["atr_14"] / df["close_adj"]
    
    # 3. 估值/质量因子计算 (含实验因子 turnover_rate_5d, turnover_rate_20d)
    print("ℹ️ [Feature] 计算估值与实验换手均值因子...")
    pe_protected = df["pe_ttm"].apply(lambda x: x if x > 0.1 else 0.1)
    df["roe"] = (df["pb"] / pe_protected).clip(-0.5, 0.5).fillna(0.0)
    df["turnover_rate_5d"] = gb["turnover_rate"].rolling(5).mean().to_numpy()
    df["turnover_rate_20d"] = gb["turnover_rate"].rolling(20).mean().to_numpy()
    
    # 4. 聪明钱/微观结构因子 (含实验因子 vol_ratio)
    print("ℹ️ [Feature] 计算微观聪明钱与实验量比因子...")
    circ_mv_protected = df["circ_mv"].apply(lambda x: x if x > 1e-4 else 1e-4)
    df["daily_inflow_ratio"] = (df["buy_elg"] - df["sell_elg"]) / circ_mv_protected
    df["north_net_inflow_ratio"] = gb["daily_inflow_ratio"].rolling(20).sum().to_numpy()
    
    # profit_ratio_estimate
    min_60 = gb["close_adj"].rolling(60).min().to_numpy()
    max_60 = gb["close_adj"].rolling(60).max().to_numpy()
    df["profit_ratio_estimate"] = (df["close_adj"] - min_60) / (max_60 - min_60 + 1e-8)
    
    # chip_concentration
    ma_20 = gb["close_adj"].rolling(20).mean().to_numpy()
    df["chip_concentration"] = (df["close_adj"] / (ma_20 + 1e-8) - 1).abs().fillna(0.0)
    
    # vol_ratio (5日/60日成交量放大系数)
    vol_5m = gb["vol"].rolling(5).mean().to_numpy()
    vol_60m = gb["vol"].rolling(60).mean().to_numpy()
    df["vol_ratio"] = vol_5m / (vol_60m + 1e-8)
    
    # 5. 市场贝塔因子 (Beta Factor) - 高效向量化计算 (毫秒级)
    print("ℹ️ [Feature] 计算市场贝塔因子...")
    market_ret = df.groupby("trade_date")["daily_ret"].transform("mean")
    df["market_excess"] = market_ret - market_ret.rolling(60, min_periods=10).mean()
    df["stock_excess"] = df["daily_ret"] - df.groupby("ts_code")["daily_ret"].transform(lambda x: x.rolling(60, min_periods=10).mean())
    
    df["_prod_ex"] = df["stock_excess"] * df["market_excess"]
    _cov_60d = df.groupby("ts_code")["_prod_ex"].transform(lambda x: x.rolling(60, min_periods=10).mean())
    _var_60d = df.groupby("ts_code")["market_excess"].transform(lambda x: x.rolling(60, min_periods=10).var())
    df["beta_60d"] = (_cov_60d / (_var_60d + 1e-8)).fillna(1.0).clip(0.1, 3.0)
    df.drop(columns=["_prod_ex"], inplace=True, errors="ignore")
    
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

    # 9. 三维资金信号复合因子（按日截面 rank + min-max 归一化到 [0,1]）
    print("ℹ️ [Feature] 计算三维资金信号复合因子...")

    # 9-A. 游资热点得分：爆量 + 快速拉升 + 高换手 - 筹码分散
    df["_r_vol_ratio"]        = df.groupby("trade_date")["vol_ratio"].rank(pct=True)
    df["_r_return_5d"]        = df.groupby("trade_date")["return_5d"].rank(pct=True)
    df["_r_turnover_5d"]      = df.groupby("trade_date")["turnover_rate_5d"].rank(pct=True)
    df["_r_chip_conc"]        = df.groupby("trade_date")["chip_concentration"].rank(pct=True)
    df["_hm_raw"] = (
        df["_r_vol_ratio"].fillna(0.5)   * 0.35
        + df["_r_return_5d"].fillna(0.5) * 0.30
        + df["_r_turnover_5d"].fillna(0.5) * 0.25
        - df["_r_chip_conc"].fillna(0.5) * 0.10
    )
    df["hot_money_score"] = df.groupby("trade_date")["_hm_raw"].transform(
        lambda x: (x - x.min()) / (x.max() - x.min() + 1e-8)
    )

    # 9-B. 强庄控盘得分：筹码集中 + 低波动 + 中期趋势 + 质量评分
    df["_r_vol_20d"]          = df.groupby("trade_date")["volatility_20d"].rank(pct=True)
    df["_r_return_60d"]       = df.groupby("trade_date")["return_60d"].rank(pct=True)
    df["_r_quality"]          = df.groupby("trade_date")["quality_score"].rank(pct=True)
    df["_sc_raw"] = (
        df["_r_chip_conc"].fillna(0.5)   * 0.40
        - df["_r_vol_20d"].fillna(0.5)   * 0.30
        + df["_r_return_60d"].fillna(0.5) * 0.20
        + df["_r_quality"].fillna(0.5)   * 0.10
    )
    df["strong_control_score"] = df.groupby("trade_date")["_sc_raw"].transform(
        lambda x: (x - x.min()) / (x.max() - x.min() + 1e-8)
    )

    # 9-C. 主力资金扫货得分：大单净流入 + 获利盘位 + 中期动量 - 最大回撤
    df["_r_north_inflow"]     = df.groupby("trade_date")["north_net_inflow_ratio"].rank(pct=True)
    df["_r_profit_est"]       = df.groupby("trade_date")["profit_ratio_estimate"].rank(pct=True)
    df["_r_return_20d"]       = df.groupby("trade_date")["return_20d"].rank(pct=True)
    df["_r_mdd_20d"]          = df.groupby("trade_date")["max_drawdown_20d"].rank(pct=True)
    df["_mf_raw"] = (
        df["_r_north_inflow"].fillna(0.5) * 0.40
        + df["_r_profit_est"].fillna(0.5) * 0.25
        + df["_r_return_20d"].fillna(0.5) * 0.20
        - df["_r_mdd_20d"].fillna(0.5)   * 0.15
    )
    df["main_force_score"] = df.groupby("trade_date")["_mf_raw"].transform(
        lambda x: (x - x.min()) / (x.max() - x.min() + 1e-8)
    )

    # 清理临时 rank 列
    _tmp_cols = [c for c in df.columns if c.startswith("_r_") or c.startswith("_hm_") or c.startswith("_sc_") or c.startswith("_mf_")]
    df.drop(columns=_tmp_cols, inplace=True, errors="ignore")
    
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
        "beta_60d", "quality_score", "low_turnover_flag", "timeliness_decay",
        # 三维资金信号复合因子
        "hot_money_score", "strong_control_score", "main_force_score"
    ]

    # 关键：策略核心只消费 return_5/10/20d、volatility_20/60d、turnover_20d、三维资金复合分、quality；
    # 不依赖 120d 窗口。如果强制 dropna(subset=["volatility_120d","return_120d"])
    # 会在"全量+近期"场景下把 5500 只股票过滤到 ~4100 只（6 年数据不够 120d 的 IPO 新股 + 停牌股）。
    # 因此改为：只要求 20d 关键窗口 + 三维复合分非空，120d 保留 NaN（策略读取时已做 fillna）。
    core_cols = ["return_20d", "volatility_20d", "turnover_rate_20d",
                 "hot_money_score", "strong_control_score", "main_force_score"]
    df_clean = df[cols_to_save].dropna(subset=core_cols).reset_index(drop=True)
    # 再做一次后验：过滤掉 20250101 之前只有极少数窗口的史前数据（首日 1 日都没窗口）
    df_clean = df_clean[df_clean["trade_date"] >= "20200301"].reset_index(drop=True)
    
    table_name = "factor_values"
    try:
        # ① 先删除旧索引和旧表，立即 commit 确保 WAL 完全落盘
        conn.execute("DROP INDEX IF EXISTS idx_factors_date_code")
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.commit()   # ← 关键：WAL 模式下必须先提交删除操作
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to drop table {table_name}: {e}")
        conn.rollback()

    # ② replace 模式写入（即使 DROP 因并发失败，replace 也会先清空再写）
    df_clean.to_sql(table_name, conn, if_exists="replace", index=False, chunksize=10000)
    conn.commit()  # 显式提交 DML 事务

    # ③ 去重保险（防止 df_clean 本身含重复行）
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            DELETE FROM {table_name}
            WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM {table_name}
                GROUP BY trade_date, stock_code
            )
        """)
        removed = cursor.rowcount
        if removed > 0:
            import logging
            logging.getLogger(__name__).warning(f"[Feature] 去重删除 {removed} 条重复行")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[Feature] 去重检查跳过: {e}")

    # ④ 创建唯一索引
    try:
        cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_factors_date_code ON {table_name}(trade_date, stock_code);")
        conn.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[Feature] 索引创建跳过: {e}")
        
    latest_date = df_clean['trade_date'].max()
    print(f"🎉 [Feature] 因子特征工程成功入库！最新因子交易日: {latest_date}，共 {len(df_clean)} 条记录。")
    conn.close()
    
    total_time = time.time() - start_time
    print(f"✅ [Feature] 26 维复合因子成功写入 SQLite 表 [{table_name}]，共 {len(df_clean)} 行数据，总耗时: {total_time:.2f} 秒。")
    return df_clean

if __name__ == "__main__":
    calculate_stock_factors()
