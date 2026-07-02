# -*- coding: utf-8 -*-
"""
cross_verify.py —— 多因子计算交叉验证与模型标签对齐测试
========================================================================
1. 从 SQLite 数据库中读取宁德时代、贵州茅台、平安银行在 2026-01-05 的入库因子值。
2. 使用原始行情数据，通过单股纯向量化 Pandas 公式进行独立计算（黄金标准）。
3. 进行双重对比（交叉验证），计算两者的绝对误差，确保因子计算精确无误。
4. 调用 model_trainer.py 的 load_training_data 对齐接口，验证特征与标签的合并对齐。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import pandas as pd
import numpy as np
from src.model_trainer import load_training_data

def verify_single_stock_volatility(db_path, stock_code, target_date="20260105"):
    """
    针对单只股票进行独立的 pandas 日收益率滚动 20 日标准差计算，并与 factor_values 库中的数据比对。
    """
    conn = sqlite3.connect(db_path)
    
    # 1. 读取单股的历史原始行情与复权因子
    query = """
        SELECT d.trade_date, d.close, f.adj_factor
        FROM fetch_test_daily d
        INNER JOIN fetch_test_stk_factor f 
            ON d.ts_code = f.ts_code AND d.trade_date = f.trade_date
        WHERE d.ts_code = ? AND d.trade_date <= ?
        ORDER BY d.trade_date;
    """
    df_raw = pd.read_sql(query, conn, params=(stock_code, target_date))
    
    # 2. 从 factor_values 中读取我们之前分组计算写入的因子值
    query_fact = """
        SELECT volatility_20d, volatility_60d, return_20d, return_60d, atr_ratio, bollinger_pct
        FROM factor_values
        WHERE stock_code = ? AND trade_date = ?;
    """
    df_db_val = pd.read_sql(query_fact, conn, params=(stock_code, target_date))
    conn.close()
    
    if df_raw.empty or df_db_val.empty:
        print(f"⚠️ [Verify] 未能获取股票 {stock_code} 的原始数据或数据库因子数据。")
        return None
    
    # 3. 独立纯 Pandas 计算（黄金标准）
    df_raw["close_adj"] = df_raw["close"] * df_raw["adj_factor"]
    df_raw["daily_ret"] = df_raw["close_adj"].pct_change(1)
    
    # 获取目标日期之前的最后 20 个交易日计算标准差
    raw_vol_20d = df_raw["daily_ret"].iloc[-20:].std()
    raw_ret_20d = (df_raw["close_adj"].iloc[-1] - df_raw["close_adj"].iloc[-21]) / df_raw["close_adj"].iloc[-21]
    
    # 数据库保存的值
    db_vol_20d = df_db_val["volatility_20d"].iloc[0]
    db_ret_20d = df_db_val["return_20d"].iloc[0]
    
    # 计算绝对误差
    vol_error = abs(raw_vol_20d - db_vol_20d)
    ret_error = abs(raw_ret_20d - db_ret_20d)
    
    print(f"\n🔍 [Stock: {stock_code} | 日期: {target_date}] 交叉验证结果:")
    print(f"   - 20日波动率 (独立计算) : {raw_vol_20d:.8f}")
    print(f"   - 20日波动率 (数据库值) : {db_vol_20d:.8f}")
    print(f"   - 波动率绝对误差         : {vol_error:.2e} ({'通过' if vol_error < 1e-12 else '失败'})")
    
    print(f"   - 20日收益率 (独立计算) : {raw_ret_20d:.8f}")
    print(f"   - 20日收益率 (数据库值) : {db_ret_20d:.8f}")
    print(f"   - 收益率绝对误差         : {ret_error:.2e} ({'通过' if ret_error < 1e-12 else '失败'})")
    
    return {
        "stock_code": stock_code,
        "raw_vol": raw_vol_20d,
        "db_vol": db_vol_20d,
        "vol_error": vol_error,
        "raw_ret": raw_ret_20d,
        "db_ret": db_ret_20d,
        "ret_error": ret_error
    }

def main():
    db_path = "db/stock_data.db"
    
    print("=" * 70)
    print("🛠️  开始对因子进行数学交叉验证与模型样本对齐测试")
    print("=" * 70)
    
    # 1. 验证三只核心测试股票的 20日波动率 和 20日收益率
    test_stocks = ["600519.SH", "300750.SZ", "000001.SZ"]
    stock_names = {"600519.SH": "贵州茅台", "300750.SZ": "宁德时代", "000001.SZ": "平安银行"}
    
    for code in test_stocks:
        print(f"\n--- 交叉验证个股: {stock_names[code]} ({code}) ---")
        verify_single_stock_volatility(db_path, code, "20260105")
        
    print("\n" + "=" * 70)
    print("⚙️  验证 Phase 2 特征与标签的 trade_date 合并对齐:")
    print("=" * 70)
    
    # 2. 调用 model_trainer 对齐模块，检测在周度调仓日期上是否对齐成功
    try:
        df_train = load_training_data(db_path, "market_regime_labels.csv")
        print(f"\n✅ 对齐验证成功！共产生 {len(df_train)} 条有效模型对齐样本。")
    except Exception as e:
        print(f"❌ 对齐验证失败: {e}")
        
    print("\n" + "=" * 70)
    print("✅ 交叉验证与对齐测试全部结束！")
    print("=" * 70)

if __name__ == "__main__":
    main()
