# -*- coding: utf-8 -*-
"""
S4 验收脚本 — 单因子回测器
验证 5 项标准:
  1. Top-N 等权组合净值曲线可输出
  2. 绩效统计完整 (年化收益/最大回撤/夏普/卡玛/胜率)
  3. 分年度收益可输出
  4. 扣除 15bp 成本后收益合理
  5. 基准对比可输出
"""

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from factor_lib.loader import FactorDataLoader
from factor_lib.backtester import FactorBacktester
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
print("S4 验收: 单因子回测器")
print("=" * 60)

# ── 准备数据 ──
print("\n📦 加载数据 (volatility_20d, 2024-01 ~ 2026-06)...")
loader = FactorDataLoader()
df = loader.load_factor_values(["volatility_20d"], "20240101", "20260630")
df = loader.compute_forward_returns(df, [5])
print(f"   行数: {len(df)}, 日期: {df['trade_date'].min()} ~ {df['trade_date'].max()}")

bt = FactorBacktester(loader=loader)

# ═══════════════════════════════════════════
# 验收 1: Top-N 净值曲线
# ═══════════════════════════════════════════
print("\n验收 1: Top-N 等权组合净值曲线")
print("-" * 50)

result = bt.run_backtest(
    df, "volatility_20d", top_n=10, return_col="fwd_ret_5d",
    rebalance_freq="weekly", cost_bps=15.0, benchmark="equal_weight"
)

print(f"   因子: {result.factor_name}, direction={result.direction}")
print(f"   Top-N: {result.top_n}, 频率: {result.rebalance_freq}")
print(f"   净值期数: {len(result.nav)}")
print(f"   净值: 起点={result.nav.iloc[0]:.6f}, 终点={result.nav.iloc[-1]:.6f}")
print(f"   收益期数: {len(result.returns)}")
print(f"   换手率: mean={result.turnover.mean():.4f}" if len(result.turnover) > 0 else "   换手率: 无")

check("净值非空", len(result.nav) > 0, f"{len(result.nav)} 期")
check("净值起点 = 1.0", abs(result.nav.iloc[0] - 1.0) < 1e-6,
      f"起点={result.nav.iloc[0]:.6f}")
check("每期收益非空", len(result.returns) > 0, f"{len(result.returns)} 期")
check("持仓非空", len(result.holdings) > 0, f"{len(result.holdings)} 条记录")

# ═══════════════════════════════════════════
# 验收 2: 绩效统计
# ═══════════════════════════════════════════
print("\n验收 2: 绩效统计")
print("-" * 50)

perf = result.performance
print(f"   年化收益: {perf['annual_return']:.4%}")
print(f"   年化波动: {perf['annual_volatility']:.4%}")
print(f"   夏普:     {perf['sharpe']:.4f}")
print(f"   Sortino:  {perf['sortino']:.4f}")
print(f"   最大回撤: {perf['max_drawdown']:.4%}")
print(f"   卡玛:     {perf['calmar']:.4f}")
print(f"   胜率:     {perf['win_rate']:.4%}")
print(f"   盈亏比:   {perf['profit_loss_ratio']:.4f}")

required_keys = {"n_periods", "total_return", "annual_return", "annual_volatility",
                 "sharpe", "sortino", "max_drawdown", "calmar", "win_rate", "profit_loss_ratio"}
check("绩效统计含全部必要字段", required_keys.issubset(perf.keys()),
      f"字段: {sorted(perf.keys())}")
check("夏普为有限值", np.isfinite(perf["sharpe"]), f"sharpe={perf['sharpe']:.4f}")
check("最大回撤 <= 0", perf["max_drawdown"] <= 0, f"max_dd={perf['max_drawdown']:.4%}")
check("胜率在 [0, 1]", 0 <= perf["win_rate"] <= 1, f"win_rate={perf['win_rate']:.4%}")
check("卡玛为有限值", np.isfinite(perf["calmar"]), f"calmar={perf['calmar']:.4f}")

# ═══════════════════════════════════════════
# 验收 3: 分年度收益
# ═══════════════════════════════════════════
print("\n验收 3: 分年度收益")
print("-" * 50)

