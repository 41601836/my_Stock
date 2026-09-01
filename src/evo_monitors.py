# -*- coding: utf-8 -*-
"""
evo_monitors.py —— EVO 阶段 3：拥挤度监控 + 因子衰减预警
=================================================================
完全独立于经典层（只读 factor_values_evo / daily_prices，只写 evo_* 表）。

【拥挤度监控 crowding_monitor】
  每因子拥挤度 = 最近 corr_window(10) 日「因子截面 rank 日间自相关」均值。
  含义：若每天 Top 票都是同一批（rank 高度稳定），说明资金拥挤在同侧交易。
  复用 IC 引擎的向量化 Spearman：auto_corr_t = spearman(rank_t, rank_{t-1})。
    score ≥ disable_threshold(0.85) → action=disable（组合端权重置 0）
    score ≥ half_weight_threshold(0.70) → action=half_weight（权重 ×0.5）
    否则 → normal
  全局警报：最新日成交额前 5% 股票的成交额占比 > market_cap_top5_share_alert(0.45)
    → 写入 factor_name='__market_amount_top5__' 的全局警报行。

【因子衰减预警 decay_monitor】
  复用权重引擎的 IC 矩阵（build_ic_df），每日 IC 全量落库 evo_factor_ic_daily。
  按因子滚动 rolling_ic_window(20) 日 RankIC 均值：
    连续 red_consecutive_negative_days(5) 日 IC < 0        → red
    滚动 IC < yellow_ic_min(0.010)                          → yellow
  auto_disable_on_red=false → 只告警不自动剔除（观察模式）。

用法：
  /Users/lyu/miniconda3/bin/python3 src/evo_monitors.py
"""

import os
import sys
import time
import sqlite3
import logging
from typing import Dict, List, Any, Tuple

import pandas as pd
import numpy as np

# ═══════════════════════════════════════════════════════════
# 路径 & 依赖注入
# ═══════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.paths import PATHS, startup_check
startup_check()

DB_PATH = PATHS.database.stock_data

