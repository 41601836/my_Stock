#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli.py — 因子测试 & 收益验证模块 CLI
=================================================
三种模式:
  test    : 单因子完整测试 → HTML 报告
  batch   : 批量测试 → 各自报告 + 对比表
  compare : 多因子对比 → 仅对比表

用法:
  python factor_test/cli.py test volatility_20d
  python factor_test/cli.py batch volatility_20d,return_20d,pe_ttm
  python factor_test/cli.py compare volatility_20d,return_20d
"""

import os
import sys
import argparse
import time
import warnings

warnings.filterwarnings("ignore")

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np

from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine, check_direction_consistency
from factor_lib.stratified_tester import StratifiedTester
from factor_lib.backtester import FactorBacktester
from factor_lib.anti_overfit import AntiOverfitChecker
from factor_lib.reporter import FactorReporter
from factor_lib.config import FactorTestConfig
from factor_lib.registry import FACTOR_REGISTRY


def run_single_factor(
    factor_name: str,
    start_date: str = "20240101",
    end_date: str = None,
    n_perm: int = 100,
    top_n: int = 10,
    n_groups: int = 5,
    cost_bps: float = 15.0,
    loader: FactorDataLoader = None,
) -> dict:
    """对单因子运行全部分析，返回结果字典。"""
    if loader is None:
        loader = FactorDataLoader()
    ic_engine = ICEngine()
    strat_tester = StratifiedTester(loader=loader)
    backtester = FactorBacktester(loader=loader)
    checker = AntiOverfitChecker(ic_engine=ic_engine)
    reporter = FactorReporter()

    print(f"\n{'='*50}")
    print(f"  因子: {factor_name}")
    meta = FACTOR_REGISTRY.get(factor_name)
    if meta:
        print(f"  方向: {'正向' if meta.direction > 0 else '反向'} | 分类: {meta.category}")
    print(f"  区间: {start_date} ~ {end_date or '最新'}")
    print(f"{'='*50}")

    # 1. 加载数据
    t0 = time.time()
    df = loader.load_factor_values([factor_name], start_date, end_date)
    df = loader.compute_forward_returns(df, [1, 3, 5, 10, 20])
    print(f"  [1/5] 数据加载: {len(df)} 行, {df['trade_date'].nunique()} 天 ({time.time()-t0:.1f}s)")

    # 2. IC 分析
    t0 = time.time()
    ic_result = ic_engine.compute_full_report(df, factor_name, "fwd_ret_5d")
    print(f"  [2/5] IC 分析: IC={ic_result['rank_ic_summary']['ic_mean']:.6f}, "
          f"ICIR={ic_result['rank_ic_summary']['icir']:.4f} ({time.time()-t0:.1f}s)")

    # 2.5 方向元数据 vs 实测 IC 符号一致性校验（P0-1：方向做反自动暴露）
    dir_check = {"severity": "ok", "message": "无 registry 元数据，跳过方向校验"}
    if meta:
        dir_check = check_direction_consistency(meta, ic_result["rank_ic_summary"])
        if dir_check["severity"] == "mismatch":
            print(f"  ❌ [方向告警] {dir_check['message']}")
        elif dir_check["severity"] == "suspect":
            print(f"  ⚠️  [方向提示] {dir_check['message']}")

    # 3. 分层测试
    t0 = time.time()
    strat_result = strat_tester.run_stratified_test(
        df, factor_name, n_groups=n_groups, return_col="fwd_ret_5d",
        rebalance_freq="weekly", cost_bps=cost_bps
    )
    print(f"  [3/5] 分层测试: {len(strat_result.group_returns)} 期, "
          f"单调性={strat_result.monotonicity_score:.4f} ({time.time()-t0:.1f}s)")

    # 4. 回测
    t0 = time.time()
    bt_result = backtester.run_backtest(
        df, factor_name, top_n=top_n, return_col="fwd_ret_5d",
        rebalance_freq="weekly", cost_bps=cost_bps, benchmark="equal_weight"
    )
    perf = bt_result.performance
    print(f"  [4/5] 回测: 年化={perf['annual_return']:.2%}, "
          f"夏普={perf['sharpe']:.4f}, 回撤={perf['max_drawdown']:.2%} ({time.time()-t0:.1f}s)")

    # 5. 防过拟合 (置换检验用近 6 个月数据提速)
    t0 = time.time()
    # 取近 6 个月数据做置换检验
    all_dates = sorted(df["trade_date"].unique())
    perm_end = end_date or all_dates[-1]
    perm_start_idx = max(0, len(all_dates) - 120)
    perm_start = all_dates[perm_start_idx]
    df_perm = df[df["trade_date"] >= perm_start]

    ao_result = checker.run_full_check(
        df, factor_name, "fwd_ret_5d", n_perm=n_perm
    )
    # 覆盖置换检验 (用短数据)
    if len(df_perm) > 0:
        ao_result["permutation_test"] = checker.permutation_test(
            df_perm, factor_name, "fwd_ret_5d", n_perm=n_perm
        )
    perm_p = ao_result["permutation_test"].get("p_value", 1)
    print(f"  [5/5] 防过拟合: 置换p={perm_p:.4f}, "
          f"AC(1)={ao_result['ic_autocorrelation']['autocorr_lag1']:.4f} ({time.time()-t0:.1f}s)")

    return {
        "factor_name": factor_name,
        "start_date": start_date,
        "end_date": end_date or all_dates[-1],
        "ic_result": ic_result,
        "stratified_result": strat_result,
        "backtest_result": bt_result,
        "anti_overfit_result": ao_result,
        "ic_summary": ic_result["rank_ic_summary"],
        "backtest_performance": bt_result.performance,
        "anti_overfit": ao_result,
        "mono_pvalue": strat_result.monotonicity_pvalue,
        "direction_check": dir_check,
    }


def save_single_report(result: dict, output_dir: str = None):
    """保存单因子 HTML 报告。"""
    output_dir = output_dir or FactorTestConfig.report_dir()
    reporter = FactorReporter()

    html = reporter.generate_single_report(
        factor_name=result["factor_name"],
        ic_result=result["ic_result"],
        stratified_result=result["stratified_result"],
        backtest_result=result["backtest_result"],
        anti_overfit_result=result["anti_overfit_result"],
        start_date=result["start_date"],
        end_date=result["end_date"],
        direction_check=result.get("direction_check"),
    )

    filename = f"{result['factor_name']}_report.html"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  📄 报告已保存: {filepath}")
    return filepath


def save_comparison_report(results: list, output_dir: str = None):
    """保存多因子对比 HTML 报告。"""
    output_dir = output_dir or FactorTestConfig.report_dir()
    reporter = FactorReporter()
    html = reporter.generate_comparison_report(results)
    filepath = os.path.join(output_dir, "comparison_report.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  📄 对比报告已保存: {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="因子测试 & 收益验证模块",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python factor_test/cli.py test volatility_20d
  python factor_test/cli.py test return_20d --start 20230101 --n-perm 200
  python factor_test/cli.py batch volatility_20d,return_20d,pe_ttm
  python factor_test/cli.py compare volatility_20d,return_20d,pe_ttm,pb,roe
        """
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # test
    p_test = sub.add_parser("test", help="单因子完整测试")
    p_test.add_argument("factor", help="因子名称")
    p_test.add_argument("--start", default="20240101", help="开始日期 (YYYYMMDD)")
    p_test.add_argument("--end", default=None, help="结束日期")
    p_test.add_argument("--n-perm", type=int, default=100, help="置换检验次数")
    p_test.add_argument("--top-n", type=int, default=10, help="Top-N 选股数")
    p_test.add_argument("--n-groups", type=int, default=5, help="分层组数")
    p_test.add_argument("--cost-bps", type=float, default=15.0, help="单边交易成本(bp)")
    p_test.add_argument("--output-dir", default=None, help="输出目录")

    # batch
    p_batch = sub.add_parser("batch", help="批量测试 (各自报告 + 对比表)")
    p_batch.add_argument("factors", help="逗号分隔的因子名称")
    p_batch.add_argument("--start", default="20240101")
    p_batch.add_argument("--end", default=None)
    p_batch.add_argument("--n-perm", type=int, default=50, help="置换检验次数(批量默认较少)")
    p_batch.add_argument("--top-n", type=int, default=10)
    p_batch.add_argument("--output-dir", default=None)

    # compare
    p_cmp = sub.add_parser("compare", help="多因子对比 (仅对比表)")
    p_cmp.add_argument("factors", help="逗号分隔的因子名称")
    p_cmp.add_argument("--start", default="20240101")
    p_cmp.add_argument("--end", default=None)
    p_cmp.add_argument("--n-perm", type=int, default=50)
    p_cmp.add_argument("--top-n", type=int, default=10)
    p_cmp.add_argument("--output-dir", default=None)

    args = parser.parse_args()

    # 校验因子名
    if args.mode in ("batch", "compare"):
        factor_list = [f.strip() for f in args.factors.split(",")]
        for f in factor_list:
            if f not in FACTOR_REGISTRY:
                print(f"❌ 未知因子: {f}")
                print(f"   可用因子: {', '.join(list(FACTOR_REGISTRY.keys())[:10])}...")
                sys.exit(1)
    elif args.mode == "test":
        if args.factor not in FACTOR_REGISTRY:
            print(f"❌ 未知因子: {args.factor}")
            print(f"   可用因子: {', '.join(list(FACTOR_REGISTRY.keys()))}")
            sys.exit(1)

    # 执行
    if args.mode == "test":
        result = run_single_factor(
            args.factor, args.start, args.end, args.n_perm,
            args.top_n, args.n_groups, args.cost_bps
        )
        save_single_report(result, args.output_dir)

    elif args.mode == "batch":
        loader = FactorDataLoader()
        results = []
        for f in factor_list:
            try:
                result = run_single_factor(
                    f, args.start, args.end, args.n_perm, args.top_n,
                    loader=loader
                )
                save_single_report(result, args.output_dir)
                results.append(result)
            except Exception as e:
                print(f"  ⚠️ 因子 {f} 测试失败: {e}")
                import traceback; traceback.print_exc()

        if results:
            save_comparison_report(results, args.output_dir)

    elif args.mode == "compare":
        loader = FactorDataLoader()
        results = []
        for f in factor_list:
            try:
                result = run_single_factor(
                    f, args.start, args.end, args.n_perm, args.top_n,
                    loader=loader
                )
                results.append(result)
            except Exception as e:
                print(f"  ⚠️ 因子 {f} 测试失败: {e}")

        if results:
            save_comparison_report(results, args.output_dir)
        else:
            print("❌ 无有效结果")


if __name__ == "__main__":
    main()
