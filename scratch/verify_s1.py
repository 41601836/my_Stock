# -*- coding: utf-8 -*-
"""
S1 验收脚本 — 公共因子库骨架 + 数据管道
验证 5 项标准:
  1. Registry 因子数正确
  2. Loader 可加载因子 + close_adj
  3. 未来5日收益率与 factor_ic_analysis.py 口径一致
  4. ST/次新股过滤生效
  5. 配置热加载生效
"""

import os
import sys
import sqlite3
import time

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from factor_lib.registry import (
    FACTOR_REGISTRY, get_factor, get_factors_by_table,
    get_factors_by_category, get_all_factor_names,
    get_classic_factor_names, get_evo_factor_names,
)
from factor_lib.config import FactorTestConfig
from factor_lib.loader import FactorDataLoader

from config.paths import PATHS

passed = 0
failed = 0
total = 5

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
        if detail:
            print(f"     {detail}")
    else:
        failed += 1
        print(f"  ❌ {name}")
        if detail:
            print(f"     {detail}")

# ═══════════════════════════════════════════
# 验收 1: Registry 因子数
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("验收 1: Registry 因子注册表")
print("=" * 60)

n_total = len(FACTOR_REGISTRY)
n_classic = len(get_classic_factor_names())
n_evo = len(get_evo_factor_names())
print(f"  总因子数: {n_total} (经典 {n_classic} + EVO {n_evo})")
print(f"  分类: {set(f.category for f in FACTOR_REGISTRY.values())}")
print(f"  表分布: factor_values={len(get_factors_by_table('factor_values'))}, "
      f"factor_values_evo={len(get_factors_by_table('factor_values_evo'))}")

check("因子数 >= 37", n_total >= 37, f"实际 {n_total} 个")
check("经典因子数 == 31", n_classic == 31, f"实际 {n_classic}")
check("EVO因子数 == 15", n_evo == 15, f"实际 {n_evo}")
check("get_factor 能查到已知因子", get_factor("return_5d") is not None)
check("get_factor 未知因子返回 None", get_factor("nonexistent") is None)

# ═══════════════════════════════════════════
# 验收 2: Loader 加载因子 + close_adj
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("验收 2: Loader 数据加载")
print("=" * 60)

loader = FactorDataLoader()

# 测试经典表因子
df_classic = loader.load_factor_values(["return_5d", "volatility_20d"], "20260801", "20260831")
check("经典因子加载非空", len(df_classic) > 0, f"行数={len(df_classic)}")
check("经典因子含 close_adj", "close_adj" in df_classic.columns)
check("经典因子列 ts_code 统一", "ts_code" in df_classic.columns)
check("close_adj 全部为正数", (df_classic["close_adj"] > 0).all(),
      f"min={df_classic['close_adj'].min():.2f}")

# 测试 EVO 表因子
df_evo = loader.load_factor_values(["inter_quality_momentum", "surprise_roe_qoq"], "20260801", "20260831")
check("EVO因子加载非空", len(df_evo) > 0, f"行数={len(df_evo)}")
check("EVO因子列 ts_code 统一", "ts_code" in df_evo.columns)

# 测试混合加载
df_mix = loader.load_factor_values(
    ["return_5d", "inter_quality_momentum"], "20260801", "20260831"
)
check("混合(经典+EVO)加载非空", len(df_mix) > 0, f"行数={len(df_mix)}")
check("混合表含两表因子", "return_5d" in df_mix.columns and "inter_quality_momentum" in df_mix.columns)

# ═══════════════════════════════════════════
# 验收 3: 未来5日收益率口径一致性
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("验收 3: 未来5日收益率口径一致性 (vs factor_ic_analysis.py)")
print("=" * 60)

# 用 loader 加载 + 计算未来收益
df_loader = loader.load_factor_values(["return_5d"], "20260101", "20260820")
df_loader = loader.compute_forward_returns(df_loader, [5])
sample_codes = df_loader["ts_code"].unique()[:5]

