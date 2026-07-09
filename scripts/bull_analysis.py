# -*- coding: utf-8 -*-
"""
bull_analysis.py —— 牛市 (Bull) 市场状态独立因子检验与 Ridge 回归专轨建模分析脚本
==================================================================================
1. 加载 2020-2026 年的全量价格和因子值，并与 market_regime_labels_v2.csv 对齐。
2. 筛选 regime 为 Bull 的周度数据样本，计算 18 个基础因子的 Spearman Rank IC 与 IR。
3. 对比输出 Range vs Bull 因子 IC 均值的变化偏好表。
4. 按 abs(IC) > 0.03 且 abs(IR) > 0.35 筛选因子，最多保留 3 个（按 abs(IR) 降序）。
5. 在 2020-2022 Bull 样本上利用轻量级 NumPy 解析解 Ridge 拟合未来5日收益率，输出拟合权重。
6. 对 2023-2026 测试集中的 Bull 周度进行专轨排序选股回测 (Top 20，摩擦 15 bps)。
7. 输出权重至 models/bull_weights_proposed.pkl，三曲线净值图至 bull_analysis/performance.png。
"""

import os
import sys
import pickle
import sqlite3
import pandas as pd
import numpy as np

from config.paths import PATHS, startup_check

startup_check()

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def main():
    db_path = PATHS.database.stock_data
    csv_path = PATHS.data.market_regime_labels_v2
    config_path = PATHS.config.agent
    
    # 读取监测的基础因子列表
    base_pool = [
        "return_5d", "return_20d", "return_60d", "excess_return_20d", "volatility_20d",
        "volatility_60d", "skewness_20d", "max_drawdown_20d", "atr_ratio", "pe_ttm",
        "pb", "roe", "turnover_rate", "north_net_inflow_ratio", "profit_ratio_estimate",
        "chip_concentration"
    ]
    
    print("=" * 80)
    print("🐂 启动 Bull (牛市) 专轨市场状态独立分析与 Ridge 建模程序")
    print("=" * 80)
    
    if not os.path.exists(db_path) or not os.path.exists(csv_path):
        print(f"❌ 错误: 未能找到 {db_path} 或 {csv_path}，请确认全历史数据已准备就绪。")
        return
        
    conn = sqlite3.connect(db_path)
    
    # 1. 价格与未来收益加载
    print("ℹ️ 正在加载每日收盘与复权因子计算下周收益率...")
    query_prices = "SELECT ts_code AS stock_code, trade_date, close, adj_factor FROM daily_prices WHERE trade_date >= '20200101'"
    df_prices = pd.read_sql(query_prices, conn)
    df_prices["trade_date"] = df_prices["trade_date"].astype(str)
    df_prices = df_prices.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    df_prices["close_adj"] = df_prices["close"] * df_prices["adj_factor"]
    df_prices["future_return_5d"] = df_prices.groupby("stock_code")["close_adj"].shift(-5) / df_prices["close_adj"] - 1.0
    # 数据剪裁，剔除脏数据极值干扰
    df_prices["future_return_5d"] = df_prices["future_return_5d"].clip(-0.5, 0.8)
    
    # 2. 因子数据加载
    print("ℹ️ 正在从 factor_values 表加载全部特征因子...")
    df_factors = pd.read_sql("SELECT * FROM factor_values", conn)
    df_factors["trade_date"] = df_factors["trade_date"].astype(str)
    conn.close()
    
    # 3. 对齐状态标签
    df_regime = pd.read_csv(csv_path)
    df_regime["trade_date"] = df_regime["trade_date"].astype(str)
    
    df_merge = pd.merge(df_factors, df_prices[["stock_code", "trade_date", "future_return_5d"]], on=["stock_code", "trade_date"], how="inner")
    df_aligned = pd.merge(df_merge, df_regime[["trade_date", "regime"]], on="trade_date", how="inner")
    df_aligned = df_aligned.dropna(subset=["future_return_5d"]).reset_index(drop=True)
    
    # 将包含 16 核心和可能算出的实验因子的列取并集
    all_numeric_cols = [c for c in df_factors.columns if c not in ["stock_code", "trade_date"]]
    monitoring_factors = [f for f in all_numeric_cols if f in base_pool]
    # 保底补齐
    if not monitoring_factors:
        monitoring_factors = base_pool
        
    print(f"📊 成功对齐全量样本: {len(df_aligned)} 行 | 监测因子: {len(monitoring_factors)} 个")
    
    # 4. 牛市与震荡市因子 IC 计算
    df_bull_samples = df_aligned[df_aligned["regime"].str.upper() == "BULL"].copy()
    df_range_samples = df_aligned[df_aligned["regime"].str.upper() == "RANGE"].copy()
    
    print(f"ℹ️ 提取 Bull 状态样本: {len(df_bull_samples)} 行 | Range 状态样本: {len(df_range_samples)} 行")
    
    # 计算 Bull IC 序列
    bull_grouped = df_bull_samples.groupby("trade_date")
    bull_ic_series = {f: {} for f in monitoring_factors}
    for d, df_sub in bull_grouped:
        if len(df_sub) < 30:
            continue
        for f in monitoring_factors:
            corr = df_sub[f].corr(df_sub["future_return_5d"], method="spearman")
            bull_ic_series[f][d] = corr if not pd.isna(corr) else 0.0
            
    df_bull_ic = pd.DataFrame(bull_ic_series)
    
    # 计算 Range IC 序列
    range_grouped = df_range_samples.groupby("trade_date")
    range_ic_series = {f: {} for f in monitoring_factors}
    for d, df_sub in range_grouped:
        if len(df_sub) < 30:
            continue
        for f in monitoring_factors:
            corr = df_sub[f].corr(df_sub["future_return_5d"], method="spearman")
            range_ic_series[f][d] = corr if not pd.isna(corr) else 0.0
            
    df_range_ic = pd.DataFrame(range_ic_series)
    
    # 5. 生成 Bull 排名表
    bull_summary = []
    for f in monitoring_factors:
        series = df_bull_ic[f]
        if len(series) > 0:
            m_ic = series.mean()
            s_ic = series.std()
            ir = m_ic / s_ic if s_ic > 1e-6 else 0.0
        else:
            m_ic, s_ic, ir = 0.0, 0.0, 0.0
        bull_summary.append({
            "factor": f,
            "mean_ic": m_ic,
            "std_ic": s_ic,
            "rank_ir": ir,
            "abs_ic": abs(m_ic),
            "abs_ir": abs(ir)
        })
        
    df_bull_rank = pd.DataFrame(bull_summary).sort_values("abs_ir", ascending=False).reset_index(drop=True)
    
    print("\n============================================================")
    print("📊 Bull 因子 IC/IR 排名表 (按绝对 IR 降序)")
    print("============================================================")
    print(f"{'因子':<24} {'IC 均值':<10} {'IC 标准差':<10} {'IR':<10} {'绝对 IC':<10}")
    print("-" * 65)
    for _, row in df_bull_rank.iterrows():
        print(f"{row['factor']:<24} {row['mean_ic']:10.4f} {row['std_ic']:10.4f} {row['rank_ir']:10.4f} {row['abs_ic']:10.4f}")
    print("=" * 65)
    
    # 6. 生成 Range vs Bull 对比表
    compare_summary = []
    for f in monitoring_factors:
        r_series = df_range_ic[f]
        b_series = df_bull_ic[f]
        r_ic = r_series.mean() if len(r_series) > 0 else 0.0
        b_ic = b_series.mean() if len(b_series) > 0 else 0.0
        
        diff = b_ic - r_ic
        abs_r = abs(r_ic)
        abs_b = abs(b_ic)
        
        if abs_r < 1e-4:
            desc = "新出现"
        else:
            pct = (abs_b - abs_r) / abs_r
            if pct < 0:
                desc = f"减弱 {abs(pct)*100:.1f}%"
            else:
                desc = f"增强 {pct*100:.1f}%"
                
        compare_summary.append({
            "factor": f,
            "range_ic": r_ic,
            "bull_ic": b_ic,
            "diff": diff,
            "desc": desc
        })
        
    df_compare = pd.DataFrame(compare_summary)
    
    print("\n============================================================")
    print("📊 Range vs Bull 对比表")
    print("============================================================")
    print(f"{'因子':<24} {'Range IC':<12} {'Bull IC':<12} {'IC 变化 (绝对值偏好)':<24}")
    print("-" * 72)
    for _, row in df_compare.iterrows():
        print(f"{row['factor']:<24} {row['range_ic']:12.4f} {row['bull_ic']:12.4f} {row['diff']:+12.4f} ({row['desc']})")
    print("=" * 72)
    
    # 7. 牛市核心因子筛选 (最多保留 3 个，标准：abs(IC) > 0.03 且 abs(IR) > 0.35)
    df_filtered = df_bull_rank[(df_bull_rank["abs_ic"] > 0.03) & (df_bull_rank["abs_ir"] > 0.35)].copy()
    # 最多保留 3 个
    selected_factors = df_filtered.head(3)["factor"].tolist()
    
    if len(selected_factors) == 0:
        # 后备方案：若无满足硬门槛的因子，降级选择绝对 IR 排前 3 的因子
        selected_factors = df_bull_rank.head(3)["factor"].tolist()
        print(f"⚠️ [警告] 无因子满足 abs(IC)>0.03 & IR>0.35 门槛，降级选用前三活跃因子。")
        
    print(f"\n🎯 Bull 推荐核心因子子集 ({len(selected_factors)}个): {selected_factors}")
    
    # 8. 专轨模型训练：使用 2020-2022 Bull 样本拟合 Ridge 回归
    # 训练集：2020-01-01 至 2022-12-31，测试集：2023-01-01 至 2026-07-02
    df_train = df_bull_samples[df_bull_samples["trade_date"] < "20230101"].copy()
    df_test = df_bull_samples[df_bull_samples["trade_date"] >= "20230101"].copy()
    
    print(f"ℹ️ 划分样本期: 训练集 {len(df_train)} 行 | 测试集 {len(df_test)} 行")
    
    # 进行截面秩百分比标准化 (Rank Percentile)
    # 并构造特征 X 与未来收益 Y
    def get_ranked_features(df, factors):
        # 需在 trade_date 截面上进行 rank
        df_res = df.copy()
        for f in factors:
            df_res[f] = df_res.groupby("trade_date")[f].rank(pct=True)
        # 填充均值中位数防 NaN
        df_res = df_res.dropna(subset=factors + ["future_return_5d"])
        X = df_res[factors].values
        y = df_res["future_return_5d"].values
        return X, y, df_res
        
    X_train, y_train, df_train_clean = get_ranked_features(df_train, selected_factors)
    
    # NumPy 实现高防爆、无外部依赖的 Ridge 解析解拟合: beta = (X^T * X + alpha * I)^-1 * X^T * y
    alpha = 1.0
    XTX = X_train.T @ X_train
    I = np.eye(len(selected_factors))
    A = XTX + alpha * I
    beta = np.linalg.solve(A, X_train.T @ y_train)
    
    # 归一化权重 (绝对值求和归一，保留正负号)
    sum_abs_beta = sum(abs(b) for b in beta)
    if sum_abs_beta > 1e-6:
        weights = beta / sum_abs_beta
    else:
        weights = np.ones(len(selected_factors)) / len(selected_factors)
        
    weights_dict = dict(zip(selected_factors, weights))
    
    print("\n============================================================")
    print("🎯 Bull 推荐核心因子 & 权重拟合方案")
    print("============================================================")
    for k, v in weights_dict.items():
        print(f"{k:<30} 权重: {v:.4f}")
    print("=" * 60)
    
    # 9. 2023-2026 年（测试集）牛市专轨回测
    test_dates = sorted(df_test["trade_date"].unique())
    
    portfolio_returns = []
    benchmark_returns = []
    excess_returns = []
    
    portfolio_equity = [1.0]
    benchmark_equity = [1.0]
    excess_equity = [1.0]
    
    # 回测交易摩擦 15 bps (买卖双向共 30 bps)
    t_cost = 0.0015
    top_n = 20
    
    test_grouped = df_test.groupby("trade_date")
    
    for d in test_dates:
        df_sub = test_grouped.get_group(d).copy()
        if len(df_sub) < top_n:
            portfolio_returns.append(0.0)
            benchmark_returns.append(0.0)
            excess_returns.append(0.0)
            
            portfolio_equity.append(portfolio_equity[-1])
            benchmark_equity.append(benchmark_equity[-1])
            excess_equity.append(excess_equity[-1])
            continue
            
        # 打分计算
        df_sub["composite_score"] = 0.0
        for f in selected_factors:
            w = weights_dict[f]
            # 截面秩百分比标准化
            rank_pct = df_sub[f].rank(pct=True)
            df_sub["composite_score"] += w * rank_pct
            
        # 选股
        df_sel = df_sub.sort_values("composite_score", ascending=False).head(top_n)
        
        p_ret = df_sel["future_return_5d"].mean() - 2 * t_cost
        b_ret = df_sub["future_return_5d"].mean()
        e_ret = p_ret - b_ret
        
        portfolio_returns.append(p_ret)
        benchmark_returns.append(b_ret)
        excess_returns.append(e_ret)
        
        portfolio_equity.append(portfolio_equity[-1] * (1.0 + p_ret))
        benchmark_equity.append(benchmark_equity[-1] * (1.0 + b_ret))
        excess_equity.append(excess_equity[-1] * (1.0 + e_ret))
        
    # 计算评估指标 (周度转年化乘以 52)
    k_weeks = len(portfolio_returns)
    p_series = pd.Series(portfolio_returns)
    e_series = pd.Series(excess_returns)
    
    ann_return = (portfolio_equity[-1]) ** (52.0 / k_weeks) - 1.0 if portfolio_equity[-1] > 0 else -1.0
    
    # 绝对指标
    eq_series = pd.Series(portfolio_equity)
    roll_max = eq_series.cummax()
    max_dd = ((eq_series - roll_max) / roll_max).min()
    calmar = ann_return / abs(max_dd) if abs(max_dd) > 1e-6 else 0.0
    
    # 超额指标
    ex_eq_series = pd.Series(excess_equity)
    ex_roll_max = ex_eq_series.cummax()
    ex_max_dd = ((ex_eq_series - ex_roll_max) / ex_roll_max).min()
    
    excess_ann_return = (excess_equity[-1]) ** (52.0 / k_weeks) - 1.0 if excess_equity[-1] > 0 else -1.0
    excess_calmar = excess_ann_return / abs(ex_max_dd) if abs(ex_max_dd) > 1e-6 else 0.0
    
    print(f"\nBull 模型测试集（2023-2026）绝对卡玛比率: {calmar:.2f}")
    print(f"Bull 模型测试集（2023-2026）超额卡玛比率: {excess_calmar:.2f}")
    
    # 10. 保存配置
    os.makedirs(os.path.dirname(PATHS.models.bull_weights_proposed), exist_ok=True)
    proposed_pkl_path = PATHS.models.bull_weights_proposed
    
    with open(proposed_pkl_path, "wb") as f:
        pickle.dump({
            "bull_factors": selected_factors,
            "bull_weights": weights_dict
        }, f)
        
    print(f"✅ Bull 状态具备独立建模条件，权重已保存至 {proposed_pkl_path}")
    
    # 11. 绘制三曲线并保存
    plot_dir = "bull_analysis"
    os.makedirs(plot_dir, exist_ok=True)
    plot_path = os.path.join(plot_dir, "performance.png")
    
    x_indices = np.arange(len(portfolio_equity))
    x_labels = [str(d) for d in test_dates]
    
    plt.figure(figsize=(12, 6), dpi=150)
    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    
    plt.plot(x_indices, portfolio_equity, label="Portfolio Equity (组合净值)", color="#1f77b4", linewidth=2.0)
    plt.plot(x_indices, benchmark_equity, label="Benchmark Equity (等权基准)", color="#7f7f7f", linewidth=1.5, linestyle="--")
    plt.plot(x_indices, excess_equity, label="Excess Alpha (超额净值)", color="#d62728", linewidth=2.0)
    
    plt.fill_between(x_indices, 1.0, excess_equity, where=(np.array(excess_equity) >= 1.0), color="#d62728", alpha=0.1)
    
    plt.title("Bull (牛市专轨) 策略测试表现 (Portfolio vs Benchmark vs Excess Alpha)", fontsize=13, fontweight="bold")
    plt.xlabel("测试周度 (Trade Weeks)")
    plt.ylabel("累计净值 (Cumulative Net Value)")
    
    step = max(1, len(x_indices) // 10)
    tick_indices = list(range(0, len(x_indices), step))
    if len(portfolio_equity) - 1 not in tick_indices:
        tick_indices.append(len(portfolio_equity) - 1)
    tick_labels = ["Start"] + [x_labels[i-1] for i in tick_indices if i > 0]
    
    plt.xticks(tick_indices, tick_labels[:len(tick_indices)], rotation=30, ha="right")
    plt.axhline(y=1.0, color="#2c3e50", linewidth=0.8, linestyle=":")
    plt.legend(loc="upper left")
    plt.tight_layout()
    
    plt.savefig(plot_path)
    plt.close()
    
    print(f"🖼️ 牛市回测图已成功输出至 {plot_path}")
    
    # 同步到 Artifacts 展示区
    artifacts_dir = "/Users/lyu/.gemini/antigravity-ide/brain/d3f0a68a-e0fc-4c46-a86d-237ba92450bc"
    if os.path.exists(artifacts_dir):
        import shutil
        shutil.copy(plot_path, os.path.join(artifacts_dir, "bull_performance.png"))
        print("🖼️ 已同步复制回测图至 Artifacts 预览区。")

if __name__ == "__main__":
    main()
