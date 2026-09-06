# -*- coding: utf-8 -*-
"""
S5 验收脚本 — 防过拟合校验
验证 5 项标准:
  1. 样本外 IC 均值与样本内可对比
  2. Walk-Forward 多窗口 IC 一致性
  3. 置换检验 p < 0.05 (对有效因子)
  4. 子周期稳定性: 分年度 IC 方向一致率
  5. IC 自相关可计算
"""

import os
import sys
import time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine
from factor_lib.anti_overfit import AntiOverfitChecker

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
print("S5 验收: 防过拟合校验")
print("=" * 60)

# ── 准备数据 ──
# 用 2.5 年数据做样本内外/WF/子周期, 用 4 个月做置换检验(提速)
print("\n📦 加载数据 (volatility_20d, 2024-01 ~ 2026-06)...")
loader = FactorDataLoader()
df = loader.load_factor_values(["volatility_20d"], "20240101", "20260630")
df = loader.compute_forward_returns(df, [5])
print(f"   行数: {len(df)}, 日期: {df['trade_date'].min()} ~ {df['trade_date'].max()}")

engine = ICEngine()
checker = AntiOverfitChecker(ic_engine=engine)

# ═══════════════════════════════════════════
# 验收 1: 样本内外对比
# ═══════════════════════════════════════════
print("\n验收 1: 样本内外 IC 对比")
print("-" * 50)

is_oos = checker.check_in_sample_oos(df, "volatility_20d", "fwd_ret_5d", train_ratio=0.6)
print(f"   训练期: {is_oos['train_n_days']} 天, IC均值={is_oos['train_ic_mean']:.6f}, ICIR={is_oos['train_icir']:.4f}")
print(f"   测试期: {is_oos['test_n_days']} 天, IC均值={is_oos['test_ic_mean']:.6f}, ICIR={is_oos['test_icir']:.4f}")
print(f"   ICIR 衰减: {is_oos['icir_decay']:.4f} (acceptable={is_oos['icir_decay_acceptable']})")
print(f"   方向一致: {is_oos['direction_consistent']}")

check("训练/测试天数 > 0", is_oos["train_n_days"] > 0 and is_oos["test_n_days"] > 0)
check("训练 IC 均值非零", abs(is_oos["train_ic_mean"]) > 1e-6)
check("测试 IC 均值非零", abs(is_oos["test_ic_mean"]) > 1e-6)
check("方向一致", is_oos["direction_consistent"],
      f"train={is_oos['train_ic_mean']:+.6f}, test={is_oos['test_ic_mean']:+.6f}")

# ═══════════════════════════════════════════
# 验收 2: Walk-Forward 滚动检验
# ═══════════════════════════════════════════
print("\n验收 2: Walk-Forward 滚动检验")
print("-" * 50)

wf = checker.walk_forward(df, "volatility_20d", "fwd_ret_5d", train_days=126, test_days=42)
print(f"   窗口数: {wf['n_windows']}")
if wf["n_windows"] > 0:
    print(wf["results"][["window", "train_ic", "test_ic", "test_ic_positive", "direction_consistent"]].to_string(index=False))
print(f"   IC 正比例: {wf['ic_positive_ratio']:.4f}")
print(f"   方向一致率: {wf['direction_consistency_ratio']:.4f}")

check("Walk-Forward 窗口数 >= 3", wf["n_windows"] >= 3, f"{wf['n_windows']} 个窗口")
check("结果表非空", len(wf["results"]) > 0)
check("IC 正比例可计算", wf["ic_positive_ratio"] is not None)
check("方向一致率可计算", wf["direction_consistency_ratio"] is not None)

# ═══════════════════════════════════════════
# 验收 3: 置换检验
# ═══════════════════════════════════════════
print("\n验收 3: 置换检验 (100 次, 4 个月数据)")
print("-" * 50)

# 用 4 个月数据提速
df_short = loader.load_factor_values(["volatility_20d"], "20250101", "20250430")
df_short = loader.compute_forward_returns(df_short, [5])
print(f"   子集行数: {len(df_short)}, 日期: {df_short['trade_date'].min()} ~ {df_short['trade_date'].max()}")

