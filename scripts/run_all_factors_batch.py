#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方向 A1: 全因子批量测试
======================
一次性运行全部 46 个因子的完整测试（IC + 分层 + 回测 + 防过拟合），
输出汇总 CSV 供评级引擎使用。

用法:
  python3 scripts/run_all_factors_batch.py
  python3 scripts/run_all_factors_batch.py --start 20240101 --end 20260630
  python3 scripts/run_all_factors_batch.py --n-perm 50 --top-n 10
"""

import os
import sys
import time
import argparse
import sqlite3
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from factor_lib.registry import (
    FACTOR_REGISTRY, get_all_factor_names,
    get_classic_factor_names, get_evo_factor_names
)
from factor_lib.config import FactorTestConfig
from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine
from factor_lib.stratified_tester import StratifiedTester
from factor_lib.backtester import FactorBacktester
from factor_lib.anti_overfit import AntiOverfitChecker

import numpy as np
import pandas as pd

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    color = {
        "INFO": "\033[36m",
        "OK": "\033[32m",
        "WARN": "\033[33m",
        "ERR": "\033[31m",
        "HEAD": "\033[1;35m",
    }.get(level, "")
    end = "\033[0m"
    print(f"{color}[{ts}] [{level}]{end} {msg}")

def main():
    parser = argparse.ArgumentParser(description="全因子批量测试")
    parser.add_argument("--start", type=str, default="20240101", help="开始日期")
    parser.add_argument("--end", type=str, default=None, help="结束日期")
    parser.add_argument("--n-perm", type=int, default=50, help="置换检验次数")
    parser.add_argument("--top-n", type=int, default=10, help="Top-N 选股数")
    parser.add_argument("--n-groups", type=int, default=5, help="分层组数")
    parser.add_argument("--cost-bps", type=float, default=15.0, help="单边成本 bp")
    parser.add_argument("--output", type=str, default=None, help="输出 CSV 路径")
    parser.add_argument("--factors", type=str, default=None, help="指定因子（逗号分隔，默认全部）")
    args = parser.parse_args()

    cfg = FactorTestConfig()
    start_date = args.start
    end_date = args.end
    n_perm = args.n_perm
    top_n = args.top_n
    n_groups = args.n_groups
    cost_bps = args.cost_bps
    output_dir = os.path.join(PROJECT_ROOT, "factor_test_reports")
    os.makedirs(output_dir, exist_ok=True)

    output_path = args.output or os.path.join(output_dir, "all_factors_full_test.csv")

    # 确定要测试的因子
    if args.factors:
        factor_list = [f.strip() for f in args.factors.split(",") if f.strip()]
        # 验证
        invalid = [f for f in factor_list if f not in FACTOR_REGISTRY]
        if invalid:
            log(f"无效因子: {invalid}", "ERR")
            sys.exit(1)
    else:
        factor_list = get_all_factor_names()

    classic_factors = [f for f in factor_list if f in get_classic_factor_names()]
    evo_factors = [f for f in factor_list if f in get_evo_factor_names()]

    log(f"全因子批量测试启动", "HEAD")
    log(f"区间: {start_date} ~ {end_date or '最新'}")
    log(f"置换次数: {n_perm}  Top-N: {top_n}  组数: {n_groups}  成本: {cost_bps}bp")
    log(f"因子数: {len(factor_list)} (经典 {len(classic_factors)} + EVO {len(evo_factors)})")

    # 初始化引擎
    loader = FactorDataLoader()
    ic_engine = ICEngine()
    strat_tester = StratifiedTester(loader=loader)
    backtester = FactorBacktester(loader=loader)
    checker = AntiOverfitChecker(ic_engine=ic_engine)

    return_col = "fwd_ret_5d"

    all_results = []
    total_start = time.time()

    # ── 加载经典因子数据 ──
    if classic_factors:
        log(f"加载经典因子数据 ({len(classic_factors)} 个)...", "HEAD")
        t0 = time.time()
        df_classic = loader.load_factor_values(classic_factors, start_date, end_date)
        df_classic = loader.compute_forward_returns(df_classic, [1, 3, 5, 10, 20])
        log(f"经典因子数据加载完成: {len(df_classic):,} 行, {df_classic['trade_date'].nunique()} 天, 耗时 {time.time()-t0:.1f}s", "OK")
    else:
        df_classic = None

    # ── 加载 EVO 因子数据 ──
    if evo_factors:
        log(f"加载 EVO 因子数据 ({len(evo_factors)} 个)...", "HEAD")
        t0 = time.time()
        df_evo = loader.load_factor_values(evo_factors, start_date, end_date)
        df_evo = loader.compute_forward_returns(df_evo, [1, 3, 5, 10, 20])
        log(f"EVO 因子数据加载完成: {len(df_evo):,} 行, {df_evo['trade_date'].nunique()} 天, 耗时 {time.time()-t0:.1f}s", "OK")
    else:
        df_evo = None

    # ── 逐因子测试 ──
    log(f"开始逐因子测试 ({len(factor_list)} 个)...", "HEAD")

    for i, fname in enumerate(factor_list):
        meta = FACTOR_REGISTRY[fname]
        df = df_classic if fname in classic_factors else df_evo

        row = {
            "factor": fname,
            "category": meta.category,
            "direction": meta.direction,
            "table": meta.table,
            "description": meta.description,
        }

        # 检查数据可用性
        if fname not in df.columns:
            row["status"] = "NO_DATA"
            log(f"[{i+1}/{len(factor_list)}] {fname:30s} ⚠️  NO_DATA", "WARN")
            all_results.append(row)
            continue

        valid_count = df[fname].notna().sum()
        if valid_count < 1000:
            row["status"] = "INSUFFICIENT"
            row["valid_rows"] = valid_count
            log(f"[{i+1}/{len(factor_list)}] {fname:30s} ⚠️  INSUFFICIENT ({valid_count} rows)", "WARN")
            all_results.append(row)
            continue

        try:
            t_factor = time.time()

            # 1. IC
            ic_result = ic_engine.compute_full_report(df, fname, return_col)
            ic_summ = ic_result.get("rank_ic_summary", {})
            row["ic_mean"] = ic_summ.get("ic_mean")
            row["ic_std"] = ic_summ.get("ic_std")
            row["icir"] = ic_summ.get("icir")
            row["ic_t_stat"] = ic_summ.get("t_stat")
            row["ic_p_value"] = ic_summ.get("p_value")
            row["ic_positive_ratio"] = ic_summ.get("positive_ratio")
            row["ic_n_days"] = ic_summ.get("n_days")

            # IC 衰减 5d / 20d
            decay = ic_result.get("ic_decay", {})
            if isinstance(decay, pd.DataFrame) and len(decay) > 0:
                row["ic_5d"] = decay.loc[decay["period"] == 5, "ic_mean"].values[0] if 5 in decay["period"].values else None
                row["ic_20d"] = decay.loc[decay["period"] == 20, "ic_mean"].values[0] if 20 in decay["period"].values else None
                # 衰减率 (20d / 5d)
                ic5 = row.get("ic_5d")
                ic20 = row.get("ic_20d")
                if ic5 and ic20 and abs(ic5) > 0.001:
                    row["ic_decay_ratio"] = abs(ic20) / abs(ic5)
                else:
                    row["ic_decay_ratio"] = None

            # 2. 分层测试
            strat_result = strat_tester.run_stratified_test(
                df, fname, n_groups=n_groups, return_col=return_col,
                rebalance_freq="weekly", cost_bps=cost_bps
            )
            row["monotonicity_score"] = strat_result.monotonicity_score
            row["monotonicity_pvalue"] = strat_result.monotonicity_pvalue
            row["avg_turnover"] = strat_result.avg_turnover
            # 多空年化收益
            ls_nav = strat_result.long_short_nav
            if len(ls_nav) > 1:
                ls_total = ls_nav.iloc[-1] - 1
                n_periods = len(ls_nav) - 1
                row["ls_annual_return"] = (1 + ls_total) ** (52 / n_periods) - 1 if n_periods > 0 else None
                row["ls_total_return"] = ls_total

            # 3. 回测
            bt_result = backtester.run_backtest(
                df, fname, top_n=top_n, return_col=return_col,
                rebalance_freq="weekly", cost_bps=cost_bps
            )
            perf = bt_result.performance
            row["annual_return"] = perf["annual_return"]
            row["annual_volatility"] = perf["annual_volatility"]
            row["sharpe"] = perf["sharpe"]
            row["sortino"] = perf["sortino"]
            row["max_drawdown"] = perf["max_drawdown"]
            row["calmar"] = perf["calmar"]
            row["win_rate"] = perf["win_rate"]
            row["profit_loss_ratio"] = perf["profit_loss_ratio"]
            row["bt_n_periods"] = perf["n_periods"]
            row["bt_turnover"] = bt_result.turnover.mean() if len(bt_result.turnover) > 0 else None

            # 4. 防过拟合
            ao_result = checker.run_full_check(df, fname, return_col, n_perm=n_perm)

            in_samp = ao_result.get("in_sample_oos", {})
            row["train_icir"] = in_samp.get("train_icir")
            row["test_icir"] = in_samp.get("test_icir")
            row["icir_decay"] = in_samp.get("icir_decay")
            row["direction_consistent_is"] = in_samp.get("direction_consistent")

            wf = ao_result.get("walk_forward", {})
            row["wf_n_windows"] = wf.get("n_windows")
            row["wf_ic_positive_ratio"] = wf.get("ic_positive_ratio")
            row["wf_direction_consistency"] = wf.get("direction_consistency_ratio")
            row["wf_pass"] = wf.get("pass")

            perm = ao_result.get("permutation_test", {})
            row["perm_p_value"] = perm.get("p_value")
            row["perm_n"] = perm.get("n_permutations")
            row["perm_significant"] = perm.get("significant")

            subp = ao_result.get("subperiod_stability", {})
            row["subp_n_years"] = subp.get("n_years")
            row["subp_consistent_ratio"] = subp.get("consistent_ratio")
            row["subp_pass"] = subp.get("pass")

            autoc = ao_result.get("ic_autocorrelation", {})
            row["ac_lag1"] = autoc.get("autocorr_lag1")
            row["ac_lag5"] = autoc.get("autocorr_lag5")
            row["ac_lag10"] = autoc.get("autocorr_lag10")
            row["ac_has_persistence"] = autoc.get("has_persistence")

            row["status"] = "OK"

            elapsed = time.time() - t_factor
            log(f"[{i+1}/{len(factor_list)}] {fname:30s} ✅ ICIR={row['icir']:+.4f} Sharpe={row['sharpe']:+.4f} Mono={row['monotonicity_score']:.3f} PermP={row['perm_p_value']:.4f} | {elapsed:.1f}s", "OK")

        except Exception as e:
            row["status"] = "ERROR"
            row["error"] = str(e)
            log(f"[{i+1}/{len(factor_list)}] {fname:30s} ❌ ERROR: {e}", "ERR")
            import traceback
            traceback.print_exc()

        all_results.append(row)

    # ── 保存结果 ──
    df_results = pd.DataFrame(all_results)
    df_results.to_csv(output_path, index=False, encoding="utf-8-sig")

    total_elapsed = time.time() - total_start

    # ── 汇总 ──
    log(f"", "HEAD")
    log(f"{'═' * 60}", "HEAD")
    log(f"全因子批量测试完成", "HEAD")
    log(f"{'═' * 60}", "HEAD")

    status_counts = df_results["status"].value_counts()
    log(f"状态统计: {dict(status_counts)}")

    valid = df_results[df_results["status"] == "OK"].copy()
    if len(valid) > 0:
        valid["abs_icir"] = valid["icir"].abs()
        valid = valid.sort_values("abs_icir", ascending=False)

        log(f"\nTop 10 by |ICIR|:", "HEAD")
        for _, r in valid.head(10).iterrows():
            log(f"  {r['factor']:30s} |ICIR|={abs(r['icir']):.4f} Sharpe={r['sharpe']:+.4f} Mono={r['monotonicity_score']:.3f}")

    log(f"\n结果已保存: {output_path}", "OK")
    log(f"总耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)", "OK")
    log(f"平均每因子: {total_elapsed/len(factor_list):.1f}s", "OK")

    return output_path

if __name__ == "__main__":
    main()
