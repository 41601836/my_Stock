# -*- coding: utf-8 -*-
"""
validator.py —— 因子 IC 衰减检验模块 (Phase 2 Agent Component)
========================================================================
1. 读取基础因子池在所有历史周度上的横截面 Rank IC。
2. 划分基准期 (前4年, 2020-2024) 与近期评估期 (最近52周)。
3. 根据 IC 均值绝对值偏离度计算衰减率：
   - 衰减 > 30% ➡️ 警告 (WARNING)
   - 衰减 > 50% ➡️ 失效剔除 (INVALID)
4. 输出验证报告字典以支持 recommender 生成最终决策。
"""

import os
import yaml
import sqlite3
import pandas as pd
import numpy as np

def load_config(config_path="agent/config.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def compute_historical_ic_series(db_path, csv_path, factors):
    """
    加载数据，计算个股未来5日收益率，并计算所有受监测因子的每日 Rank IC 时间序列
    """
    conn = sqlite3.connect(db_path)
    
    # 1. 计算未来 5 日收益率
    query_prices = "SELECT ts_code AS stock_code, trade_date, close, adj_factor FROM daily_prices WHERE trade_date >= '20200101'"
    df_prices = pd.read_sql(query_prices, conn)
    df_prices["trade_date"] = df_prices["trade_date"].astype(str)
    df_prices = df_prices.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    df_prices["close_adj"] = df_prices["close"] * df_prices["adj_factor"]
    df_prices["future_return_5d"] = df_prices.groupby("stock_code")["close_adj"].shift(-5) / df_prices["close_adj"] - 1.0
    df_prices["future_return_5d"] = df_prices["future_return_5d"].clip(-0.5, 0.8)
    
    # 2. 读取因子
    query_factors = f"SELECT * FROM factor_values"
    df_factors = pd.read_sql(query_factors, conn)
    df_factors["trade_date"] = df_factors["trade_date"].astype(str)
    conn.close()
    
    # 3. 读取状态标签
    df_regime = pd.read_csv(csv_path)
    df_regime["trade_date"] = df_regime["trade_date"].astype(str)
    
    # 4. 对齐
    df_merge = pd.merge(df_factors, df_prices[["stock_code", "trade_date", "future_return_5d"]], on=["stock_code", "trade_date"], how="inner")
    df_aligned = pd.merge(df_merge, df_regime[["trade_date", "regime"]], on="trade_date", how="inner")
    df_aligned = df_aligned.dropna(subset=["future_return_5d"]).reset_index(drop=True)
    
    # 5. 按照日期计算 Spearman corr (Rank IC) 的极速向量化重构
    print(f"ℹ️ [Validator] 数据对齐完毕，总对齐样本数: {len(df_aligned)} 行，开始计算 IC 时间序列...")
    
    # 过滤单日样本数太小的交易日
    date_counts = df_aligned["trade_date"].value_counts()
    valid_dates = date_counts[date_counts >= 30].index
    df_valid = df_aligned[df_aligned["trade_date"].isin(valid_dates)].copy()
    
    # 批量求秩 (等价于 Spearman 横截面转换)
    df_valid["future_return_5d_rank"] = df_valid.groupby("trade_date")["future_return_5d"].rank()
    
    rank_cols = []
    for f in factors:
        rank_col = f + "_rank"
        df_valid[rank_col] = df_valid.groupby("trade_date")[f].rank()
        rank_cols.append(rank_col)
        
    # 一次性计算 Pearson 相关性 (向量化 corrwith)
    df_ic_grouped = df_valid.groupby("trade_date")[rank_cols].corrwith(df_valid["future_return_5d_rank"], method="pearson")
    
    # 还原列名并整理
    df_ic_grouped.columns = [c[:-5] for c in df_ic_grouped.columns]
    df_ic = df_ic_grouped.fillna(0.0).reset_index()
    df_ic = df_ic.sort_values("trade_date").reset_index(drop=True)
    return df_ic, df_aligned

def validate_factors(config_path="agent/config.yaml"):
    """
    核心校验入口。返回所有监测因子的衰减评价字典
    """
    config = load_config(config_path)
    paths = config["paths"]
    val_cfg = config["validation"]
    factors = config["factors"]["base_pool"]
    
    # 1. 计算全历史 IC 序列
    df_ic, df_aligned = compute_historical_ic_series(paths["stock_data_db"], paths["market_labels_csv"], factors)
    
    # 2. 截取时间区间
    # 基准期 (Baseline): 历史前4年 (如 2020-2024)
    base_start = val_cfg["baseline_start_date"]
    base_end = val_cfg["baseline_end_date"]
    df_ic_base = df_ic[(df_ic["trade_date"] >= base_start) & (df_ic["trade_date"] <= base_end)]
    
    # 近景区 (Recent): 最近 52 个交易周 (即末尾 52 行)
    df_ic_recent = df_ic.tail(val_cfg["recent_weeks_lookback"])
    
    print(f"ℹ️ [Validator] 划分为基准期 ({len(df_ic_base)}周) 与近景区 ({len(df_ic_recent)}周) 进行衰减度校对...")
    
    report = {}
    
    decay_warn = val_cfg["decay_warning_threshold"]
    decay_inv = val_cfg["decay_invalid_threshold"]
    
    for f in factors:
        # 在基准期上的 Rank IC 均值 (真实正负符号)
        base_ic_mean = df_ic_base[f].mean() if len(df_ic_base) > 0 else 0.0
        # 在近景区上的 Rank IC 均值 (真实正负符号)
        recent_ic_mean = df_ic_recent[f].mean() if len(df_ic_recent) > 0 else 0.0
        
        base_ic_abs = abs(base_ic_mean)
        recent_ic_abs = abs(recent_ic_mean)
        
        # 衰减比例 = 1.0 - 近期绝对IC / 基准绝对IC
        if base_ic_abs > 1e-6:
            decay_ratio = 1.0 - (recent_ic_abs / base_ic_abs)
        else:
            decay_ratio = 1.0
            
        # 状态标定
        # 如果基准期 IC 绝对值极小 (例如 < 0.015)，说明因子本就失效，直接标定为 INVALID
        if base_ic_abs < 0.015:
            status = "INVALID"
            reason = "历史基准 IC 绝对值过小，属低效因子"
        elif decay_ratio >= decay_inv:
            status = "INVALID"
            reason = f"因子 IC 衰减比高达 {decay_ratio*100:.2f}%, 超过阈值 {decay_inv*100}%"
        elif decay_ratio >= decay_warn:
            status = "WARNING"
            reason = f"因子 IC 衰减比达 {decay_ratio*100:.2f}%, 处于警戒区间"
        else:
            status = "VALID"
            reason = f"因子近期效能正常，衰减比为 {decay_ratio*100:.2f}%"
            
        report[f] = {
            "factor": f,
            "baseline_ic": base_ic_mean,
            "recent_ic": recent_ic_mean,
            "decay_ratio": float(decay_ratio),
            "status": status,
            "reason": reason
        }
        
    print(f"✅ [Validator] 基础因子池校验完成。")
    return report, df_aligned

if __name__ == "__main__":
    report, _ = validate_factors()
    for f, details in report.items():
        print(f"因子 [{f:<24}] ➡️ 状态: {details['status']:<8} | 基准IC: {details['baseline_ic']:.4f} | 近期IC: {details['recent_ic']:.4f} | 衰减: {details['decay_ratio']*100:.1f}%")