yearly = result.yearly_returns
print(yearly.to_string(index=False))

check("分年度收益非空", len(yearly) > 0, f"{len(yearly)} 年")
required_cols = {"year", "n_periods", "portfolio_return", "benchmark_return", "excess_return", "sharpe"}
check("分年度含必要列", required_cols.issubset(yearly.columns),
      f"列: {sorted(yearly.columns)}")
check("分年度至少 2 年", len(yearly) >= 2, f"年: {yearly['year'].tolist()}")
check("分年度组合收益非全零", yearly["portfolio_return"].abs().sum() > 0)

# ═══════════════════════════════════════════
# 验收 4: 扣除 15bp 成本
# ═══════════════════════════════════════════
print("\n验收 4: 扣除 15bp 交易成本")
print("-" * 50)

# 对比: 有成本 vs 无成本
result_no_cost = bt.run_backtest(
    df, "volatility_20d", top_n=10, return_col="fwd_ret_5d",
    rebalance_freq="weekly", cost_bps=0.0, benchmark="equal_weight"
)

print(f"   有成本: 年化={perf['annual_return']:.4%}, 总收益={perf['total_return']:.4%}")
print(f"   无成本: 年化={result_no_cost.performance['annual_return']:.4%}, "
      f"总收益={result_no_cost.performance['total_return']:.4%}")
cost_drag = result_no_cost.performance["total_return"] - perf["total_return"]
print(f"   成本拖累: {cost_drag:.4%}")

check("有成本总收益 < 无成本总收益",
      perf["total_return"] < result_no_cost.performance["total_return"],
      f"成本拖累={cost_drag:.4%}")
check("成本拖累为正且合理", 0 < cost_drag < 0.5,
      f"拖累={cost_drag:.4%}")

# ═══════════════════════════════════════════
# 验收 5: 基准对比
# ═══════════════════════════════════════════
print("\n验收 5: 基准对比")
print("-" * 50)

print(f"   组合净值终点: {result.nav.iloc[-1]:.6f}")
print(f"   基准净值终点: {result.benchmark_nav.iloc[-1]:.6f}")
print(f"   超额收益: {(result.nav.iloc[-1] / result.benchmark_nav.iloc[-1] - 1):.4%}")

bench_perf = result.benchmark_performance
print(f"   基准年化: {bench_perf['annual_return']:.4%}")
print(f"   基准夏普: {bench_perf['sharpe']:.4f}")
print(f"   基准回撤: {bench_perf['max_drawdown']:.4%}")

check("基准净值非空", len(result.benchmark_nav) > 0)
check("基准起点 = 1.0", abs(result.benchmark_nav.iloc[0] - 1.0) < 1e-6,
      f"起点={result.benchmark_nav.iloc[0]:.6f}")
check("基准绩效非空", result.benchmark_performance["n_periods"] > 0)
check("分年度含基准收益", "benchmark_return" in result.yearly_returns.columns)

# ═══════════════════════════════════════════
# 附加: direction -1 因子测试
# ═══════════════════════════════════════════
print("\n附加: direction=+1 因子 (return_20d) Top-N 回测")
print("-" * 50)

df2 = loader.load_factor_values(["return_20d"], "20240101", "20260630")
df2 = loader.compute_forward_returns(df2, [5])
result2 = bt.run_backtest(
    df2, "return_20d", top_n=10, return_col="fwd_ret_5d",
    rebalance_freq="weekly", cost_bps=15.0, benchmark="equal_weight"
)
print(f"   return_20d direction={result2.direction}")
print(f"   年化收益: {result2.performance['annual_return']:.4%}")
print(f"   超额收益: {(result2.nav.iloc[-1] / result2.benchmark_nav.iloc[-1] - 1):.4%}")
check("direction=+1 选最高值", result2.direction == 1)

# ═══════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print(f"S4 验收结果: {passed} PASS / {failed} FAIL")
print("=" * 60)

if failed > 0:
    sys.exit(1)
else:
    print("🎉 S4 全部通过!")
