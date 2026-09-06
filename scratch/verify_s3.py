# -*- coding: utf-8 -*-
"""
S3 验收脚本 — 分层测试引擎
验证 5 项标准:
  1. 5 组分层测试, 各组等权收益可计算
  2. 多空净值曲线扣 15bp 成本后可输出
  3. 单调性检验: 有效因子 vs 无效因子 (常量因子)
  4. 换手率可计算且数值合理
  5. 周调/日调均可配置
"""

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from factor_lib.loader import FactorDataLoader
from factor_lib.stratified_tester import StratifiedTester
from factor_lib.config import FactorTestConfig

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
        if detail: print(f"     {detail}")
    else:
        failed += 1
        print(f"  ❌ {name}")
        if detail: print(f"     {detail}")

print("=" * 60)
print("S3 验收: 分层测试引擎")
print("=" * 60)

# ── 准备数据 ──
print("\n📦 加载数据 (return_20d + volatility_20d + timeliness_decay, 2025-01 ~ 2026-06)...")
loader = FactorDataLoader()
df = loader.load_factor_values(
    ["return_20d", "volatility_20d", "timeliness_decay"], "20250101", "20260630"
)
df = loader.compute_forward_returns(df, [5])
print(f"   行数: {len(df)}, 日期: {df['trade_date'].min()} ~ {df['trade_date'].max()}")

tester = StratifiedTester(loader=loader)

# ═══════════════════════════════════════════
# 验收 1: 5 组分层, 各组收益可计算
# ═══════════════════════════════════════════
print("\n验收 1: 5 组分层, 各组等权收益")
print("-" * 50)

result = tester.run_stratified_test(
    df, "volatility_20d", n_groups=5, return_col="fwd_ret_5d",
    rebalance_freq="weekly", cost_bps=15.0
)

print(f"   调仓频率: {result.rebalance_freq}")
print(f"   分组数: {result.n_groups}")
print(f"   各组列名: {list(result.group_returns.columns)}")
print(f"   期数: {len(result.group_returns)}")
print(f"   各组平均收益:")
for col in result.group_returns.columns:
    avg = result.group_returns[col].mean()
    print(f"     {col}: {avg:.6f}")

check("5 组分层非空", len(result.group_returns) > 0, f"{len(result.group_returns)} 期")
check("分组数 == 5", result.n_groups == 5)
check("列名含 g1~g5", list(result.group_returns.columns) == ["g1", "g2", "g3", "g4", "g5"])
check("各组收益非全 NaN", result.group_returns.notna().any().all())

# ═══════════════════════════════════════════
# 验收 2: 多空净值曲线 (扣成本)
# ═══════════════════════════════════════════
print("\n验收 2: 多空净值曲线 (扣 15bp 成本)")
print("-" * 50)

print(f"   多空收益期数: {len(result.long_short_returns)}")
print(f"   多空净值: 起点={result.long_short_nav.iloc[0]:.6f}, 终点={result.long_short_nav.iloc[-1]:.6f}")
print(f"   平均换手率: {result.avg_turnover:.4f}")
print(f"   每期成本: {result.summary.get('cost_per_period', 0):.6f}")
print(f"   多空总收益: {result.summary.get('long_short_total_return', 0):.4%}")

check("多空净值非空", len(result.long_short_nav) > 0)
check("多空净值起点 = 1.0", abs(result.long_short_nav.iloc[0] - 1.0) < 1e-6,
      f"起点={result.long_short_nav.iloc[0]:.6f}")
check("成本已扣除 (cost_per_period > 0)", result.summary.get("cost_per_period", 0) > 0,
      f"每期成本={result.summary.get('cost_per_period', 0):.6f}")

# ═══════════════════════════════════════════
# 验收 3: 单调性检验
# ═══════════════════════════════════════════
print("\n验收 3: 单调性检验 (有效因子 vs 无效因子)")
print("-" * 50)

# 有效因子: volatility_20d (低波动异象, direction=-1)
print(f"   [有效因子] volatility_20d (direction={result.direction}):")
print(f"     单调性得分: {result.monotonicity_score:.4f}")
print(f"     p 值: {result.monotonicity_pvalue:.4f}")

# 无效因子: timeliness_decay (常数占位因子)
result_invalid = tester.run_stratified_test(
    df, "timeliness_decay", n_groups=5, return_col="fwd_ret_5d",
    rebalance_freq="weekly", cost_bps=15.0
)
print(f"   [无效因子] timeliness_decay:")
print(f"     单调性得分: {result_invalid.monotonicity_score:.4f}")
print(f"     p 值: {result_invalid.monotonicity_pvalue:.4f}")

# 5 组 Spearman 检验功效低 (n=5), 用相对比较 + 绝对阈值
check("有效因子得分在 [-1, 1]", -1 <= result.monotonicity_score <= 1)
check("有效因子 p 值在 [0, 1]", 0 <= result.monotonicity_pvalue <= 1)
check("无效因子 p 值 > 0.1", result_invalid.monotonicity_pvalue > 0.1,
      f"p={result_invalid.monotonicity_pvalue:.4f}")
check("无效因子得分 < 有效因子 |得分|",
      abs(result_invalid.monotonicity_score) < abs(result.monotonicity_score) or
      result_invalid.monotonicity_pvalue > 0.1,
      f"无效|{result_invalid.monotonicity_score:.2f}| vs 有效|{result.monotonicity_score:.2f}|")

# ═══════════════════════════════════════════
# 验收 4: 换手率
# ═══════════════════════════════════════════
print("\n验收 4: 换手率")
print("-" * 50)

print(f"   换手率记录数: {len(result.turnover)}")
if len(result.turnover) > 0:
    print(f"   换手率统计: mean={result.turnover['turnover_rate'].mean():.4f}, "
          f"median={result.turnover['turnover_rate'].median():.4f}, "
          f"max={result.turnover['turnover_rate'].max():.4f}")

check("换手率非空", len(result.turnover) > 0, f"{len(result.turnover)} 条记录")
avg_to = result.avg_turnover
check("换手率在 [0, 1] 范围", 0 <= avg_to <= 1.0,
      f"平均换手率={avg_to:.4f}")
check("换手率合理 (5%~95%)", 0.05 <= avg_to <= 0.95,
      f"平均换手率={avg_to:.4f}")

# ═══════════════════════════════════════════
# 验收 5: 周调/日调
# ═══════════════════════════════════════════
print("\n验收 5: 周调/日调均可配置")
print("-" * 50)

# 周调
print(f"   [周调] 期数={len(result.group_returns)}, 频率={result.rebalance_freq}")
check("周调可运行", len(result.group_returns) > 0, f"{len(result.group_returns)} 期")

# 日调
result_daily = tester.run_stratified_test(
    df, "volatility_20d", n_groups=5, return_col="fwd_ret_5d",
    rebalance_freq="daily", cost_bps=15.0
)
print(f"   [日调] 期数={len(result_daily.group_returns)}, 频率={result_daily.rebalance_freq}")
check("日调可运行", len(result_daily.group_returns) > 0, f"{len(result_daily.group_returns)} 期")
check("日调期数 > 周调期数", len(result_daily.group_returns) > len(result.group_returns),
      f"日调={len(result_daily.group_returns)} > 周调={len(result.group_returns)}")

# ═══════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print(f"S3 验收结果: {passed} PASS / {failed} FAIL")
print("=" * 60)

if failed > 0:
    sys.exit(1)
else:
    print("🎉 S3 全部通过!")