sys.path.insert(0, os.path.join(PROJECT_ROOT, "web", "backend"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # src/ → 复用权重引擎
from services.evo import ensure_evo_tables, EvoConfig  # noqa: E402
from evo_dynamic_weights import build_ic_df, vectorized_spearman_ic  # noqa: E402

logger = logging.getLogger("evo_monitors")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

MARKET_ALERT_FACTOR = "__market_amount_top5__"


# ═══════════════════════════════════════════════════════════
# ① 拥挤度监控
# ═══════════════════════════════════════════════════════════
def load_factor_rank_matrices(dates: List[str], factor_cols: List[str]) -> Dict[str, pd.DataFrame]:
    """重新加载因子 → dates×codes 原始值矩阵（拥挤度用原始 rank，不用未来收益）"""
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        ph = ",".join("?" * len(dates))
        fv = pd.read_sql(
            f"SELECT ts_code, trade_date, {', '.join(factor_cols)} "
            f"FROM factor_values_evo WHERE trade_date IN ({ph})",
            conn, params=dates,
        )
    finally:
        conn.close()
    fv["trade_date"] = fv["trade_date"].astype(str)
    mats: Dict[str, pd.DataFrame] = {}
    for col in factor_cols:
        mats[col] = fv.pivot_table(index="trade_date", columns="ts_code", values=col,
                                   aggfunc="last").sort_index().reindex(dates)
    return mats


def run_crowding_monitor(dates: List[str], factor_cols: List[str]) -> List[Tuple[str, str, float, str]]:
    """
    每因子拥挤度 → action；返回 [(trade_date, factor_name, score, action)]
    trade_date 用最新因子交易日（拥挤度是「当下」状态）。
    """
    corr_window = int(EvoConfig.get("crowding_monitor.corr_window", 10))
    half_th = float(EvoConfig.get("crowding_monitor.half_weight_threshold", 0.70))
    dis_th = float(EvoConfig.get("crowding_monitor.disable_threshold", 0.85))
    last_date = dates[-1]

    # 因子 rank 矩阵（截面 pct rank，0~1）
    mats = load_factor_rank_matrices(dates, factor_cols)
    rows: List[Tuple[str, str, float, str]] = []
    for col in factor_cols:
        F = mats[col]
        if F.notna().sum().sum() < 1000:
            rows.append((last_date, col, 0.0, "normal"))
            continue
        # 日间自相关：spearman(rank_t, rank_{t-1})，复用 IC 向量化工具
        auto = vectorized_spearman_ic(F, F.shift(1), min_samples=100)
        score = float(auto.tail(corr_window).mean()) if auto.notna().any() else 0.0
        score = float(np.clip(0.0 if np.isnan(score) else score, 0.0, 1.0))
        if score >= dis_th:
            action = "disable"
        elif score >= half_th:
            action = "half_weight"
        else:
            action = "normal"
        rows.append((last_date, col, score, action))

    # 全局成交额集中度警报（daily_prices 需有 amount 列）
    try:
        conn = sqlite3.connect(DB_PATH, timeout=60.0)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_prices)").fetchall()}
            if "amount" in cols:
                amt = pd.read_sql(
                    "SELECT ts_code, amount FROM daily_prices WHERE trade_date = ? AND amount > 0",
                    conn, params=(last_date,),
                )
                if len(amt) >= 100:
                    amt = amt.sort_values("amount", ascending=False).reset_index(drop=True)
                    top_n = max(1, int(len(amt) * 0.05))
                    share = float(amt.head(top_n)["amount"].sum() / amt["amount"].sum())
                    m_alert = float(EvoConfig.get("crowding_monitor.market_cap_top5_share_alert", 0.45))
                    action = "global_alert" if share > m_alert else "normal"
                    rows.append((last_date, MARKET_ALERT_FACTOR, round(share, 4), action))
                    logger.info(f"[Crowding] 全局成交额前5%占比={share:.2%} "
                                f"(阈值 {m_alert:.0%}) → {action}")
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[Crowding] 全局成交额警报跳过: {e}")

    return rows


# ═══════════════════════════════════════════════════════════
# ② 因子衰减预警
# ═══════════════════════════════════════════════════════════
def run_decay_monitor(ic_df: pd.DataFrame) -> Tuple[List[Tuple[str, str, str, float, str]], List[Tuple[str, str, float]]]:
    """
    滚动 IC 衰减预警 + 每日 IC 序列落库。
    返回 (alerts, ic_rows)
      alerts: [(alert_date, factor_name, level, rolling_ic, description)]
      ic_rows: [(trade_date, factor_name, rank_ic)] → evo_factor_ic_daily
    """
    roll_win = int(EvoConfig.get("decay_monitor.rolling_ic_window", 20))
    yellow_min = float(EvoConfig.get("decay_monitor.yellow_ic_min", 0.010))
    red_days = int(EvoConfig.get("decay_monitor.red_consecutive_negative_days", 5))

    rolling_mean = ic_df.rolling(roll_win, min_periods=roll_win).mean()
    last_date = ic_df.index[-1]

    alerts: List[Tuple[str, str, str, float, str]] = []
    ic_rows: List[Tuple[str, str, float]] = []
    for col in ic_df.columns:
        # 每日 IC 序列全量落库（供 /decay/history 曲线）
        for d, v in ic_df[col].items():
            if pd.notna(v):
                ic_rows.append((str(d), col, float(v)))

        rm = rolling_mean[col].dropna()
        if rm.empty:
            continue
        cur_ic = float(rm.iloc[-1])

        # 红警：最近 red_days 个有效 IC 全部 < 0
        recent = ic_df[col].dropna().tail(red_days)
        if len(recent) >= red_days and (recent < 0).all():
            alerts.append((last_date, col, "red", cur_ic,
                           f"连续 {len(recent)} 日 IC<0，滚动IC={cur_ic:+.4f}"))
        # 黄警：滚动 IC 低于阈值（仍为正但衰减）
        elif cur_ic < yellow_min:
            alerts.append((last_date, col, "yellow", cur_ic,
                           f"滚动{roll_win}日IC={cur_ic:+.4f} < 阈值{yellow_min}"))

    return alerts, ic_rows


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def run() -> Dict[str, Any]:
    t0 = time.time()
    ensure_evo_tables(DB_PATH)

    # 复用权重引擎的 IC 矩阵（含价格加载，约 20s）
    ic_df, dates, factor_cols = build_ic_df()
    logger.info(f"[Monitors] IC 矩阵就绪：{dates[0]}~{dates[-1]} 共 {len(dates)} 日 × {len(factor_cols)} 因子")

    # ① 拥挤度
    crowd_rows = run_crowding_monitor(dates, factor_cols)

    # ② 衰减
    alerts, ic_rows = run_decay_monitor(ic_df)

    # ── 落库（全部 UPSERT 幂等） ─────────────────────────────
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        if EvoConfig.get("crowding_monitor.enabled", False):
            conn.executemany(
                "INSERT OR REPLACE INTO evo_crowding_log (trade_date, factor_name, crowding_score, action) "
                "VALUES (?, ?, ?, ?)", crowd_rows)
        if EvoConfig.get("decay_monitor.enabled", False):
            conn.executemany(
                "INSERT OR REPLACE INTO evo_factor_ic_daily (trade_date, factor_name, rank_ic) "
                "VALUES (?, ?, ?)", ic_rows)
            conn.executemany(
                "INSERT OR REPLACE INTO evo_decay_alerts "
                "(alert_date, factor_name, level, rolling_ic, description) "
                "VALUES (?, ?, ?, ?, ?)", alerts)
        conn.commit()
    finally:
        conn.close()

    # ── 摘要 ────────────────────────────────────────────────
    logger.info("═" * 64)
    if crowd_rows:
        logger.info(f"[Monitors] 拥挤度（最新日 {crowd_rows[0][0]}）：")
        for _, name, score, action in crowd_rows:
            bar = "█" * int(score * 30)
            mark = "⛔" if action == "disable" else ("🟡" if action == "half_weight" else "·")
            logger.info(f"  {mark} {name:32s} {score:.3f} |{bar:<30}| {action}")
    if alerts:
        logger.info(f"[Monitors] 衰减预警 {len(alerts)} 条：")
        for _, name, level, ric, desc in sorted(alerts, key=lambda x: (x[2], x[1])):
            mark = "🔴" if level == "red" else "🟡"
            logger.info(f"  {mark} [{level:6s}] {name:32s} {desc}")
    else:
        logger.info("[Monitors] 衰减预警：全部因子健康，无告警")
    logger.info(f"🎉 监控完成：拥挤度 {len(crowd_rows)} 行 + IC 序列 {len(ic_rows)} 行 + "
                f"预警 {len(alerts)} 条，总耗时 {time.time() - t0:.1f}s")
    return {"crowding": crowd_rows, "alerts": alerts, "ic_rows": len(ic_rows)}


if __name__ == "__main__":
    run()
