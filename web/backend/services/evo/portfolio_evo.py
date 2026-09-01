# -*- coding: utf-8 -*-
"""
services.evo.portfolio_evo —— EVO 版组合推荐（阶段 2 雏形）
=================================================================
用 evo_dynamic_weights_log 的最新动态权重，对最新交易日 factor_values_evo
的 13 个因子做加权综合打分，叠加 Graham 画像调整与拥挤度惩罚（阶段 3 数据）。

只读表：factor_values_evo / evo_dynamic_weights_log / evo_crowding_log
绝不读写经典层任何表，绝不 import 经典层业务模块。
"""

import json
import sqlite3
import logging
from typing import Dict, Any, List, Optional

from services.evo._common import (
    EvoConfig,
    DB_PATH,
    get_db_connection,
    clean_nan_inf,
    check_overlap_and_maybe_fallback,
)

logger = logging.getLogger("services.evo.portfolio_evo")


# ───────────────────────────────────────────────────────────
# 内部工具
# ───────────────────────────────────────────────────────────
def _load_latest_weights(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """读最新权重快照；无则 None"""
    row = conn.execute(
        "SELECT trade_date, weights_json, regime, created_at "
        "FROM evo_dynamic_weights_log ORDER BY trade_date DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[1])
    except Exception:
        return None
    return {
        "trade_date": str(row[0]),
        "regime": row[2],
        "created_at": row[3],
        "weights": payload.get("weights", {}) or {},
        "ic_mean": payload.get("ic_mean", {}) or {},
        "ic_ir": payload.get("ic_ir", {}) or {},
        "meta": payload.get("meta", {}) or {},
    }


def _load_crowding_actions(conn: sqlite3.Connection) -> Dict[str, str]:
    """最新日的拥挤度动作（阶段 3 有数据才非空）：{factor: normal/half_weight/disable}"""
    row = conn.execute(
        "SELECT MAX(trade_date) FROM evo_crowding_log").fetchone()
    if not row or not row[0]:
        return {}
    try:
        rows = conn.execute(
            "SELECT factor_name, action FROM evo_crowding_log WHERE trade_date = ?",
            (str(row[0]),),
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def _effective_weights(
    base_weights: Dict[str, float], crowding: Dict[str, str]
) -> Dict[str, float]:
    """拥挤度动作应用：disable→0，half_weight→×0.5，然后归一化"""
    if not crowding:
        return dict(base_weights)
    w = {}
    for f, v in base_weights.items():
        act = crowding.get(f, "normal")
        w[f] = 0.0 if act == "disable" else v * 0.5 if act == "half_weight" else v
    total = sum(w.values())
    if total <= 1e-12:
        return dict(base_weights)
    return {f: v / total for f, v in w.items()}


# ───────────────────────────────────────────────────────────
# 主入口：EVO TopN 组合
# ───────────────────────────────────────────────────────────
def calc_evo_portfolio(
    top_n: int = 10,
    trade_date: str = "",
    classic_top_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    返回 EVO 侧组合结果（结构对齐 routers.evo /compare/portfolio 的 evo 占位）：
    {
      "stocks": [{ts_code, trade_date, evo_score, dynamic_part, graham_adj,
                  graham_score, factor_components:{...}}],
      "weights_used": {...}, "weight_mode": ..., "weight_as_of": ...,
      "engine_flags": {...}, "classic_overlap_ratio": ..., "fused_by_fallback": ...
    }
    """
    dw_on = bool(EvoConfig.get("dynamic_weights.enabled", False))
    graham_on = bool(EvoConfig.get("graham_filter.enabled", False))

    conn = get_db_connection(DB_PATH)
    try:
        # 1. 权重快照（空 → 均匀兜底在调用方体现；此处返回空 weights 即可触发）
        snap = _load_latest_weights(conn) if dw_on else None

        # 2. 因子交易日
        if trade_date:
            factor_date = str(trade_date)
        else:
            row = conn.execute(
                "SELECT MAX(trade_date) FROM factor_values_evo").fetchone()
            factor_date = str(row[0]) if row and row[0] else ""

        stocks: List[Dict[str, Any]] = []
        weights_used: Dict[str, float] = {}
        weight_mode = "no_snapshot"
        weight_as_of = None
        engine_flags = {
            "dynamic_weight": False,
            "ml_rank": False,
            "graham": graham_on,
            "surprise": bool(EvoConfig.get("surprise_factors.enabled", False)),
            "crowding_filter": False,
        }

        if factor_date:
            # 3. 拥挤度动作（阶段 3 数据，兼容读取）
            crowding = _load_crowding_actions(conn) if EvoConfig.get(
                "crowding_monitor.enabled", False) else {}
            engine_flags["crowding_filter"] = bool(crowding)

            # 4. 权重：快照 > 均匀兜底（用 crowding_log 之外无法知道启用因子集，
            #    从最新日 factor 表列取非空因子作为兜底池）
            if snap and snap["weights"]:
                weights_used = _effective_weights(snap["weights"], crowding)
                weight_mode = snap["meta"].get("mode", "icir_weighted")
                weight_as_of = snap["trade_date"]
                engine_flags["dynamic_weight"] = True
            else:
                cols = [
                    r[1] for r in conn.execute(
                        "PRAGMA table_info(factor_values_evo)").fetchall()
                    if r[1] not in ("ts_code", "trade_date", "graham_score",
                                    "graham_detail_json", "text_sentiment_score")
                ]
                # 只取当日非空率 > 50% 的因子列
                nonnull = {}
                for c in cols:
                    r = conn.execute(
                        f"SELECT AVG(CASE WHEN {c} IS NOT NULL THEN 1.0 ELSE 0.0 END) "
                        f"FROM factor_values_evo WHERE trade_date = ?", (factor_date,)
                    ).fetchone()
                    if r and r[0] and float(r[0]) > 0.5:
                        nonnull[c] = float(r[0])
                if nonnull:
                    k = len(nonnull)
                    weights_used = _effective_weights(
                        {c: 1.0 / k for c in nonnull}, crowding)
                    weight_mode = "uniform_fallback"

            # 5. 加权综合打分（单条 SQL 取当日全部因子 + Graham）
            if weights_used:
                # ── M5.4 mixer 灰度项 ─────────────────────────────
                # β：ML LambdaRank 分（evo_ml_predictions 当日截面 rank）
                # δ：惊喜度分（surprise 三因子截面 rank 均值，剔除拥挤度 disable 项）
                # 说明：α 保持隐含（dyn=Σw×rank, Σw=1 ∈[0,1]），β/δ 为同量纲加成项，
                #       γ 走原 graham_adj 画像加减分路径，ε 已通过拥挤度权重过滤生效。
                beta = float(EvoConfig.get("portfolio_mixer.lambdarank_beta", 0.0))
                delta = float(EvoConfig.get("portfolio_mixer.surprise_delta", 0.0))
                import pandas as pd

                ml_rank_map: Dict[str, float] = {}
                if beta > 1e-9 and EvoConfig.get("lambdarank.enabled", False):
                    try:
                        mrows = conn.execute(
                            "SELECT ts_code, rank_score FROM evo_ml_predictions "
                            "WHERE trade_date = ?", (factor_date,)).fetchall()
                        if len(mrows) >= 100:
                            ms = pd.Series({r[0]: r[1] for r in mrows}, dtype="float32")
                            ml_rank_map = {k: float(v) for k, v in
                                           ms.rank(pct=True).to_dict().items()}
                            engine_flags["ml_rank"] = True
                        else:
                            _logger.warning("[EvoPort] ML 预测数据不足，β 项本次跳过")
                    except Exception as _e:
                        _logger.warning(f"[EvoPort] ML 预测读取失败（β 项跳过）: {_e}")

                surp_cols: List[str] = []
                if delta > 1e-9 and engine_flags.get("surprise"):
                    surp_cols = [
                        c for c in ("surprise_price_vote", "surprise_earnings_gap",
                                    "surprise_roe_qoq")
                        if crowding.get(c, "normal") != "disable"   # 安全闸：拥挤 disable 不进 δ 池
                    ]

                sel_cols = ", ".join(["ts_code"] + list(weights_used.keys()) +
                                     (["graham_score"] if graham_on else []) +
                                     [c for c in surp_cols if c not in weights_used])
                cur = conn.execute(
                    f"SELECT {sel_cols} FROM factor_values_evo WHERE trade_date = ?",
                    (factor_date,),
                )
                cdesc = [d[0] for d in cur.description]
                raw_rows = cur.fetchall()

                # ⚠️ 量纲统一：surprise_roe_qoq 等是 Z-score（±5），交叉因子是 rank（0~1）。
                #    加权前对每个因子先做【当日截面 pct rank】→ 全部统一 [0,1]。
                df_day = pd.DataFrame(raw_rows, columns=cdesc).set_index("ts_code")
                rank_mat: Dict[str, "pd.Series"] = {}
                for f, w in weights_used.items():
                    if w <= 1e-12:
                        continue
                    rank_mat[f] = df_day[f].rank(pct=True).astype("float32") \
                        if f in df_day.columns else None
                surp_rank_mat = {c: (df_day[c].rank(pct=True).astype("float32")
                                     if c in df_day.columns else None)
                                 for c in surp_cols}

                bonus_min = int(EvoConfig.get("graham_filter.scoring.bonus_min_checks", 4))
                bonus_pts = float(EvoConfig.get("graham_filter.scoring.bonus_points", 5.0))
                pen_max = int(EvoConfig.get("graham_filter.scoring.penalty_max_checks", 1))
                pen_pts = float(EvoConfig.get("graham_filter.scoring.penalty_points", 10.0))

                scored: List[Dict[str, Any]] = []
                for ts_code in df_day.index:
                    dyn = 0.0
                    comps: Dict[str, float] = {}
                    for f, w in weights_used.items():
                        if w <= 1e-12:
                            continue
                        sr = rank_mat.get(f)
                        v = None if sr is None else sr.get(ts_code)
                        v = 0.5 if (v is None or pd.isna(v)) else float(v)  # NaN → 中性 0.5
                        comps[f] = round(v, 4)
                        dyn += w * v

                    # β 项：ML 排序分（当日截面 pct rank；无数据时 0）
                    if engine_flags["ml_rank"]:
                        mv = ml_rank_map.get(ts_code)
                        ml_v = 0.5 if (mv is None or pd.isna(mv)) else float(mv)
                        ml_part = beta * ml_v
                    else:
                        ml_part = 0.0

                    # δ 项：惊喜度分（surprise 有效项截面 rank 均值）
                    if surp_rank_mat:
                        svals = []
                        for c, sm in surp_rank_mat.items():
                            if sm is None:
                                continue
                            sv = sm.get(ts_code)
                            svals.append(0.5 if (sv is None or pd.isna(sv)) else float(sv))
                        surp_part = delta * (sum(svals) / len(svals)) if svals else 0.0
                    else:
                        surp_part = 0.0

                    gs = df_day.at[ts_code, "graham_score"] if graham_on and "graham_score" in df_day.columns else None
                    g_adj = 0.0
                    if graham_on and gs is not None and not pd.isna(gs):
                        if gs >= bonus_min:
                            g_adj = bonus_pts * 0.1   # 归一到与 dyn 同量纲（dyn∈[0,1]）
                        elif gs <= pen_max:
                            g_adj = -pen_pts * 0.1
                    scored.append({
                        "ts_code": ts_code,
                        "evo_score": round(dyn + ml_part + surp_part + g_adj, 6),
                        "dynamic_part": round(dyn, 6),
                        "ml_part": round(ml_part, 4),
                        "surprise_part": round(surp_part, 4),
                        "graham_adj": round(g_adj, 3),
                        "graham_score": None if (gs is None or pd.isna(gs)) else int(gs),
                        "factor_components": comps,
                    })
                scored.sort(key=lambda x: -x["evo_score"])
                stocks = scored[:top_n]

                # 6.5 名称映射（只读经典 stock_list，不写不 import 业务逻辑）
                name_map: Dict[str, str] = {}
                try:
                    for tc, nm in conn.execute(
                            "SELECT ts_code, name FROM stock_list"):
                        if nm:
                            name_map[tc] = str(nm).strip()
                except Exception as _e:
                    logger.warning(f"[EvoPort] stock_list 名称映射失败（name 置空）: {_e}")

                # 6.6 等级：组合内 evo_score 分位（透明规则：前20% S / 前50% A / 前80% B / 其余 C）
                n = len(stocks)
                for i, s in enumerate(stocks):
                    s["name"] = name_map.get(s["ts_code"], "")
                    q = (i + 1) / n if n else 1.0
                    s["grade"] = "S" if q <= 0.2 else "A" if q <= 0.5 else "B" if q <= 0.8 else "C"

        # 6. 熔断检查（classic codes 由调用方传入）
        overlap_ratio, should_fb = 0.0, False
        if classic_top_codes and stocks:
            evo_codes = [s["ts_code"] for s in stocks]
            overlap_ratio, should_fb = check_overlap_and_maybe_fallback(
                classic_top_codes, evo_codes)

        return clean_nan_inf({
            "stocks": stocks,
            "factor_date": factor_date or None,
            "weights_used": {k: round(v, 6) for k, v in weights_used.items()},
            "weight_mode": weight_mode,
            "weight_as_of": weight_as_of,
            "weight_snapshot_meta": (snap or {}).get("meta", {}),
            "engine_flags": engine_flags,
            "mixer": {
                "alpha_dynamic": "implicit(sum w=1)",
                "beta_ml": float(EvoConfig.get("portfolio_mixer.lambdarank_beta", 0.0)),
                "gamma_graham": "via graham_adj",
                "delta_surprise": float(EvoConfig.get("portfolio_mixer.surprise_delta", 0.0)),
                "epsilon_crowding": "via effective_weights",
            },
            "classic_overlap_ratio": round(overlap_ratio, 4),
            "fused_by_fallback": should_fb,
            "note": ("EVO 组合：α动态权重 + β ML排序 + δ惊喜度 + γ画像加减（M5.4 完整 mixer）"
                     if stocks else "EVO 组合无数据：先跑 feature_engineering_evo.py"),
        })
    finally:
        conn.close()
