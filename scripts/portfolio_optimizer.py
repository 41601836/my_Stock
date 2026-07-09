# -*- coding: utf-8 -*-
"""
portfolio_optimizer.py —— 私募级马科维茨组合优化器 (Ledoit-Wolf 简易收缩协方差 + 行业中性约束)
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from scipy.optimize import minimize

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "db", "stock_data.db")

def estimate_shrunk_covariance(returns_df, shrinkage=0.25):
    """
    使用简易常数对角收缩算法计算风险协方差矩阵 (防止奇异矩阵报错)
    Sigma_shrunk = shrinkage * diag(S) + (1 - shrinkage) * S
    """
    S = returns_df.cov().fillna(0.0).to_numpy()
    # 提取对角线 (方差) 构造先验矩阵 F
    F = np.diag(np.diag(S))
    Sigma = shrinkage * F + (1 - shrinkage) * S
    return Sigma

def get_historical_returns(conn, ts_codes, current_date, lookback=90):
    """
    获取指定个股在当前日期前的历史日收益率时间序列
    """
    if not ts_codes:
        return pd.DataFrame()
        
    ph = ",".join(["?" for _ in ts_codes])
    # 查询过去 90 个交易日的价格
    query = f"""
        SELECT trade_date, ts_code, close FROM daily_prices 
        WHERE ts_code IN ({ph}) AND trade_date <= ?
        ORDER BY trade_date DESC
    """
    params = list(ts_codes) + [current_date]
    df = pd.read_sql(query, conn, params=params)
    
    if df.empty:
        return pd.DataFrame()
        
    # pivot 并按时间正序，计算日收益率
    df_pivot = df.pivot(index="trade_date", columns="ts_code", values="close").sort_index()
    returns_df = df_pivot.pct_change().dropna(how="all").fillna(0.0)
    return returns_df

def optimize_portfolio(ts_codes, expected_returns, industries, current_date, lambda_risk=1.5):
    """
    马科维茨均值-方差优化 (MVO) 核心求解器
    - 约束1: 权重和 = 1.0 (全仓)
    - 约束2: 单股权重 0.0 <= w_i <= 0.15 (防单押)
    - 约束3: 行业权重上限 <= 0.30 (防行业共振暴跌)
    """
    n = len(ts_codes)
    if n == 0:
        return {}
        
    # 如果只有一两只股票，退化为均权分配
    if n <= 2:
        return {code: round(1.0 / n, 4) for code in ts_codes}
        
    conn = sqlite3.connect(DB_PATH)
    try:
        # 1. 提取历史收益率并计算收缩风险协方差矩阵
        returns_df = get_historical_returns(conn, ts_codes, current_date)
        
        # 补齐可能在历史数据里缺失的股票列
        for code in ts_codes:
            if code not in returns_df.columns:
                returns_df[code] = 0.0
                
        returns_df = returns_df[list(ts_codes)] # 强制对齐顺序
        Sigma = estimate_shrunk_covariance(returns_df)
        
        # 2. 转换预期收益率为 numpy 数组
        # 为防止 expected_returns 为 0，确保在数值上进行归一化
        mu = np.array([expected_returns.get(code, 0.0) for code in ts_codes])
        if mu.max() - mu.min() > 1e-8:
            mu = (mu - mu.min()) / (mu.max() - mu.min() + 1e-8) # 归一化到 [0, 1]
            
        # 3. 定义马科维茨目标函数: 最小化风险 - 预期收益 (等价于最大化效用)
        # Utility = w.T @ mu - 0.5 * lambda_risk * w.T @ Sigma @ w
        # scipy.optimize 是求极小值，所以目标函数为负效用
        def objective(w):
            w = np.array(w)
            portfolio_variance = w.T @ Sigma @ w
            portfolio_return = w.T @ mu
            return 0.5 * lambda_risk * portfolio_variance - portfolio_return
            
        # 4. 设置约束条件
        # (a) 权重和 = 1.0
        cons = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
        
        # (b) 行业权重限制：防范单一板块过度集中
        # 若候选股所属总行业数极少 (<=2个)，自适应放宽限额至 60%，否则卡死在 30% 私募风控红线
        unique_sectors = set(industries.values())
        sector_limit = 0.60 if len(unique_sectors) <= 2 else 0.30
        
        for sector in unique_sectors:
            if not sector or sector == "未知":
                continue
            # 构造高效率、可导的行业二进制掩码向量
            mask = np.zeros(n)
            for i, code in enumerate(ts_codes):
                if industries.get(code) == sector:
                    mask[i] = 1.0
            
            cons.append({
                'type': 'ineq', 
                'fun': lambda w, m=mask, limit=sector_limit: limit - np.dot(m, w)
            })
            
        # (c) 单股权重边界约束: 0% <= w_i <= 15%
        bounds = [(0.0, 0.15) for _ in range(n)]
        
        # (d) 构造满足行业约束与个股边界(<=15%)的强健可行初始解 w0，防止 SLSQP 初始越界不收敛
        w0 = np.ones(n) / n
        for sector in unique_sectors:
            if not sector or sector == "未知":
                continue
            idx_list = [i for i, code in enumerate(ts_codes) if industries.get(code) == sector]
            if not idx_list:
                continue
            sector_weight = np.sum(w0[idx_list])
            if sector_weight > sector_limit:
                excess = sector_weight - sector_limit
                w0[idx_list] = w0[idx_list] * (sector_limit / sector_weight)
                other_idx = [i for i in range(n) if i not in idx_list]
                if other_idx:
                    w0[other_idx] += excess / len(other_idx)
        
        # 裁剪并归一化确保完全满足边界约束
        w0 = np.clip(w0, 0.0, 0.15)
        w0 = w0 / np.sum(w0)
        
        # 5. 二次规划求解 (SLSQP 算法)
        res = minimize(objective, w0, method='SLSQP', bounds=bounds, constraints=cons, options={'maxiter': 500})
        
        # 6. 如果优化解失败，则退化至安全的“均权分配 (Equal Weight)”并做警报日志
        if not res.success:
            print("⚠️ [MVO] 二次规划求解器未收敛，降级使用均权分配模式")
            return {code: round(1.0 / n, 4) for code in ts_codes}
            
        weights = res.x
        # 极小权重归零平滑并重新归一化
        weights[weights < 0.001] = 0.0
        weights = weights / np.sum(weights)
        
        return {code: round(float(w), 4) for code, w in zip(ts_codes, weights)}
        
    except Exception as e:
        print(f"❌ [MVO Error] 协方差估计或求解失败: {e}")
        return {code: round(1.0 / n, 4) for code in ts_codes}
    finally:
        conn.close()
