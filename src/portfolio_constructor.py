# -*- coding: utf-8 -*-
"""
portfolio_constructor.py —— 投资组合构建模块 (Phase 3 优化版)
============================================================
核心思路（替代 Phase 1/2 的朴素"画像分按比例配权"）：

  Layer 0 输入：画像三层漏斗筛选后的 K 只精选股（通常 3~8 只）
    │
    ├─► Phase 3-① 因子过滤层（filter）：
    │      · 硬门槛：剔除 portrait_grade == "D" 或 portrait_score < 合格线
    │      · z-score 去尾部：factor_score_norm 截面 z < -2 (或 5% 分位以下) → 剔（踩雷保护）
    │      · 返回 过滤后候选 + 过滤统计
    │
    ├─► Phase 3-② 目标权重生成（equal-weight target）：
    │      · 等权 1/N（私募精选组合惯例：排名靠前只代表进入组合，不代表多押）
    │      · 单股权重硬上限 ≤ 30%（文件头约定）；N ≤ 3 时自动放松等权条件
    │
    └─► Phase 3-③ 多周滚动平滑（rolling turnover blend）：
           · 读取 scan_history 最近一个交易日的同策略持仓权重 (mvo_weight 列复用)
           · 按 max_turnover (默认 0.5) 做"旧仓 ↔ 新目标仓"的线性混合：
               w_blend[i] = w_old[i] + Clip(0, max_turnover_total, target[i] - w_old[i])
           · 对消失在新组合的旧持仓，按 100% 上限减仓 / 新进入股票 按 max_turnover 加仓，
             归一化保证总和=1.0
           · 输出 blend 后权重 + 换手率指标 + 元数据

对外 API：
    df_portfolio, stats = construct_portfolio(
        df_signals,           # 候选 DataFrame (必备列见 docstring)
        *,
        max_turnover = 0.5,   # 组合相对总换手率上限
        max_weight   = 0.30,  # 单股权重上限 30%
        prev_weights = None,  # [可选] {ts_code: weight_fraction} 旧持仓；不传则从 DB 推断
        conn         = None,  # [可选] sqlite3 连接；若传 prev_weights=None+conn 则查 DB
        current_date = None,  # [可选] 今日 str "YYYYMMDD"，用于找"上一交易日"
        strategy     = "left",# 画像/扫描策略名：left / right / scan / ……
        db_path      = None,  # [可选] conn=None 时新建连接用
        drop_grade_d = True,
        factor_tail_quantile = 0.05,  # 因子截面最低 X% 分位剔除（去尾部）
        min_portfolio_size   = 3,     # 过滤后若不足此数，则放宽过滤确保至少凑够
        final_max_size       = 5,     # 最终输出上限（层三漏斗 final_pick_top_n 对齐，仅当过滤后多时截断）
    )

返回：
    df_portfolio : 与 df_signals 对齐的 DataFrame，多列：
        - target_weight       (float): 等权目标权重 (小数 0~1，sum=1.0)
        - prev_weight         (float): 推断出的上次持仓权重（如无则=0）
        - blended_weight      (float): 多周滚动平滑后最终权重（小数，0~1，sum=1.0）
        - blended_weight_pct  (float): blended_weight × 100，与 suggested_weight 契约对齐
        - delta_weight        (float): blended - prev，正=加仓，负=减仓
        - dropped_reason      (str)   : 若被过滤层剔除，记录原因
    stats : dict，含：
        - in_count, filter_dropped, out_count,
        - drop_breakdown: {reason: n}
        - turnover_vs_prev: 0~1 换手率（sum(|delta|)/2）
        - phase: "Phase 3 (factor filter + EW target + rolling turnover blend)"
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional, Dict, Any, Tuple, List

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────
# 必备列校验（df_signals 必须包含）
# ─────────────────────────────────────────────────────────────────
_REQUIRED_COLS = [
    "ts_code",                 # 股票代码，str
    "portrait_score",          # 画像综合分 0~100
    "portrait_grade",          # 画像等级 A/B/C/D
    "factor_score_norm",       # 因子标准化得分 0~1 （截面 min-max 后）
    "build_score",             # 综合建仓分 0~1 或 0~100 均可（自动归一化识别）
]


def _infer_db_path() -> str:
    """尽力从后端路径推断数据库位置（无需在 src/ 内写死）"""
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    candidates = [
        os.path.join(project_root, "db", "stock_data.db"),
        os.path.join(os.path.dirname(project_root), "db", "stock_data.db"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # 最后兜底：返回第一个（稍后在外面调用时会 FileNotFound 提示）
    return candidates[0]


def _get_previous_trading_date(conn, current_date: Optional[str]) -> Optional[str]:
    """从 daily_prices 找 current_date 之前一个最大的交易日（多周滚动基准日）。
    若 current_date 为 None，则拿 MAX(trade_date) 当"今天"。"""
    try:
        cur = conn.cursor()
        if not current_date:
            today = cur.execute("SELECT MAX(trade_date) FROM daily_prices").fetchone()
            current_date = str(today[0]) if today and today[0] else None
        if not current_date:
            return None
        row = cur.execute(
            "SELECT MAX(trade_date) FROM daily_prices WHERE trade_date < ?",
            (str(current_date),)
        ).fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception:
        return None


def _infer_previous_weights(
    conn,
    prev_date: Optional[str],
    strategy: str,
    universe_codes: List[str],
) -> Dict[str, float]:
    """从 scan_history 推断前一个交易日的持仓权重（小数，0~1）。

    优先规则：
      1) 如果 prev_date + 相同 regime 列存了这些股票 → 用 mvo_weight / 100 转为小数；
         再做一次归一化 sum=1.0（防止历史表四舍五入残留）
      2) 否则回退 {code: 0 for code in universe}（第 1 天建仓）
    """
    empty = {c: 0.0 for c in universe_codes}
    if not prev_date or not universe_codes:
        return empty
    try:
        cur = conn.cursor()
        ph = ",".join(["?"] * len(universe_codes))
        rows = cur.execute(
            f"SELECT ts_code, mvo_weight FROM scan_history "
            f"WHERE scan_date=? AND ts_code IN ({ph}) AND mvo_weight IS NOT NULL",
            [prev_date] + list(universe_codes),
        ).fetchall()
        if not rows:
            return empty
        w = {code: float(wt or 0.0) / 100.0 for code, wt in rows}
        total = sum(w.values())
        if total <= 1e-9:
            return empty
        # 归一化到 1.0（scan_history mvo_weight 百分号 × 100 存储的误差四舍五入累计）
        return {c: (v / total) for c, v in w.items()}
    except Exception:
        return empty


def _filter_candidates(
    df: pd.DataFrame,
    drop_grade_d: bool,
    factor_tail_quantile: float,
    min_portfolio_size: int,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """执行 Phase 3-① 过滤层。返回 (过滤后 df, 各原因剔除计数)。"""
    breakdown: Dict[str, int] = {}
    df = df.copy()
    df["_reason"] = ""

    # ── 1. grade-D 硬门槛 ──
    if drop_grade_d and "portrait_grade" in df.columns:
        mask_bad_grade = df["portrait_grade"].astype(str).str.upper() == "D"
        n_bad = int(mask_bad_grade.sum())
        if n_bad:
            breakdown["grade_D 剔除"] = n_bad
            df.loc[mask_bad_grade, "_reason"] = "画像D级(不合格)"

    # ── 2. factor_score_norm 5% 分位以下尾部剔除（截面 z-score 近似：分位数更鲁棒） ──
    if "factor_score_norm" in df.columns and factor_tail_quantile > 0 and len(df) >= 5:
        f = pd.to_numeric(df["factor_score_norm"], errors="coerce").fillna(0.5)
        threshold = float(f.quantile(factor_tail_quantile))
        # 如果门槛太极端（所有分位一致时 threshold 会等于 max；避免误删）
        mask_tail = (f < threshold) & (df["_reason"] == "")
        n_tail = int(mask_tail.sum())
        if n_tail and threshold < 0.3:  # 只在"真的存在一批差等生"场景剔除
            breakdown["因子尾部分位剔除"] = n_tail
            df.loc[mask_tail, "_reason"] = f"因子分低于{factor_tail_quantile*100:.0f}%分位({threshold:.2f})"

    # ── 应用过滤 ──
    keep_mask = df["_reason"] == ""
    df_out = df[keep_mask].copy()
    df_rej = df[~keep_mask].copy()

    # 防御：若过滤后不足 min_portfolio_size，按 portrait_score 从拒绝池里补回
    if len(df_out) < min_portfolio_size and len(df_rej) > 0:
        slot = min_portfolio_size - len(df_out)
        df_rej_sorted = df_rej.sort_values("portrait_score", ascending=False)
        restore = df_rej_sorted.head(slot).copy()
        restore["_reason"] = ""
        breakdown["过滤后不足最小持仓，补回高分"] = len(restore)
        df_out = pd.concat([df_out, restore], ignore_index=True)

    # 把 dropped_reason 对齐回主 df（合并后只有保留行+拒绝行的完整信息）
    df_out["dropped_reason"] = ""
    df_full = pd.concat([
        df_out,
        df_rej.rename(columns={"_reason": "dropped_reason"}) if not df_rej.empty else df_rej.assign(dropped_reason=""),
    ], ignore_index=True, sort=False)

    return df_full, breakdown


def construct_portfolio(
    df_signals: pd.DataFrame,
    max_turnover: float = 0.5,
    max_weight: float = 0.30,
    prev_weights: Optional[Dict[str, float]] = None,
    conn=None,
    current_date: Optional[str] = None,
    strategy: str = "left",
    db_path: Optional[str] = None,
    drop_grade_d: bool = True,
    factor_tail_quantile: float = 0.05,
    min_portfolio_size: int = 1,
    final_max_size: int = 5,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    组合构建 Phase 3：因子过滤 → 等权目标 → 多周滚动平滑。

    详见文件级 docstring。
    """
    # ────────────────── 输入校验 ──────────────────
    in_count = len(df_signals)
    if df_signals is None or in_count == 0:
        return pd.DataFrame(), {
            "in_count": 0, "filter_dropped": 0, "out_count": 0,
            "drop_breakdown": {}, "turnover_vs_prev": 0.0,
            "phase": "Phase 3 (factor filter + EW target + rolling turnover blend)",
        }
    missing = [c for c in _REQUIRED_COLS if c not in df_signals.columns]
    if missing:
        # 容错：如果少列（如 portrait.py 少 build_score → 用 factor_score_norm 代替）
        df_signals = df_signals.copy()
        if "build_score" not in df_signals.columns and "factor_score_norm" in df_signals.columns:
            df_signals["build_score"] = pd.to_numeric(df_signals["factor_score_norm"], errors="coerce").fillna(0.0)
        if "portrait_score" not in df_signals.columns:
            df_signals["portrait_score"] = 50.0
        if "portrait_grade" not in df_signals.columns:
            df_signals["portrait_grade"] = "C"
        if "factor_score_norm" not in df_signals.columns:
            df_signals["factor_score_norm"] = 0.5
        if "ts_code" not in df_signals.columns:
            df_signals["ts_code"] = [f"C{i:06d}" for i in range(in_count)]

    # 数字列 cast 为 numeric
    for c in ["portrait_score", "factor_score_norm", "build_score"]:
        df_signals[c] = pd.to_numeric(df_signals[c], errors="coerce").fillna(0.0)

    # ────────────────── 过滤层 ──────────────────
    df_f, breakdown = _filter_candidates(
        df_signals,
        drop_grade_d       = drop_grade_d,
        factor_tail_quantile = factor_tail_quantile,
        min_portfolio_size = min_portfolio_size,
    )
    df_keep = df_f[df_f["dropped_reason"].fillna("") == ""].copy()
    df_rej  = df_f[df_f["dropped_reason"].fillna("") != ""].copy()

    # 截断到 final_max_size（按 portrait_score 降序）
    if final_max_size and 0 < final_max_size < len(df_keep):
        df_keep = df_keep.sort_values("portrait_score", ascending=False).head(final_max_size).copy()

    filter_dropped = len(df_rej)

    # ────────────────── 目标权重（等权 EW）+ 单股 ≤ max_weight 帽 ──────────────────
    n = len(df_keep)
    if n == 0:
        stats = {
            "in_count": in_count, "filter_dropped": filter_dropped, "out_count": 0,
            "drop_breakdown": breakdown, "turnover_vs_prev": 0.0,
            "phase": "Phase 3 (factor filter + EW target + rolling turnover blend)",
        }
        return df_signals.assign(target_weight=np.nan, prev_weight=0.0,
                                 blended_weight=np.nan, blended_weight_pct=np.nan,
                                 delta_weight=0.0, dropped_reason=df_signals.get("dropped_reason", "")), stats

    target = 1.0 / n
    # 自动调整单股权重上限（N 极小时 1/N > max_weight）
    cap = max(max_weight, target)
    df_keep["target_weight"] = np.clip(target, 0.0, cap)
    # 如果 cap 起作用，归一化回 1.0（不会发生，但保留防御性 normalize）
    tot = float(df_keep["target_weight"].sum())
    if tot > 0:
        df_keep["target_weight"] = df_keep["target_weight"] / tot

    # ────────────────── 多周滚动：推断前仓 + 换手率平滑 ──────────────────
    codes = df_keep["ts_code"].astype(str).tolist()
    close_conn_after = False
    _conn = conn
    if _conn is None and (prev_weights is None):
        _path = db_path or _infer_db_path()
        if os.path.exists(_path):
            try:
                _conn = sqlite3.connect(_path, timeout=20)
                close_conn_after = True
            except Exception:
                _conn = None

    prev = dict(prev_weights) if prev_weights is not None else None
    if prev is None and _conn is not None:
        prev_date = _get_previous_trading_date(_conn, current_date)
        prev = _infer_previous_weights(_conn, prev_date, strategy, codes)
    elif prev is None:
        prev = {c: 0.0 for c in codes}

    # 补齐缺失 code → 0
    for c in codes:
        prev.setdefault(c, 0.0)

    df_keep["prev_weight"] = df_keep["ts_code"].astype(str).map(lambda c: float(prev.get(c, 0.0)))

    # Turnover blend：
    #   先以「从旧仓 w_old → 目标 w_target」计算一个允许最多「max_turnover 的换手总量」。
    #   简化版（私募常用）：逐股票线性插值 + 最后归一化
    #   w_blend[i] = w_old[i] * (1-α) + w_target[i] * α ，其中 α 控制换手上限的强度；
    #   但通常换手定义：turnover = 0.5 * Σ|w_blend[i] - w_old[i]| ，
    #   若直接插值则 turnover = 0.5 * |α| * Σ|target - old| ，反解 α 即可刚好满足 ≤ max_turnover。
    prev_arr = df_keep["prev_weight"].to_numpy(dtype=float)
    tgt_arr  = df_keep["target_weight"].to_numpy(dtype=float)
    # 对于从 0→target 的新进入股票，插值式等价于一次性加仓 α*target（不超过 total target）
    denom = np.sum(np.abs(tgt_arr - prev_arr))
    if denom <= 1e-12:
        # 已经完全是目标仓位（首次建仓：old 全 0，target 总和=1 → denom=1 → 不会走这里）
        alpha = 1.0
    else:
        # 需要的换手上限 max_turnover 对应 0.5*Σ|Δ|=T → Σ|Δ|=2T
        # 直接用 clip 1.0 的 alpha = min(1, 2T / denom)
        alpha = min(1.0, (2.0 * float(max_turnover)) / denom)

    blend_arr = prev_arr + alpha * (tgt_arr - prev_arr)

    # 防御：单股 ≤ cap（通常插值完后不会超，但可能因为 old 过大 → 裁掉然后归一化）
    blend_arr = np.clip(blend_arr, 0.0, cap)
    s = blend_arr.sum()
    if s <= 1e-9:
        blend_arr = tgt_arr.copy()
    else:
        blend_arr = blend_arr / s

    df_keep["blended_weight"] = blend_arr
    df_keep["blended_weight_pct"] = (blend_arr * 100.0).round(1)
    df_keep["delta_weight"] = df_keep["blended_weight"] - df_keep["prev_weight"]

    # 计算换手率（新仓整体 vs 旧仓整体）
    turnover = float(0.5 * np.sum(np.abs(df_keep["delta_weight"].to_numpy(dtype=float))))

    if close_conn_after and _conn is not None:
        try: _conn.close()
        except Exception: pass

    # 合并回完整 df（包含被 drop 的）输出
    # 对齐：先 df_rej，再 df_keep，补齐默认列
    if not df_rej.empty:
        df_rej = df_rej.assign(
            target_weight         = np.nan,
            prev_weight           = df_rej["ts_code"].astype(str).map(lambda c: float(prev.get(c, 0.0))),
            blended_weight        = np.nan,
            blended_weight_pct    = np.nan,
            delta_weight          = 0.0,
        )
    else:
        df_rej = pd.DataFrame(columns=list(df_keep.columns))

    df_out = pd.concat([df_keep, df_rej], ignore_index=True, sort=False)

    stats = {
        "in_count":         in_count,
        "filter_dropped":   filter_dropped,
        "out_count":        len(df_keep),
        "drop_breakdown":   breakdown,
        "turnover_vs_prev": round(turnover, 4),
        "blend_alpha":      round(alpha, 4),
        "target_equal_w":   round(target * 100, 2),   # 百分号：如 5 只 → 20.00%
        "cap_weight_pct":   round(cap * 100, 2),
        "phase": "Phase 3 (factor filter + EW target + rolling turnover blend)",
    }
    return df_out, stats
