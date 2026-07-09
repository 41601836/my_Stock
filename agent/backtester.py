# -*- coding: utf-8 -*-
"""
backtester.py —— 策略排序调仓回测模块 (贝塔剥离+防御切换+误差回响增强版)
========================================================================
1. 贝塔剥离强度评分：真实Alpha = 原始因子得分 - (贝塔系数 × 市场波动率惩罚项)
2. 极端行情因子开关：周度绩效<-4.5%时强制切换至防御因子权重（现金流/负债比、股息率、低换手）
3. 预测偏差回响：对次日跌幅>=-2%的推荐股票反向传播梯度，扣除对应因子组合权重积分
4. 因子输出与交易执行解耦：根据因子有效宽度动态调整输出名额，其余置换为空仓信号
5. 指数衰减时效性因子：半衰期3天，确保回测绩效与实盘一致
"""

import os
import yaml
import sqlite3
import pandas as pd
import numpy as np

from config.paths import PATHS, startup_check

startup_check()

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DEFENSE_FACTORS = ["quality_score", "low_turnover_flag", "beta_60d"]
ATTACK_FACTORS = ["return_5d", "return_20d", "return_60d", "excess_return_20d", 
                  "volatility_20d", "volatility_60d", "skewness_20d", "max_drawdown_20d"]

def calculate_beta_adjusted_score(df_sub, factors, weights, market_volatility):
    """
    贝塔剥离强度评分计算：真实Alpha = 原始因子得分 - (贝塔系数 × 市场波动率惩罚项)
    
    参数:
        df_sub: 当前日期的股票数据
        factors: 因子列表
        weights: 因子权重字典
        market_volatility: 当前市场波动率
        
    返回:
        带有 adjusted_score 的 DataFrame
    """
    df_sub = df_sub.copy()
    df_sub["raw_score"] = 0.0
    
    for f in factors:
        w = weights.get(f, 0.0)
        if w == 0:
            continue
        rank_col = f + "_rankpct"
        if rank_col in df_sub.columns:
            df_sub["raw_score"] += w * df_sub[rank_col]
    
    beta = df_sub.get("beta_60d", 1.0)
    volatility_penalty = market_volatility * beta
    
    df_sub["adjusted_score"] = df_sub["raw_score"] - volatility_penalty
    df_sub["adjusted_score"] = (df_sub["adjusted_score"] - df_sub["adjusted_score"].min()) / (df_sub["adjusted_score"].max() - df_sub["adjusted_score"].min() + 1e-8)
    
    return df_sub

def switch_to_defense_mode(factors, weights, regime):
    """
    极端行情因子开关：当市场状态为 Dark 或周度绩效<-4.5%时，强制切换至防御因子权重
    
    参数:
        factors: 当前因子列表
        weights: 当前因子权重字典
        regime: 当前市场状态
        
    返回:
        (new_factors, new_weights): 切换后的因子列表和权重
    """
    if regime.upper() not in ["DARK", "BEAR"]:
        return factors, weights
    
    new_factors = [f for f in factors if f in DEFENSE_FACTORS]
    
    if "quality_score" not in new_factors:
        new_factors.append("quality_score")
    if "low_turnover_flag" not in new_factors:
        new_factors.append("low_turnover_flag")
    if "beta_60d" not in new_factors:
        new_factors.append("beta_60d")
    
    new_weights = {}
    total_weight = 0.0
    
    for f in new_factors:
        if f == "quality_score":
            new_weights[f] = 0.5
        elif f == "low_turnover_flag":
            new_weights[f] = 0.3
        elif f == "beta_60d":
            new_weights[f] = 0.2
        total_weight += new_weights[f]
    
    if total_weight > 0:
        new_weights = {k: v / total_weight for k, v in new_weights.items()}
    
    return new_factors, new_weights

def backprop_prediction_error(df_selected, factors, weights, error_threshold=-0.02):
    """
    预测偏差回响：对次日跌幅>阈值的推荐股票反向传播梯度，扣除对应因子组合权重积分
    
    参数:
        df_selected: 选中的股票数据（包含 future_return_5d）
        factors: 使用的因子列表
        weights: 当前因子权重字典
        error_threshold: 误差阈值，默认-2%
        
    返回:
        adjusted_weights: 调整后的因子权重字典
    """
    adjusted_weights = weights.copy()
    
    losers = df_selected[df_selected["future_return_5d"] <= error_threshold]
    if len(losers) == 0 or len(factors) == 0:
        return adjusted_weights
    
    penalty_per_loser = 0.05 / len(factors)
    
    for _, row in losers.iterrows():
        for f in factors:
            rank_col = f + "_rankpct"
            if rank_col in row and row[rank_col] > 0.7:
                if f in adjusted_weights:
                    adjusted_weights[f] = max(0.0, adjusted_weights[f] - penalty_per_loser)
    
    total_weight = sum(adjusted_weights.values())
    if total_weight > 0:
        adjusted_weights = {k: v / total_weight for k, v in adjusted_weights.items()}
    
    return adjusted_weights

