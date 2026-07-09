# -*- coding: utf-8 -*-
"""
factor_ic_analysis.py —— 因子有效性分析与相关性去冗余脚本 (Phase 2)
========================================================================
1. 从 SQLite 加载 2020-2026 全量 18 维个股因子。
2. 计算未来 5 日个股后复权收益率 future_return_5d。
3. 对齐周度平移市场状态 labels v2。
4. 测算 Range (震荡市) 与 Bull (牛市) 环境下的每日 Rank IC 均值与 Rank IR。
5. 按照 abs(IC) > 0.025 且 IR > 0.4 对 Range 状态下的因子进行初筛。
6. 测算初筛因子横截面相关性，剔除共线共振冗余特征 (相关性 > 0.7)，输出最终核心子集。
7. 输出 Range vs Bull 的偏好排名差异表。
"""

import os
import sys
import sqlite3
import shutil
import pandas as pd
import numpy as np
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.paths import PATHS, startup_check

startup_check()

def load_data(db_path=None, csv_path=None):
    if db_path is None:
        db_path = PATHS.database.stock_data
    if csv_path is None:
        csv_path = PATHS.data.market_regime_labels_v2
    """
    加载多因子数据、行情数据并计算未来5日收益率，与状态对齐
    """
    conn = sqlite3.connect(db_path)
    
    # 1. 加载行情计算未来5日后复权收益率
    print("ℹ️ [IC] 正在读取价格数据以计算个股未来 5 日后复权收益率...")
    query_prices = "SELECT ts_code AS stock_code, trade_date, close, adj_factor FROM daily_prices WHERE trade_date >= '20200101'"
    df_prices = pd.read_sql(query_prices, conn)
    df_prices["trade_date"] = df_prices["trade_date"].astype(str)
    
    # 排序并计算后复权价及未来收益率
    df_prices = df_prices.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    df_prices["close_adj"] = df_prices["close"] * df_prices["adj_factor"]
    
    # 5日未来收益率：(5日后的后复权价 - 当日的后复权价) / 当日的后复权价
    df_prices["future_return_5d"] = df_prices.groupby("stock_code")["close_adj"].shift(-5) / df_prices["close_adj"] - 1.0
    df_prices["future_return_5d"] = df_prices["future_return_5d"].clip(-0.5, 0.8)
    
    # 2. 从 factor_values 加载 18 维特征因子
    print("ℹ️ [IC] 正在读取 factor_values 表中的 18 维特征数据...")
    df_factors = pd.read_sql("SELECT * FROM factor_values", conn)
    df_factors["trade_date"] = df_factors["trade_date"].astype(str)
    conn.close()
    
    # 3. 加载已平移的市场状态标签
    print(f"ℹ️ [IC] 正在读取周度平移市场状态标签: {csv_path}")
    df_regime = pd.read_csv(csv_path)
    df_regime["trade_date"] = df_regime["trade_date"].astype(str)
    
    # 合并未来收益率与特征因子
    df_merge = pd.merge(df_factors, df_prices[["stock_code", "trade_date", "future_return_5d"]], on=["stock_code", "trade_date"], how="inner")
    
    # 与市场标签对齐 (只有处于周五调仓日上的个股样本才保留)
    df_aligned = pd.merge(df_merge, df_regime[["trade_date", "regime"]], on="trade_date", how="inner")
    
    df_aligned = df_aligned.dropna(subset=["future_return_5d"]).reset_index(drop=True)
    print(f"✅ [IC] 样本加载与对齐完毕，有效对齐行数: {len(df_aligned)}")
    
    return df_aligned

