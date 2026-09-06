#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方向 A: 两阶段全因子筛选
==========================
阶段 1 (快速): 全部 46 因子跑 IC + 分层 + 回测 (跳过置换)
阶段 2 (深测): Top N 因子补跑防过拟合 (置换检验)

比一次性跑完全量快 3-4 倍，且能快速看到初步排名。
"""

import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from factor_lib.registry import FACTOR_REGISTRY, get_all_factor_names
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
        "INFO": "\033[36m", "OK": "\033[32m", "WARN": "\033[33m",
        "ERR": "\033[31m", "HEAD": "\033[1;35m", "STEP": "\033[1;34m",
    }.get(level, "")
    end = "\033[0m"
    print(f"{color}[{ts}] [{level}]{end} {msg}", flush=True)

def run_fast_screen(start_date, end_date, top_n, n_groups, cost_bps):
    """阶段 1: 快速筛选 - IC + 分层 + 回测"""
    log("═══ 阶段 1: 快速筛选 (IC + 分层 + 回测) ═══", "STEP")

    loader = FactorDataLoader()
    ic_engine = ICEngine()
    strat_tester = StratifiedTester(loader=loader)
    backtester = FactorBacktester(loader=loader)

    all_factors = get_all_factor_names()
    classic = [f for f in all_factors if FACTOR_REGISTRY[f].table == "factor_values"]
    evo = [f for f in all_factors if FACTOR_REGISTRY[f].table == "factor_values_evo"]
    return_col = "fwd_ret_5d"

    log(f"因子数: {len(all_factors)} (经典 {len(classic)} + EVO {len(evo)})")
    total_start = time.time()

    # 加载经典因子
    log(f"加载经典因子 ({len(classic)} 个)...")
    t0 = time.time()
    df_classic = loader.load_factor_values(classic, start_date, end_date)
    df_classic = loader.compute_forward_returns(df_classic, [5])
    log(f"经典数据: {len(df_classic):,} 行, {df_classic['trade_date'].nunique()} 天, {time.time()-t0:.1f}s", "OK")

    # 加载 EVO 因子
    log(f"加载 EVO 因子 ({len(evo)} 个)...")
    t0 = time.time()
    df_evo = loader.load_factor_values(evo, start_date, end_date)
    df_evo = loader.compute_forward_returns(df_evo, [5])
    log(f"EVO 数据: {len(df_evo):,} 行, {df_evo['trade_date'].nunique()} 天, {time.time()-t0:.1f}s", "OK")

    results = []
    for i, fname in enumerate(all_factors):
        meta = FACTOR_REGISTRY[fname]
        df = df_classic if fname in classic else df_evo

        row = {"factor": fname, "category": meta.category,
               "direction": meta.direction, "table": meta.table}

        if fname not in df.columns:
            row["status"] = "NO_DATA"
            log(f"[{i+1}/{len(all_factors)}] {fname:30s} ⚠️  NO_DATA", "WARN")
            results.append(row)
            continue

        if df[fname].notna().sum() < 1000:
            row["status"] = "INSUFFICIENT"
            results.append(row)
            log(f"[{i+1}/{len(all_factors)}] {fname:30s} ⚠️  INSUFFICIENT", "WARN")
            continue

        try:
            t0 = time.time()

            # IC
            ic_result = ic_engine.compute_full_report(df, fname, return_col)
            ic_s = ic_result.get("rank_ic_summary", {})
            row["ic_mean"] = ic_s.get("ic_mean")
            row["icir"] = ic_s.get("icir")
            row["ic_p_value"] = ic_s.get("p_value")
            row["ic_positive_ratio"] = ic_s.get("positive_ratio")
            row["ic_n_days"] = ic_s.get("n_days")

            # IC 衰减
            decay = ic_result.get("ic_decay", {})
            if isinstance(decay, pd.DataFrame) and len(decay) > 0:
                ic5 = decay.loc[decay["period"] == 5, "ic_mean"].values[0] if 5 in decay["period"].values else None
                ic20 = decay.loc[decay["period"] == 20, "ic_mean"].values[0] if 20 in decay["period"].values else None
                row["ic_5d"] = ic5
                row["ic_20d"] = ic20
                if ic5 and ic20 and abs(ic5) > 0.001:
                    row["ic_decay_ratio"] = abs(ic20) / abs(ic5)

            # 分层
            strat = strat_tester.run_stratified_test(
                df, fname, n_groups=n_groups, return_col=return_col,
                rebalance_freq="weekly", cost_bps=cost_bps
            )
            row["monotonicity_score"] = strat.monotonicity_score
            row["monotonicity_pvalue"] = strat.monotonicity_pvalue
            row["avg_turnover"] = strat.avg_turnover
            ls_nav = strat.long_short_nav
            if len(ls_nav) > 1:
                ls_total = ls_nav.iloc[-1] - 1
                n_p = len(ls_nav) - 1
                row["ls_annual_return"] = (1 + ls_total) ** (52 / n_p) - 1 if n_p > 0 else None
                row["ls_total_return"] = ls_total

            # 回测
            bt = backtester.run_backtest(
                df, fname, top_n=top_n, return_col=return_col,
                rebalance_freq="weekly", cost_bps=cost_bps
            )
            p = bt.performance
            row["annual_return"] = p["annual_return"]
            row["annual_volatility"] = p["annual_volatility"]
            row["sharpe"] = p["sharpe"]
            row["sortino"] = p["sortino"]
            row["max_drawdown"] = p["max_drawdown"]
            row["calmar"] = p["calmar"]
            row["win_rate"] = p["win_rate"]
            row["profit_loss_ratio"] = p["profit_loss_ratio"]
            row["bt_n_periods"] = p["n_periods"]
            row["bt_turnover"] = bt.turnover.mean() if len(bt.turnover) > 0 else None

            row["status"] = "OK"
            elapsed = time.time() - t0
            log(f"[{i+1}/{len(all_factors)}] {fname:30s} ✅ ICIR={row['icir']:+.4f} Sharpe={row['sharpe']:+.4f} Mono={row['monotonicity_score']:.3f} | {elapsed:.1f}s", "OK")

        except Exception as e:
            row["status"] = "ERROR"
            row["error"] = str(e)
            log(f"[{i+1}/{len(all_factors)}] {fname:30s} ❌ {e}", "ERR")

        results.append(row)

    df_results = pd.DataFrame(results)
    total_time = time.time() - total_start

    ok_count = (df_results["status"] == "OK").sum()
    log(f"阶段 1 完成: {ok_count}/{len(all_factors)} 有效，耗时 {total_time:.1f}s", "OK")

    return df_results, df_classic, df_evo, loader

def run_deep_test(df_results, df_classic, df_evo, loader, n_perm, top_n):
    """阶段 2: 对 Top N 因子补充防过拟合校验"""
    log("", "STEP")
    log("═══ 阶段 2: 深测 Top 20 因子 (防过拟合) ═══", "STEP")

    valid = df_results[df_results["status"] == "OK"].copy()
    valid["abs_icir"] = valid["icir"].abs()
    top_factors = valid.nlargest(20, "abs_icir")["factor"].tolist()

    log(f"Top 20 by |ICIR|: {', '.join(top_factors[:10])}...")

    ic_engine = ICEngine()
    checker = AntiOverfitChecker(ic_engine=ic_engine)
    return_col = "fwd_ret_5d"

    classic_names = set()
    evo_names = set()
    for f in top_factors:
        if FACTOR_REGISTRY[f].table == "factor_values":
            classic_names.add(f)
        else:
            evo_names.add(f)

    ao_results = {}
    total_start = time.time()

    for i, fname in enumerate(top_factors):
        df = df_classic if fname in classic_names else df_evo
        try:
            t0 = time.time()
            ao = checker.run_full_check(df, fname, return_col, n_perm=n_perm)
            elapsed = time.time() - t0

            # 提取关键指标
            perm = ao.get("permutation_test", {})
            subp = ao.get("subperiod_stability", {})
            autoc = ao.get("ic_autocorrelation", {})
            wf = ao.get("walk_forward", {})
            in_samp = ao.get("in_sample_oos", {})

            ao_results[fname] = {
                "perm_p_value": perm.get("p_value"),
                "perm_significant": perm.get("significant"),
                "subp_consistent_ratio": subp.get("consistent_ratio"),
                "subp_pass": subp.get("pass"),
                "ac_lag1": autoc.get("autocorr_lag1"),
                "ac_has_persistence": autoc.get("has_persistence"),
                "wf_direction_consistency": wf.get("direction_consistency_ratio"),
                "wf_pass": wf.get("pass"),
                "train_icir": in_samp.get("train_icir"),
                "test_icir": in_samp.get("test_icir"),
                "icir_decay": in_samp.get("icir_decay"),
                "direction_consistent_is": in_samp.get("direction_consistent"),
            }
            log(f"[{i+1}/{len(top_factors)}] {fname:30s} ✅ perm_p={perm.get('p_value'):.4f} AC1={autoc.get('autocorr_lag1'):.3f} | {elapsed:.1f}s", "OK")
        except Exception as e:
            log(f"[{i+1}/{len(top_factors)}] {fname:30s} ❌ {e}", "ERR")
            ao_results[fname] = {"error": str(e)}

    total_time = time.time() - total_start
    log(f"阶段 2 完成: {len(ao_results)} 因子，耗时 {total_time:.1f}s", "OK")

    return ao_results

def merge_results(df_results, ao_results):
    """合并快筛 + 深测结果"""
    df = df_results.copy()
    for fname, ao in ao_results.items():
        mask = df["factor"] == fname
        for k, v in ao.items():
            df.loc[mask, k] = v
    # 有防过拟合结果的标记为 FULL，没有的为 FAST
    df["test_level"] = df["factor"].apply(
        lambda f: "FULL" if f in ao_results else "FAST"
    )
    return df

def main():
    import argparse
    parser = argparse.ArgumentParser(description="两阶段全因子筛选")
    parser.add_argument("--start", type=str, default="20250101")
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--n-perm", type=int, default=20, help="深测阶段置换次数")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--n-groups", type=int, default=5)
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--deep-top", type=int, default=20, help="深测 Top N")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--skip-deep", action="store_true", help="只跑快筛阶段")
    args = parser.parse_args()

    report_dir = os.path.join(PROJECT_ROOT, "factor_test_reports")
    os.makedirs(report_dir, exist_ok=True)
    output_path = args.output or os.path.join(report_dir, "all_factors_full_test.csv")

    log("═" * 60, "HEAD")
    log("方向 A: 两阶段全因子筛选", "HEAD")
    log("═" * 60, "HEAD")
    log(f"区间: {args.start} ~ {args.end or '最新'}")
    log(f"快筛: 全部因子 (IC + 分层 + 回测)")
    log(f"深测: Top {args.deep_top} 因子 (防过拟合, 置换 {args.n_perm} 次)")

    total_start = time.time()

    # 阶段 1
    df_results, df_classic, df_evo, loader = run_fast_screen(
        args.start, args.end, args.top_n, args.n_groups, args.cost_bps
    )

    # 阶段 2
    ao_results = {}
    if not args.skip_deep:
        ao_results = run_deep_test(
            df_results, df_classic, df_evo, loader,
            n_perm=args.n_perm, top_n=args.top_n
        )

    # 合并
    df_final = merge_results(df_results, ao_results)
    df_final.to_csv(output_path, index=False, encoding="utf-8-sig")

    total_time = time.time() - total_start

    # 汇总
    log("", "HEAD")
    log("═" * 60, "HEAD")
    log("全因子筛选完成", "HEAD")
    log("═" * 60, "HEAD")

    status_counts = df_final["status"].value_counts().to_dict()
    log(f"状态: {status_counts}")
    log(f"总耗时: {total_time:.1f}s ({total_time/60:.1f} min)")

    # Top 10
    valid = df_final[df_final["status"] == "OK"].copy()
    if len(valid) > 0:
        valid["abs_icir"] = valid["icir"].abs()
        valid = valid.sort_values("abs_icir", ascending=False)
        log(f"\nTop 10 by |ICIR|:")
        for _, r in valid.head(10).iterrows():
            level = r.get("test_level", "FAST")
            lvl_str = "FULL" if level == "FULL" else "FAST"
            log(f"  {r['factor']:30s} |ICIR|={abs(r['icir']):.4f} Sharpe={r['sharpe']:+.3f} [{lvl_str}]")

    log(f"\n📄 结果: {output_path}")
    log(f"   快筛: {len(df_final)} 因子")
    log(f"   深测: {len(ao_results)} 因子 (Top {args.deep_top})")

if __name__ == "__main__":
    main()
