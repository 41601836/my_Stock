# -*- coding: utf-8 -*-
"""
evo_dynamic_weights.py —— EVO 阶段 2：IC/ICIR 动态权重引擎
=================================================================
完全独立于经典层（只读 factor_values_evo / daily_prices，只写 evo_dynamic_weights_log）。

工作原理：
  1. 取 factor_values_evo 最近 N 个交易日的 13 个 EVO 因子（10 交叉 + 3 预期差）
  2. 用 daily_prices 构造未来 fwd_period 日收益率（close × adj_factor 复权）
  3. 对每个交易日 t 计算每个因子的截面 Spearman RankIC（向量化，非逐日循环）
  4. 滚动 ic_window 日 → ICMean / ICIR
  5. 权重规则（读 evo.yaml dynamic_weights.*）：
       - zero_negative_ic:  ICMean ≤ 0      → 权重 0
       - min_ir_for_weight: ICIR < 阈值      → 权重 0
       - raw = ICMean × ICIR → 归一化 → clip 单因子上限 → 再归一化
       - 全部为 0 → 均匀权重兜底
  6. 把最近 snapshot_days 个可算 IC 日的权重快照 UPSERT 到 evo_dynamic_weights_log
     （weights_json = {"weights": {...}, "ic_mean": {...}, "ic_ir": {...}, "meta": {...}}）

用法：
  /Users/lyu/miniconda3/bin/python3 src/evo_dynamic_weights.py
"""

import os
import sys
import json
import time
import sqlite3
import logging
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

# ═══════════════════════════════════════════════════════════
# 路径 & 依赖注入（与 feature_engineering_evo.py 保持一致）
# ═══════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.paths import PATHS, startup_check
startup_check()

DB_PATH = PATHS.database.stock_data

sys.path.insert(0, os.path.join(PROJECT_ROOT, "web", "backend"))
from services.evo import ensure_evo_tables, EvoConfig  # noqa: E402

logger = logging.getLogger("evo_dynamic_weights")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ═══════════════════════════════════════════════════════════
# 因子清单：evo.yaml enabled 项 ∩ 表实际列
# ═══════════════════════════════════════════════════════════
def get_enabled_factor_cols(conn: sqlite3.Connection) -> List[str]:
    cols: List[str] = []
    cross_cfg = EvoConfig.get("cross_factors.factors", {}) or {}
    if EvoConfig.get("cross_factors.enabled", False):
        cols += [k for k, v in cross_cfg.items() if v]
    if EvoConfig.get("surprise_factors.enabled", True):
        for c in ["surprise_price_vote", "surprise_earnings_gap", "surprise_roe_qoq"]:
            if EvoConfig.get(f"surprise_factors.{c}", True):
                cols.append(c)
    # M6.3：text 因子（text_factors.enabled 时自动纳入 IC/权重/ML 全链）
    if EvoConfig.get("text_factors.enabled", False):
        cols.append("text_sentiment_score")
    # 与表实际列取交集（防配置先于表结构）
    table_cols = {r[1] for r in conn.execute("PRAGMA table_info(factor_values_evo)").fetchall()}
    valid = [c for c in cols if c in table_cols]
    dropped = [c for c in cols if c not in table_cols]
    if dropped:
        logger.warning(f"[Engine] 配置中 {len(dropped)} 个因子列不在表中，跳过: {dropped}")
    return valid


# ═══════════════════════════════════════════════════════════
# 向量化截面 Spearman IC（dates × codes 矩阵，避免逐日循环）
# ═══════════════════════════════════════════════════════════
def vectorized_spearman_ic(
    F: pd.DataFrame, R: pd.DataFrame, min_samples: int = 10
) -> pd.Series:
    """
    F: 因子矩阵（index=trade_date 升序, columns=ts_code）
    R: 未来收益矩阵（同结构，同 index/columns）
    返回：每日截面 Spearman RankIC 序列（样本 < min_samples 的日为 NaN）
    """
    mask = F.notna() & R.notna()
    n = mask.sum(axis=1)
    fr = F.where(mask).rank(axis=1, pct=True)
    rr = R.where(mask).rank(axis=1, pct=True)
    fr_c = fr.sub(fr.mean(axis=1), axis=0)
    rr_c = rr.sub(rr.mean(axis=1), axis=0)
    num = (fr_c * rr_c).sum(axis=1)
    den = np.sqrt((fr_c ** 2).sum(axis=1) * (rr_c ** 2).sum(axis=1))
    ic = num / (den + 1e-12)
    ic[n < min_samples] = np.nan
    return ic


