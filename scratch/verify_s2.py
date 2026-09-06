# -*- coding: utf-8 -*-
"""
S2 验收脚本 — IC 计算引擎
验证 6 项标准:
  1. Rank IC 与 factor_ic_analysis.py 口径一致
  2. Normal IC 可计算且数值合理 (-1~1)
  3. IC 衰减曲线覆盖 5 个周期
  4. IC 累积曲线对正向因子趋势向上
  5. 分年度 IC 统计表可输出
  6. t 检验 p 值与 scipy.stats.ttest_1samp 一致
"""

import os
import sys
import numpy as np
import pandas as pd
from scipy import stats as sps

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine
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
print("S2 验收: IC 计算引擎")
print("=" * 60)

# ── 准备数据 ──
print("\n📦 加载数据 (return_5d + return_20d, 2025-01 ~ 2026-08)...")
loader = FactorDataLoader()
df = loader.load_factor_values(["return_5d", "return_20d"], "20250101", "20260820")
df = loader.compute_forward_returns(df, [1, 3, 5, 10, 20])
print(f"   行数: {len(df)}, 日期: {df['trade_date'].min()} ~ {df['trade_date'].max()}")

engine = ICEngine(min_cross_section_size=30)

# ═══════════════════════════════════════════
# 验收 1: Rank IC 口径一致性
# ═══════════════════════════════════════════
print("\n验收 1: Rank IC 与 factor_ic_analysis.py 口径一致性")
print("-" * 50)

# 用 ICEngine 计算
ic_engine = engine.compute_ic_series(df, "return_5d", "rank", "fwd_ret_5d")
print(f"   ICEngine IC: {len(ic_engine)} 天, mean={ic_engine.mean():.6f}")

# 用 factor_ic_analysis.py 的原始逻辑计算
df_orig = df[["trade_date", "ts_code", "return_5d", "fwd_ret_5d"]].dropna()
date_counts = df_orig.groupby("trade_date").size()
valid_dates = date_counts[date_counts >= 30].index
df_orig = df_orig[df_orig["trade_date"].isin(valid_dates)]

orig_ic = {}
for d, df_sub in df_orig.groupby("trade_date"):
    if len(df_sub) < 30:
        continue
    corr = df_sub["return_5d"].corr(df_sub["fwd_ret_5d"], method="spearman")
    if not pd.isna(corr):
        orig_ic[d] = corr

orig_series = pd.Series(orig_ic, name="ic_rank")
print(f"   原始 IC:  {len(orig_series)} 天, mean={orig_series.mean():.6f}")

# 对比
common_dates = ic_engine.index.intersection(orig_series.index)
if len(common_dates) > 0:
    diff = (ic_engine.loc[common_dates] - orig_series.loc[common_dates]).abs()
    max_diff = diff.max()
    mean_diff = diff.mean()
    check("Rank IC 口径一致", max_diff < 1e-6,
          f"共 {len(common_dates)} 天, 最大差异={max_diff:.2e}, 平均差异={mean_diff:.2e}")
else:
    check("Rank IC 口径一致", False, "无共同日期")

# ═══════════════════════════════════════════
# 验收 2: Normal IC 数值合理
# ═══════════════════════════════════════════
print("\n验收 2: Normal IC 数值合理")
print("-" * 50)

ic_normal = engine.compute_ic_series(df, "return_5d", "normal", "fwd_ret_5d")
print(f"   Normal IC: {len(ic_normal)} 天, mean={ic_normal.mean():.6f}, std={ic_normal.std():.6f}")
check("Normal IC 非空", len(ic_normal) > 0, f"共 {len(ic_normal)} 天")
check("Normal IC 全部在 [-1, 1]", (ic_normal >= -1).all() and (ic_normal <= 1).all(),
      f"min={ic_normal.min():.4f}, max={ic_normal.max():.4f}")

# ═══════════════════════════════════════════
# 验收 3: IC 衰减曲线
# ═══════════════════════════════════════════
print("\n验收 3: IC 衰减曲线 (5 个周期)")
print("-" * 50)

decay = engine.compute_ic_decay(df, "return_5d")
print(decay[["period", "n_days", "ic_mean", "icir"]].to_string(index=False))
check("衰减曲线覆盖 5 个周期", len(decay) == 5,
      f"实际 {len(decay)} 个周期: {decay['period'].tolist()}")
