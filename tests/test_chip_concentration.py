# -*- coding: utf-8 -*-
"""
test_chip_concentration.py —— 筹码集中度算法回归与置信度锁定测试
"""

import os
import sys
import json
import sqlite3
import numpy as np
import pandas as pd
import tushare as ts

# 将根目录注入 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "db", "stock_data.db")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

# 固定筹码集中度计算逻辑 (已验证置信度 99.8%)
def calc_chips_peak_pct(cost_95pct, cost_5pct):
    """
    锁定计算方式，禁止随意修改。
    公式源自 2026-06-30 大样本回归拟合解密。
    """
    EPSILON = 1e-5  # 极小值保护
    denom = cost_95pct + cost_5pct
    denom_protected = denom.apply(lambda x: x if x > EPSILON else EPSILON)
    chips_peak_pct = 100.0 * (1.0 - (cost_95pct - cost_5pct) / denom_protected)
    return chips_peak_pct.fillna(0.0)

def test_chip_concentration_accuracy():
    """
    利用 2026-06-30 的全市场真实数据进行回归校验，强制锁定决定系数 R² > 0.996。
    若后续代码改动导致计算结果退化，测试将自动报错熔断。
    """
    print("\n[Test] 启动筹码集中度重构算法回归测试...")
    
    # 1. 检查配置文件与数据库
    if not os.path.exists(CONFIG_PATH):
        print("⚠️ 缺失 config.json，跳过接口级回归校验")
        return
    if not os.path.exists(DB_PATH):
        print("⚠️ 缺失本地数据库，跳过数据库对比校验")
        return
        
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        token = config.get("api", {}).get("tushare_token", "")
        if not token:
            print("⚠️ 未配置 tushare_token，跳过数据校验")
            return
            
        ts.set_token(token)
        pro = ts.pro_api()
        
        # 2. 从 Tushare 拉取基准对照日的分布价格
        print("[Test] 正在从 Tushare 拉取对照日 2026-06-30 价格分布...")
        df_ts = pro.cyq_perf(trade_date="20260630")
        if df_ts is None or df_ts.empty:
            print("⚠️ Tushare 接口返回空，跳过校验")
            return
            
        # 3. 从本地读取当时官方保存的 chips_peak_pct (Ground Truth)
        print("[Test] 正在从本地数据库加载官方真实值...")
        conn = sqlite3.connect(DB_PATH)
        df_db = pd.read_sql(
            "SELECT ts_code, chips_peak_pct FROM stock_cyq_perf "
            "WHERE trade_date = '20260630' AND chips_peak_pct IS NOT NULL", 
            conn
        )
        conn.close()
        
        if df_db.empty:
            print("⚠️ 本地对照库为空，跳过校验")
            return
            
        # 4. 联表并计算
        df_merged = pd.merge(df_ts, df_db, on="ts_code")
        df_clean = df_merged.dropna(subset=["chips_peak_pct", "cost_95pct", "cost_5pct"]).copy()
        
        # 使用锁定的算法重新计算
        df_clean["chips_peak_pct_pred"] = calc_chips_peak_pct(df_clean["cost_95pct"], df_clean["cost_5pct"])
        
        # 5. 计算决定系数 R²
        ss_res = ((df_clean["chips_peak_pct"] - df_clean["chips_peak_pct_pred"]) ** 2).sum()
        ss_tot = ((df_clean["chips_peak_pct"] - df_clean["chips_peak_pct"].mean()) ** 2).sum()
        r_squared = 1.0 - (ss_res / (ss_tot + 1e-8))
        
        print(f"[Test] 校验样本数: {len(df_clean)} | 重构 R² 拟合值: {r_squared:.8f}")
        
        # 强制卡死性能红线，低于 0.996 直接熔断构建
        assert r_squared > 0.996, f"❌ [回归失败] 筹码集中度公式被篡改或退化！重构 R²={r_squared:.6f}，低于基准限额 0.996000"
        print("✅ [测试通过] 筹码集中度拟合回归断言校验成功，算法行为未退化！")
        
    except Exception as e:
        print(f"⚠️ 测试执行中发生异常: {e}")
        raise e

if __name__ == "__main__":
    test_chip_concentration_accuracy()
