#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S7 集成测试 — 46 因子全测试 + 零侵入验证 + 一行回滚验证
=================================================
验收标准:
  1. 46 个因子全测试通过（不崩溃，有结果输出）
  2. 零侵入验证：factor_lib/ 不 import 任何 agent/ 或 web/ 代码
  3. 一行回滚验证：现有系统不依赖 factor_lib/
  4. 文档存在且完整
"""

import os
import sys
import time
import subprocess
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine
from factor_lib.backtester import FactorBacktester
from factor_lib.registry import FACTOR_REGISTRY

passed = 0
failed = 0
warnings = 0

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

def warn(name, detail=""):
    global warnings
    warnings += 1
    print(f"  ⚠️  {name}")
    if detail: print(f"     {detail}")

print("=" * 60)
print("S7 集成测试: 46 因子全测试 + 零侵入 + 回滚验证")
print("=" * 60)

# ═══════════════════════════════════════════
#  Part 1: 46 因子全测试
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("Part 1: 46 因子全测试 (IC + 回测)")
print("=" * 60)

all_factors = list(FACTOR_REGISTRY.keys())
print(f"  注册因子数: {len(all_factors)}")

# 按表分组加载
classic_factors = [f for f in all_factors if FACTOR_REGISTRY[f].table == "factor_values"]
evo_factors = [f for f in all_factors if FACTOR_REGISTRY[f].table == "factor_values_evo"]
print(f"  经典因子: {len(classic_factors)} (factor_values)")
print(f"  EVO 因子: {len(evo_factors)} (factor_values_evo)")

loader = FactorDataLoader()
ic_engine = ICEngine()
backtester = FactorBacktester(loader=loader)

# 用 6 个月数据加速
start_date = "20250101"
end_date = "20250630"

print(f"\n  数据区间: {start_date} ~ {end_date}")

# 加载经典因子
print(f"\n  加载经典因子 ({len(classic_factors)} 个)...")
t0 = time.time()
df_classic = loader.load_factor_values(classic_factors, start_date, end_date)
df_classic = loader.compute_forward_returns(df_classic, [5])
print(f"    行数: {len(df_classic)}, 天数: {df_classic['trade_date'].nunique()}, 耗时: {time.time()-t0:.1f}s")

# 加载 EVO 因子
print(f"\n  加载 EVO 因子 ({len(evo_factors)} 个)...")
t0 = time.time()
df_evo = loader.load_factor_values(evo_factors, start_date, end_date)
df_evo = loader.compute_forward_returns(df_evo, [5])
print(f"    行数: {len(df_evo)}, 天数: {df_evo['trade_date'].nunique()}, 耗时: {time.time()-t0:.1f}s")

# 逐因子测试
results = []
print(f"\n  逐因子测试开始...")
for i, fname in enumerate(all_factors):
    df = df_classic if fname in classic_factors else df_evo
    meta = FACTOR_REGISTRY[fname]
    row = {"factor": fname, "category": meta.category, "direction": meta.direction}

    try:
        # 检查数据可用性
        if fname not in df.columns:
            row["status"] = "NO_DATA"
            row["ic_mean"] = np.nan
            row["icir"] = np.nan
            row["sharpe"] = np.nan
            row["annual_ret"] = np.nan
            results.append(row)
            print(f"    [{i+1:2d}/{len(all_factors)}] {fname:25s} ⚠️  NO_DATA")
            continue

        valid_count = df[fname].notna().sum()
        if valid_count < 1000:
            row["status"] = "INSUFFICIENT"
            row["ic_mean"] = np.nan
            row["icir"] = np.nan
            row["sharpe"] = np.nan
            row["annual_ret"] = np.nan
            results.append(row)
            print(f"    [{i+1:2d}/{len(all_factors)}] {fname:25s} ⚠️  INSUFFICIENT ({valid_count} rows)")
            continue

        # IC
        ic_series = ic_engine.compute_ic_series(df, fname, "rank", "fwd_ret_5d")
        ic_summary = ic_engine.compute_ic_summary(ic_series)
        row["ic_mean"] = ic_summary["ic_mean"]
        row["icir"] = ic_summary["icir"]

        # 回测
        bt = backtester.run_backtest(df, fname, top_n=10, return_col="fwd_ret_5d")
        row["sharpe"] = bt.performance["sharpe"]
        row["annual_ret"] = bt.performance["annual_return"]
        row["max_dd"] = bt.performance["max_drawdown"]
        row["status"] = "OK"

        print(f"    [{i+1:2d}/{len(all_factors)}] {fname:25s} ✅ IC={row['ic_mean']:+.4f} ICIR={row['icir']:+.4f} Sharpe={row['sharpe']:+.4f}")

    except Exception as e:
        row["status"] = "ERROR"
        row["ic_mean"] = np.nan
        row["icir"] = np.nan
        row["sharpe"] = np.nan
        row["annual_ret"] = np.nan
        print(f"    [{i+1:2d}/{len(all_factors)}] {fname:25s} ❌ ERROR: {e}")

    results.append(row)

# 汇总
df_results = pd.DataFrame(results)
ok_count = (df_results["status"] == "OK").sum()
no_data_count = (df_results["status"] == "NO_DATA").sum()
insufficient_count = (df_results["status"] == "INSUFFICIENT").sum()
error_count = (df_results["status"] == "ERROR").sum()

print(f"\n  汇总: OK={ok_count}, NO_DATA={no_data_count}, INSUFFICIENT={insufficient_count}, ERROR={error_count}")

# 显示有效因子的排名
valid = df_results[df_results["status"] == "OK"].copy()
if len(valid) > 0:
    valid["abs_icir"] = valid["icir"].abs()
    valid = valid.sort_values("abs_icir", ascending=False)
    print(f"\n  有效因子排名 (按 |ICIR|):")
    print(f"  {'因子':25s} {'分类':15s} {'方向':6s} {'IC均值':>10s} {'ICIR':>8s} {'夏普':>8s} {'年化':>8s}")
    print(f"  {'-'*85}")
    for _, r in valid.iterrows():
        dir_str = "正向" if r["direction"] > 0 else "反向"
        print(f"  {r['factor']:25s} {r['category']:15s} {dir_str:6s} {r['ic_mean']:+10.4f} {r['icir']:+8.4f} {r['sharpe']:+8.4f} {r['annual_ret']:+8.2%}")

check("46 因子全测试不崩溃", error_count == 0, f"ERROR={error_count}")
check(f"有效因子 >= 30", ok_count >= 30, f"OK={ok_count}/{len(all_factors)}")

# ═══════════════════════════════════════════
#  Part 2: 零侵入验证
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("Part 2: 零侵入验证")
print("=" * 60)

# 检查 factor_lib/ 不 import agent/ 或 web/
factor_lib_dir = os.path.join(PROJECT_ROOT, "factor_lib")
factor_test_dir = os.path.join(PROJECT_ROOT, "factor_test")

# Grep for forbidden imports in factor_lib/
forbidden_patterns = [
    ("from agent", "agent import in factor_lib"),
    ("import agent", "agent import in factor_lib"),
    ("from web", "web import in factor_lib"),
    ("import web", "web import in factor_lib"),
    ("from app", "app import in factor_lib"),
    ("import app", "app import in factor_lib"),
]

found_forbidden = False
for pattern, desc in forbidden_patterns:
    result = subprocess.run(
        ["grep", "-r", pattern, factor_lib_dir, factor_test_dir, "--include=*.py"],
        capture_output=True, text=True
    )
    if result.stdout.strip():
        found_forbidden = True
        print(f"  ❌ 发现禁止导入: {desc}")
        print(f"     {result.stdout.strip()[:200]}")

check("factor_lib/ 不 import agent/ 或 web/", not found_forbidden)

# 检查 agent/ 和 web/ 不 import factor_lib/
reverse_patterns = [
    ("from factor_lib", "factor_lib import in agent/"),
    ("import factor_lib", "factor_lib import in agent/"),
    ("from factor_test", "factor_test import in agent/"),
]

found_reverse = False
dirs_to_check = []
agent_dir = os.path.join(PROJECT_ROOT, "agent")
web_dir = os.path.join(PROJECT_ROOT, "web")

for d in [agent_dir, web_dir]:
    if os.path.isdir(d):
        dirs_to_check.append(d)

for pattern, desc in reverse_patterns:
    for d in dirs_to_check:
        result = subprocess.run(
            ["grep", "-r", pattern, d, "--include=*.py"],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            found_reverse = True
            print(f"  ❌ 发现反向依赖: {desc} in {d}")
            print(f"     {result.stdout.strip()[:200]}")

check("agent/ 和 web/ 不 import factor_lib/", not found_reverse)

# 检查 factor_lib/ 依赖关系 (只依赖标准库 + 第三方库)
result = subprocess.run(
    ["grep", "-r", "^from\|^import", factor_lib_dir, "--include=*.py"],
    capture_output=True, text=True
)
# 提取所有导入的模块
imports = set()
for line in result.stdout.splitlines():
    if line.startswith("from ") or line.startswith("import "):
        # 提取模块名
        parts = line.split()
        if parts[0] == "from":
            mod = parts[1]
        else:
            mod = parts[1].split(".")[0]
        if mod not in ("factor_lib", "__future__"):
            imports.add(mod)

allowed = {"os", "sys", "json", "time", "warnings", "datetime",
           "typing", "dataclasses", "pathlib", "argparse",
           "numpy", "pandas", "scipy", "yaml"}
# scipy 子模块
scipy_subs = {"sps"}  # 如果有

external_imports = imports - allowed
if external_imports:
    # 检查是否都是允许的
    for imp in external_imports:
        if imp.startswith("scipy"):
            continue
        warn(f"外部依赖: {imp}")

check("factor_lib/ 只依赖允许的库", len(external_imports) == 0 or all(imp.startswith("scipy") for imp in external_imports),
      f"imports={sorted(imports)}")

# ═══════════════════════════════════════════
#  Part 3: 一行回滚验证
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("Part 3: 一行回滚验证")
print("=" * 60)

# 验证: 删除 factor_lib/ + factor_test/ 后现有系统不受影响
# 方法: 检查 agent/ 和 web/ 的所有 Python 文件不引用 factor_lib 或 factor_test

# 检查所有 Python 文件
all_py_files = []
for root_dir in [agent_dir, web_dir]:
    if not os.path.isdir(root_dir):
        continue
    for dirpath, _, filenames in os.walk(root_dir):
        for f in filenames:
            if f.endswith(".py"):
                all_py_files.append(os.path.join(dirpath, f))

# 也检查根目录的 Python 文件
for f in os.listdir(PROJECT_ROOT):
    if f.endswith(".py"):
        all_py_files.append(os.path.join(PROJECT_ROOT, f))

found_rollback_issue = False
for pyfile in all_py_files:
    try:
        with open(pyfile, "r") as f:
            content = f.read()
        if "factor_lib" in content or "factor_test" in content:
            found_rollback_issue = True
            print(f"  ❌ {pyfile} 引用了 factor_lib/factor_test")
    except:
        pass

check("删除 factor_lib/ + factor_test/ 后现有系统不受影响", not found_rollback_issue,
      f"扫描了 {len(all_py_files)} 个 Python 文件")

# 检查 config/ 目录是否有对 factor_lib 的引用
config_dir = os.path.join(PROJECT_ROOT, "config")
if os.path.isdir(config_dir):
    result = subprocess.run(
        ["grep", "-r", "factor_lib\|factor_test", config_dir],
        capture_output=True, text=True
    )
    # factor_test.yaml 本身是允许的 (它是因子测试模块自己的配置)
    config_refs = [l for l in result.stdout.splitlines() if "factor_test.yaml" not in l]
    check("config/ 不引用 factor_lib/ (factor_test.yaml 除外)", len(config_refs) == 0)

# ═══════════════════════════════════════════
#  Part 4: 文档完整性
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("Part 4: 文档完整性")
print("=" * 60)

doc_path = os.path.join(PROJECT_ROOT, "docs", "factor_test_module.md")
check("文档文件存在", os.path.exists(doc_path))

if os.path.exists(doc_path):
    with open(doc_path, "r") as f:
        doc = f.read()
    check("文档非空", len(doc) > 500, f"{len(doc)} 字符")
    check("含架构说明", "架构" in doc or "Architecture" in doc)
    check("含 CLI 用法", "CLI" in doc or "cli" in doc)
    check("含 API 参考", "API" in doc or "api" in doc)
    check("含因子列表", "因子" in doc)
    check("含配置说明", "配置" in doc or "config" in doc.lower())

# 检查 factor_lib/__init__.py 导出完整
check("factor_lib/__init__.py 存在", os.path.exists(os.path.join(factor_lib_dir, "__init__.py")))
check("factor_test/cli.py 存在", os.path.exists(os.path.join(factor_test_dir, "cli.py")))
check("config/factor_test.yaml 存在", os.path.exists(os.path.join(PROJECT_ROOT, "config", "factor_test.yaml")))

# ═══════════════════════════════════════════
#  Part 5: 模块完整性
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print("Part 5: 模块文件完整性")
print("=" * 60)

expected_files = [
    "factor_lib/__init__.py",
    "factor_lib/registry.py",
    "factor_lib/config.py",
    "factor_lib/loader.py",
    "factor_lib/ic_engine.py",
    "factor_lib/stratified_tester.py",
    "factor_lib/backtester.py",
    "factor_lib/anti_overfit.py",
    "factor_lib/reporter.py",
    "factor_test/__init__.py",
    "factor_test/cli.py",
    "config/factor_test.yaml",
]

for f in expected_files:
    path = os.path.join(PROJECT_ROOT, f)
    check(f"{f} 存在", os.path.exists(path))

# ═══════════════════════════════════════════
#  汇总
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print(f"S7 集成测试结果: {passed} PASS / {failed} FAIL / {warnings} WARN")
print("=" * 60)

# 保存因子测试结果
output_path = os.path.join(PROJECT_ROOT, "factor_test_reports", "all_factors_integration_test.csv")
df_results.to_csv(output_path, index=False, encoding="utf-8-sig")
print(f"\n  📄 因子测试结果: {output_path}")

if failed > 0:
    sys.exit(1)
else:
    print("🎉 S7 全部通过!")