# ═══════════════════════════════════════════════════════════
# IC 序列 → 权重（按 evo.yaml 规则）
# ═══════════════════════════════════════════════════════════
def _cap_and_renorm(weights: Dict[str, float], cap: float) -> Dict[str, float]:
    """
    Water-filling 上限约束：超限因子固定为 cap，剩余质量按未超限因子的
    相对份额重新分配（迭代直至全部 ≤ cap），最终严格归一到 sum=1。
    """
    w = {c: max(v, 0.0) for c, v in weights.items()}
    t = sum(w.values())
    if t <= 1e-12:
        return w
    w = {c: v / t for c, v in w.items()}
    fixed: Dict[str, float] = {}
    for _ in range(len(w)):
        free = {c: v for c, v in w.items() if c not in fixed}
        ft = sum(free.values())
        if ft <= 1e-12:
            break
        free_mass = 1.0 - sum(fixed.values())
        free = {c: v / ft * free_mass for c, v in free.items()}
        over = {c: v for c, v in free.items() if v > cap + 1e-12}
        if not over:
            w.update(free)
            break
        for c in over:
            fixed[c] = cap
        w = {**{c: v for c, v in free.items() if c not in over}, **fixed}
    t = sum(w.values())
    if t > 1e-12:
        w = {c: v / t for c, v in w.items()}
    return w


def calc_weights_snapshot(
    ic_df: pd.DataFrame, as_of: str
) -> Dict[str, Any]:
    """
    ic_df: index=trade_date（升序）, columns=因子名, 值=每日 RankIC
    as_of: 权重快照对应的交易日（滚动窗口截止该日）
    返回：{"weights": {...}, "ic_mean": {...}, "ic_ir": {...}}
    """
    win = int(EvoConfig.get("dynamic_weights.ic_window", 20))
    min_ir = float(EvoConfig.get("dynamic_weights.min_ir_for_weight", 0.10))
    max_w = float(EvoConfig.get("dynamic_weights.max_single_factor_weight", 0.30))
    zero_neg = bool(EvoConfig.get("dynamic_weights.zero_negative_ic", True))

    window = ic_df.loc[:as_of].tail(win)
    ic_mean = window.mean().fillna(0.0)        # NaN（无数据因子）→ 0，防污染归一化
    ic_std = window.std().fillna(0.0)
    ic_ir = (ic_mean / (ic_std + 1e-9)).fillna(0.0)

    raw: Dict[str, float] = {}
    for col in ic_df.columns:
        m, ir = float(ic_mean.get(col, 0.0)), float(ic_ir.get(col, 0.0))
        if zero_neg and m <= 0:
            raw[col] = 0.0
            continue
        if abs(ir) < min_ir:
            raw[col] = 0.0
            continue
        raw[col] = max(m, 0.0) * max(ir, 0.0)

    total = sum(raw.values())
    if total <= 1e-12:
        # 兜底：均匀权重
        k = len(ic_df.columns)
        weights = {c: round(1.0 / k, 6) for c in ic_df.columns}
        mode = "uniform_fallback"
    else:
        weights = {c: w / total for c, w in raw.items()}
        mode = "icir_weighted"
        # 单因子上限：若有效因子数 × max_w < 1，数学上无法归一，上限放宽为 1/n_eff
        n_eff = sum(1 for v in weights.values() if v > 1e-12)
        cap = max(max_w, 1.0 / max(n_eff, 1))
        weights = _cap_and_renorm(weights, cap)

    return {
        "weights": {c: round(float(w), 6) for c, w in weights.items()},
        "ic_mean": {c: round(float(ic_mean.get(c, 0.0) or 0.0), 6) for c in ic_df.columns},
        "ic_ir": {c: round(float(ic_ir.get(c, 0.0) or 0.0), 6) for c in ic_df.columns},
        "mode": mode,
    }


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def build_ic_df(lookback: Optional[int] = None,
                min_samples: Optional[int] = None):
    """
    加载因子 + 价格 → 构建每日截面 IC 矩阵（权重引擎与监控共用）。
    返回 (ic_df: dates×factors, dates: 因子交易日列表, factor_cols: 因子列名)
    """
    if lookback is None:
        lookback = int(EvoConfig.get("dynamic_weights.weight_lookback_days", 160))
    if min_samples is None:
        min_samples = int(EvoConfig.get("dynamic_weights.min_periods_for_ic", 10))
    fwd = int(EvoConfig.get("dynamic_weights.fwd_period", 5))

    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        factor_cols = get_enabled_factor_cols(conn)
        if not factor_cols:
            raise RuntimeError("evo.yaml 未启用任何 EVO 因子，无法计算 IC")

        # ── 1. 取最近 lookback 个因子交易日 ─────────────────────
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM factor_values_evo ORDER BY trade_date DESC LIMIT ?",
            (lookback,)
        ).fetchall()]
        dates = sorted(str(d) for d in dates)
        if len(dates) < min_samples + fwd + 5:
            raise RuntimeError(
                f"因子交易日不足（{len(dates)} < {min_samples + fwd + 5}），先跑 feature_engineering_evo.py")
        logger.info(f"[IC] 因子交易日 {dates[0]}~{dates[-1]} 共 {len(dates)} 日，因子 {len(factor_cols)} 个")

        # ── 2. 加载因子 → 逐因子 pivot 成 dates×codes 矩阵 ──────
        ph = ",".join("?" * len(dates))
        fv = pd.read_sql(
            f"SELECT ts_code, trade_date, {', '.join(factor_cols)} "
            f"FROM factor_values_evo WHERE trade_date IN ({ph})",
            conn, params=dates,
        )
        fv["trade_date"] = fv["trade_date"].astype(str)

        # ── 3. 加载价格 → 复权 close → 未来 fwd 日收益矩阵 ──────
        dp = pd.read_sql(
            "SELECT ts_code, trade_date, close, adj_factor FROM daily_prices WHERE trade_date >= ?",
            conn, params=(dates[0],),
        )
        dp["trade_date"] = dp["trade_date"].astype(str)
        dp["close_adj"] = dp["close"].astype(float) * dp["adj_factor"].fillna(1.0).astype(float)
    finally:
        conn.close()

    # close_adj pivot（dates 全轴：含因子末日之后 fwd 天的价格，用于未来收益）
    close_mat = dp.pivot_table(index="trade_date", columns="ts_code",
                               values="close_adj", aggfunc="last").sort_index()
    fwd_ret = close_mat.shift(-fwd) / close_mat - 1.0
    fwd_ret = fwd_ret.reindex(dates)  # 只保留因子日期轴

    # ── 4. 逐因子向量化算 IC → ic_df (dates × factors) ─────────
    ic_df = pd.DataFrame(index=dates, columns=factor_cols, dtype=np.float32)
    for col in factor_cols:
        F = fv.pivot_table(index="trade_date", columns="ts_code", values=col,
                           aggfunc="last").sort_index().reindex(dates)
        ic_df[col] = vectorized_spearman_ic(F, fwd_ret, min_samples).astype(np.float32)
    return ic_df, dates, factor_cols


