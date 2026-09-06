#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方向 B2: 多因子组合回测对比
==============================
用独立因子池构建多因子组合，对比多种合成方法的回测表现。

因子来源: 方向 A 输出的 independent_factors.csv（5 个独立代表因子）
对比方法: 等权 / ICIR加权 / IC加权 / 最大化IC / 风险平价 / 排名平均
对比基准: 单因子最优解（ICIR 最高的因子）
"""

import os
import sys
import time
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from factor_lib.registry import FACTOR_REGISTRY, get_all_factor_names
from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine
from factor_lib.backtester import FactorBacktester
from factor_lib.stratified_tester import StratifiedTester
from factor_lib.multi_factor import MultiFactorCombiner, run_multi_factor_compare

import numpy as np
import pandas as pd
from typing import List

REPORT_DIR = os.path.join(PROJECT_ROOT, "factor_test_reports")


def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    color = {
        "INFO": "\033[36m", "OK": "\033[32m", "WARN": "\033[33m",
        "ERR": "\033[31m", "HEAD": "\033[1;35m", "STEP": "\033[1;34m",
    }.get(level, "")
    end = "\033[0m"
    print(f"{color}[{ts}] [{level}]{end} {msg}", flush=True)


def load_independent_factors(top_n: int = 5) -> List[str]:
    """从独立因子结果中加载因子列表"""
    path = os.path.join(REPORT_DIR, "independent_factors.csv")
    if not os.path.exists(path):
        log(f"独立因子文件不存在: {path}", "ERR")
        sys.exit(1)
    df = pd.read_csv(path)
    factors = df["representative"].head(top_n).tolist()
    return factors


def main():
    import argparse
    parser = argparse.ArgumentParser(description="多因子组合回测对比")
    parser.add_argument("--start", type=str, default="20250101")
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--top-n-factors", type=int, default=5,
                        help="使用前 N 个独立因子")
    parser.add_argument("--top-n-stocks", type=int, default=10,
                        help="Top-N 选股数")
    parser.add_argument("--n-groups", type=int, default=5)
    parser.add_argument("--cost-bps", type=float, default=15.0)
    parser.add_argument("--rebalance", type=str, default="weekly",
                        choices=["daily", "weekly"])
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    log("═" * 60, "HEAD")
    log("方向 B2: 多因子组合回测对比", "HEAD")
    log("═" * 60, "HEAD")

    # 加载独立因子
    factors = load_independent_factors(args.top_n_factors)
    log(f"独立因子池 ({len(factors)} 个): {', '.join(factors)}")

    # 按表分类
    classic_factors = [f for f in factors if FACTOR_REGISTRY[f].table == "factor_values"]
    evo_factors = [f for f in factors if FACTOR_REGISTRY[f].table == "factor_values_evo"]
    log(f"  经典因子: {classic_factors}")
    log(f"  EVO 因子: {evo_factors}")

    total_start = time.time()

    # 加载数据
    log("加载因子数据...", "STEP")
    loader = FactorDataLoader()

    df_list = []
    if classic_factors:
        df_c = loader.load_factor_values(classic_factors, args.start, args.end)
        df_list.append(df_c)
    if evo_factors:
        df_e = loader.load_factor_values(evo_factors, args.start, args.end)
        df_list.append(df_e)

    if len(df_list) == 1:
        df = df_list[0]
    else:
        # 合并经典 + EVO
        common_cols = ["trade_date", "ts_code", "close_adj"]
        df = df_list[0].merge(df_list[1], on=common_cols, how="inner", suffixes=("", "_evo"))

    df = loader.compute_forward_returns(df, [5])
    return_col = "fwd_ret_5d"

    log(f"数据量: {len(df):,} 行, {df['trade_date'].nunique()} 天", "OK")

    # 过滤有效因子
    valid_factors = [f for f in factors if f in df.columns and df[f].notna().sum() > 1000]
    log(f"有效因子: {len(valid_factors)}/{len(factors)}")

    if len(valid_factors) < 2:
        log("有效因子不足 2 个，无法合成", "ERR")
        sys.exit(1)

    # 合成 + 回测
    log("多因子合成 + 回测...", "STEP")
    methods = ["equal_weight", "icir_weighted", "ic_weighted",
               "risk_parity", "rank_average"]
    # max_ic 容易数值不稳定，暂不默认启用

    df_work = df.copy()
    bt_results = {}

    for method in methods:
        try:
            t0 = time.time()

            # 合成
            combiner = MultiFactorCombiner(FACTOR_REGISTRY, method=method)
            df_work = combiner.combine(df_work, valid_factors,
                                       return_col=return_col,
                                       output_col=f"score_{method}")
            score_col = f"score_{method}"
            weights = combiner.get_weights()

            # IC
            daily_ic = df_work.groupby("trade_date").apply(
                lambda g: g[score_col].corr(g[return_col], method="spearman")
            )
            ic_mean = daily_ic.mean()
            ic_std = daily_ic.std() if daily_ic.std() > 0 else 1e-6
            icir = ic_mean / ic_std

            # 手动回测
            df_bt = df_work.copy()
            df_bt["rank"] = df_bt.groupby("trade_date")[score_col].rank(ascending=False, method="first")
            top_mask = df_bt["rank"] <= args.top_n_stocks

            # 调仓日
            dates = sorted(df_bt["trade_date"].unique())
            if args.rebalance == "weekly":
                rebalance_dates = []
                last_week = None
                for d in dates:
                    w = pd.Timestamp(d).week
                    if w != last_week:
                        rebalance_dates.append(d)
                        last_week = w
            else:
                rebalance_dates = dates

            rb_mask = df_bt["trade_date"].isin(rebalance_dates) & top_mask
            holdings = df_bt[rb_mask][["trade_date", "ts_code", return_col]]

            # 等权组合收益
            port_ret = holdings.groupby("trade_date")[return_col].mean()
            cost = args.cost_bps / 10000 * 2  # 双边
            port_ret_net = port_ret - cost

            # 净值
            nav = (1 + port_ret_net.dropna()).cumprod()
            if len(nav) > 0:
                nav_list = [1.0] + nav.tolist()
                idx_list = ["start"] + list(nav.index)
                nav = pd.Series(nav_list, index=idx_list)
            else:
                nav = pd.Series([1.0])

            # 绩效
            total_ret = nav.iloc[-1] - 1
            n_periods = len(nav) - 1
            periods_per_year = 52 if args.rebalance == "weekly" else 252
            ann_ret = (1 + total_ret) ** (periods_per_year / n_periods) - 1 if n_periods > 0 else 0
            ann_vol = port_ret_net.std() * np.sqrt(periods_per_year) if len(port_ret_net) > 1 else 0
            sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

            running_max = nav.cummax()
            drawdown = (nav - running_max) / running_max
            max_dd = drawdown.min()

            downside = port_ret_net[port_ret_net < 0]
            downside_vol = downside.std() * np.sqrt(periods_per_year) if len(downside) > 1 else 1e-6
            sortino = ann_ret / downside_vol if downside_vol > 0 else 0

            win_rate = (port_ret_net > 0).mean() if len(port_ret_net) > 0 else 0
            calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

            # 换手率
            turnover_list = []
            holdings_by_date = holdings.groupby("trade_date")["ts_code"].apply(set)
            for i in range(1, len(holdings_by_date)):
                prev = holdings_by_date.iloc[i-1]
                curr = holdings_by_date.iloc[i]
                changed = len(prev - curr) / max(len(prev), 1)
                turnover_list.append(changed)
            avg_turnover = np.mean(turnover_list) if turnover_list else 0

            bt_results[method] = {
                "total_return": total_ret,
                "annual_return": ann_ret,
                "annual_volatility": ann_vol,
                "sharpe": sharpe,
                "sortino": sortino,
                "max_drawdown": max_dd,
                "calmar": calmar,
                "win_rate": win_rate,
                "n_periods": n_periods,
                "avg_turnover": avg_turnover,
                "nav": nav,
                "weights": weights,
                "ic_mean": ic_mean,
                "icir": icir,
                "elapsed": time.time() - t0,
            }

            w_str = " ".join(f"{k}={v:.2f}" for k, v in sorted(weights.items(), key=lambda x: -x[1])[:3])
            log(f"  {method:20s} ICIR={icir:+.4f} 年化={ann_ret:+.2%} 夏普={sharpe:+.3f} 回撤={max_dd:.2%} | {time.time()-t0:.1f}s", "OK")
            log(f"    权重: {w_str}", "INFO")

        except Exception as e:
            log(f"  {method:20s} ❌ {e}", "ERR")
            import traceback
            traceback.print_exc()

    # 基准：单因子最优解
    log("基准: 单因子最优解 (ICIR 最高)...", "STEP")

    # 用 ICIR 找最优单因子
    best_icir = -999
    best_f = valid_factors[0]
    for f in valid_factors:
        daily_ic = df.groupby("trade_date").apply(
            lambda g: g[f].corr(g[return_col], method="spearman")
        )
        icir = abs(daily_ic.mean() / daily_ic.std()) if daily_ic.std() > 0 else 0
        if icir > best_icir:
            best_icir = icir
            best_f = f

    # 回测最优单因子（与多因子同一方法，可比）
    try:
        meta = FACTOR_REGISTRY[best_f]
        df_best = df.copy()
        df_best["score_best"] = df_best[best_f] * meta.direction
        df_best["rank"] = df_best.groupby("trade_date")["score_best"].rank(ascending=False, method="first")
        top_mask = df_best["rank"] <= args.top_n_stocks

        dates = sorted(df_best["trade_date"].unique())
        if args.rebalance == "weekly":
            rebalance_dates = []
            last_week = None
            for d in dates:
                w = pd.Timestamp(d).week
                if w != last_week:
                    rebalance_dates.append(d)
                    last_week = w
        else:
            rebalance_dates = dates

        rb_mask = df_best["trade_date"].isin(rebalance_dates) & top_mask
        holdings = df_best[rb_mask][["trade_date", "ts_code", return_col]]

        port_ret = holdings.groupby("trade_date")[return_col].mean()
        cost = args.cost_bps / 10000 * 2
        port_ret_net = port_ret - cost

        nav = (1 + port_ret_net.dropna()).cumprod()
        if len(nav) > 0:
            # 在第一个收益日前插入起点 1.0
            nav_list = [1.0] + nav.tolist()
            idx_list = ["start"] + list(nav.index)
            nav = pd.Series(nav_list, index=idx_list)
        else:
            nav = pd.Series([1.0])

        total_ret = nav.iloc[-1] - 1
        n_periods = len(nav) - 1
        periods_per_year = 52 if args.rebalance == "weekly" else 252
        ann_ret = (1 + total_ret) ** (periods_per_year / n_periods) - 1 if n_periods > 0 else 0
        ann_vol = port_ret_net.std() * np.sqrt(periods_per_year) if len(port_ret_net) > 1 else 0
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

        running_max = nav.cummax()
        drawdown = (nav - running_max) / running_max
        max_dd = drawdown.min()

        downside = port_ret_net[port_ret_net < 0]
        downside_vol = downside.std() * np.sqrt(periods_per_year) if len(downside) > 1 else 1e-6
        sortino = ann_ret / downside_vol if downside_vol > 0 else 0

        win_rate = (port_ret_net > 0).mean() if len(port_ret_net) > 0 else 0

        # 换手率
        turnover_list = []
        holdings_by_date = holdings.groupby("trade_date")["ts_code"].apply(set)
        for i in range(1, len(holdings_by_date)):
            prev = holdings_by_date.iloc[i-1]
            curr = holdings_by_date.iloc[i]
            changed = len(prev - curr) / max(len(prev), 1)
            turnover_list.append(changed)
        avg_turnover = np.mean(turnover_list) if turnover_list else 0

        bt_results["best_single_factor"] = {
            "total_return": total_ret,
            "annual_return": ann_ret,
            "annual_volatility": ann_vol,
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown": max_dd,
            "calmar": ann_ret / abs(max_dd) if max_dd != 0 else 0,
            "win_rate": win_rate,
            "n_periods": n_periods,
            "avg_turnover": avg_turnover,
            "nav": nav,
            "factor": best_f,
            "icir": best_icir,
            "elapsed": 0,
        }
        log(f"  最优单因子: {best_f} (ICIR={best_icir:.4f})", "OK")
        log(f"  年化={ann_ret:+.2%} 夏普={sharpe:+.3f} 回撤={max_dd:.2%} 期数={n_periods}", "OK")
    except Exception as e:
        log(f"  基准回测错误: {e}", "ERR")
        import traceback
        traceback.print_exc()

    # 保存结果
    log("保存结果...", "STEP")

    # 1. 绩效对比表
    perf_rows = []
    for method, r in bt_results.items():
        perf_rows.append({
            "method": method,
            "annual_return": r["annual_return"],
            "annual_volatility": r["annual_volatility"],
            "sharpe": r["sharpe"],
            "sortino": r["sortino"],
            "max_drawdown": r["max_drawdown"],
            "calmar": r["calmar"],
            "win_rate": r["win_rate"],
            "total_return": r["total_return"],
            "n_periods": r["n_periods"],
            "avg_turnover": r.get("avg_turnover"),
            "ic_mean": r.get("ic_mean"),
            "icir": r.get("icir"),
        })
    df_perf = pd.DataFrame(perf_rows)
    perf_path = os.path.join(REPORT_DIR, "multi_factor_performance.csv")
    df_perf.to_csv(perf_path, index=False, encoding="utf-8-sig")
    log(f"  绩效对比: {perf_path}", "OK")

    # 2. 权重表
    weight_rows = []
    for method, r in bt_results.items():
        w = r.get("weights", {})
        if w:
            for f, wgt in w.items():
                weight_rows.append({"method": method, "factor": f, "weight": wgt})
        if method == "best_single_factor":
            weight_rows.append({"method": method, "factor": r.get("factor", "?"), "weight": 1.0})
    df_weights = pd.DataFrame(weight_rows)
    w_path = os.path.join(REPORT_DIR, "multi_factor_weights.csv")
    df_weights.to_csv(w_path, index=False, encoding="utf-8-sig")
    log(f"  权重表: {w_path}", "OK")

    # 3. 净值序列（用于画图）
    nav_data = {}
    for method, r in bt_results.items():
        nav_series = r["nav"]
        nav_data[method] = nav_series
    df_nav = pd.DataFrame(nav_data)
    nav_path = os.path.join(REPORT_DIR, "multi_factor_nav.csv")
    df_nav.to_csv(nav_path, encoding="utf-8-sig")
    log(f"  净值序列: {nav_path}", "OK")

    total_time = time.time() - total_start

    # 汇总
    log("", "HEAD")
    log("═" * 60, "HEAD")
    log("多因子组合回测完成", "HEAD")
    log("═" * 60, "HEAD")
    log(f"因子数: {len(valid_factors)} | 方法数: {len(bt_results)} | 总耗时: {total_time:.1f}s")

    # 排名
    df_sorted = df_perf.sort_values("sharpe", ascending=False)
    log(f"\n夏普排名:")
    for _, r in df_sorted.iterrows():
        log(f"  {r['method']:25s} 夏普={r['sharpe']:+.3f} 年化={r['annual_return']:+.2%} 回撤={r['max_drawdown']:.2%}")

    log(f"\n📄 结果保存在: {REPORT_DIR}/")
    log(f"   - multi_factor_performance.csv (绩效对比)")
    log(f"   - multi_factor_weights.csv (权重表)")
    log(f"   - multi_factor_nav.csv (净值序列)")

    return bt_results


if __name__ == "__main__":
    main()