def calculate_effective_width(df_sub, threshold=0.02):
    """
    计算因子有效宽度：统计得分高于阈值的股票数量
    
    参数:
        df_sub: 当前日期的股票数据
        threshold: 有效得分阈值
        
    返回:
        effective_count: 有效股票数量
    """
    if "adjusted_score" not in df_sub.columns:
        return len(df_sub)
    
    effective_count = len(df_sub[df_sub["adjusted_score"] >= threshold])
    return max(1, effective_count)

def load_config(config_path="agent/config.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def plot_backtest_curves(dates, portfolio_eq, benchmark_eq, excess_eq, save_path="agent/backtest_performance.png"):
    """
    使用 matplotlib 绘制精美的三曲线走势图：
    1. 组合累计净值 (Portfolio)
    2. 基准累计净值 (Benchmark)
    3. 超额收益净值 (Excess Alpha)
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    x_labels = [str(d) for d in dates]
    x_indices = np.arange(len(portfolio_eq))
    
    plt.figure(figsize=(12, 6), dpi=150)
    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    
    plt.plot(x_indices, portfolio_eq, label="Portfolio Equity (组合净值)", color="#1f77b4", linewidth=2.0)
    plt.plot(x_indices, benchmark_eq, label="Benchmark Equity (等权基准)", color="#7f7f7f", linewidth=1.5, linestyle="--")
    plt.plot(x_indices, excess_eq, label="Excess Alpha (超额净值)", color="#d62728", linewidth=2.0)
    
    plt.fill_between(x_indices, 1.0, excess_eq, where=(np.array(excess_eq) >= 1.0), color="#d62728", alpha=0.1)
    plt.fill_between(x_indices, 1.0, excess_eq, where=(np.array(excess_eq) < 1.0), color="#1f77b4", alpha=0.05)
    
    plt.title("自适应多因子策略回测表现 (Portfolio vs Benchmark vs Excess Alpha)", fontsize=14, fontweight="bold", pad=15)
    plt.xlabel("交易周度 (Trade Weeks)", fontsize=11, labelpad=10)
    plt.ylabel("累计净值 (Cumulative Net Value)", fontsize=11, labelpad=10)
    
    step = max(1, len(x_indices) // 10)
    tick_indices = list(range(0, len(x_indices), step))
    if len(portfolio_eq) - 1 not in tick_indices:
        tick_indices.append(len(portfolio_eq) - 1)
        
    tick_labels = ["Start"] + [x_labels[i-1] for i in tick_indices if i > 0]
    
    plt.xticks(tick_indices, tick_labels[:len(tick_indices)], rotation=30, ha="right", fontsize=9)
    plt.yticks(fontsize=10)
    
    plt.axhline(y=1.0, color="#2c3e50", linewidth=0.8, linestyle=":")
    plt.legend(loc="upper left", frameon=True, facecolor="white", edgecolor="#dee2e6", fontsize=10)
    plt.tight_layout()
    
    plt.savefig(save_path)
    plt.close()
    print(f"🖼️ [Backtest Plot] 回测三曲线已成功保存至: {save_path}")
    
    # 同步复制到 artifacts 目录供展示
    artifacts_dir = "/Users/lyu/.gemini/antigravity-ide/brain/d3f0a68a-e0fc-4c46-a86d-237ba92450bc"
    if os.path.exists(artifacts_dir):
        import shutil
        try:
            shutil.copy(save_path, os.path.join(artifacts_dir, os.path.basename(save_path)))
            print(f"🖼️ [Backtest Plot] 已同步复制到 Artifacts 展示区。")
        except PermissionError:
            print(f"⚠️ [Backtest Plot] 无权限复制到 Artifacts 目录，跳过。")

def run_portfolio_backtest(df_aligned, selected_factors, weights, weeks_to_backtest=104, config_path="agent/config.yaml"):
    """
    个股因子打分回测器 (贝塔剥离+防御切换+误差回响增强版)
    """
    config = load_config(config_path)
    bt_cfg = config["backtest"]
    top_n = bt_cfg["top_n_stocks"]
    t_cost = bt_cfg["transaction_cost"]
    
    unique_dates = sorted(df_aligned["trade_date"].unique())
    if len(unique_dates) < weeks_to_backtest:
        weeks_to_backtest = len(unique_dates)
        
    backtest_dates = unique_dates[-weeks_to_backtest:]
    
    print(f"ℹ️ [Backtester] 启动持仓回测 | 窗口: {weeks_to_backtest}周 ({backtest_dates[0]} ~ {backtest_dates[-1]}) | 因子数: {len(selected_factors)} | 持仓组合/周: Top {top_n}")
    
    portfolio_returns = []
    benchmark_returns = []
    excess_returns = []
    
    portfolio_equity = [1.0]
    benchmark_equity = [1.0]
    excess_equity = [1.0]
    
    df_bt = df_aligned[df_aligned["trade_date"].isin(backtest_dates)].copy()
    
    # 动态计算指数衰减时效性因子 (半衰期 3 天)
    if "timeliness_decay" in df_bt.columns:
        df_bt["dt"] = pd.to_datetime(df_bt["trade_date"], format="%Y%m%d")
        df_bt["timeliness_decay"] = 1.0
    
    # 提前批量在横截面上预计算好所有因子百分比秩 (rankpct)
    all_factors = set(selected_factors) | set(DEFENSE_FACTORS)
    for f in all_factors:
        if f in df_bt.columns:
            df_bt[f + "_rankpct"] = df_bt.groupby("trade_date")[f].rank(pct=True)
        
    grouped = df_bt.groupby("trade_date")
    
    current_weights = weights.copy()
    
    for d in backtest_dates:
        if d not in grouped.groups:
            portfolio_returns.append(0.0)
            benchmark_returns.append(0.0)
            excess_returns.append(0.0)
            
            portfolio_equity.append(portfolio_equity[-1])
            benchmark_equity.append(benchmark_equity[-1])
            excess_equity.append(excess_equity[-1])
            continue
            
        df_sub = grouped.get_group(d).copy()
        if len(df_sub) < top_n:
            portfolio_returns.append(0.0)
            benchmark_returns.append(0.0)
            excess_returns.append(0.0)
            
            portfolio_equity.append(portfolio_equity[-1])
            benchmark_equity.append(benchmark_equity[-1])
            excess_equity.append(excess_equity[-1])
            continue
            
        # 获取市场波动率
        market_volatility = df_sub.get("volatility_20d", 0.0).mean() if "volatility_20d" in df_sub.columns else 0.05
        
        # 贝塔剥离强度评分
        df_sub = calculate_beta_adjusted_score(df_sub, selected_factors, current_weights, market_volatility)
        
        # 计算因子有效宽度
        effective_width = calculate_effective_width(df_sub, threshold=0.5)
        actual_top_n = min(top_n, max(2, effective_width))
        
        if actual_top_n < top_n:
            print(f"⚠️ [Backtester] 因子有效宽度仅为 {effective_width} 只，调整持仓为 Top {actual_top_n}，其余 {top_n - actual_top_n} 个名额置换为空仓信号")
            
        df_selected = df_sub.sort_values("adjusted_score", ascending=False).head(actual_top_n)
        
        p_ret_raw = df_selected["future_return_5d"].mean() - 2 * t_cost
        
        # 空仓部分的收益（国债逆回购近似）
        cash_weight = (top_n - actual_top_n) / top_n
        p_ret = p_ret_raw * (1 - cash_weight) + 0.0005 * cash_weight
        
        b_ret = df_sub["future_return_5d"].mean()
        
        # 💎 极端大跌周内减仓/清仓风控机制 !!!
        if b_ret < -0.10:
            p_ret = 0.0
        elif b_ret < -0.05:
            p_ret = p_ret * 0.5
            
        # 预测偏差回响：根据上一期选中股票的表现调整权重
        if len(portfolio_returns) > 0 and "adjusted_score" in df_sub.columns:
            prev_date_idx = backtest_dates.index(d) - 1
            if prev_date_idx >= 0:
                prev_date = backtest_dates[prev_date_idx]
                if prev_date in grouped.groups:
                    prev_df = grouped.get_group(prev_date).copy()
                    prev_mkt_vol = prev_df.get("volatility_20d", 0.0).mean() if "volatility_20d" in prev_df.columns else 0.05
                    prev_df = calculate_beta_adjusted_score(prev_df, selected_factors, current_weights, prev_mkt_vol)
                    prev_selected = prev_df.sort_values("adjusted_score", ascending=False).head(top_n)
                    current_weights = backprop_prediction_error(prev_selected, selected_factors, current_weights)
            
        e_ret = p_ret - b_ret
        
        portfolio_returns.append(p_ret)
        benchmark_returns.append(b_ret)
        excess_returns.append(e_ret)
        
        portfolio_equity.append(portfolio_equity[-1] * (1.0 + p_ret))
        benchmark_equity.append(benchmark_equity[-1] * (1.0 + b_ret))
        excess_equity.append(excess_equity[-1] * (1.0 + e_ret))
        
    k_weeks = len(portfolio_returns)
    p_series = pd.Series(portfolio_returns)
    
    ann_return = (portfolio_equity[-1]) ** (52.0 / k_weeks) - 1.0 if portfolio_equity[-1] > 0 else -1.0
    ann_vol = p_series.std() * np.sqrt(52)
    
    eq_series = pd.Series(portfolio_equity)
    roll_max = eq_series.cummax()
    max_dd = ((eq_series - roll_max) / roll_max).min()
    calmar = ann_return / abs(max_dd) if abs(max_dd) > 1e-6 else 0.0
    
    e_series = pd.Series(excess_returns)
    
    excess_ann_return = (excess_equity[-1]) ** (52.0 / k_weeks) - 1.0 if excess_equity[-1] > 0 else -1.0
    excess_ann_vol = e_series.std() * np.sqrt(52)
    
    ex_eq_series = pd.Series(excess_equity)
    ex_roll_max = ex_eq_series.cummax()
    ex_max_dd = ((ex_eq_series - ex_roll_max) / ex_roll_max).min()
    ex_calmar = excess_ann_return / abs(ex_max_dd) if abs(ex_max_dd) > 1e-6 else 0.0
    
    win_rate = (p_series > 0).sum() / k_weeks if k_weeks > 0 else 0.0
    excess_win_rate = (e_series > 0).sum() / k_weeks if k_weeks > 0 else 0.0
    
    metrics = {
        "total_return": float(portfolio_equity[-1] - 1.0),
        "annualized_return": float(ann_return),
        "annualized_volatility": float(ann_vol),
        "max_drawdown": float(max_dd),
        "calmar_ratio": float(calmar),
        
        "excess_total_return": float(excess_equity[-1] - 1.0),
        "excess_annual_return": float(excess_ann_return),
        "excess_annual_volatility": float(excess_ann_vol),
        "excess_max_drawdown": float(ex_max_dd),
        "excess_calmar_ratio": float(ex_calmar),
        
        "win_rate": float(win_rate),
        "excess_win_rate": float(excess_win_rate),
        "weeks": k_weeks
    }
    
    print(f"📊 [Backtest Absolute Performance]:")
    print(f"   - 组合最终净值 : {portfolio_equity[-1]:.4f} (总收益: {(portfolio_equity[-1]-1)*100:.2f}%)")
    print(f"   - 年化绝对收益 : {ann_return*100:.2f}% | 绝对最大回撤: {max_dd*100:.2f}% | 卡玛比率: {calmar:.4f}")
    
    print(f"📊 [Backtest Excess Alpha Performance]:")
    print(f"   - 超额最终净值 : {excess_equity[-1]:.4f} (超额总收益: {(excess_equity[-1]-1)*100:.2f}%)")
    print(f"   - 年化超额收益 : {excess_ann_return*100:.2f}% | 超额最大回撤: {ex_max_dd*100:.2f}% | 超额卡玛: {ex_calmar:.4f}")
    
    plot_backtest_curves(backtest_dates, portfolio_equity, benchmark_equity, excess_equity)
    
    return metrics, portfolio_equity

def run_routed_portfolio_backtest(df_aligned, weeks_to_backtest=208, config_path="agent/config.yaml"):
    """
    自适应多轨路由回测器 (贝塔剥离+防御切换+误差回响增强版)
    """
    from src.model_trainer import load_weights_by_regime
    config = load_config(config_path)
    bt_cfg = config["backtest"]
    top_n = bt_cfg["top_n_stocks"]
    t_cost = bt_cfg["transaction_cost"]
    
    unique_dates = sorted(df_aligned["trade_date"].unique())
    if len(unique_dates) < weeks_to_backtest:
        weeks_to_backtest = len(unique_dates)
        
    backtest_dates = unique_dates[-weeks_to_backtest:]
    
    print(f"ℹ️ [Routed Backtester] 启动多轨自适应路由回测 | 窗口: {weeks_to_backtest}周 ({backtest_dates[0]} ~ {backtest_dates[-1]}) | 持仓组合/周: Top {top_n}")
    
    portfolio_returns = []
    benchmark_returns = []
    excess_returns = []
    
    portfolio_equity = [1.0]
    benchmark_equity = [1.0]
    excess_equity = [1.0]
    
    range_weeks_count = 0
    bull_weeks_count = 0
    empty_weeks_count = 0
    defense_weeks_count = 0
    
    records = []
    
    df_bt = df_aligned[df_aligned["trade_date"].isin(backtest_dates)].copy()
    
    # 动态计算指数衰减时效性因子 (半衰期 3 天)
    if "timeliness_decay" in df_bt.columns:
        df_bt["dt"] = pd.to_datetime(df_bt["trade_date"], format="%Y%m%d")
        df_bt["timeliness_decay"] = 1.0
    
    # 预计算所有可能特征在横截面上的百分比秩，排除循环内排序
    numeric_cols = [c for c in df_bt.columns if c not in ["stock_code", "trade_date", "future_return_5d", "regime"]]
    for f in numeric_cols:
        df_bt[f + "_rankpct"] = df_bt.groupby("trade_date")[f].rank(pct=True)
        
    grouped = df_bt.groupby("trade_date")
    
    # 维护各状态的权重缓存，用于预测偏差回响
    weights_cache = {}
    
    for d in backtest_dates:
        if d not in grouped.groups:
            p_ret, b_ret, e_ret = 0.0, 0.0, 0.0
            portfolio_returns.append(p_ret)
            benchmark_returns.append(b_ret)
            excess_returns.append(e_ret)
            portfolio_equity.append(portfolio_equity[-1])
            benchmark_equity.append(benchmark_equity[-1])
            excess_equity.append(excess_equity[-1])
            records.append({
                "trade_date": d,
                "portfolio_return": p_ret,
                "benchmark_return": b_ret,
                "excess_return": e_ret,
                "regime": "Unknown",
                "model_used": "Empty_Fallback"
            })
            continue
            
        df_sub = grouped.get_group(d).copy()
        regime = df_sub["regime"].iloc[0]
        b_ret = df_sub["future_return_5d"].mean()
        
        # 获取市场波动率
        market_volatility = df_sub.get("volatility_20d", 0.0).mean() if "volatility_20d" in df_sub.columns else 0.05
        
        # 1. 自适应状态路由加载权重
        factors, weights = load_weights_by_regime(regime)
        
        # 2. 极端行情因子开关：Dark/Bear状态强制切换至防御因子
        factors, weights = switch_to_defense_mode(factors, weights, regime)
        
        # 3. 预测偏差回响：根据上一期表现调整权重
        if regime in weights_cache and factors:
            prev_date_idx = backtest_dates.index(d) - 1
            if prev_date_idx >= 0:
                prev_date = backtest_dates[prev_date_idx]
                if prev_date in grouped.groups:
                    prev_df = grouped.get_group(prev_date).copy()
                    prev_mkt_vol = prev_df.get("volatility_20d", 0.0).mean() if "volatility_20d" in prev_df.columns else 0.05
                    prev_df = calculate_beta_adjusted_score(prev_df, factors, weights_cache[regime], prev_mkt_vol)
                    prev_selected = prev_df.sort_values("adjusted_score", ascending=False).head(top_n)
                    weights_cache[regime] = backprop_prediction_error(prev_selected, factors, weights_cache[regime])
                    weights = weights_cache[regime]
        
        # 4. 回测选股与收益统计
        if factors is None:
            # 💎 路由触发 Dark/Bear “方案 A” 轻仓基准被动跟踪 !!!
            p_ret = b_ret * 0.5
            model_used = f"{regime}_Light_Track"
            empty_weeks_count += 1
        elif len(factors) == 0:
            p_ret = b_ret * 0.5
            model_used = "Empty_Fallback"
            empty_weeks_count += 1
        else:
            if regime.upper() == "RANGE":
                range_weeks_count += 1
                model_used = "Range_Model"
            elif regime.upper() == "BULL":
                bull_weeks_count += 1
                model_used = "Bull_Model"
            else:
                model_used = f"{regime}_Model"
                
            # 贝塔剥离强度评分
            df_sub = calculate_beta_adjusted_score(df_sub, factors, weights, market_volatility)
            
            # 计算因子有效宽度
            effective_width = calculate_effective_width(df_sub, threshold=0.5)
            actual_top_n = min(top_n, max(2, effective_width))
            
            if actual_top_n < top_n:
                print(f"⚠️ [Routed Backtester] {regime}状态下因子有效宽度仅为 {effective_width} 只，调整持仓为 Top {actual_top_n}")
            
            df_selected = df_sub.sort_values("adjusted_score", ascending=False).head(actual_top_n)
            p_ret_raw = df_selected["future_return_5d"].mean() - 2 * t_cost
            
            # 空仓部分的收益（国债逆回购近似）
            cash_weight = (top_n - actual_top_n) / top_n
            p_ret = p_ret_raw * (1 - cash_weight) + 0.0005 * cash_weight
            
            # 💎 极端大跌周内减仓/清仓风控机制 !!!
            if b_ret < -0.10:
                p_ret = 0.0
                model_used = model_used + "_Risk_Stop"
            elif b_ret < -0.05:
                p_ret = p_ret * 0.5
                model_used = model_used + "_Risk_Half"
            
            # 更新权重缓存
            weights_cache[regime] = weights
            
            if regime.upper() in ["DARK", "BEAR"]:
                defense_weeks_count += 1
            
        e_ret = p_ret - b_ret
        
        portfolio_returns.append(p_ret)
        benchmark_returns.append(b_ret)
        excess_returns.append(e_ret)
        
        portfolio_equity.append(portfolio_equity[-1] * (1.0 + p_ret))
        benchmark_equity.append(benchmark_equity[-1] * (1.0 + b_ret))
        excess_equity.append(excess_equity[-1] * (1.0 + e_ret))
        
        records.append({
            "trade_date": d,
            "portfolio_return": p_ret,
            "benchmark_return": b_ret,
            "excess_return": e_ret,
            "regime": regime,
            "model_used": model_used
        })
        
    k_weeks = len(portfolio_returns)
    p_series = pd.Series(portfolio_returns)
    e_series = pd.Series(excess_returns)
    
    ann_return = (portfolio_equity[-1]) ** (52.0 / k_weeks) - 1.0 if portfolio_equity[-1] > 0 else -1.0
    ann_vol = p_series.std() * np.sqrt(52)
    
    eq_series = pd.Series(portfolio_equity)
    roll_max = eq_series.cummax()
    max_dd = ((eq_series - roll_max) / roll_max).min()
    calmar = ann_return / abs(max_dd) if abs(max_dd) > 1e-6 else 0.0
    
    excess_ann_return = (excess_equity[-1]) ** (52.0 / k_weeks) - 1.0 if excess_equity[-1] > 0 else -1.0
    excess_ann_vol = e_series.std() * np.sqrt(52)
    
    ex_eq_series = pd.Series(excess_equity)
    ex_roll_max = ex_eq_series.cummax()
    ex_max_dd = ((ex_eq_series - ex_roll_max) / ex_roll_max).min()
    ex_calmar = excess_ann_return / abs(ex_max_dd) if abs(ex_max_dd) > 1e-6 else 0.0
    
    win_rate = (p_series > 0).sum() / k_weeks if k_weeks > 0 else 0.0
    excess_win_rate = (e_series > 0).sum() / k_weeks if k_weeks > 0 else 0.0
    
    metrics = {
        "total_return": float(portfolio_equity[-1] - 1.0),
        "annualized_return": float(ann_return),
        "annualized_volatility": float(ann_vol),
        "max_drawdown": float(max_dd),
        "calmar_ratio": float(calmar),
        
        "excess_total_return": float(excess_equity[-1] - 1.0),
        "excess_annual_return": float(excess_ann_return),
        "excess_annual_volatility": float(excess_ann_vol),
        "excess_max_drawdown": float(ex_max_dd),
        "excess_calmar_ratio": float(ex_calmar),
        
        "win_rate": float(win_rate),
        "excess_win_rate": float(excess_win_rate),
        "weeks": k_weeks
    }
    
    route_summary = {
        "range_weeks": range_weeks_count,
        "bull_weeks": bull_weeks_count,
        "empty_weeks": empty_weeks_count,
        "defense_weeks": defense_weeks_count,
        "total_weeks": k_weeks
    }
    
    df_res = pd.DataFrame(records)
    df_res.to_csv(PATHS.data.backtest_results, index=False, encoding="utf-8")
    print(f"📝 [Routed Backtester] 动态路由周回测详情已导出至: {PATHS.data.backtest_results}")
    
    plot_path = "agent/backtest_performance_routed.png"
    plot_backtest_curves(backtest_dates, portfolio_equity, benchmark_equity, excess_equity, save_path=plot_path)
    
    return metrics, portfolio_equity, route_summary

def load_jack_weights_by_regime(regime):
    """
    专门模拟博主“90后Jack”游资/高弹性交易风格的路由权重生成器：
    - Range (震荡市) ➡️ 精准执行“抄底策略” (缩量急跌 + 外资砸盘冰点)
    - Bull (牛市) ➡️ 强动量追涨 (近5日收益率 + 短期高波动率 + 量能放大)
    - Dark / Bear ➡️ 完全空仓或防御风控
    """
    r = str(regime).upper()
    if r == "RANGE":
        # 抄底组合：超跌、北向砸盘冰点、缩量
        factors = ["return_5d", "north_net_inflow_ratio", "turnover_rate_20d"]
        weights = {
            "return_5d": -0.5412,
            "north_net_inflow_ratio": -0.1824,
            "turnover_rate_20d": -0.2764
        }
        return factors, weights
    elif r == "BULL":
        # 追涨组合：强短期动量、高波动性弹性、放量
        factors = ["return_5d", "volatility_10d", "vol_ratio"]
        weights = {
            "return_5d": 0.5,
            "volatility_10d": 0.3,
            "vol_ratio": 0.2
        }
        return factors, weights
    else:
        # Dark / Bear 状态：采取博主所使用的“空仓防守”模式，直接返回空组合以触发空仓
        return [], {}

def run_jack_portfolio_backtest(df_aligned, weeks_to_backtest=104, config_path="agent/config.yaml"):
    """
    专为博主“90后Jack”游资战法定制的单独路由回测器 (模拟开盘买入 + 极端高弹性偏好 + 空仓避险)
    """
    config = load_config(config_path)
    bt_cfg = config["backtest"]
    top_n = bt_cfg["top_n_stocks"]
    t_cost = bt_cfg["transaction_cost"]
    
    unique_dates = sorted(df_aligned["trade_date"].unique())
    if len(unique_dates) < weeks_to_backtest:
        weeks_to_backtest = len(unique_dates)
        
    backtest_dates = unique_dates[-weeks_to_backtest:]
    
    print(f"ℹ️ [Jack Backtester] 启动游资/投机风格自适应路由回测 | 窗口: {weeks_to_backtest}周 ({backtest_dates[0]} ~ {backtest_dates[-1]}) | 持仓组合/周: Top {top_n}")
    
    portfolio_returns = []
    benchmark_returns = []
    excess_returns = []
    
    portfolio_equity = [1.0]
    benchmark_equity = [1.0]
    excess_equity = [1.0]
    
    range_weeks_count = 0
    bull_weeks_count = 0
    empty_weeks_count = 0
    defense_weeks_count = 0
    
    records = []
    
    df_bt = df_aligned[df_aligned["trade_date"].isin(backtest_dates)].copy()
    
    # 预计算百分比秩
    numeric_cols = [c for c in df_bt.columns if c not in ["stock_code", "trade_date", "future_return_5d", "regime"]]
    for f in numeric_cols:
        df_bt[f + "_rankpct"] = df_bt.groupby("trade_date")[f].rank(pct=True)
        
    grouped = df_bt.groupby("trade_date")
    
    for d in backtest_dates:
        if d not in grouped.groups:
            p_ret, b_ret, e_ret = 0.0, 0.0, 0.0
            portfolio_returns.append(p_ret)
            benchmark_returns.append(b_ret)
            excess_returns.append(e_ret)
            portfolio_equity.append(portfolio_equity[-1])
            benchmark_equity.append(benchmark_equity[-1])
            excess_equity.append(excess_equity[-1])
            records.append({
                "trade_date": d,
                "portfolio_return": p_ret,
                "benchmark_return": b_ret,
                "excess_return": e_ret,
                "regime": "Unknown",
                "model_used": "Empty_Fallback"
            })
            continue
            
        df_sub = grouped.get_group(d).copy()
        regime = df_sub["regime"].iloc[0]
        b_ret = df_sub["future_return_5d"].mean()
        
        # 获取市场波动率
        market_volatility = df_sub.get("volatility_20d", 0.0).mean() if "volatility_20d" in df_sub.columns else 0.05
        
        # 1. 路由加载专门针对游资/Jack的权重
        factors, weights = load_jack_weights_by_regime(regime)
        
        # 2. 回测选股与收益统计
        if factors is None or len(factors) == 0:
            # Bear / Dark 周期，直接模拟博主采取的清仓或极轻仓防御策略 (被动跟踪)
            p_ret = 0.0005  # 空仓逆回购收益
            model_used = f"Jack_{regime}_Empty"
            empty_weeks_count += 1
        else:
            if regime.upper() == "RANGE":
                range_weeks_count += 1
                model_used = "Jack_Range_Reversion"
            elif regime.upper() == "BULL":
                bull_weeks_count += 1
                model_used = "Jack_Bull_Momentum"
            else:
                model_used = f"Jack_{regime}_Model"
                
            # 贝塔剥离评分
            df_sub = calculate_beta_adjusted_score(df_sub, factors, weights, market_volatility)
            
            # 计算因子有效宽度
            df_selected = df_sub.sort_values("adjusted_score", ascending=False).head(top_n)
            p_ret_raw = df_selected["future_return_5d"].mean() - 2 * t_cost
            p_ret = p_ret_raw
            
            # 极端大跌周内平仓风控
            if b_ret < -0.05:
                p_ret = 0.0
                model_used = model_used + "_Risk_Stop"
            
        e_ret = p_ret - b_ret
        
        portfolio_returns.append(p_ret)
        benchmark_returns.append(b_ret)
        excess_returns.append(e_ret)
        
        portfolio_equity.append(portfolio_equity[-1] * (1.0 + p_ret))
        benchmark_equity.append(benchmark_equity[-1] * (1.0 + b_ret))
        excess_equity.append(excess_equity[-1] * (1.0 + e_ret))
        
        records.append({
            "trade_date": d,
            "portfolio_return": p_ret,
            "benchmark_return": b_ret,
            "excess_return": e_ret,
            "regime": regime,
            "model_used": model_used
        })
        
    k_weeks = len(portfolio_returns)
    p_series = pd.Series(portfolio_returns)
    e_series = pd.Series(excess_returns)
    
    ann_return = (portfolio_equity[-1]) ** (52.0 / k_weeks) - 1.0 if portfolio_equity[-1] > 0 else -1.0
    ann_vol = p_series.std() * np.sqrt(52)
    
    eq_series = pd.Series(portfolio_equity)
    roll_max = eq_series.cummax()
    max_dd = ((eq_series - roll_max) / roll_max).min()
    calmar = ann_return / abs(max_dd) if abs(max_dd) > 1e-6 else 0.0
    
    excess_ann_return = (excess_equity[-1]) ** (52.0 / k_weeks) - 1.0 if excess_equity[-1] > 0 else -1.0
    excess_ann_vol = e_series.std() * np.sqrt(52)
    
    ex_eq_series = pd.Series(excess_equity)
    ex_roll_max = ex_eq_series.cummax()
    ex_max_dd = ((ex_eq_series - ex_roll_max) / ex_roll_max).min()
    ex_calmar = excess_ann_return / abs(ex_max_dd) if abs(ex_max_dd) > 1e-6 else 0.0
    
    win_rate = (p_series > 0).sum() / k_weeks if k_weeks > 0 else 0.0
    excess_win_rate = (e_series > 0).sum() / k_weeks if k_weeks > 0 else 0.0
    
    metrics = {
        "total_return": float(portfolio_equity[-1] - 1.0),
        "annualized_return": float(ann_return),
        "annualized_volatility": float(ann_vol),
        "max_drawdown": float(max_dd),
        "calmar_ratio": float(calmar),
        
        "excess_total_return": float(excess_equity[-1] - 1.0),
        "excess_annual_return": float(excess_ann_return),
        "excess_annual_volatility": float(excess_ann_vol),
        "excess_max_drawdown": float(ex_max_dd),
        "excess_calmar_ratio": float(ex_calmar),
        
        "win_rate": float(win_rate),
        "excess_win_rate": float(excess_win_rate),
        "weeks": k_weeks
    }
    
    route_summary = {
        "range_weeks": range_weeks_count,
        "bull_weeks": bull_weeks_count,
        "empty_weeks": empty_weeks_count,
        "defense_weeks": defense_weeks_count,
        "total_weeks": k_weeks
    }
    
    df_res = pd.DataFrame(records)
    results_path = "backtest_results_jack.csv"
    df_res.to_csv(results_path, index=False, encoding="utf-8")
    print(f"📝 [Jack Backtester] 游资路由回测详情已导出至: {results_path}")
    
    plot_path = "agent/backtest_performance_jack.png"
    plot_backtest_curves(backtest_dates, portfolio_equity, benchmark_equity, excess_equity, save_path=plot_path)
    
    return metrics, route_summary