def run() -> Dict[str, Any]:
    t0 = time.time()
    ensure_evo_tables(DB_PATH)

    fwd = int(EvoConfig.get("dynamic_weights.fwd_period", 5))
    snapshot_days = int(EvoConfig.get("dynamic_weights.snapshot_days", 20))

    ic_df, dates, factor_cols = build_ic_df()

    # 可算 IC 的日期（该日至少一半因子有 IC）
    valid_dates = ic_df.dropna(thresh=max(1, len(factor_cols) // 2)).index.tolist()
    if not valid_dates:
        raise RuntimeError("没有任何交易日可算出 IC（数据可能太薄）")
    logger.info(f"[Engine] IC 序列：{valid_dates[0]}~{valid_dates[-1]} 共 {len(valid_dates)} 日")

    # ── 5. 最近 snapshot_days 个快照日 → 权重 → UPSERT ─────────
    snap_dates = valid_dates[-snapshot_days:]
    rows = []
    for s in snap_dates:
        snap = calc_weights_snapshot(ic_df, s)
        payload = {
            "weights": snap["weights"],
            "ic_mean": snap["ic_mean"],
            "ic_ir": snap["ic_ir"],
            "meta": {
                "mode": snap["mode"],
                "ic_window": int(EvoConfig.get("dynamic_weights.ic_window", 20)),
                "fwd_period": fwd,
                "factor_date": dates[-1],
                "engine_version": "2.0",
            },
        }
        rows.append((s, json.dumps(payload, ensure_ascii=False), "all_weather"))

    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO evo_dynamic_weights_log (trade_date, weights_json, regime) "
            "VALUES (?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()

    # ── 6. 控制台摘要（最新快照） ─────────────────────────────
    latest = json.loads(rows[-1][1])
    logger.info("═" * 64)
    logger.info(f"[Engine] 最新权重快照 @ {rows[-1][0]}（mode={latest['meta']['mode']}）")
    w = latest["weights"]
    for c, weight in sorted(w.items(), key=lambda x: -(x[1] if x[1] == x[1] else -1)):
        bar = "█" * int((weight if weight == weight else 0.0) * 50)   # NaN→0
        ic = latest['ic_mean'].get(c, float('nan'))
        icir = latest['ic_ir'].get(c, float('nan'))
        logger.info(
            f"  {c:30s} w={weight:.4f} |{bar}| "
            f"ICMean={ic:+.4f} ICIR={icir:+.3f}"
        )
    zeroed = [c for c, ww in w.items() if ww <= 1e-9]
    if zeroed:
        logger.info(f"  ⛔ ICIR 不足被置 0 的因子: {zeroed}")
    logger.info(f"🎉 动态权重完成：写 {len(rows)} 日快照，总耗时 {time.time() - t0:.1f}s")
    return {"snapshot_dates": snap_dates, "latest": latest}


if __name__ == "__main__":
    run()