def compute_rank_ic_ir(df, factor_names, target_regime):
    """
    计算特定市场环境下各因子的每日横截面 Rank IC、IC均值以及 Rank IR
    """
    df_reg = df[df["regime"] == target_regime].copy()
    unique_dates = df_reg["trade_date"].unique()
    
    print(f"ℹ️ [IC] 正在计算 [{target_regime}] 状态下的 Rank IC (包含 {len(unique_dates)} 个交易周，共 {len(df_reg)} 条样本)...")
    
    ic_results = {f: [] for f in factor_names}
    valid_dates = []
    
    # 按日期分组进行横截面 Rank IC 的极速测算
    grouped = df_reg.groupby("trade_date")
    
    for d, df_sub in grouped:
        if len(df_sub) < 30: # 剔除个股样本数太少的异常截面
            continue
        valid_dates.append(d)
        
        for f in factor_names:
            # 使用 pandas 的 corr 计算 spearman 秩相关系数
            corr = df_sub[f].corr(df_sub["future_return_5d"], method="spearman")
            if not pd.isna(corr):
                ic_results[f].append(corr)
            else:
                ic_results[f].append(0.0)
                
    # 统计均值和 IR
    summary_list = []
    for f in factor_names:
        ic_series = pd.Series(ic_results[f])
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
            "abs_ic": abs(mean_ic)
        })
        
    df_summary = pd.DataFrame(summary_list)
    df_summary = df_summary.sort_values("abs_ic", ascending=False).reset_index(drop=True)
    return df_summary, ic_results

def filter_and_remove_redundancy(df_ic_range, df_samples, range_factor_names, ic_threshold=0.025, ir_threshold=0.40):
    """
    因子初筛并基于相关性矩阵剔除共线冗余特征
    """
    print(f"\nℹ️ [Filter] 开始进行震荡市 (Range) 因子初筛 (阈值: abs_IC > {ic_threshold} 且 IR > {ir_threshold})...")
    
    # 1. 满足初筛条件
    df_filtered = df_ic_range[
        (df_ic_range["abs_ic"] > ic_threshold) & 
        (df_ic_range["rank_ir"].abs() > ir_threshold)
    ].copy()
    
    print(f"📊 初筛出符合要求的候选有效因子数: {len(df_filtered)}")
    print(df_filtered[["factor", "mean_ic", "rank_ir"]])
    
    if len(df_filtered) <= 1:
        return df_filtered["factor"].tolist(), df_filtered
        
    candidate_factors = df_filtered["factor"].tolist()
    
    # 2. 计算候选因子在 Range 样本下的横截面相关性矩阵 (Spearman)
    df_range_samples = df_samples[df_samples["regime"] == "Range"][candidate_factors].copy()
    corr_matrix = df_range_samples.corr(method="spearman").abs()
    
    # 3. 贪心算法剔除高度冗余因子
    # 按照 Rank IR 绝对值从大到小对因子进行排序，优先保留 IR 大的
    df_filtered["abs_ir"] = df_filtered["rank_ir"].abs()
    df_sorted = df_filtered.sort_values("abs_ir", ascending=False).reset_index(drop=True)
    
    selected_factors = []
    discarded_factors = []
    
    for _, row in df_sorted.iterrows():
        f = row["factor"]
        # 检查是否与已选因子的相关性大于 0.70
        is_redundant = False
        for sf in selected_factors:
            if corr_matrix.loc[f, sf] > 0.70:
                is_redundant = True
                discarded_factors.append((f, sf, corr_matrix.loc[f, sf]))
                break
        if not is_redundant:
            selected_factors.append(f)
            
    print("\nℹ️ [Filter] 因子相关性去冗余处理 (阈值: > 0.70):")
    for f, sf, corr in discarded_factors:
        print(f"   - 剔除因子 [{f:<24}] : 因其与因子 [{sf:<24}] 相关性达 {corr:.2f}，且后者的 IR 更优。")
        
    print(f"✅ 最终筛选出的核心特征子集 ({len(selected_factors)} 个): {selected_factors}")
    
    df_final_weights = df_sorted[df_sorted["factor"].isin(selected_factors)].copy()
    return selected_factors, df_final_weights

