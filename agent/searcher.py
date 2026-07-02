# -*- coding: utf-8 -*-
"""
searcher.py —— 因子搜索与挖掘模块 (Phase 2 Agent Component)
========================================================================
1. 在 10-12 个实验特征因子上进行 Rank IC-IR 测试。
2. 聚焦于震荡市 (Range) 状态，筛选满足 abs(IC) > 0.025 且 IR > 0.4 的因子。
3. 校验其与当前已存的“非失效基础因子”的相关性，剔除 > 0.7 的高度重叠冗余特征。
4. 返回被推荐的新因子及相应权重，以支持 recommender 做组合重组。
"""

import os
import yaml
import sqlite3
import pandas as pd
import numpy as np

def load_config(config_path="agent/config.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def search_new_factors(df_aligned, active_base_factors, config_path="agent/config.yaml"):
    """
    在实验因子池中搜索能够填补失效因子空白的新候选因子。
    - df_aligned: 已经对齐了价格、因子与 regime 标签的完整 DataFrame (由 validator 传入以复用计算)
    - active_base_factors: 基础因子池中目前 VALID / WARNING 的因子列表
    """
    config = load_config(config_path)
    exp_factors = config["factors"]["experimental_pool"]
    
    df_range = df_aligned[df_aligned["regime"] == "Range"].copy()
    unique_dates = df_range["trade_date"].unique()
    
    print(f"ℹ️ [Searcher] 开始在 {len(exp_factors)} 个实验因子中进行有效性搜索...")
    
    # 1. 计算每个实验因子在 Range 状态下的 Rank IC 时间序列 (向量化重构)
    date_counts = df_range["trade_date"].value_counts()
    valid_dates = date_counts[date_counts >= 30].index
    df_valid = df_range[df_range["trade_date"].isin(valid_dates)].copy()
    
    # 横截面 Rank 秩转换
    df_valid["future_return_5d_rank"] = df_valid.groupby("trade_date")["future_return_5d"].rank()
    
    rank_cols = []
    for f in exp_factors:
        rank_col = f + "_rank"
        df_valid[rank_col] = df_valid.groupby("trade_date")[f].rank()
        rank_cols.append(rank_col)
        
    # 一次性计算 Pearson 相关性 (corrwith)
    df_ic_grouped = df_valid.groupby("trade_date")[rank_cols].corrwith(df_valid["future_return_5d_rank"], method="pearson")
    df_ic_grouped.columns = [c[:-5] for c in df_ic_grouped.columns]
    df_ic = df_ic_grouped.fillna(0.0)
    
    # 统计 IC 均值与 IR
    summary_list = []
    for f in exp_factors:
        ic_series = df_ic[f]
        if len(ic_series) > 0:
            mean_ic = ic_series.mean()
            std_ic = ic_series.std()
            ir = mean_ic / std_ic if std_ic > 1e-6 else 0.0
        else:
            mean_ic = 0.0
            std_ic = 0.0
            ir = 0.0
            
        summary_list.append({
            "factor": f,
            "mean_ic": mean_ic,
            "std_ic": std_ic,
            "rank_ir": ir,
            "abs_ic": abs(mean_ic),
            "abs_ir": abs(ir)
        })
        
    df_exp_summary = pd.DataFrame(summary_list)
    
    # 2. 依据有效性门槛进行筛选 (abs(IC) > 0.025 且 IR > 0.40)
    ic_threshold = config["validation"]["decay_warning_threshold"]  # 或者是 config 里面配置的阈值，这里直接用 0.025 / 0.4
    df_candidates = df_exp_summary[(df_exp_summary["abs_ic"] > 0.025) & (df_exp_summary["abs_ir"] > 0.40)].copy()
    
    print(f"📊 实验池初筛有效候选因子个数: {len(df_candidates)} 个")
    if len(df_candidates) == 0:
        return {}, []
        
    # 按 IR 绝对值从大到小排序，优先考虑优良因子
    df_candidates = df_candidates.sort_values("abs_ir", ascending=False).reset_index(drop=True)
    
    # 3. 去共振去重叠检验 (相关性 <= 0.70)
    # 计算候选因子与现有活跃老因子在 Range 样本下的相关性矩阵
    all_needed_cols = list(set(active_base_factors + df_candidates["factor"].tolist()))
    df_corr_samples = df_range[all_needed_cols].copy()
    corr_matrix = df_corr_samples.corr(method="spearman").abs()
    
    recommended_factors = []
    search_report = {}
    
    for _, row in df_candidates.iterrows():
        f = row["factor"]
        # 检测是否与活跃老因子或者是已经录用的新因子存在高度共线
        max_corr_with_base = 0.0
        corr_partner = ""
        
        # 对比老活跃因子
        for bf in active_base_factors:
            c = corr_matrix.loc[f, bf]
            if c > max_corr_with_base:
                max_corr_with_base = c
                corr_partner = bf
                
        # 对比已经选中的其他新因子
        for rf in recommended_factors:
            c = corr_matrix.loc[f, rf]
            if c > max_corr_with_base:
                max_corr_with_base = c
                corr_partner = rf
                
        if max_corr_with_base > 0.70:
            print(f"   - 实验因子 [{f:<24}] 冗余剔除 : 与已存活跃因子 [{corr_partner}] 相关性高达 {max_corr_with_base:.2f}")
        else:
            recommended_factors.append(f)
            search_report[f] = {
                "factor": f,
                "mean_ic": row["mean_ic"],
                "rank_ir": row["rank_ir"],
                "max_base_corr": max_corr_with_base,
                "most_correlated_factor": corr_partner
            }
            print(f"   - 录用实验因子 [{f:<24}] : IC: {row['mean_ic']:.4f} | IR: {row['rank_ir']:.4f} | 最大共线相关系数: {max_corr_with_base:.2f}")
            
    print(f"✅ [Searcher] 实验因子搜索完成，共录用新因子 {len(recommended_factors)} 个。")
    return search_report, recommended_factors

def generate_factor_combinations(config_path="agent/config.yaml", candidate_path="config/candidate_factors.yaml", num_combinations=25):
    """
    因子组合生成器
    从候选因子池中，穷举或启发式生成 3-5 个因子的组合，输出 25 个候选组合清单。
    """
    factors = []
    if os.path.exists(candidate_path):
        try:
            with open(candidate_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                factors = cfg.get("candidate_factors", [])
        except Exception:
            pass
            
    if not factors and os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                factors = cfg.get("factors", {}).get("base_pool", [])
        except Exception:
            pass
            
    if not factors:
        factors = [
            "return_5d", "return_20d", "return_60d", "excess_return_20d",
            "volatility_20d", "volatility_60d", "skewness_20d", "max_drawdown_20d",
            "atr_ratio", "pe_ttm", "pb", "roe", "turnover_rate",
            "north_net_inflow_ratio", "profit_ratio_estimate", "chip_concentration"
        ]
        
    # 写回 candidate_path，保持一致
    os.makedirs(os.path.dirname(candidate_path), exist_ok=True)
    try:
        with open(candidate_path, "w", encoding="utf-8") as f:
            yaml.dump({"candidate_factors": factors}, f)
    except Exception:
        pass
        
    import random
    rng = random.Random(42) # 固定种子以支持幂等性
    
    # 类别区分
    momentum = [f for f in factors if "return" in f]
    risk = [f for f in factors if "volatility" in f or "drawdown" in f or "atr" in f]
    market = [f for f in factors if f in ["turnover_rate", "north_net_inflow_ratio", "profit_ratio_estimate", "chip_concentration", "pe_ttm", "pb", "roe"]]
    
    combinations = []
    
    # 启发式生成
    for _ in range(num_combinations * 2):
        size = rng.randint(3, 5)
        combo = set()
        
        # 类别拼装
        if momentum and rng.random() > 0.2:
            combo.add(rng.choice(momentum))
        if risk and rng.random() > 0.2:
            combo.add(rng.choice(risk))
        if market and rng.random() > 0.2:
            combo.add(rng.choice(market))
            
        while len(combo) < size:
            combo.add(rng.choice(factors))
            
        combo_list = sorted(list(combo))
        if combo_list not in combinations:
            combinations.append(combo_list)
            
    # 不够则随机补充
    while len(combinations) < num_combinations:
        size = rng.randint(3, 5)
        combo = rng.sample(factors, size)
        combo_list = sorted(combo)
        if combo_list not in combinations:
            combinations.append(combo_list)
            
    return combinations[:num_combinations]
