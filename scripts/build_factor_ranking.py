#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方向 A2: 因子评级引擎 + factor_ranking 数据表
==============================================
从 all_factors_full_test.csv 读取测试结果，按 7 维评分体系评级，
写入 factor_ranking 表（_evo 后缀避免污染现有表）。

评级体系 (7 分制 → 八档):
  维度            权重  得分条件
  |ICIR|          2     ≥0.5 得2, ≥0.3 得1, 否则0
  单调性 score    1     ≥0.8 得1, ≥0.5 得0.5, 否则0
  置换检验 p      2     <0.01 得2, <0.05 得1, 否则0
  子周期一致率    1     ≥80% 得1, ≥60% 得0.5, 否则0
  IC自相关 AC(1)  1     ≥0.5 得1, ≥0.2 得0.5, 否则0
  合计            7

  星级    分数      等级
  7★     6.5-7.0   S   黄金因子
  6★     5.5-6.4   A+  强有效
  5★     4.5-5.4   A   有效
  4★     3.5-4.4   B+  弱有效
  3★     2.5-3.4   B   边际有效
  2★     1.5-2.4   C+  弱信号
  1★     0.5-1.4   C   几乎无效
  0★     0.0-0.4   D   无效

用法:
  python3 scripts/build_factor_ranking.py
  python3 scripts/build_factor_ranking.py --input factor_test_reports/all_factors_full_test.csv
  python3 scripts/build_factor_ranking.py --write-db  # 写入数据库
