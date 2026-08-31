#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T+1 上涨特性分析脚本
分析最近10个推荐日中，T+1 上涨 vs 下跌 的股票在各维度因子上的差异
"""

import sqlite3
import pandas as pd
import numpy as np
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "db", "stock_data.db")

def run_analysis():
    conn = sqlite3.connect(DB_PATH)

    # ── 1. 拉取最近10天有结算数据的推荐记录 ──────────────────────────────────
    df_rec = pd.read_sql("""
        SELECT 
            r.recommend_date,
            r.ts_code,
            r.regime,
            r.factor_score,
            r.winner_rate,
            r.chips_concentration,
            r.net_mf_amount,
            r.ret_1d,
            r.ret_3d,
            r.ret_5d,
            r.alpha_1d,
            CASE WHEN r.ret_1d > 0 THEN 1 ELSE 0 END as is_up
        FROM recommendation_tracker r
        WHERE r.recommend_date >= '20260724'
          AND r.ret_1d IS NOT NULL
    """, conn)

    # ── 2. 关联 factor_values 表取得完整的五维因子值 ─────────────────────────
    df_fv = pd.read_sql("""
        SELECT 
            trade_date as recommend_date,
            stock_code as ts_code,
            excess_return_20d,
            north_net_inflow_ratio,
            profit_ratio_estimate,
            return_60d,
            volatility_60d,
            return_5d,
            return_20d,
            volatility_20d,
            turnover_rate,
            turnover_rate_5d,
            skewness_20d,
            max_drawdown_20d,
            max_drawdown_60d,
            atr_ratio,
            vol_ratio,
            pe_ttm,
            pb,
            roe,
            hot_money_score,
            strong_control_score,
            main_force_score
        FROM factor_values
        WHERE trade_date >= '20260724'
    """, conn)
    conn.close()

    # ── 3. 合并 ──────────────────────────────────────────────────────────────
    df = pd.merge(df_rec, df_fv, on=["recommend_date", "ts_code"], how="left")
    print(f"\n📊 最近10天有效样本: {len(df)} 条  |  上涨: {df['is_up'].sum()} 条  |  下跌: {(df['is_up']==0).sum()} 条")
    print(f"   整体T+1胜率: {df['is_up'].mean()*100:.1f}%")
    print(f"   平均T+1收益: {df['ret_1d'].mean()*100:.2f}%\n")

    # ── 4. 按日期统计胜率 ────────────────────────────────────────────────────
    daily_wr = df.groupby("recommend_date").agg(
        total=("is_up","count"),
        up=("is_up","sum"),
        avg_ret=("ret_1d","mean"),
        avg_factor=("factor_score","mean"),
        regime=("regime","first")
    )
    daily_wr["win_rate"] = daily_wr["up"] / daily_wr["total"]
    print("=== 各推荐日胜率汇总 ===")
    print(daily_wr.to_string())
    print()

    # ── 5. 上涨/下跌组因子均值对比 ──────────────────────────────────────────
    factor_cols = [
        "factor_score", "winner_rate", "chips_concentration", "net_mf_amount",
        "excess_return_20d", "north_net_inflow_ratio", "profit_ratio_estimate",
        "return_60d", "volatility_60d", "return_5d", "return_20d",
        "volatility_20d", "turnover_rate", "turnover_rate_5d",
        "skewness_20d", "max_drawdown_20d", "atr_ratio", "vol_ratio",
        "hot_money_score", "strong_control_score", "main_force_score",
        "pe_ttm", "pb", "roe"
    ]

    up_group = df[df["is_up"] == 1][factor_cols].describe()
    dn_group = df[df["is_up"] == 0][factor_cols].describe()

    up_mean = df[df["is_up"] == 1][factor_cols].mean()
    dn_mean = df[df["is_up"] == 0][factor_cols].mean()

    comparison = pd.DataFrame({
        "上涨组均值": up_mean,
        "下跌组均值": dn_mean,
        "差值(涨-跌)": up_mean - dn_mean,
        "差异方向": ["↑更高" if (up_mean[c] - dn_mean[c]) > 0 else "↓更低" for c in factor_cols]
    })
    print("=== 上涨/下跌组因子均值对比 ===")
    pd.set_option("display.float_format", lambda x: f"{x:.4f}")
    print(comparison.to_string())
    print()

    # ── 6. 关键阈值分析（上涨组分位数）──────────────────────────────────────
    key_cols = ["factor_score", "winner_rate", "chips_concentration",
                "net_mf_amount", "profit_ratio_estimate",
                "north_net_inflow_ratio", "volatility_60d",
                "hot_money_score", "strong_control_score", "main_force_score"]

    up_df = df[df["is_up"] == 1]
    dn_df = df[df["is_up"] == 0]

    print("=== 上涨组关键因子分位数分布 ===")
    up_quantile = up_df[key_cols].quantile([0.25, 0.50, 0.75])
    print(up_quantile.to_string())
    print()

    print("=== 下跌组关键因子分位数分布 ===")
    dn_quantile = dn_df[key_cols].quantile([0.25, 0.50, 0.75])
    print(dn_quantile.to_string())
    print()

    # ── 7. 按 factor_score 分桶胜率 ─────────────────────────────────────────
    df["score_bin"] = pd.cut(df["factor_score"], bins=[0, 0.6, 0.7, 0.8, 0.9, 1.01],
                              labels=["0-0.6", "0.6-0.7", "0.7-0.8", "0.8-0.9", "0.9-1.0"])
    bucket_wr = df.groupby("score_bin", observed=True).agg(
        总数=("is_up","count"),
        上涨数=("is_up","sum"),
        平均收益=("ret_1d","mean")
    )
    bucket_wr["胜率"] = bucket_wr["上涨数"] / bucket_wr["总数"]
    print("=== 按 factor_score 分桶胜率 ===")
    print(bucket_wr.to_string())
    print()

    # ── 8. 按 winner_rate 分桶胜率 ──────────────────────────────────────────
    df["wr_bin"] = pd.cut(df["winner_rate"], bins=[0, 60, 70, 80, 90, 101],
                           labels=["<60%", "60-70%", "70-80%", "80-90%", ">90%"])
    wr_bucket = df.groupby("wr_bin", observed=True).agg(
        总数=("is_up","count"),
        上涨数=("is_up","sum"),
        平均收益=("ret_1d","mean")
    )
    wr_bucket["胜率"] = wr_bucket["上涨数"] / wr_bucket["总数"]
    print("=== 按 winner_rate（历史胜率）分桶胜率 ===")
    print(wr_bucket.to_string())
    print()

    # ── 9. 按 chips_concentration 分桶 ──────────────────────────────────────
    df["chip_bin"] = pd.cut(df["chips_concentration"],
                             bins=[0, 75, 80, 85, 90, 101],
                             labels=["<75", "75-80", "80-85", "85-90", ">90"])
    chip_bucket = df.groupby("chip_bin", observed=True).agg(
        总数=("is_up","count"),
        上涨数=("is_up","sum"),
        平均收益=("ret_1d","mean")
    )
    chip_bucket["胜率"] = chip_bucket["上涨数"] / chip_bucket["总数"]
    print("=== 按筹码集中度分桶胜率 ===")
    print(chip_bucket.to_string())
    print()

    # ── 10. 输出 JSON 供前端使用 ─────────────────────────────────────────────
    result = {
        "summary": {
            "total": int(len(df)),
            "up_count": int(df["is_up"].sum()),
            "down_count": int((df["is_up"]==0).sum()),
            "win_rate": round(float(df["is_up"].mean()), 4),
            "avg_ret_1d": round(float(df["ret_1d"].mean()), 4)
        },
        "daily_win_rate": daily_wr.reset_index().to_dict(orient="records"),
        "factor_comparison": comparison.reset_index().rename(columns={"index":"factor"}).to_dict(orient="records"),
        "score_bucket": bucket_wr.reset_index().to_dict(orient="records"),
        "wr_bucket": wr_bucket.reset_index().to_dict(orient="records"),
        "chip_bucket": chip_bucket.reset_index().to_dict(orient="records"),
        "up_group_median": up_df[key_cols].median().to_dict(),
        "dn_group_median": dn_df[key_cols].median().to_dict(),
    }

    out_path = os.path.join(PROJECT_ROOT, "scratch", "t1_analysis_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✅ 分析结果已保存至: {out_path}")
    return result

if __name__ == "__main__":
    run_analysis()