def main():
    print("=" * 80)
    print("🚀 开始进行 Phase 2: 2020-2026 全历史因子 IC-IR 有效性分析及筛选")
    print("=" * 80)
    
    db_path = PATHS.database.stock_data
    csv_path = PATHS.data.market_regime_labels_v2
    
    # 1. 载入并合并对齐数据
    try:
        df_samples = load_data(db_path, csv_path)
    except Exception as e:
        print(f"❌ 数据加载失败: {e}")
        return
        
    # 定义 24 个特征因子池名称（含 6 个新实验因子）
    factor_pool = [
        "return_5d", "return_20d", "return_60d", "excess_return_20d",
        "volatility_20d", "volatility_60d", "skewness_20d", "max_drawdown_20d", "atr_ratio",
        "pe_ttm", "pb", "roe", "turnover_rate",
        "north_net_inflow_ratio", "profit_ratio_estimate", "chip_concentration",
        # 新增实验因子
        "return_10d", "return_120d",
        "volatility_10d", "volatility_120d", "max_drawdown_60d",
        "turnover_rate_5d", "turnover_rate_20d", "vol_ratio"
    ]
    
    # 2. 对震荡市 (Range) 单独进行 IC/IR 评估
    print("\n" + "=" * 50)
    print("📊 Range 震荡市因子 IC-IR 排名表:")
    print("=" * 50)
    df_ic_range, _ = compute_rank_ic_ir(df_samples, factor_pool, "Range")
    print(df_ic_range[["factor", "mean_ic", "std_ic", "rank_ir"]].to_string())
    
    # 3. 因子初筛与去冗余
    selected_range_factors, df_range_weights = filter_and_remove_redundancy(
        df_ic_range, df_samples, factor_pool, 
        ic_threshold=0.025, ir_threshold=0.40
    )
    
    # 4. 对牛市 (Bull) 单独进行 IC/IR 评估以进行偏好对比
    print("\n" + "=" * 50)
    print("📊 Bull 牛市因子 IC-IR 排名表:")
    print("=" * 50)
    df_ic_bull, _ = compute_rank_ic_ir(df_samples, factor_pool, "Bull")
    print(df_ic_bull[["factor", "mean_ic", "std_ic", "rank_ir"]].to_string())
    
    # 5. 因子偏好差异对比展示
    print("\n" + "=" * 80)
    print("🔍 Range (震荡市) vs Bull (牛市) 因子表现差异偏好对比表:")
    print("=" * 80)
    df_compare = pd.merge(
        df_ic_range[["factor", "mean_ic", "rank_ir"]].rename(columns={"mean_ic": "range_ic", "rank_ir": "range_ir"}),
        df_ic_bull[["factor", "mean_ic", "rank_ir"]].rename(columns={"mean_ic": "bull_ic", "rank_ir": "bull_ir"}),
        on="factor"
    )
    # 按 Range 绝对 IC 排序
    df_compare["abs_range_ic"] = df_compare["range_ic"].abs()
    df_compare = df_compare.sort_values("abs_range_ic", ascending=False).drop(columns=["abs_range_ic"]).reset_index(drop=True)
    print(df_compare.to_string(index=False))
    
    # 6. 保存最终筛选核心因子配置权重
    # 特权加成因子：north_net_inflow_ratio, profit_ratio_estimate, chip_concentration
    # 如果初筛被选中，则这些聪明钱/微观因子的权重乘以 1.2 加成
    print("\n" + "=" * 50)
    print("⚙️  模型配置权重输出:")
    print("=" * 50)
    
    # 保存策略因子及权重
    weights_dict = {}
    special_proxies = ["north_net_inflow_ratio", "profit_ratio_estimate", "chip_concentration"]
    
    for _, row in df_range_weights.iterrows():
        f = row["factor"]
        base_w = abs(row["mean_ic"]) / df_range_weights["abs_ic"].sum() # 基于IC绝对值占比归一化作为基础权重
        if f in special_proxies:
            base_w = base_w * 1.2
            print(f"   - 因子 [{f:<24}] : 基础归一权重已赋予 1.2 倍聪明钱/微观结构正交加成 ➡️ 最终权重: {base_w:.4f}")
        else:
            print(f"   - 因子 [{f:<24}] : 赋予基础归一化权重 ➡️ 最终权重: {base_w:.4f}")
        weights_dict[f] = base_w
        
    # 保存至 pickle 供后续训练和实盘模型载入
    os.makedirs(os.path.dirname(PATHS.models.regime_weights), exist_ok=True)
    weights_path = PATHS.models.regime_weights
    
    import pickle
    with open(weights_path, "wb") as f:
        pickle.dump({"range_weights": weights_dict, "range_factors": selected_range_factors}, f)
    print(f"💾 [Config] 核心因子筛选子集及配置权重已保存至: {weights_path}")
    print("=" * 80)

if __name__ == "__main__":
    main()