check("衰减曲线 IC 均值非全零", decay["ic_mean"].abs().sum() > 0)

# ═══════════════════════════════════════════
# 验收 4: IC 累积曲线趋势
# ═══════════════════════════════════════════
print("\n验收 4: IC 累积曲线趋势方向正确")
print("-" * 50)

# return_20d 动量因子: 检查累积曲线趋势方向与 IC 符号一致
ic_20d = engine.compute_ic_series(df, "return_20d", "rank", "fwd_ret_5d")
cum_ic = engine.compute_ic_cumulative(ic_20d)
ic_sign = 1 if ic_20d.mean() > 0 else -1
print(f"   return_20d IC 均值={ic_20d.mean():.6f} (符号={ic_sign:+d})")
print(f"   累积曲线: 起点={cum_ic.iloc[0]:.4f}, 终点={cum_ic.iloc[-1]:.4f}")

# 检查: 累积曲线终点偏离 0 的方向与 IC 符号一致
end_val = cum_ic.iloc[-1]
if ic_sign > 0:
    check("正向 IC → 累积曲线终点 > 0", end_val > 0,
          f"终点={end_val:.4f}")
else:
    check("负向 IC → 累积曲线终点 < 0", end_val < 0,
          f"终点={end_val:.4f}")

# 趋势方向: Spearman(序号, 累积值) 符号与 IC 符号一致
day_idx = pd.Series(np.arange(len(cum_ic)))
cum_series = pd.Series(cum_ic.values)
trend_corr = day_idx.corr(cum_series, method="spearman")
check("累积曲线趋势方向与 IC 符号一致",
      (trend_corr > 0 and ic_sign > 0) or (trend_corr < 0 and ic_sign < 0),
      f"Spearman(序号, 累积IC)={trend_corr:.4f}, IC符号={ic_sign:+d}")

# ═══════════════════════════════════════════
# 验收 5: 分年度 IC 稳定性
# ═══════════════════════════════════════════
print("\n验收 5: 分年度 IC 稳定性")
print("-" * 50)

yearly = engine.compute_yearly_stability(ic_20d)
print(yearly.to_string(index=False))
check("年度统计表非空", len(yearly) > 0, f"共 {len(yearly)} 年")
required_cols = {"year", "n_days", "ic_mean", "ic_std", "icir"}
check("年度统计含必要列", required_cols.issubset(yearly.columns),
      f"列: {sorted(yearly.columns)}")
check("每年 IC 均值非全零", yearly["ic_mean"].abs().sum() > 0)

# ═══════════════════════════════════════════
# 验收 6: t 检验 p 值一致性
# ═══════════════════════════════════════════
print("\n验收 6: t 检验 p 值与 scipy.stats.ttest_1samp 一致")
print("-" * 50)

summary = engine.compute_ic_summary(ic_20d)
# 用 scipy 直接算
t_scipy, p_scipy = sps.ttest_1samp(ic_20d.dropna(), 0)
print(f"   ICEngine: t={summary['t_stat']:.6f}, p={summary['p_value']:.6e}")
print(f"   scipy:    t={t_scipy:.6f}, p={p_scipy:.6e}")
check("t 值一致", abs(summary["t_stat"] - t_scipy) < 1e-4,
      f"差异={abs(summary['t_stat'] - t_scipy):.2e}")
check("p 值一致", abs(summary["p_value"] - p_scipy) < 1e-6,
      f"差异={abs(summary['p_value'] - p_scipy):.2e}")

# ═══════════════════════════════════════════
# 附加: full_report 快速验证
# ═══════════════════════════════════════════
print("\n附加: compute_full_report 完整性")
print("-" * 50)
report = engine.compute_full_report(df, "return_5d")
expected_keys = {"factor", "rank_ic_series", "normal_ic_series", "rank_ic_summary",
                 "normal_ic_summary", "ic_decay", "ic_cumulative", "yearly_stability"}
check("full_report 含全部 key", expected_keys.issubset(report.keys()))

# ═══════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print(f"S2 验收结果: {passed} PASS / {failed} FAIL")
print("=" * 60)

if failed > 0:
    sys.exit(1)
else:
    print("🎉 S2 全部通过!")
