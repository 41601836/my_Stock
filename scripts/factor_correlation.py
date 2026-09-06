#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方向 A3: 因子相关性矩阵 + 聚类分析
====================================
计算全部有效因子之间的截面相关系数矩阵，做层次聚类，
识别独立因子簇和冗余因子。

输出:
  - corr_matrix.csv: 相关系数矩阵
  - clusters.csv: 每个因子所属聚类
  - independent_factors.csv: 每簇代表性因子

用法:
  python3 scripts/factor_correlation.py
  python3 scripts/factor_correlation.py --start 20240101 --n-clusters 5
"""

import os
import sys
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from factor_lib.registry import FACTOR_REGISTRY, get_all_factor_names, get_classic_factor_names, get_evo_factor_names
from factor_lib.config import FactorTestConfig
from factor_lib.loader import FactorDataLoader

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
from scipy.spatial.distance import pdist, squareform

def compute_corr_matrix(df, factor_list, method="spearman"):
    """计算因子间相关系数矩阵（全样本面板 pairwise 相关）

    直接用全量 stock-day 观测计算 pairwise 相关系数，
    每对因子使用其共同有效的所有观测，避免 dropna 导致样本量不足。
    """
    factor_cols = [f for f in factor_list if f in df.columns]
    if len(factor_cols) < 2:
        raise ValueError(f"有效因子不足: {len(factor_cols)}")

    # 全面板 pairwise 相关（自动处理 NaN）
    df_corr = df[factor_cols].corr(method=method)

    # 估算有效观测数（非 NaN 对数的均值）
    valid_obs = 0
    n_pairs = 0
    for i in range(len(factor_cols)):
        for j in range(i+1, len(factor_cols)):
            mask = df[factor_cols[i]].notna() & df[factor_cols[j]].notna()
            valid_obs += mask.sum()
            n_pairs += 1
    avg_obs = valid_obs / n_pairs if n_pairs > 0 else 0

    return df_corr, int(avg_obs)

def hierarchical_clustering(corr_matrix, n_clusters=5):
    """层次聚类（基于相关系数距离 = 1 - |corr|）"""
    # 距离矩阵: 1 - |correlation|
    dist = 1 - np.abs(corr_matrix.values)
    # NaN 填 1（最大距离，视为无关）
    dist = np.nan_to_num(dist, nan=1.0)
    # 确保对称（pairwise 相关可能因有效观测不同导致微小不对称）
    dist = (dist + dist.T) / 2
    # 确保对角线为 0
    np.fill_diagonal(dist, 0)
    # 压缩为向量
    dist_vec = squareform(dist)

    # 层次聚类 (Ward 方法)
    Z = linkage(dist_vec, method="ward")

    # 聚类分配
    labels = fcluster(Z, n_clusters, criterion="maxclust")

    df_cluster = pd.DataFrame({
        "factor": corr_matrix.index,
        "cluster": labels,
    })
    df_cluster = df_cluster.sort_values(["cluster", "factor"]).reset_index(drop=True)

    return Z, df_cluster

def find_independent_factors(corr_matrix, df_cluster, ranking_df=None):
    """
    从每个簇中选出代表性因子（独立因子）。
    策略: 选簇内 ICIR 最高的因子（如果有排名数据），
         否则选簇内与其他因子平均相关度最低的。
    """
    results = []

    for c in sorted(df_cluster["cluster"].unique()):
        cluster_factors = df_cluster[df_cluster["cluster"] == c]["factor"].tolist()

        # 计算每个因子与簇内其他因子的平均绝对相关
        avg_abs_corr = {}
        for f in cluster_factors:
            others = [x for x in cluster_factors if x != f]
            if not others:
                avg_abs_corr[f] = 0.0
            else:
                avg_abs_corr[f] = corr_matrix.loc[f, others].abs().mean()

        # 选代表因子
        if ranking_df is not None and len(ranking_df) > 0:
            # 有排名数据: 选 ICIR 最高的
            cluster_ranking = ranking_df[ranking_df["factor"].isin(cluster_factors)]
            if len(cluster_ranking) > 0:
                best = cluster_ranking.loc[cluster_ranking["icir"].abs().idxmax()]
                rep_factor = best["factor"]
                rep_icir = best["icir"]
                rep_grade = best["grade"]
            else:
                rep_factor = min(avg_abs_corr, key=avg_abs_corr.get)
                rep_icir = None
                rep_grade = None
        else:
            # 无排名数据: 选平均相关度最低的
            rep_factor = min(avg_abs_corr, key=avg_abs_corr.get)
            rep_icir = None
            rep_grade = None

        results.append({
            "cluster": c,
            "n_factors": len(cluster_factors),
            "representative": rep_factor,
            "rep_icir": rep_icir,
            "rep_grade": rep_grade,
            "factors": ", ".join(cluster_factors),
            "avg_abs_corr_of_rep": avg_abs_corr.get(rep_factor, 0),
            "cluster_avg_abs_corr": np.mean([avg_abs_corr[f] for f in cluster_factors]),
        })

    return pd.DataFrame(results)

def main():
    parser = argparse.ArgumentParser(description="因子相关性与聚类分析")
    parser.add_argument("--start", type=str, default="20240101", help="开始日期")
    parser.add_argument("--end", type=str, default=None, help="结束日期")
    parser.add_argument("--n-clusters", type=int, default=5, help="聚类数量")
    parser.add_argument("--method", type=str, default="spearman", help="相关方法: spearman/pearson")
    parser.add_argument("--min-valid", type=int, default=1000, help="最少有效行数")
    parser.add_argument("--ranking", type=str, default=None, help="评级 CSV 路径（用于选代表因子）")
    parser.add_argument("--output-dir", type=str, default=None, help="输出目录")
    args = parser.parse_args()

    cfg = FactorTestConfig()
    output_dir = args.output_dir or os.path.join(PROJECT_ROOT, "factor_test_reports")
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n  因子相关性 & 聚类分析")
    print(f"  {'─' * 50}")
    print(f"  区间: {args.start} ~ {args.end or '最新'}")
    print(f"  聚类数: {args.n_clusters}  方法: {args.method}")

    loader = FactorDataLoader()

    # 加载所有因子
    all_factors = get_all_factor_names()
    classic = get_classic_factor_names()
    evo = get_evo_factor_names()

    print(f"  因子数: {len(all_factors)}")

    # 分别加载
    df_classic = loader.load_factor_values(classic, args.start, args.end)
    df_evo = loader.load_factor_values(evo, args.start, args.end)

    # 合并 (按 ts_code + trade_date)
    print(f"  合并经典 + EVO 因子...")
    df_merged = pd.merge(df_classic, df_evo, on=["ts_code", "trade_date"], how="inner")
    print(f"  合并后: {len(df_merged):,} 行")

    # 过滤有效因子（数据量充足）
    valid_factors = []
    for f in all_factors:
        if f in df_merged.columns and df_merged[f].notna().sum() >= args.min_valid:
            valid_factors.append(f)

    print(f"  有效因子: {len(valid_factors)} / {len(all_factors)}")

    if len(valid_factors) < 2:
        print("❌ 有效因子不足，无法计算相关性")
        sys.exit(1)

    # 计算相关矩阵
    print(f"\n  计算相关系数矩阵 ({args.method})...")
    corr_matrix, valid_days = compute_corr_matrix(df_merged, valid_factors, method=args.method)
    print(f"  有效观测均值: {valid_days}")
    print(f"  矩阵大小: {corr_matrix.shape}")

    # 保存
    corr_path = os.path.join(output_dir, "factor_corr_matrix.csv")
    corr_matrix.to_csv(corr_path, encoding="utf-8-sig")
    print(f"  📄 相关矩阵: {corr_path}")

    # 相关性统计
    corr_values = corr_matrix.values[np.triu_indices(len(corr_matrix), k=1)]
    print(f"\n  相关性统计 (上三角):")
    print(f"    均值: {np.mean(np.abs(corr_values)):.4f}")
    print(f"    中位数: {np.median(np.abs(corr_values)):.4f}")
    print(f"    最大值: {np.max(np.abs(corr_values)):.4f}")
    print(f"    >0.7 比例: {(np.abs(corr_values) > 0.7).mean():.1%}")
    print(f"    >0.5 比例: {(np.abs(corr_values) > 0.5).mean():.1%}")
    print(f"    >0.3 比例: {(np.abs(corr_values) > 0.3).mean():.1%}")

    # Top 高相关对
    pairs = []
    for i in range(len(corr_matrix)):
        for j in range(i+1, len(corr_matrix)):
            pairs.append((corr_matrix.index[i], corr_matrix.columns[j], corr_matrix.iloc[i, j]))
    pairs.sort(key=lambda x: abs(x[2]), reverse=True)

    print(f"\n  Top 10 最高相关因子对:")
    for f1, f2, c in pairs[:10]:
        print(f"    {f1:28s} ↔ {f2:28s}  corr={c:+.4f}")

    # 聚类
    print(f"\n  层次聚类 ({args.n_clusters} 簇, Ward 方法)...")
    Z, df_cluster = hierarchical_clustering(corr_matrix, n_clusters=args.n_clusters)

    cluster_path = os.path.join(output_dir, "factor_clusters.csv")
    df_cluster.to_csv(cluster_path, index=False, encoding="utf-8-sig")
    print(f"  📄 聚类结果: {cluster_path}")

    # 读取评级数据（如果有）
    ranking_df = None
    if args.ranking and os.path.exists(args.ranking):
        ranking_df = pd.read_csv(args.ranking)
    else:
        default_ranking = os.path.join(output_dir, "factor_ranking.csv")
        if os.path.exists(default_ranking):
            ranking_df = pd.read_csv(default_ranking)

    # 独立因子
    print(f"\n  每簇代表因子（独立因子）:")
    df_indep = find_independent_factors(corr_matrix, df_cluster, ranking_df)
    for _, r in df_indep.iterrows():
        grade_str = f" [{r['rep_grade']}]" if pd.notna(r.get("rep_grade")) else ""
        icir_str = f" ICIR={r['rep_icir']:+.3f}" if pd.notna(r.get("rep_icir")) else ""
        print(f"    簇{r['cluster']:2d} ({r['n_factors']:2d} 因子): {r['representative']:28s}{grade_str}{icir_str}")

    indep_path = os.path.join(output_dir, "independent_factors.csv")
    df_indep.to_csv(indep_path, index=False, encoding="utf-8-sig")
    print(f"\n  📄 独立因子: {indep_path}")

    # 打印每簇详情
    print(f"\n  各簇详情:")
    for c in sorted(df_cluster["cluster"].unique()):
        factors = df_cluster[df_cluster["cluster"] == c]["factor"].tolist()
        print(f"\n  簇 {c}: {len(factors)} 个因子")
        for f in factors:
            cat = FACTOR_REGISTRY[f].category if f in FACTOR_REGISTRY else "?"
            print(f"    • {f:28s} ({cat})")

    print(f"\n  ✓ 分析完成")
    return corr_matrix, df_cluster, df_indep

if __name__ == "__main__":
    main()