"""

import os
import sys
import argparse
import sqlite3
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from factor_lib.config import FactorTestConfig

import numpy as np
import pandas as pd

# ── 评级配置 ──
def score_icir(icir):
    """|ICIR| 评分 (2分)"""
    if pd.isna(icir):
        return 0.0
    abs_icir = abs(icir)
    if abs_icir >= 0.5:
        return 2.0
    elif abs_icir >= 0.3:
        return 1.0
    return 0.0

def score_monotonicity(mono_score):
    """单调性评分 (1分)"""
    if pd.isna(mono_score):
        return 0.0
    abs_mono = abs(mono_score)
    if abs_mono >= 0.8:
        return 1.0
    elif abs_mono >= 0.5:
        return 0.5
    return 0.0

def score_permutation(p_value):
    """置换检验 p 值评分 (2分)"""
    if pd.isna(p_value):
        return 0.0
    if p_value < 0.01:
        return 2.0
    elif p_value < 0.05:
        return 1.0
    return 0.0

def score_subperiod(consistent_ratio):
    """子周期一致率评分 (1分)"""
    if pd.isna(consistent_ratio):
        return 0.0
    if consistent_ratio >= 0.8:
        return 1.0
    elif consistent_ratio >= 0.6:
        return 0.5
    return 0.0

def score_autocorr(ac_lag1):
    """IC 自相关评分 (1分)"""
    if pd.isna(ac_lag1):
        return 0.0
    abs_ac = abs(ac_lag1)
    if abs_ac >= 0.5:
        return 1.0
    elif abs_ac >= 0.2:
        return 0.5
    return 0.0

def grade_from_score(score):
    """分数 → 星级 + 等级"""
    if score >= 6.5:
        return 7, "S"
    elif score >= 5.5:
        return 6, "A+"
    elif score >= 4.5:
        return 5, "A"
    elif score >= 3.5:
        return 4, "B+"
    elif score >= 2.5:
        return 3, "B"
    elif score >= 1.5:
        return 2, "C+"
    elif score >= 0.5:
        return 1, "C"
    else:
        return 0, "D"

GRADE_ORDER = {"S": 0, "A+": 1, "A": 2, "B+": 3, "B": 4, "C+": 5, "C": 6, "D": 7}

def rate_factor(row):
    """对单个因子行计算评分和评级"""
    s_icir = score_icir(row.get("icir"))
    s_mono = score_monotonicity(row.get("monotonicity_score"))
    s_perm = score_permutation(row.get("perm_p_value"))
    s_subp = score_subperiod(row.get("subp_consistent_ratio"))
    s_ac = score_autocorr(row.get("ac_lag1"))

    total = s_icir + s_mono + s_perm + s_subp + s_ac
    stars, grade = grade_from_score(total)

    return {
        "score_icir": s_icir,
        "score_monotonicity": s_mono,
        "score_permutation": s_perm,
        "score_subperiod": s_subp,
        "score_autocorr": s_ac,
        "total_score": total,
        "stars": stars,
        "grade": grade,
    }

def build_ranking(input_csv):
    """从 CSV 构建评级结果"""
    df = pd.read_csv(input_csv)

    # 只处理 OK 状态的因子
    df_ok = df[df["status"] == "OK"].copy()

    ratings = []
    for _, row in df_ok.iterrows():
        r = rate_factor(row)
        r["factor"] = row["factor"]
        r["category"] = row.get("category", "")
        r["direction"] = row.get("direction", 0)
        r["table"] = row.get("table", "")
        r["ic_mean"] = row.get("ic_mean")
        r["icir"] = row.get("icir")
        r["ic_p_value"] = row.get("ic_p_value")
        r["monotonicity_score"] = row.get("monotonicity_score")
        r["perm_p_value"] = row.get("perm_p_value")
        r["subp_consistent_ratio"] = row.get("subp_consistent_ratio")
        r["ac_lag1"] = row.get("ac_lag1")
        r["sharpe"] = row.get("sharpe")
        r["annual_return"] = row.get("annual_return")
        r["max_drawdown"] = row.get("max_drawdown")
        r["ls_annual_return"] = row.get("ls_annual_return")
        r["ic_decay_ratio"] = row.get("ic_decay_ratio")
        ratings.append(r)

    df_rating = pd.DataFrame(ratings)

    if len(df_rating) > 0:
        # 按总分降序
        df_rating = df_rating.sort_values("total_score", ascending=False).reset_index(drop=True)
        df_rating["rank"] = df_rating.index + 1

    return df_rating

def write_to_db(df_rating, db_path):
    """写入 factor_ranking 表"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 建表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS factor_ranking (
        rank INTEGER,
        factor TEXT PRIMARY KEY,
        category TEXT,
        direction INTEGER,
        source_table TEXT,
        total_score REAL,
        stars INTEGER,
        grade TEXT,
        score_icir REAL,
        score_monotonicity REAL,
        score_permutation REAL,
        score_subperiod REAL,
        score_autocorr REAL,
        ic_mean REAL,
        icir REAL,
        ic_p_value REAL,
        monotonicity_score REAL,
        perm_p_value REAL,
        subp_consistent_ratio REAL,
        ac_lag1 REAL,
        sharpe REAL,
        annual_return REAL,
        max_drawdown REAL,
        ls_annual_return REAL,
        ic_decay_ratio REAL,
        update_time TEXT
    )
    """)

    # UPSERT
    update_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    for _, row in df_rating.iterrows():
        cursor.execute("""
        INSERT OR REPLACE INTO factor_ranking VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            int(row["rank"]),
            row["factor"],
            row["category"],
            int(row["direction"]),
            row["table"],
            float(row["total_score"]),
            int(row["stars"]),
            row["grade"],
            float(row["score_icir"]),
            float(row["score_monotonicity"]),
            float(row["score_permutation"]),
            float(row["score_subperiod"]),
            float(row["score_autocorr"]),
            float(row["ic_mean"]) if pd.notna(row["ic_mean"]) else None,
            float(row["icir"]) if pd.notna(row["icir"]) else None,
            float(row["ic_p_value"]) if pd.notna(row["ic_p_value"]) else None,
            float(row["monotonicity_score"]) if pd.notna(row["monotonicity_score"]) else None,
            float(row["perm_p_value"]) if pd.notna(row["perm_p_value"]) else None,
            float(row["subp_consistent_ratio"]) if pd.notna(row["subp_consistent_ratio"]) else None,
            float(row["ac_lag1"]) if pd.notna(row["ac_lag1"]) else None,
            float(row["sharpe"]) if pd.notna(row["sharpe"]) else None,
            float(row["annual_return"]) if pd.notna(row["annual_return"]) else None,
            float(row["max_drawdown"]) if pd.notna(row["max_drawdown"]) else None,
            float(row["ls_annual_return"]) if pd.notna(row["ls_annual_return"]) else None,
            float(row["ic_decay_ratio"]) if pd.notna(row["ic_decay_ratio"]) else None,
            update_time,
        ))

    conn.commit()
    conn.close()

