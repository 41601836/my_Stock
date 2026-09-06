#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方向 A: 全因子筛选 + 因子池构建 — 一键全流程
==========================================
依次执行:
  A1. 全因子批量测试 (IC + 分层 + 回测 + 防过拟合)
  A2. 因子评级引擎 (7 维评分 → S/A+/A/B+/B/C+/C/D)
  A3. 因子相关性 + 聚类分析
  A4. 全因子总览报告 (HTML)

用法:
  python3 scripts/run_factor_screening.py
  python3 scripts/run_factor_screening.py --start 20240101 --n-perm 50
  python3 scripts/run_factor_screening.py --skip-batch  # 跳过A1，直接从已有数据开始
"""

import os
import sys
import time
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
REPORT_DIR = os.path.join(PROJECT_ROOT, "factor_test_reports")

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    color = {
        "INFO": "\033[36m",
        "OK": "\033[32m",
        "WARN": "\033[33m",
        "ERR": "\033[31m",
        "HEAD": "\033[1;35m",
        "STEP": "\033[1;34m",
    }.get(level, "")
    end = "\033[0m"
    print(f"{color}[{ts}] [{level}]{end} {msg}")

def run_step(step_name, script_path, args_list):
    """运行一个步骤"""
    cmd = f"python3 {script_path} {' '.join(args_list)}"
    log(f"执行: {cmd}", "STEP")

    import subprocess
    result = subprocess.run(
        [sys.executable, script_path] + args_list,
        cwd=PROJECT_ROOT,
        capture_output=False,
        text=True
    )
    return result.returncode == 0

def main():
    parser = argparse.ArgumentParser(description="因子筛选一键全流程")
    parser.add_argument("--start", type=str, default="20240101", help="开始日期")
    parser.add_argument("--end", type=str, default=None, help="结束日期")
    parser.add_argument("--n-perm", type=int, default=50, help="置换检验次数")
    parser.add_argument("--top-n", type=int, default=10, help="Top-N")
    parser.add_argument("--n-groups", type=int, default=5, help="分层组数")
    parser.add_argument("--cost-bps", type=float, default=15.0, help="单边成本 bp")
    parser.add_argument("--n-clusters", type=int, default=5, help="聚类数量")
    parser.add_argument("--skip-batch", action="store_true", help="跳过 A1 (用已有数据)")
    parser.add_argument("--write-db", action="store_true", help="写入数据库 factor_ranking 表")
    parser.add_argument("--factors", type=str, default=None, help="指定因子（逗号分隔）")
    args = parser.parse_args()

    os.makedirs(REPORT_DIR, exist_ok=True)
    total_start = time.time()

    log("═" * 60, "HEAD")
    log("方向 A: 全因子筛选 + 因子池构建 — 一键全流程", "HEAD")
    log("═" * 60, "HEAD")
    log(f"区间: {args.start} ~ {args.end or '最新'}")
    log(f"置换: {args.n_perm}  Top-N: {args.top_n}  聚类: {args.n_clusters}")

    # ── A1: 全因子批量测试 ──
    if not args.skip_batch:
        log("", "STEP")
        log("═══ A1: 全因子批量测试 ═══", "STEP")
        log("", "STEP")

        batch_args = [
            "--start", args.start,
            "--n-perm", str(args.n_perm),
            "--top-n", str(args.top_n),
            "--n-groups", str(args.n_groups),
            "--cost-bps", str(args.cost_bps),
        ]
        if args.end:
            batch_args.extend(["--end", args.end])
        if args.factors:
            batch_args.extend(["--factors", args.factors])

        ok = run_step(
            "A1 全因子批量测试",
            os.path.join(SCRIPTS_DIR, "run_all_factors_batch.py"),
            batch_args
        )
        if not ok:
            log("❌ A1 失败，终止", "ERR")
            sys.exit(1)
    else:
        log("⏭️  跳过 A1 (使用已有数据)", "WARN")

    # ── A2: 因子评级 ──
    log("", "STEP")
    log("═══ A2: 因子评级引擎 ═══", "STEP")
    log("", "STEP")

    rank_args = []
    if args.write_db:
        rank_args.append("--write-db")

    ok = run_step(
        "A2 因子评级",
        os.path.join(SCRIPTS_DIR, "build_factor_ranking.py"),
        rank_args
    )
    if not ok:
        log("❌ A2 失败，终止", "ERR")
        sys.exit(1)

    # ── A3: 相关性 + 聚类 ──
    log("", "STEP")
    log("═══ A3: 因子相关性 & 聚类分析 ═══", "STEP")
    log("", "STEP")

    corr_args = [
        "--start", args.start,
        "--n-clusters", str(args.n_clusters),
        "--ranking", os.path.join(REPORT_DIR, "factor_ranking.csv"),
    ]
    if args.end:
        corr_args.extend(["--end", args.end])

    ok = run_step(
        "A3 相关性分析",
        os.path.join(SCRIPTS_DIR, "factor_correlation.py"),
        corr_args
    )
    if not ok:
        log("❌ A3 失败，终止", "ERR")
        sys.exit(1)

    # ── A4: 总览报告 ──
    log("", "STEP")
    log("═══ A4: 全因子总览报告 ═══", "STEP")
    log("", "STEP")

    report_args = [
        "--n-clusters", str(args.n_clusters),
    ]

    ok = run_step(
        "A4 生成报告",
        os.path.join(SCRIPTS_DIR, "generate_overview_report.py"),
        report_args
    )
    if not ok:
        log("❌ A4 失败，终止", "ERR")
        sys.exit(1)

    # ── 汇总 ──
    total_elapsed = time.time() - total_start

    log("", "HEAD")
    log("═" * 60, "HEAD")
    log("全流程完成！", "HEAD")
    log("═" * 60, "HEAD")
    log(f"总耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)", "OK")
    log(f"")
    log(f"产出文件:", "OK")
    log(f"  📊 {os.path.join(REPORT_DIR, 'all_factors_full_test.csv')}", "INFO")
    log(f"  📊 {os.path.join(REPORT_DIR, 'factor_ranking.csv')}", "INFO")
    log(f"  📊 {os.path.join(REPORT_DIR, 'factor_corr_matrix.csv')}", "INFO")
    log(f"  📊 {os.path.join(REPORT_DIR, 'factor_clusters.csv')}", "INFO")
    log(f"  📊 {os.path.join(REPORT_DIR, 'independent_factors.csv')}", "INFO")
    log(f"  📄 {os.path.join(REPORT_DIR, 'factor_overview_report.html')}", "OK")

if __name__ == "__main__":
    main()
