# -*- coding: utf-8 -*-
"""
model_trainer.py —— 模型训练与样本对齐模块 (防御型因子权重切换版)
==================================================
实现特征因子 (factor_values 表) 与周度平移预测标签 (market_regime_labels.csv) 在 trade_date 上的合并对齐，
为 Phase 2 滚动线性打分模型和 Ridge 回归提供干净的训练样本流。
支持防御型因子权重切换：Dark/Bear 状态下自动切换至质量防御因子组合。
"""

import os
import sqlite3
import pandas as pd
import numpy as np

from config.paths import PATHS, startup_check

startup_check()

def load_training_data(db_path=None, csv_path=None):
    if db_path is None:
        db_path = PATHS.database.stock_data
    if csv_path is None:
        csv_path = PATHS.data.market_regime_labels
    """
    核心对接逻辑：
    1. 从本地 csv 载入已做 shift(1) 平移的市场状态预测环境标签。
    2. 从 sqlite 数据库的 factor_values 表载入个股在 2026 年 1 月计算出的多因子指标。
    3. 通过 trade_date 联合键进行 Merge，确保模型训练样本与市场所处环境完全对齐。
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"❌ 预测标签文件未找到: {csv_path}")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"❌ 因子数据库未找到: {db_path}")
        
    print(f"ℹ️ [Trainer] 正在读取周度状态标签: {csv_path}")
    # 预测标签包含列：trade_date, regime, ret_20d, vol_20d, drawdown_5d
    # 这里的 trade_date 是 int 或 str
    df_regime = pd.read_csv(csv_path)
    df_regime["trade_date"] = df_regime["trade_date"].astype(str)
    
    print(f"ℹ️ [Trainer] 正在从 {db_path} 加载个股特征因子数据...")
    conn = sqlite3.connect(db_path)
    # factor_values 表包含：trade_date, stock_code, volatility_20d, volatility_60d, atr_ratio, bollinger_pct, return_20d, return_60d
    df_factors = pd.read_sql("SELECT * FROM factor_values", conn)
    conn.close()
    df_factors["trade_date"] = df_factors["trade_date"].astype(str)
    
    print(f"ℹ️ [Trainer] 因子库记录: {len(df_factors)} 行 | 状态标签库记录: {len(df_regime)} 行")
    
    # 4. 在 trade_date 上合并
    # 只有处于周度调仓决策日（通常是周五）的个股因子样本，才会匹配上当周要运用的预测状态标签 (regime)
    df_aligned = pd.merge(df_factors, df_regime, on="trade_date", how="inner")
    
    # 调整排序
    df_aligned = df_aligned.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    
    print(f"✅ [Trainer] 样本对齐完成！最终可用训练样本条数: {len(df_aligned)} 行 (因子值与市场状态在同一交易日对齐)")
    if len(df_aligned) > 0:
        unique_dates = df_aligned["trade_date"].nunique()
        unique_stocks = df_aligned["stock_code"].nunique()
        print(f"   - 包含的独特交易日 (周调仓点) 数: {unique_dates} 个")
        print(f"   - 包含的个股数: {unique_stocks} 只")
        print(f"   - 各状态样本点分布:\n{df_aligned['regime'].value_counts()}")
        
    return df_aligned

def train_model(df_aligned, train_window_weeks=52, predict_window_weeks=4):
    """
    执行 Walk-Forward (滚动步进) 滚动训练与样本划分。
    - 训练集起点：2020-01-01
    - 滚动训练窗口：52 周
    - 滚动预测窗口：4 周
    """
    # 提取按时间排序的独特周度交易日
    unique_dates = sorted(df_aligned["trade_date"].unique())
    total_weeks = len(unique_dates)
    
    print(f"\n⚙️ [Trainer] 开始构建 Walk-Forward 滚动训练样本集...")
    print(f"   - 全历史有效交易周: {total_weeks} 周 | 预设训练集: {train_window_weeks} 周 | 预设测试集: {predict_window_weeks} 周")
    
    if total_weeks < train_window_weeks + predict_window_weeks:
        print("   ⚠️ [Trainer] 对齐样本总周数不足以支持一次完整的训练+测试周期，跳过滚动分轨。")
        return
        
    step = predict_window_weeks
    iteration = 0
    
    # 滚动步进划分
    for start_idx in range(0, total_weeks - train_window_weeks, step):
        train_end_idx = start_idx + train_window_weeks
        predict_end_idx = min(train_end_idx + predict_window_weeks, total_weeks)
        
        train_dates = unique_dates[start_idx:train_end_idx]
        predict_dates = unique_dates[train_end_idx:predict_end_idx]
        
        # 提取当前时间窗的训练集和预测集
        df_train = df_aligned[df_aligned["trade_date"].isin(train_dates)]
        df_predict = df_aligned[df_aligned["trade_date"].isin(predict_dates)]
        
        iteration += 1
        print(f"   [滚动第 {iteration:02d} 轮] 训练区间: {train_dates[0]} ~ {train_dates[-1]} ({len(train_dates)}周) | "
              f"预测区间: {predict_dates[0]} ~ {predict_dates[-1]} ({len(predict_dates)}周)")
        print(f"                 训练集记录: {len(df_train)} 行 | 预测/测试集记录: {len(df_predict)} 行")
        
        if predict_end_idx >= total_weeks:
            break
            
    print(f"✅ [Trainer] Walk-Forward 滚动分轨构建成功，共划分 {iteration} 组滚动训练集。")

DEFENSE_FACTOR_POOL = ["quality_score", "low_turnover_flag", "beta_60d", "roe", "pb"]

def load_weights_by_regime(regime):
    """
    根据当前周的市场状态 regime 路由加载对应的因子池与权重配置字典。
    - Range ➡️ 加载 models/regime_weights.pkl 或 regime_weights_proposed.pkl
    - Bull ➡️ 加载 models/bull_weights_proposed.pkl
    - Dark / Bear ➡️ 返回防御型因子组合（质量评分、低换手、低贝塔）
    """
    import pickle
    r = str(regime).upper()
    if r == "RANGE":
        path = PATHS.models.regime_weights
        if not os.path.exists(path):
            path = PATHS.models.regime_weights_proposed
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = pickle.load(f)
            return data.get("range_factors", []), data.get("range_weights", {})
        else:
            return [], {}
    elif r == "BULL":
        path = PATHS.models.bull_weights_proposed
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = pickle.load(f)
            return data.get("bull_factors", []), data.get("bull_weights", {})
        else:
            return [], {}
    else:
        # Dark / Bear 状态：返回防御型因子组合
        # 权重配置：质量评分(40%)、低换手(30%)、低贝塔(20%)、ROE(10%)
        defense_weights = {
            "quality_score": 0.4,
            "low_turnover_flag": 0.3,
            "beta_60d": 0.2,
            "roe": 0.1
        }
        return DEFENSE_FACTOR_POOL, defense_weights

if __name__ == "__main__":
    df_train = load_training_data(PATHS.database.stock_data, PATHS.data.market_regime_labels_v2)
    if len(df_train) > 0:
        train_model(df_train, train_window_weeks=52, predict_window_weeks=4)