# 用 factor_ic_analysis.py 的原始逻辑手动计算
conn = sqlite3.connect(PATHS.database.stock_data)
df_prices = pd.read_sql(
    "SELECT ts_code AS stock_code, trade_date, close, adj_factor "
    "FROM daily_prices WHERE trade_date >= '20260101' AND trade_date <= '20260831'",
    conn
)
conn.close()
df_prices["trade_date"] = df_prices["trade_date"].astype(str)
df_prices = df_prices.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
df_prices["close_adj"] = df_prices["close"] * df_prices["adj_factor"]
df_prices["future_return_5d"] = (
    df_prices.groupby("stock_code")["close_adj"].shift(-5)
    / df_prices["close_adj"] - 1.0
)
df_prices["future_return_5d"] = df_prices["future_return_5d"].clip(-0.5, 0.8)

# 对比 5 只股票
all_match = True
for code in sample_codes:
    loader_vals = df_loader[df_loader["ts_code"] == code][["trade_date", "fwd_ret_5d"]].set_index("trade_date")
    original_vals = df_prices[df_prices["stock_code"] == code][["trade_date", "future_return_5d"]].set_index("trade_date")
    common = loader_vals.index.intersection(original_vals.index)
    if len(common) > 0:
        l = loader_vals.loc[common, "fwd_ret_5d"].dropna()
        o = original_vals.loc[common, "future_return_5d"].dropna()
        common_valid = l.index.intersection(o.index)
        if len(common_valid) > 0:
            diff = (l.loc[common_valid] - o.loc[common_valid]).abs().max()
            if diff > 1e-8:
                all_match = False
                print(f"     {code}: 最大差异={diff:.2e}")

check("未来5日收益率口径一致", all_match, "与 factor_ic_analysis.py 计算逻辑一致")

# ═══════════════════════════════════════════
# 验收 4: ST/次新股过滤
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("验收 4: ST/次新股过滤")
print("=" * 60)

excluded = loader._load_excluded_codes()
check("过滤名单非空", len(excluded) > 0, f"排除 {len(excluded)} 只 ST/次新股")

# 验证 ST 股票不在加载结果中
df_check = loader.load_factor_values(["return_5d"], "20260825", "20260831")
if len(excluded) > 0:
    st_in_result = excluded.intersection(set(df_check["ts_code"].unique()))
    check("ST/次新股不在结果中", len(st_in_result) == 0,
          f"结果中有 {len(st_in_result)} 只应被过滤")

# ═══════════════════════════════════════════
# 验收 5: 配置热加载
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("验收 5: 配置热加载")
print("=" * 60)

cfg_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "factor_test.yaml"
)

# 读取原始值
original_groups = FactorTestConfig.n_groups()
check("配置可读", original_groups == 5, f"n_groups={original_groups}")

# 修改配置
import yaml
with open(cfg_path, "r", encoding="utf-8") as f:
    original_yaml = f.read()
modified = yaml.safe_load(original_yaml)
modified["stratified"]["n_groups"] = 10
with open(cfg_path, "w", encoding="utf-8") as f:
    yaml.dump(modified, f, allow_unicode=True, default_flow_style=False)

# 验证热刷新
time.sleep(0.1)
new_groups = FactorTestConfig.n_groups()
check("热加载生效", new_groups == 10, f"修改后 n_groups={new_groups}")

# 恢复原配置
with open(cfg_path, "w", encoding="utf-8") as f:
    f.write(original_yaml)
time.sleep(0.1)
restored = FactorTestConfig.n_groups()
check("恢复配置生效", restored == 5, f"恢复后 n_groups={restored}")

# ═══════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print(f"S1 验收结果: {passed} PASS / {failed} FAIL / {total} 总项")
print("=" * 60)

if failed > 0:
    sys.exit(1)
else:
    print("🎉 S1 全部通过!")