def print_summary(df_rating):
    """打印评级汇总"""
    if len(df_rating) == 0:
        print("  无有效因子")
        return

    grade_counts = df_rating["grade"].value_counts().reindex(
        ["S", "A+", "A", "B+", "B", "C+", "C", "D"], fill_value=0
    )

    print(f"\n  {'═' * 50}")
    print(f"  因子评级汇总 (共 {len(df_rating)} 个有效因子)")
    print(f"  {'═' * 50}")

    for grade, count in grade_counts.items():
        if count == 0:
            continue
        stars = df_rating[df_rating["grade"] == grade].iloc[0]["stars"]
        star_str = "★" * stars + "☆" * (7 - stars)
        bar = "█" * int(count)
        print(f"  {star_str} {grade:3s} {count:2d} 个  {bar}")

    print(f"\n  Top 15 因子:")
    print(f"  {'排名':>4s} {'因子':28s} {'等级':4s} {'总分':>6s}  ICIR   单调   置换p   子周  AC(1)  夏普")
    print(f"  {'─' * 85}")
    for _, r in df_rating.head(15).iterrows():
        star_str = "★" * int(r["stars"]) + "☆" * (7 - int(r["stars"]))
        print(f"  {int(r['rank']):>4d} {r['factor']:28s} {r['grade']:4s} {r['total_score']:6.2f}  "
              f"{abs(r['icir']):.3f}  {abs(r['monotonicity_score']):.3f}  {r['perm_p_value']:.4f}  "
              f"{r['subp_consistent_ratio']:.2f}  {abs(r['ac_lag1']):.3f}  {r['sharpe']:+.3f}")

    # 各分类最佳
    print(f"\n  各分类最佳因子:")
    for cat in sorted(df_rating["category"].unique()):
        cat_df = df_rating[df_rating["category"] == cat]
        best = cat_df.iloc[0]
        print(f"    {cat:12s}: {best['factor']:28s} {best['grade']} ({best['total_score']:.2f}分)")

def main():
    parser = argparse.ArgumentParser(description="因子评级引擎")
    parser.add_argument("--input", type=str, default=None, help="输入 CSV 路径")
    parser.add_argument("--write-db", action="store_true", help="写入数据库 factor_ranking 表")
    parser.add_argument("--output", type=str, default=None, help="输出 CSV 路径")
    args = parser.parse_args()

    cfg = FactorTestConfig()
    input_csv = args.input or os.path.join(PROJECT_ROOT, "factor_test_reports", "all_factors_full_test.csv")

    if not os.path.exists(input_csv):
        print(f"❌ 输入文件不存在: {input_csv}")
        sys.exit(1)

    print(f"\n  因子评级引擎")
    print(f"  {'─' * 50}")
    print(f"  输入: {input_csv}")

    df_rating = build_ranking(input_csv)
    print_summary(df_rating)

    # 保存 CSV
    output_csv = args.output or os.path.join(PROJECT_ROOT, "factor_test_reports", "factor_ranking.csv")
    df_rating.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"\n  📄 评级结果: {output_csv}")

    # 写入数据库
    if args.write_db:
        db_path = cfg.db_path()
        write_to_db(df_rating, db_path)
        print(f"  💾 已写入数据库: {db_path} (factor_ranking 表)")

    return df_rating

if __name__ == "__main__":
    main()
