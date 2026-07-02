# -*- coding: utf-8 -*-
"""
recommender.py —— 因子组合重组与自适应推荐模块 (超额收益卡玛版)
========================================================================
1. 根据验证报告剔除失效的基础因子，保留 VALID / WARNING 因子。
2. 引入 searcher 挖掘出的优质实验因子填补空白。
3. 因子权重计算中保留 IC 真实正负方向号以用于信号翻转。
4. 对新旧组合开展平行回测比对 (基于超额卡玛比率 excess_calmar_ratio)。
5. 决策条件：新组合的超额卡玛比率 > 老组合，且新组合超额卡玛必须 > 0.50 门槛才准入。
"""

import os
import yaml
import numpy as np
import pandas as pd
from agent.backtester import run_portfolio_backtest, run_routed_portfolio_backtest

def load_config(config_path="agent/config.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def recommend_adaptive_portfolio(df_aligned, val_report, search_report, new_factors, weeks_to_test=104, config_path="agent/config.yaml"):
    """
    进行因子替换，运行新旧组合平行回测并输出最佳组合推荐。
    """
    config = load_config(config_path)
    base_pool = config["factors"]["base_pool"]
    special_cfg = config["special_boost"]
    special_factors = special_cfg["factors"]
    multiplier = special_cfg["multiplier"]
    
    # 1. 过滤老的基础因子池，挑出非失效 (VALID 或 WARNING) 的老因子
    active_base_factors = []
    old_raw_weights = {}
    
    for f in base_pool:
        if f not in val_report:
            continue
        details = val_report[f]
        if details["status"] in ["VALID", "WARNING"]:
            active_base_factors.append(f)
            # 老权重 (保留正负符号的 baseline_ic)
            old_raw_weights[f] = details["baseline_ic"]
            
    # 对老权重进行归一化 (保留真实方向符号)
    sum_old_abs = sum(abs(v) for v in old_raw_weights.values())
    if sum_old_abs > 1e-6:
        old_weights = {k: v / sum_old_abs for k, v in old_raw_weights.items()}
    else:
        old_weights = {f: 1.0 / len(active_base_factors) for f in active_base_factors}
        
    print(f"\nℹ️ [Recommender] 原基础活跃因子子集 ({len(active_base_factors)}个): {active_base_factors}")
    
    # 2. 组装新组合 = 支持自动进化 custom_new_factors 配置，或默认使用 6 因子核心防守池
    custom_factors = config.get("factors", {}).get("custom_new_factors", [])
    if custom_factors:
        new_portfolio_factors = custom_factors
    else:
        new_portfolio_factors = ["return_5d", "excess_return_20d", "profit_ratio_estimate", 
                                 "north_net_inflow_ratio", "volatility_20d", "turnover_rate"]
    print(f"ℹ️ [Recommender] 自适应重组新因子组合: {new_portfolio_factors}")
    
    # 3. 计算新组合的推荐权重 (保留真实方向符号)
    new_raw_weights = {}
    
    for f in new_portfolio_factors:
        # 获取其带符号的 IC 均值
        if f in base_pool:
            ic_val = val_report[f]["recent_ic"]
        else:
            ic_val = search_report[f]["mean_ic"]
            
        # 如果是正交特权因子，绝对值乘以加成系数，保留正负号
        if f in special_factors:
            ic_val = ic_val * multiplier
            
        new_raw_weights[f] = ic_val
        
    # 对新权重进行归一化 (绝对值求和，保留符号)
    sum_new_abs = sum(abs(v) for v in new_raw_weights.values())
    if sum_new_abs > 1e-6:
        new_weights = {k: v / sum_new_abs for k, v in new_raw_weights.items()}
    else:
        new_weights = {f: (1.0 / len(new_portfolio_factors)) for f in new_portfolio_factors}
        
    # 4. 执行平行回测验证绩效差异 (回测周数由入参决定：quick为104周，full为208周)
    print(f"\nℹ️ [Recommender] 正在运行原核心组合平行回测 (回测周数: {weeks_to_test}周)...")
    old_metrics, _ = run_portfolio_backtest(df_aligned, active_base_factors, old_weights, weeks_to_test, config_path)
    
    print(f"\nℹ️ [Recommender] 正在运行自适应重组组合平行回测 (回测周数: {weeks_to_test}周)...")
    new_metrics, _ = run_portfolio_backtest(df_aligned, new_portfolio_factors, new_weights, weeks_to_test, config_path)
    
    print(f"\nℹ️ [Recommender] 正在运行自适应多状态权重路由合并回测 (回测周数: {weeks_to_test}周)...")
    routed_metrics, _, route_summary = run_routed_portfolio_backtest(df_aligned, weeks_to_test, config_path)
    
    # 5. 比较超额卡玛比率进行推荐决策
    old_excess_calmar = old_metrics["excess_calmar_ratio"]
    new_excess_calmar = new_metrics["excess_calmar_ratio"]
    
    recommendation_triggered = False
    
    print(f"\n📈 [Comparison Summary (Alpha Excess Metrics)]:")
    print(f"   - 原老核心组合 ➡️ 超额卡玛: {old_excess_calmar:.4f} | 超额年化: {old_metrics['excess_annual_return']*100:.2f}% | 最大超额回撤: {old_metrics['excess_max_drawdown']*100:.2f}%")
    print(f"   - 自适应重组组合 ➡️ 超额卡玛: {new_excess_calmar:.4f} | 超额年化: {new_metrics['excess_annual_return']*100:.2f}% | 最大超额回撤: {new_metrics['excess_max_drawdown']*100:.2f}%")
    print(f"   - 多状态路由组合 ➡️ 超额卡玛: {routed_metrics['excess_calmar_ratio']:.4f} | 超额年化: {routed_metrics['excess_annual_return']*100:.2f}% | 最大超额回撤: {routed_metrics['excess_max_drawdown']*100:.2f}%")
    
    # 优化重构决策：新超额卡玛高于老组合，且必须 > 0.50 准入门槛才有效
    if new_excess_calmar > old_excess_calmar and new_excess_calmar > 0.50 and len(new_factors) > 0:
        recommendation_triggered = True
        decision_status = "RECOMMENDED_NEW_COMBINATION"
        decision_msg = f"🔥 【自适应重组成功】新重组因子组合的超额卡玛比率 {new_excess_calmar:.4f} 优于原组合且高于 0.5 门槛，强烈推荐替换！"
        print(f"\n{decision_msg}")
    else:
        decision_status = "RETAIN_ORIGINAL_COMBINATION"
        if len(new_factors) == 0:
            decision_msg = "⚖️ 【维持原样】未搜寻到有效的新实验因子，推荐继续沿用现有基础活跃因子组合。"
        elif new_excess_calmar <= old_excess_calmar:
            decision_msg = "⚖️ 【维持原样】新重组组合在超额卡玛绩效上未能显现优越性，沿用老组合。"
        else:
            decision_msg = f"⚖️ 【维持原样】新组合的超额卡玛为 {new_excess_calmar:.4f}，未达到 0.50 的有效准入门槛。"
        print(f"\n{decision_msg}")
        
    recommendation_report = {
        "decision_status": decision_status,
        "decision_message": decision_msg,
        "recommendation_triggered": recommendation_triggered,
        "old_portfolio": {
            "factors": active_base_factors,
            "weights": old_weights,
            "metrics": old_metrics
        },
        "new_portfolio": {
            "factors": new_portfolio_factors,
            "weights": new_weights,
            "metrics": new_metrics
        },
        "routed_portfolio": {
            "metrics": routed_metrics,
            "route_summary": route_summary
        }
    }
    
    return recommendation_report
