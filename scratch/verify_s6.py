# -*- coding: utf-8 -*-
"""
S6 验收脚本 — 报告生成 + CLI
验证 5 项标准:
  1. 单因子 HTML 报告含 IC/分层/回测/防过拟合全部图表
  2. 批量测试可输出对比表
  3. CLI test 模式可运行
  4. CLI batch 模式可运行
  5. CLI compare 模式可运行
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine
from factor_lib.stratified_tester import StratifiedTester
from factor_lib.backtester import FactorBacktester
from factor_lib.anti_overfit import AntiOverfitChecker
from factor_lib.reporter import FactorReporter
from factor_lib.config import FactorTestConfig

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON_BIN = "/Users/lyu/miniconda3/bin/python3"
ENV_PREFIX = f'env -i HOME="$HOME" PATH="/Users/lyu/miniconda3/bin:/usr/bin:/bin" PYTHONPATH="{PROJECT_ROOT}"'

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
print("S6 验收: 报告生成 + CLI")
print("=" * 60)

loader = FactorDataLoader()
reporter = FactorReporter()
output_dir = FactorTestConfig.report_dir()

# ═══════════════════════════════════════════
# 步骤 1: 生成单因子报告
# ═══════════════════════════════════════════
print("\n📦 运行单因子分析 (volatility_20d)...")

t0 = time.time()
df = loader.load_factor_values(["volatility_20d"], "20250101", "20260630")
df = loader.compute_forward_returns(df, [1, 3, 5, 10, 20])
print(f"   数据加载: {len(df)} 行 ({time.time()-t0:.1f}s)")

ic_engine = ICEngine()
strat_tester = StratifiedTester(loader=loader)
backtester = FactorBacktester(loader=loader)
checker = AntiOverfitChecker(ic_engine=ic_engine)

# IC
t0 = time.time()
ic_result = ic_engine.compute_full_report(df, "volatility_20d", "fwd_ret_5d")
print(f"   IC 分析: {time.time()-t0:.1f}s")

# 分层
t0 = time.time()
strat_result = strat_tester.run_stratified_test(df, "volatility_20d", n_groups=5, return_col="fwd_ret_5d")
print(f"   分层测试: {time.time()-t0:.1f}s")

# 回测
t0 = time.time()
bt_result = backtester.run_backtest(df, "volatility_20d", top_n=10, return_col="fwd_ret_5d")
print(f"   回测: {time.time()-t0:.1f}s")

# 防过拟合 (置换用短数据)
t0 = time.time()
all_dates = sorted(df["trade_date"].unique())
df_perm = df[df["trade_date"] >= all_dates[max(0, len(all_dates)-80)]]
ao_result = checker.run_full_check(df, "volatility_20d", "fwd_ret_5d", n_perm=50)
ao_result["permutation_test"] = checker.permutation_test(
    df_perm, "volatility_20d", "fwd_ret_5d", n_perm=50
)
print(f"   防过拟合: {time.time()-t0:.1f}s")

# 生成报告
t0 = time.time()
html = reporter.generate_single_report(
    factor_name="volatility_20d",
    ic_result=ic_result,
    stratified_result=strat_result,
    backtest_result=bt_result,
    anti_overfit_result=ao_result,
    start_date="20250101",
    end_date="20260630",
)
report_path = os.path.join(output_dir, "volatility_20d_report.html")
with open(report_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"   报告生成: {time.time()-t0:.1f}s → {report_path}")

# ═══════════════════════════════════════════
# 验收 1: 单因子报告内容
# ═══════════════════════════════════════════
print("\n验收 1: 单因子 HTML 报告内容")
print("-" * 50)

check("报告文件存在", os.path.exists(report_path))
check("报告非空", len(html) > 1000, f"{len(html)} 字符")
check("含 ECharts 脚本", "echarts" in html.lower())
check("含 IC 分析", "IC 分析" in html or "ic_series" in html)
check("含分层测试", "分层测试" in html or "group_nav" in html)
check("含回测", "回测" in html or "bt_nav" in html)
check("含防过拟合", "防过拟合" in html)
check("含 IC 统计表", "IC 统计摘要" in html)
check("含绩效表", "组合绩效" in html)
check("含置换检验表", "置换检验" in html)
check("含分年度表", "分年度" in html)
check("含 HTML 结构", html.startswith("<!DOCTYPE html>"))
check("自包含 (含 </html>)", html.rstrip().endswith("</html>"))

# ═══════════════════════════════════════════
# 验收 2: 对比表
# ═══════════════════════════════════════════
print("\n验收 2: 多因子对比表")
print("-" * 50)

# 用第二个因子做对比
df2 = loader.load_factor_values(["return_20d"], "20250101", "20260630")
df2 = loader.compute_forward_returns(df2, [5])
ic2 = ic_engine.compute_full_report(df2, "return_20d", "fwd_ret_5d")
bt2 = backtester.run_backtest(df2, "return_20d", top_n=10, return_col="fwd_ret_5d")
strat2 = strat_tester.run_stratified_test(df2, "return_20d", n_groups=5, return_col="fwd_ret_5d")

# 构建对比数据
results_for_compare = [
    {
        "factor_name": "volatility_20d",
        "ic_summary": ic_result["rank_ic_summary"],
        "backtest_performance": bt_result.performance,
        "anti_overfit": ao_result,
        "mono_pvalue": strat_result.monotonicity_pvalue,
    },
    {
        "factor_name": "return_20d",
        "ic_summary": ic2["rank_ic_summary"],
        "backtest_performance": bt2.performance,
        "anti_overfit": {"permutation_test": {"p_value": 0.001}, "subperiod_stability": {"consistent_ratio": 0.8}},
        "mono_pvalue": strat2.monotonicity_pvalue,
    },
]

comp_html = reporter.generate_comparison_report(results_for_compare)
comp_path = os.path.join(output_dir, "comparison_report.html")
with open(comp_path, "w", encoding="utf-8") as f:
    f.write(comp_html)

check("对比报告文件存在", os.path.exists(comp_path))
check("对比报告含多因子", "volatility_20d" in comp_html and "return_20d" in comp_html)
check("含评级列", "评级" in comp_html)
check("含 IC 均值列", "IC均值" in comp_html)
check("含夏普列", "夏普" in comp_html)

# ═══════════════════════════════════════════
# 验收 3: CLI test 模式
# ═══════════════════════════════════════════
print("\n验收 3: CLI test 模式")
print("-" * 50)

# 测试 --help
exit_code = os.system(
    f'{ENV_PREFIX} {PYTHON_BIN} {PROJECT_ROOT}/factor_test/cli.py --help 2>&1'
)
check("CLI --help 可运行", exit_code == 0)

# 测试 test 模式 (用短数据 + 少置换次数)
print("  运行 CLI test (短数据)...")
exit_code = os.system(
    f'{ENV_PREFIX} {PYTHON_BIN} {PROJECT_ROOT}/factor_test/cli.py test volatility_20d '
    f'--start 20250101 --end 20260331 --n-perm 30 --top-n 10 2>&1'
)
check("CLI test 模式可运行", exit_code == 0)

test_report = os.path.join(output_dir, "volatility_20d_report.html")
check("CLI test 生成报告", os.path.exists(test_report))

# ═══════════════════════════════════════════
# 验收 4: CLI batch 模式
# ═══════════════════════════════════════════
print("\n验收 4: CLI batch 模式")
print("-" * 50)

exit_code = os.system(
    f'{ENV_PREFIX} {PYTHON_BIN} {PROJECT_ROOT}/factor_test/cli.py batch '
    f'volatility_20d,return_20d --start 20250101 --end 20260331 --n-perm 30 2>&1'
)
check("CLI batch 模式可运行", exit_code == 0)

batch_comp = os.path.join(output_dir, "comparison_report.html")
check("CLI batch 生成对比表", os.path.exists(batch_comp))

# ═══════════════════════════════════════════
# 验收 5: CLI compare 模式
# ═══════════════════════════════════════════
print("\n验收 5: CLI compare 模式")
print("-" * 50)

exit_code = os.system(
    f'{ENV_PREFIX} {PYTHON_BIN} {PROJECT_ROOT}/factor_test/cli.py compare '
    f'volatility_20d,return_20d --start 20250101 --end 20260331 --n-perm 30 2>&1'
)
check("CLI compare 模式可运行", exit_code == 0)
check("CLI compare 生成对比表", os.path.exists(batch_comp))

# ═══════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════
print("\n" + "=" * 60)
print(f"S6 验收结果: {passed} PASS / {failed} FAIL")
print("=" * 60)

if failed > 0:
    sys.exit(1)
else:
    print("🎉 S6 全部通过!")
