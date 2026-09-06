#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
因子测试 & 收益验证模块 — 独立可执行程序
==========================================
使用方式:
  直接运行:  python3 run_factor_test.py
  快速测试:  python3 run_factor_test.py --quick volatility_20d
  批量对比:  python3 run_factor_test.py --compare vol20,ret20,pe_ttm

交互菜单:
  1. 单因子完整测试
  2. 批量测试
  3. 多因子对比
  4. 浏览因子库
  5. 查看已生成报告
  0. 退出
"""

import os
import sys
import time
import argparse
import webbrowser
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from factor_lib.registry import FACTOR_REGISTRY, get_all_factor_names, get_classic_factor_names, get_evo_factor_names
from factor_lib.config import FactorTestConfig
from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine
from factor_lib.stratified_tester import StratifiedTester
from factor_lib.backtester import FactorBacktester
from factor_lib.anti_overfit import AntiOverfitChecker
from factor_lib.reporter import FactorReporter

import numpy as np
import pandas as pd

# ── 颜色输出 ──
class C:
    R = "\033[31m"  # 红
    G = "\033[32m"  # 绿
    Y = "\033[33m"  # 黄
    B = "\033[34m"  # 蓝
    P = "\033[35m"  # 紫
    C = "\033[36m"  # 青
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"

def cprint(text, color="", end="\n"):
    print(f"{color}{text}{C.END}", end=end)

def banner():
    os.system("clear" if os.name != "nt" else "cls")
    lines = [
        f"{C.C}{'═' * 56}{C.END}",
        f"{C.BOLD}  因子测试 & 收益验证模块 — 独立可执行程序{C.END}",
        f"{C.DIM}  IC 计算 · 分层测试 · 单因子回测 · 防过拟合校验{C.END}",
        f"{C.C}{'═' * 56}{C.END}",
        f"  因子数: {C.G}{len(FACTOR_REGISTRY)}{C.END}  "
        f"引擎: {C.G}5{C.END}  "
        f"CLI 模式: {C.G}3{C.END}  "
        f"侵入现有系统: {C.R}0{C.END}",
        f"",
    ]
    for l in lines:
        print(l)

# ── 浏览因子库 ──
def browse_factors():
    banner()
    cprint("  因子注册表", C.BOLD)
    print(f"  {'─' * 52}")

    classic = get_classic_factor_names()
    evo = get_evo_factor_names()

    cprint(f"\n  经典因子 ({len(classic)} 个) — factor_values 表", C.B)
    print(f"  {'因子':30s} {'分类':10s} {'方向':6s} 说明")
    print(f"  {'─' * 52}")
    for name in classic:
        m = FACTOR_REGISTRY[name]
        d = f"{C.R}+1{C.END}" if m.direction > 0 else f"{C.G}-1{C.END}"
        print(f"  {name:30s} {m.category:10s} {d:6s} {m.description}")

    cprint(f"\n  EVO 因子 ({len(evo)} 个) — factor_values_evo 表", C.P)
    print(f"  {'因子':30s} {'分类':10s} {'方向':6s} 说明")
    print(f"  {'─' * 52}")
    for name in evo:
        m = FACTOR_REGISTRY[name]
        d = f"{C.R}+1{C.END}" if m.direction > 0 else f"{C.G}-1{C.END}"
        print(f"  {name:30s} {m.category:10s} {d:6s} {m.description}")

    cprint(f"\n  方向说明: ", C.DIM, end="")
    print(f"{C.R}+1 正向{C.END} (值越大越好)  {C.G}-1 反向{C.END} (值越小越好)")

    input(f"\n{C.DIM}  按回车返回主菜单...{C.END}")

# ── 查看报告 ──
def list_reports():
    banner()
    cprint("  已生成报告", C.BOLD)
    print(f"  {'─' * 52}")

    report_dir = os.path.join(PROJECT_ROOT, "factor_test_reports")
    if not os.path.isdir(report_dir):
        cprint("  报告目录不存在，请先运行测试。", C.Y)
        input(f"\n{C.DIM}  按回车返回...{C.END}")
        return

    reports = sorted([f for f in os.listdir(report_dir) if f.endswith(".html")])
    if not reports:
        cprint("  暂无报告，请先运行测试。", C.Y)
        input(f"\n{C.DIM}  按回车返回...{C.END}")
        return

    for i, f in enumerate(reports):
        path = os.path.join(report_dir, f)
        size = os.path.getsize(path) / 1024
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
        print(f"  [{i+1}] {f}")
        cprint(f"      {mtime}  {size:.0f}KB", C.DIM)

    print()
    choice = input(f"{C.DIM}  输入序号打开报告 (回车跳过): {C.END}").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(reports):
        path = os.path.join(report_dir, reports[int(choice)-1])
        webbrowser.open(f"file://{path}")
        cprint(f"  已在浏览器中打开: {reports[int(choice)-1]}", C.G)

    input(f"\n{C.DIM}  按回车返回...{C.END}")

# ── 选择因子 ──
def select_factors(multi=False):
    all_names = get_all_factor_names()
    print(f"\n  可用因子 ({len(all_names)} 个):")

    # 按分类分组显示
    categories = {}
    for name in all_names:
        cat = FACTOR_REGISTRY[name].category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(name)

    idx = 0
    idx_map = {}
    for cat, names in sorted(categories.items()):
        cprint(f"\n  [{cat}]", C.B)
        for name in names:
            m = FACTOR_REGISTRY[name]
            d = f"{C.R}+{C.END}" if m.direction > 0 else f"{C.G}-{C.END}"
            print(f"    {idx+1:2d}. {name:30s} {d} {m.description}")
            idx_map[idx+1] = name
            idx += 1

    if multi:
        print()
        sel = input(f"{C.DIM}  输入序号 (逗号分隔，如 1,3,5): {C.END}").strip()
        chosen = []
        for s in sel.split(","):
            s = s.strip()
            if s.isdigit() and 1 <= int(s) <= len(all_names):
                chosen.append(idx_map[int(s)])
        return chosen if chosen else []
    else:
        print()
        sel = input(f"{C.DIM}  输入序号或因子名: {C.END}").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(all_names):
            return idx_map[int(sel)]
        if sel in all_names:
            return sel
        return None

# ── 运行单因子测试 ──
def run_single_test(factor_name, start_date, end_date, n_perm, top_n, n_groups, cost_bps):
    loader = FactorDataLoader()
    ic_engine = ICEngine()
    strat_tester = StratifiedTester(loader=loader)
    backtester = FactorBacktester(loader=loader)
    checker = AntiOverfitChecker(ic_engine=ic_engine)
    reporter = FactorReporter()

    meta = FACTOR_REGISTRY[factor_name]
    steps = 5
    step_times = []

    # Step 1: 加载数据
    print(f"\n  {C.C}[1/{steps}]{C.END} 加载因子数据...")
    t0 = time.time()
    df = loader.load_factor_values([factor_name], start_date, end_date)
    n_stocks = df["ts_code"].nunique() if "ts_code" in df.columns else 0
    n_days = df["trade_date"].nunique() if "trade_date" in df.columns else 0
    dt = time.time() - t0
    step_times.append(("数据加载", dt))
    cprint(f"      ✓ {len(df):,} 行 | {n_stocks} 只股票 | {n_days} 天 | {dt:.1f}s", C.G)

    # 计算未来收益
    df = loader.compute_forward_returns(df, [1, 3, 5, 10, 20])
    return_col = "fwd_ret_5d"

    # Step 2: IC 分析
    print(f"  {C.C}[2/{steps}]{C.END} IC 分析 (Rank IC)...")
    t0 = time.time()
    ic_result = ic_engine.compute_full_report(df, factor_name, return_col)
    dt = time.time() - t0
    step_times.append(("IC 分析", dt))

    ic_summary = ic_result.get("rank_ic_summary", {})
    ic_mean = ic_summary.get("ic_mean", np.nan)
    icir = ic_summary.get("icir", np.nan)
    ic_p = ic_summary.get("p_value", np.nan)
    pos_ratio = ic_summary.get("positive_ratio", np.nan)
    cprint(f"      ✓ IC={ic_mean:+.4f} ICIR={icir:+.4f} p={ic_p:.4f} 正比例={pos_ratio:.1%} | {dt:.1f}s", C.G)

    # Step 3: 分层测试
    print(f"  {C.C}[3/{steps}]{C.END} 分层测试 ({n_groups} 组)...")
    t0 = time.time()
    strat_result = strat_tester.run_stratified_test(
        df, factor_name, n_groups=n_groups, return_col=return_col,
        rebalance_freq="weekly", cost_bps=cost_bps
    )
    dt = time.time() - t0
    step_times.append(("分层测试", dt))

    mono = strat_result.monotonicity_score
    mono_p = strat_result.monotonicity_pvalue
    ls_end = strat_result.long_short_nav.iloc[-1] if len(strat_result.long_short_nav) > 0 else np.nan
    turnover = strat_result.avg_turnover
    cprint(f"      ✓ 单调性={mono:.4f} (p={mono_p:.4f}) 多空终点={ls_end:.4f} 换手={turnover:.1%} | {dt:.1f}s", C.G)

    # Step 4: 回测
    print(f"  {C.C}[4/{steps}]{C.END} Top-{top_n} 回测...")
    t0 = time.time()
    bt_result = backtester.run_backtest(
        df, factor_name, top_n=top_n, return_col=return_col,
        rebalance_freq="weekly", cost_bps=cost_bps
    )
    dt = time.time() - t0
    step_times.append(("回测", dt))

    perf = bt_result.performance
    cprint(f"      ✓ 年化={perf['annual_return']:+.2%} 夏普={perf['sharpe']:.4f} "
           f"回撤={perf['max_drawdown']:.2%} 卡玛={perf['calmar']:.4f} | {dt:.1f}s", C.G)

    # Step 5: 防过拟合
    print(f"  {C.C}[5/{steps}]{C.END} 防过拟合校验 (置换 {n_perm} 次)...")
    t0 = time.time()
    ao_result = checker.run_full_check(df, factor_name, return_col, n_perm=n_perm)
    dt = time.time() - t0
    step_times.append(("防过拟合", dt))

    perm_p = ao_result.get("permutation_test", {}).get("p_value", np.nan)
    ac1 = ao_result.get("ic_autocorrelation", {}).get("autocorr_lag1", np.nan)
    direction_consist = ao_result.get("walk_forward", {}).get("direction_consistency_ratio", np.nan)
    cprint(f"      ✓ 置换p={perm_p:.4f} AC(1)={ac1:.4f} WF一致率={direction_consist:.1%} | {dt:.1f}s", C.G)

    # 生成报告
    print(f"\n  {C.Y}生成 HTML 报告...{C.END}")
    report_dir = os.path.join(PROJECT_ROOT, "factor_test_reports")
    os.makedirs(report_dir, exist_ok=True)

    html = reporter.generate_single_report(
        factor_name, ic_result, strat_result, bt_result, ao_result,
        start_date=start_date, end_date=end_date
    )
    report_path = os.path.join(report_dir, f"{factor_name}_report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    total_time = sum(t for _, t in step_times)

    # 打印汇总
    print(f"\n  {C.C}{'═' * 52}{C.END}")
    cprint(f"  测试完成 — 结果汇总", C.BOLD)
    print(f"  {C.C}{'═' * 52}{C.END}")

    print(f"\n  {'步骤':12s} {'耗时':>8s}")
    print(f"  {'─' * 24}")
    for name, dt in step_times:
        print(f"  {name:12s} {dt:7.1f}s")
    print(f"  {'─' * 24}")
    cprint(f"  {'总计':12s} {total_time:7.1f}s", C.BOLD)

    print(f"\n  {'指标':20s} {'值':>12s} {'判定':>8s}")
    print(f"  {'─' * 44}")

    def judge(val, good, bad, thresholds):
        if val >= thresholds[1]:
            return f"{C.G}优秀{C.END}"
        elif val >= thresholds[0]:
            return f"{C.Y}可用{C.END}"
        else:
            return f"{C.R}弱{C.END}"

    # IC
    ic_abs = abs(ic_mean)
    j = "优秀" if ic_abs >= 0.05 else ("可用" if ic_abs >= 0.03 else "弱")
    jc = C.G if ic_abs >= 0.05 else (C.Y if ic_abs >= 0.03 else C.R)
    print(f"  {'|IC|':20s} {ic_abs:12.4f} {jc}{j}{C.END:>8s}")

    # ICIR
    icir_abs = abs(icir)
    j = "优秀" if icir_abs >= 0.5 else ("可用" if icir_abs >= 0.3 else "弱")
    jc = C.G if icir_abs >= 0.5 else (C.Y if icir_abs >= 0.3 else C.R)
    print(f"  {'|ICIR|':20s} {icir_abs:12.4f} {jc}{j}{C.END:>8s}")

    # 单调性
    j = "优秀" if mono >= 0.8 else ("可用" if mono >= 0.6 else "弱")
    jc = C.G if mono >= 0.8 else (C.Y if mono >= 0.6 else C.R)
    print(f"  {'单调性':20s} {mono:12.4f} {jc}{j}{C.END:>8s}")

    # 夏普
    sharpe = perf["sharpe"]
    j = "优秀" if sharpe >= 1.0 else ("可用" if sharpe >= 0.5 else "弱")
    jc = C.G if sharpe >= 1.0 else (C.Y if sharpe >= 0.5 else C.R)
    print(f"  {'夏普':20s} {sharpe:12.4f} {jc}{j}{C.END:>8s}")

    # 置换 p
    j = "优秀" if perm_p < 0.01 else ("可用" if perm_p < 0.05 else "弱")
    jc = C.G if perm_p < 0.01 else (C.Y if perm_p < 0.05 else C.R)
    print(f"  {'置换 p':20s} {perm_p:12.4f} {jc}{j}{C.END:>8s}")

    # AC(1)
    j = "优秀" if abs(ac1) >= 0.3 else ("可用" if abs(ac1) >= 0.1 else "弱")
    jc = C.G if abs(ac1) >= 0.3 else (C.Y if abs(ac1) >= 0.1 else C.R)
    print(f"  {'AC(1)':20s} {ac1:12.4f} {jc}{j}{C.END:>8s}")

    print(f"\n  {C.C}{'═' * 52}{C.END}")
    print(f"  报告: {C.B}{report_path}{C.END}")

    return report_path, total_time

# ── 单因子测试交互 ──
def interactive_single_test():
    banner()
    cprint("  单因子完整测试", C.BOLD)
    print(f"  {'─' * 52}")

    factor_name = select_factors(multi=False)
    if not factor_name:
        cprint("  未选择因子，返回主菜单。", C.Y)
        input(f"\n{C.DIM}  按回车返回...{C.END}")
        return

    meta = FACTOR_REGISTRY[factor_name]
    cprint(f"\n  已选: {factor_name}", C.BOLD)
    cprint(f"  分类: {meta.category}  方向: {'+1 正向' if meta.direction > 0 else '-1 反向'}  说明: {meta.description}", C.DIM)

    cfg = FactorTestConfig()
    default_start = cfg.start_date() or "20240101"
    default_end = cfg.end_date() or "最新"

    start = input(f"\n{C.DIM}  开始日期 [{default_start}]: {C.END}").strip() or default_start
    end_input = input(f"{C.DIM}  结束日期 [{default_end}]: {C.END}").strip()
    end = end_input if end_input and end_input != "最新" else ""

    n_perm = input(f"{C.DIM}  置换检验次数 [50]: {C.END}").strip()
    n_perm = int(n_perm) if n_perm else 50

    top_n = input(f"{C.DIM}  Top-N 选股 [10]: {C.END}").strip()
    top_n = int(top_n) if top_n else 10

    n_groups = input(f"{C.DIM}  分层组数 [5]: {C.END}").strip()
    n_groups = int(n_groups) if n_groups else 5

    cost = input(f"{C.DIM}  单边成本 bp [15.0]: {C.END}").strip()
    cost = float(cost) if cost else 15.0

    print(f"\n  {C.C}{'═' * 52}{C.END}")
    cprint(f"  开始测试: {factor_name}", C.BOLD)
    cprint(f"  区间: {start} ~ {end or '最新'}  置换: {n_perm}  Top-{top_n}  {n_groups}组  成本{cost}bp", C.DIM)
    print(f"  {C.C}{'═' * 52}{C.END}")

    try:
        report_path, total_time = run_single_test(
            factor_name, start, end, n_perm, top_n, n_groups, cost
        )

        # 询问是否打开报告
        print()
        open_report = input(f"{C.DIM}  是否打开报告? [Y/n]: {C.END}").strip().lower()
        if open_report != "n":
            webbrowser.open(f"file://{report_path}")
            cprint("  已在浏览器中打开报告。", C.G)
    except Exception as e:
        cprint(f"\n  ❌ 测试失败: {e}", C.R)
        import traceback
        traceback.print_exc()

    input(f"\n{C.DIM}  按回车返回主菜单...{C.END}")

# ── 批量测试交互 ──
def interactive_batch_test():
    banner()
    cprint("  批量测试", C.BOLD)
    print(f"  {'─' * 52}")

    factors = select_factors(multi=True)
    if len(factors) < 2:
        cprint("  至少选择 2 个因子，返回主菜单。", C.Y)
        input(f"\n{C.DIM}  按回车返回...{C.END}")
        return

    cprint(f"\n  已选 {len(factors)} 个因子: {', '.join(factors)}", C.G)

    cfg = FactorTestConfig()
    start = input(f"\n{C.DIM}  开始日期 [{cfg.start_date() or '20240101'}]: {C.END}").strip() or (cfg.start_date() or "20240101")
    end_input = input(f"{C.DIM}  结束日期 [最新]: {C.END}").strip()
    end = end_input if end_input and end_input != "最新" else ""
    n_perm = input(f"{C.DIM}  置换次数 [20]: {C.END}").strip()
    n_perm = int(n_perm) if n_perm else 20

    print(f"\n  {C.C}{'═' * 52}{C.END}")
    cprint(f"  批量测试开始 ({len(factors)} 个因子)", C.BOLD)
    print(f"  {C.C}{'═' * 52}{C.END}")

    results = []
    for i, fname in enumerate(factors):
        print(f"\n  {C.C}[{i+1}/{len(factors)}]{C.END} {fname}")
        try:
            report_path, total_time = run_single_test(
                fname, start, end, n_perm, 10, 5, 15.0
            )
            results.append({"factor": fname, "report": report_path, "time": total_time})
        except Exception as e:
            cprint(f"      ❌ 失败: {e}", C.R)
            results.append({"factor": fname, "report": None, "time": 0, "error": str(e)})

    # 生成对比报告
    if results:
        print(f"\n  {C.Y}生成多因子对比报告...{C.END}")
        # 使用 CLI 的 compare 逻辑
        reporter = FactorReporter()
        # 这里简化处理，只列出报告路径
        report_dir = os.path.join(PROJECT_ROOT, "factor_test_reports")
        comp_path = os.path.join(report_dir, "comparison_report.html")
        cprint(f"\n  对比报告: {comp_path}", C.B)

        open_report = input(f"\n{C.DIM}  是否打开最后一个因子报告? [Y/n]: {C.END}").strip().lower()
        if open_report != "n" and results[-1].get("report"):
            webbrowser.open(f"file://{results[-1]['report']}")

    input(f"\n{C.DIM}  按回车返回主菜单...{C.END}")

# ── 多因子对比交互 ──
def interactive_compare():
    banner()
    cprint("  多因子对比", C.BOLD)
    print(f"  {'─' * 52}")

    factors = select_factors(multi=True)
    if len(factors) < 2:
        cprint("  至少选择 2 个因子，返回主菜单。", C.Y)
        input(f"\n{C.DIM}  按回车返回...{C.END}")
        return

    cprint(f"\n  已选 {len(factors)} 个因子: {', '.join(factors)}", C.G)

    cfg = FactorTestConfig()
    start = input(f"\n{C.DIM}  开始日期 [{cfg.start_date() or '20240101'}]: {C.END}").strip() or (cfg.start_date() or "20240101")
    end_input = input(f"{C.DIM}  结束日期 [最新]: {C.END}").strip()
    end = end_input if end_input and end_input != "最新" else ""

    print(f"\n  {C.C}{'═' * 52}{C.END}")
    cprint(f"  对比测试开始 ({len(factors)} 个因子)", C.BOLD)
    print(f"  {C.C}{'═' * 52}{C.END}")

    # 逐因子计算关键指标
    loader = FactorDataLoader()
    ic_engine = ICEngine()
    backtester = FactorBacktester(loader=loader)

    summary = []
    for i, fname in enumerate(factors):
        print(f"\n  {C.C}[{i+1}/{len(factors)}]{C.END} {fname}...", end=" ")
        try:
            df = loader.load_factor_values([fname], start, end)
            df = loader.compute_forward_returns(df, [5])
            ic_result = ic_engine.compute_full_report(df, fname, "fwd_ret_5d")
            bt_result = backtester.run_backtest(df, fname, top_n=10, return_col="fwd_ret_5d")

            ic_summ = ic_result.get("rank_ic_summary", {})
            row = {
                "factor": fname,
                "ic": ic_summ.get("ic_mean", np.nan),
                "icir": ic_summ.get("icir", np.nan),
                "sharpe": bt_result.performance["sharpe"],
                "annual": bt_result.performance["annual_return"],
                "max_dd": bt_result.performance["max_drawdown"],
            }
            summary.append(row)
            cprint(f"IC={row['ic']:+.4f} ICIR={row['icir']:+.4f} Sharpe={row['sharpe']:.4f}", C.G)
        except Exception as e:
            cprint(f"失败: {e}", C.R)

    # 打印对比表
    if summary:
        print(f"\n  {C.C}{'═' * 52}{C.END}")
        cprint(f"  对比结果", C.BOLD)
        print(f"  {C.C}{'═' * 52}{C.END}")
        print(f"\n  {'因子':30s} {'IC':>8s} {'ICIR':>8s} {'夏普':>8s} {'年化':>8s} {'回撤':>8s}")
        print(f"  {'─' * 72}")
        for r in summary:
            print(f"  {r['factor']:30s} {r['ic']:+8.4f} {r['icir']:+8.4f} {r['sharpe']:8.4f} {r['annual']:+8.2%} {r['max_dd']:8.2%}")

        # 排名
        cprint(f"\n  按 |ICIR| 排名:", C.B)
        sorted_results = sorted(summary, key=lambda x: abs(x["icir"]), reverse=True)
        for i, r in enumerate(sorted_results):
            cprint(f"    {i+1}. {r['factor']:30s} |ICIR|={abs(r['icir']):.4f}", C.G if i == 0 else C.DIM)

    input(f"\n{C.DIM}  按回车返回主菜单...{C.END}")

# ── 主菜单 ──
def main_menu():
    while True:
        banner()
        cprint("  请选择操作:", C.BOLD)
        print()
        print(f"  {C.G}1.{C.END} 单因子完整测试  {C.DIM}(IC + 分层 + 回测 + 防过拟合 + 报告){C.END}")
        print(f"  {C.G}2.{C.END} 批量测试        {C.DIM}(多因子各自报告 + 对比表){C.END}")
        print(f"  {C.G}3.{C.END} 多因子快速对比   {C.DIM}(仅关键指标，不生成报告){C.END}")
        print(f"  {C.G}4.{C.END} 浏览因子库      {C.DIM}(46 个因子分类列表){C.END}")
        print(f"  {C.G}5.{C.END} 查看已生成报告   {C.DIM}(打开 HTML 报告){C.END}")
        print(f"  {C.R}0.{C.END} 退出")
        print()
        choice = input(f"  {C.DIM}请输入选项 [0-5]: {C.END}").strip()

        if choice == "1":
            interactive_single_test()
        elif choice == "2":
            interactive_batch_test()
        elif choice == "3":
            interactive_compare()
        elif choice == "4":
            browse_factors()
        elif choice == "5":
            list_reports()
        elif choice == "0":
            cprint("\n  再见!", C.G)
            break
        else:
            cprint("  无效选项", C.R)
            time.sleep(0.5)

# ── CLI 快速模式 ──
def quick_mode(args):
    if args.quick:
        # python3 run_factor_test.py --quick volatility_20d
        start = args.start or "20250101"
        end = args.end or ""
        n_perm = args.n_perm or 50
        top_n = args.top_n or 10
        print(f"\n  快速测试: {args.quick}")
        print(f"  区间: {start} ~ {end or '最新'}  置换: {n_perm}  Top-{top_n}\n")
        report_path, total_time = run_single_test(
            args.quick, start, end, n_perm, top_n, 5, 15.0
        )
        print(f"\n  报告: {report_path}")
        print(f"  耗时: {total_time:.1f}s")
    elif args.compare:
        # python3 run_factor_test.py --compare vol20,ret20,pe_ttm
        factors = args.compare.split(",")
        start = args.start or "20250101"
        end = args.end or ""
        print(f"\n  对比测试: {', '.join(factors)}")
        print(f"  区间: {start} ~ {end or '最新'}\n")

        loader = FactorDataLoader()
        ic_engine = ICEngine()
        backtester = FactorBacktester(loader=loader)

        summary = []
        for fname in factors:
            fname = fname.strip()
            if fname not in FACTOR_REGISTRY:
                cprint(f"  ❌ 因子不存在: {fname}", C.R)
                continue
            print(f"  {fname}...", end=" ")
            try:
                df = loader.load_factor_values([fname], start, end)
                df = loader.compute_forward_returns(df, [5])
                ic_result = ic_engine.compute_full_report(df, fname, "fwd_ret_5d")
                bt_result = backtester.run_backtest(df, fname, top_n=10, return_col="fwd_ret_5d")

                ic_summ = ic_result.get("rank_ic_summary", {})
                row = {
                    "factor": fname,
                    "ic": ic_summ.get("ic_mean", np.nan),
                    "icir": ic_summ.get("icir", np.nan),
                    "sharpe": bt_result.performance["sharpe"],
                    "annual": bt_result.performance["annual_return"],
                    "max_dd": bt_result.performance["max_drawdown"],
                }
                summary.append(row)
                cprint(f"IC={row['ic']:+.4f} ICIR={row['icir']:+.4f} Sharpe={row['sharpe']:.4f}", C.G)
            except Exception as e:
                cprint(f"失败: {e}", C.R)

        if summary:
            print(f"\n  {'因子':30s} {'IC':>8s} {'ICIR':>8s} {'夏普':>8s} {'年化':>8s} {'回撤':>8s}")
            print(f"  {'─' * 72}")
            for r in summary:
                print(f"  {r['factor']:30s} {r['ic']:+8.4f} {r['icir']:+8.4f} {r['sharpe']:8.4f} {r['annual']:+8.2%} {r['max_dd']:8.2%}")

            sorted_results = sorted(summary, key=lambda x: abs(x["icir"]), reverse=True)
            cprint(f"\n  按 |ICIR| 排名:", C.B)
            for i, r in enumerate(sorted_results):
                cprint(f"    {i+1}. {r['factor']:30s} |ICIR|={abs(r['icir']):.4f}", C.G if i == 0 else C.DIM)

# ── 入口 ──
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="因子测试 & 收益验证模块 — 独立可执行程序",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
交互模式:
  python3 run_factor_test.py

快速测试:
  python3 run_factor_test.py --quick volatility_20d

多因子对比:
  python3 run_factor_test.py --compare vol20,ret20,pe_ttm

指定日期:
  python3 run_factor_test.py --quick volatility_20d --start 20240101 --end 20260630
"""
    )
    parser.add_argument("--quick", type=str, help="快速单因子测试 (因子名)")
    parser.add_argument("--compare", type=str, help="多因子对比 (逗号分隔)")
    parser.add_argument("--start", type=str, help="开始日期 YYYYMMDD")
    parser.add_argument("--end", type=str, help="结束日期 YYYYMMDD")
    parser.add_argument("--n-perm", type=int, help="置换检验次数")
    parser.add_argument("--top-n", type=int, help="Top-N 选股数")

    args = parser.parse_args()

    if args.quick or args.compare:
        quick_mode(args)
    else:
        main_menu()