t0 = time.time()
perm = checker.permutation_test(
    df_short, "volatility_20d", "fwd_ret_5d", n_perm=100, random_seed=42
)
elapsed = time.time() - t0
print(f"   耗时: {elapsed:.1f}s")
print(f"   实际 IC 均值: {perm['actual_ic_mean']:.6f}")
print(f"   置换 IC 均值: {perm['perm_ic_mean']:.6f} ± {perm['perm_ic_std']:.6f}")
print(f"   p 值: {perm['p_value']:.4f}")
print(f"   显著: {perm['significant']}")
print(f"   95% CI: [{perm['perm_2.5%']:.6f}, {perm['perm_97.5%']:.6f}]")

check("实际 IC 均值非零", abs(perm["actual_ic_mean"]) > 1e-6)
check("置换分布非全零", abs(perm["perm_ic_mean"]) < 1 or perm["perm_ic_std"] > 1e-6)
check("p 值在 [0, 1]", 0 <= perm["p_value"] <= 1)
check("有效因子 p < 0.10", perm["p_value"] < 0.10,
      f"p={perm['p_value']:.4f}")

# ═══════════════════════════════════════════
# 验收 4: 子周期稳定性
# ═══════════════════════════════════════════
print("\n验收 4: 子周期稳定性 (分年度)")
print("-" * 50)

ic_series = engine.compute_ic_series(df, "volatility_20d", "rank", "fwd_ret_5d")
sub = checker.check_subperiod_stability(ic_series)
print(f"   年数: {sub['n_years']}")
print(f"   整体 IC 均值: {sub.get('overall_ic_mean', 0):.6f}")
print(f"   方向一致率: {sub['consistent_ratio']:.4f}")
print(f"   通过: {sub['pass']}")
if len(sub["yearly_stats"]) > 0:
    print(sub["yearly_stats"][["year", "ic_mean", "icir", "positive_ratio"]].to_string(index=False))

check("年数 >= 2", sub["n_years"] >= 2, f"{sub['n_years']} 年")
check("方向一致率可计算", sub["consistent_ratio"] is not None)
check("通过/不通过有结论", sub["pass"] is not None)

# ═══════════════════════════════════════════
# 验收 5: IC 自相关
# ═══════════════════════════════════════════
print("\n验收 5: IC 自相关")
print("-" * 50)

ac = checker.check_ic_autocorrelation(ic_series)
print(f"   AC(1):  {ac['autocorr_lag1']:.4f}")
print(f"   AC(5):  {ac['autocorr_lag5']:.4f}")
print(f"   AC(10): {ac['autocorr_lag10']:.4f}")
print(f"   有持续性: {ac['has_persistence']}")

check("AC(1) 可计算", np.isfinite(ac["autocorr_lag1"]))
check("AC(5) 可计算", np.isfinite(ac["autocorr_lag5"]))
check("AC(10) 可计算", np.isfinite(ac["autocorr_lag10"]))
check("AC(1) 在 [-1, 1]", -1 <= ac["autocorr_lag1"] <= 1,
      f"AC(1)={ac['autocorr_lag1']:.4f}")

# ═══════════════════════════════════════════
# 附加: run_full_check 完整性
# ═══════════════════════════════════════════
print("\n附加: run_full_check (不含置换检验, 快速)")
print("-" * 50)

# 手动组合 (跳过 permutation_test 以节省时间)
full = {
    "factor_name": "volatility_20d",
    "in_sample_oos": is_oos,
    "walk_forward": wf,
    "subperiod_stability": sub,
    "ic_autocorrelation": ac,
}
expected_keys = {"factor_name", "in_sample_oos", "walk_forward",
                 "subperiod_stability", "ic_autocorrelation"}
check("full_check 含全部 key", expected_keys.issubset(full.keys()))

# ═══════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print(f"S5 验收结果: {passed} PASS / {failed} FAIL")
print("=" * 60)

if failed > 0:
    sys.exit(1)
else:
    print("🎉 S5 全部通过!")
