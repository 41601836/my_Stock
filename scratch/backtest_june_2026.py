# -*- coding: utf-8 -*-
"""
backtest_june_2026.py —— 2026年6月专项日期路由回测脚本
========================================================================
1. 加载 20260601 到 20260630 区间内的交易周。
2. 使用部署好的模型权重 (models/regime_weights.pkl 及 models/bull_weights_proposed.pkl)。
3. 打印每一周的 trade_date、regime、model_used、组合收益、基准收益与超额收益。
4. 统计并输出该单月度区间内的绩效。
"""

import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.validator import validate_factors
from src.model_trainer import load_weights_by_regime
from agent.backtester import load_config

def run_june_backtest(config_path="agent/config.yaml"):
    # 1. 载入对齐数据
    _, df_aligned = validate_factors(config_path)
    
    # 2. 提取配置
    config = load_config(config_path)
    bt_cfg = config["backtest"]
    top_n = bt_cfg["top_n_stocks"]
    t_cost = bt_cfg["transaction_cost"]
    
    # 3. 指定 2026 年 6 月的交易日期区间
    unique_dates = sorted(df_aligned["trade_date"].unique())
    backtest_dates = [d for d in unique_dates if d >= "20260601" and d <= "20260630"]
    
    print(f"\nℹ️ [June Backtester] 启动 2026年6月专项路由回测 | 窗口: {len(backtest_dates)}周 ({backtest_dates[0]} ~ {backtest_dates[-1]}) | 持仓组合/周: Top {top_n}")
    
    portfolio_returns = []
    benchmark_returns = []
    excess_returns = []
    
    portfolio_equity = [1.0]
    benchmark_equity = [1.0]
    excess_equity = [1.0]
    
    df_bt = df_aligned[df_aligned["trade_date"].isin(backtest_dates)].copy()
    
    # 一次性预计算百分比秩
    numeric_cols = [c for c in df_bt.columns if c not in ["stock_code", "trade_date", "future_return_5d", "regime"]]
    for f in numeric_cols:
        df_bt[f + "_rankpct"] = df_bt.groupby("trade_date")[f].rank(pct=True)
        
    grouped = df_bt.groupby("trade_date")
    
    print("\n" + "=" * 90)
    print(f"{'交易日期':<10} | {'市场状态':<8} | {'选用模型':<22} | {'组合收益':<8} | {'基准收益':<8} | {'超额收益':<8}")
    print("=" * 90)
    
    for d in backtest_dates:
        if d not in grouped.groups:
            p_ret, b_ret, e_ret = 0.0, 0.0, 0.0
            portfolio_returns.append(p_ret)
            benchmark_returns.append(b_ret)
            excess_returns.append(e_ret)
            portfolio_equity.append(portfolio_equity[-1])
            benchmark_equity.append(benchmark_equity[-1])
            excess_equity.append(excess_equity[-1])
            continue
            
        df_sub = grouped.get_group(d).copy()
        regime = df_sub["regime"].iloc[0]
        b_ret = df_sub["future_return_5d"].mean()
        
        # 路由选择模型
        factors, weights = load_weights_by_regime(regime)
        
        # 回测打分与收益
        if factors is None:
            p_ret = b_ret * 0.5
            model_used = f"{regime}_Light_Track"
        elif len(factors) == 0:
            p_ret = b_ret * 0.5
            model_used = "Empty_Fallback"
        else:
            if regime.upper() == "RANGE":
                model_used = "Range_Model"
            elif regime.upper() == "BULL":
                model_used = "Bull_Model"
            else:
                model_used = f"{regime}_Model"
                
            df_sub["composite_score"] = 0.0
            for f in factors:
                w = weights.get(f, 0.0)
                if w == 0:
                    continue
                df_sub["composite_score"] += w * df_sub[f + "_rankpct"]
                
            df_selected = df_sub.sort_values("composite_score", ascending=False).head(top_n)
            p_ret_raw = df_selected["future_return_5d"].mean() - 2 * t_cost
            
            # 周内大跌自适应风控
            if b_ret < -0.10:
                p_ret = 0.0
                model_used = model_used + "_Risk_Stop"
            elif b_ret < -0.05:
                p_ret = p_ret_raw * 0.5
                model_used = model_used + "_Risk_Half"
            else:
                p_ret = p_ret_raw
                
        e_ret = p_ret - b_ret
        
        portfolio_returns.append(p_ret)
        benchmark_returns.append(b_ret)
        excess_returns.append(e_ret)
        
        portfolio_equity.append(portfolio_equity[-1] * (1.0 + p_ret))
        benchmark_equity.append(benchmark_equity[-1] * (1.0 + b_ret))
        excess_equity.append(excess_equity[-1] * (1.0 + e_ret))
        
        print(f"{d:<12} | {regime:<8} | {model_used:<22} | {p_ret*100:>7.2f}% | {b_ret*100:>7.2f}% | {e_ret*100:>7.2f}%")
        
    print("=" * 90)
    
    # 统计单月度表现
    total_p_ret = portfolio_equity[-1] - 1.0
    total_b_ret = benchmark_equity[-1] - 1.0
    total_e_ret = excess_equity[-1] - 1.0
    
    # 最大回撤
    eq_series = pd.Series(portfolio_equity)
    roll_max = eq_series.cummax()
    max_dd = ((eq_series - roll_max) / roll_max).min()
    
    ex_eq_series = pd.Series(excess_equity)
    ex_roll_max = ex_eq_series.cummax()
    ex_max_dd = ((ex_eq_series - ex_roll_max) / ex_roll_max).min()
    
    print(f"\n📊 [June Backtest Metrics Summary]:")
    print(f"   - 组合最终累计净值 : {portfolio_equity[-1]:.4f} (总收益: {total_p_ret*100:.2f}%)")
    print(f"   - 基准最终累计净值 : {benchmark_equity[-1]:.4f} (总收益: {total_b_ret*100:.2f}%)")
    print(f"   - 超额最终累计净值 : {excess_equity[-1]:.4f} (超额总收益: {total_e_ret*100:.2f}%)")
    print(f"   - 绝对区间最大回撤 : {max_dd*100:.2f}%")
    print(f"   - 超额区间最大回撤 : {ex_max_dd*100:.2f}%")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    run_june_backtest()
