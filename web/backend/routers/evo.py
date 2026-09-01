# -*- coding: utf-8 -*-
"""
routers.evo —— EVO 进化层独立路由（前缀 /api/evo，永不与现有路由冲突）
=============================================================================
阶段 0 只实现骨架接口（返回模块状态 + 对比数据兜底）；
阶段 1+ 逐步把 factors_evo / portfolio_evo / scanner_evo / ml_predict 等服务接进来。

⚠️ 设计约束（务必遵守）：
1. 本路由文件绝不 import 任何经典层 /api/* 的路由函数实现；
   需要经典层数据时，通过"懒加载 + 局部 from services import xxx"获取，避免循环依赖。
2. 所有错误都返回 SafeJSONResponse 风格的结构化错误，禁止把 traceback 暴露给前端。
3. 新增接口的 Query / Body 参数必须给默认值 + 范围校验，避免前端漏参崩后端。
"""

import sys
import os
import json
import logging
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Query

# services.evo 全局初始化 & 公共工具
from services.evo import (
    EvoConfig,
    ensure_evo_tables,
    clean_nan_inf,
    DB_PATH, PROJECT_ROOT,
)

_logger = logging.getLogger("routers.evo")

# ═══════════════════════════════════════════════════════════
# 启动时一次幂等建表（只建 _evo 后缀表，不碰任何现有表）
# ═══════════════════════════════════════════════════════════
try:
    _table_status = ensure_evo_tables(DB_PATH)
    _logger.info(f"[EvoRouter] 启动自检：EVO 表={list(_table_status.keys())}")
except Exception as _e:
    _logger.error(f"[EvoRouter] 建表失败（将继续运行，接口会降级）: {_e}")
    _table_status = {}


# ═══════════════════════════════════════════════════════════
# EVO 路由组
# ═══════════════════════════════════════════════════════════
router = APIRouter(
    prefix="/api/evo",
    tags=["evo"],
    responses={404: {"description": "EVO 进化层接口不存在，可能尚未进入阶段 N 实现"}},
)


# ───────────────────────────────────────────────────────────
# ① 对比 & 状态类（阶段 0 必须可用）
# ───────────────────────────────────────────────────────────

@router.get("/status")
def evo_status() -> Dict[str, Any]:
    """
    EVO 进化层总状态：
    - 8 大模块启用状态
    - 数据库表就绪情况
    - evo.yaml 版本 & note
    """
    status = {
        "ok": True,
        "layer": "EVO 进化层（平行路由，不影响经典系统）",
        "version": EvoConfig.version,
        "note": EvoConfig.get("note", ""),
        "modules": EvoConfig.all_modules_status,
        "tables_ready": _table_status,
        "frontend": EvoConfig.get("frontend", {}),
    }
    return clean_nan_inf(status)


@router.get("/compare/portfolio")
def evo_compare_portfolio(top_n: int = Query(10, ge=5, le=30)) -> Dict[str, Any]:
    """
    经典 vs 进化 今日推荐 A/B 对比（阶段 0 返回占位；
    阶段 2 动态权重实现后，evo 列会填充真实结果）
    """
    # 懒加载经典层 get_today_portfolio（避免在模块 import 期触发循环依赖）
    # ⚠️ 经典层返回结构：成功=list[stock]；失败=[] → 统一包装为 dict（不改经典层）
    classic: Dict[str, Any] = {"error": "classic_portfolio_not_ready", "stocks": [], "date": None}
    try:
        from services import get_today_portfolio as _classic_portfolio_fn
        _raw = _classic_portfolio_fn()
        if isinstance(_raw, list):
            classic = {"stocks": _raw, "date": None}
        elif isinstance(_raw, dict):
            classic = _raw or classic
    except Exception as _e:
        _logger.warning(f"[Compare] 经典 portfolio 获取失败: {_e}")

    # EVO 列占位：阶段 2 会由 portfolio_evo.calc_evo_portfolio() 替换
    classic_codes: List[str] = []
    if isinstance(classic, dict):
        for s in classic.get("stocks") or []:
            # 经典层主键=stock_code，EVO 层主键=ts_code → 双键兼容
            if isinstance(s, dict):
                code = s.get("ts_code") or s.get("stock_code")
                if code:
                    classic_codes.append(code)

    evo_result: Dict[str, Any] = {
        "stocks": [],
        "note": "EVO 组合：阶段 2+ 启用。当前仅为骨架，展示『经典 + EVO』对比框架。",
        "engine_flags": {
            "dynamic_weight": False,
            "ml_rank": False,
            "graham": False,
            "surprise": False,
            "crowding_filter": False,
        },
        "classic_overlap_ratio": 0.0,
        "fused_by_fallback": False,
    }

    # 阶段 2：动态权重 × 最新日因子 → EVO TopN（失败保持占位，绝不影响接口可用性）
    try:
        from services.evo.portfolio_evo import calc_evo_portfolio
        evo_result = calc_evo_portfolio(
            top_n=top_n, classic_top_codes=classic_codes or None)
    except Exception as _e:
        _logger.warning(f"[Compare] EVO 组合计算失败，保持占位: {_e}")

    # 共同推荐（经典 ∩ EVO）
    evo_codes = [s.get("ts_code") for s in (evo_result.get("stocks") or [])
                 if isinstance(s, dict) and s.get("ts_code")]
    overlap_codes = sorted(set(classic_codes) & set(evo_codes))

    result = {
        "date": classic.get("date") if isinstance(classic, dict) else None,
        "top_n": top_n,
        "classic": classic,
        "evo": evo_result,
        "overlap_codes": overlap_codes,
    }
    return clean_nan_inf(result)


@router.get("/compare/scan")
def evo_compare_scan() -> Dict[str, Any]:
    """经典 vs 进化 建仓扫描 A/B 对比（阶段 1 实现交叉因子后填充 EVO 侧）"""
    classic = {"error": "classic_scan_not_ready", "stocks": []}
    try:
        from services import get_build_position_opportunities as _classic_scan_fn
        classic = _classic_scan_fn() or classic
    except Exception as _e:
        _logger.warning(f"[Compare] 经典 scan 获取失败: {_e}")

    return clean_nan_inf({
        "classic": classic,
        "evo": {
            "stocks": [],
            "note": "EVO 扫描：阶段 3+ 启用。将融合交叉因子、拥挤度过滤、Graham 评分与动态权重。",
        },
    })


# ───────────────────────────────────────────────────────────
# ② 动态权重（P0-1，阶段 2 实现）
# ───────────────────────────────────────────────────────────

@router.get("/weights/dynamic")
def evo_weights_dynamic() -> Dict[str, Any]:
    """当日各因子的 ICIR 动态权重（读 evo_dynamic_weights_log 最新快照）"""
    if not EvoConfig.get("dynamic_weights.enabled", False):
        return {"ok": True, "enabled": False, "weights": {},
                "note": "dynamic_weights 模块未在 evo.yaml 中启用"}
    try:
        from services.evo import get_db_connection
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "SELECT trade_date, weights_json, regime, created_at "
                "FROM evo_dynamic_weights_log ORDER BY trade_date DESC LIMIT 1"
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except Exception as _e:
        row = None
        _logger.warning(f"[Weights/Dynamic] 读快照失败: {_e}")

    if row:
        try:
            payload = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
        except Exception:
            payload = {}
        return clean_nan_inf({
            "ok": True,
            "enabled": True,
            "trade_date": str(row[0]),
            "regime": row[2],
            "weights": payload.get("weights", {}),
            "ic_mean": payload.get("ic_mean", {}),
            "ic_ir": payload.get("ic_ir", {}),
            "meta": payload.get("meta", {}),
            "ic_window": EvoConfig.get("dynamic_weights.ic_window", 20),
            "updated_at": row[3],
            "note": "快照由 src/evo_dynamic_weights.py 每日 pipeline 写入。",
        })

    # 兜底：尚无快照 → 均匀权重（enabled 因子均分），接口仍可用
    enabled_factors: List[str] = []
    if EvoConfig.get("cross_factors.enabled", False):
        enabled_factors += [k for k, v in (EvoConfig.get("cross_factors.factors", {}) or {}).items() if v]
    if EvoConfig.get("surprise_factors.enabled", True):
        enabled_factors += [c for c in ("surprise_price_vote", "surprise_earnings_gap", "surprise_roe_qoq")
                            if EvoConfig.get(f"surprise_factors.{c}", True)]
    k = max(1, len(enabled_factors))
    return clean_nan_inf({
        "ok": True,
        "enabled": True,
        "trade_date": None,
        "weights": {f: round(1.0 / k, 6) for f in enabled_factors},
        "ic_mean": {}, "ic_ir": {}, "meta": {},
        "ic_window": EvoConfig.get("dynamic_weights.ic_window", 20),
        "note": "尚无动态权重快照（先运行 src/evo_dynamic_weights.py），当前返回均匀权重兜底。",
    })


@router.get("/weights/history")
def evo_weights_history(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
    """最近 N 日权重变化曲线（读 evo_dynamic_weights_log 快照序列）"""
    series: List[Dict[str, Any]] = []
    try:
        from services.evo import get_db_connection
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "SELECT trade_date, weights_json, regime, created_at "
                "FROM evo_dynamic_weights_log ORDER BY trade_date DESC LIMIT ?", (days,)
            )
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                item = dict(zip(cols, r))
                try:
                    payload = json.loads(item.get("weights_json") or "{}")
                    item["weights"] = payload.get("weights", {})
                    item["ic_ir"] = payload.get("ic_ir", {})
                except Exception:
                    item["weights"] = {}
                series.append(item)
        finally:
            conn.close()
    except Exception as _e:
        series = []
        _logger.warning(f"[W/History] 查历史权重失败: {_e}")
    return clean_nan_inf({
        "days": days,
        "count": len(series),
        "series": series,
        "note": "有值=动态权重引擎已在每日 pipeline 运行；空=尚未产出。",
    })


# ───────────────────────────────────────────────────────────
# ③ 交叉因子（P0-2，阶段 1 实现）
# ───────────────────────────────────────────────────────────

@router.get("/factors/list")
def evo_factors_list() -> Dict[str, Any]:
    """进化层完整因子清单（经典 26 + EVO 新增 20+）& 模块启用情况"""
    classic_factors = []
    try:
        import yaml
        cf_path = os.path.join(PROJECT_ROOT, "config", "candidate_factors.yaml")
        if os.path.isfile(cf_path):
            with open(cf_path, "r", encoding="utf-8") as f:
                classic_factors = yaml.safe_load(f) or []
                if isinstance(classic_factors, dict):
                    classic_factors = classic_factors.get("candidate_factors", []) or []
    except Exception:
        classic_factors = []

    cross_cfg = EvoConfig.get("cross_factors.factors", {}) or {}
    cross_enabled = [k for k, v in cross_cfg.items() if v]

    return clean_nan_inf({
        "classic": {
            "count": len(classic_factors),
            "factors": list(classic_factors),
            "source": "config/candidate_factors.yaml",
        },
        "evo_cross": {
            "enabled_count": len(cross_enabled),
            "enabled_factors": cross_enabled,
            "all_factors": list(cross_cfg.keys()),
        },
        "modules_status": EvoConfig.all_modules_status,
    })


@router.get("/factors/cross")
def evo_factors_cross(
    trade_date: str = "",
    top_n: int = Query(20, ge=5, le=100),
) -> Dict[str, Any]:
    """
    交叉因子 Top/Bottom 股票（阶段 1 factor_values_evo 写入后返回真实数据；
    当前阶段返回表结构与占位，便于前端先渲染组件框架）
    """
    enabled_cfg = EvoConfig.get("cross_factors.factors", {}) or {}
    enabled = [k for k, v in enabled_cfg.items() if v]

    rows: List[Dict[str, Any]] = []
    resolved_date = trade_date
    if EvoConfig.get("cross_factors.enabled", False):
        try:
            from services.evo import get_db_connection
            conn = get_db_connection()
            try:
                sel_cols_list = ["ts_code", "trade_date"] + [c for c in enabled]
                sel_cols = ", ".join(sel_cols_list)
                if not resolved_date:
                    last = conn.execute(
                        "SELECT MAX(trade_date) FROM factor_values_evo"
                    ).fetchone()
                    if last and last[0]:
                        resolved_date = str(last[0])
                if resolved_date:
                    q = f"SELECT {sel_cols} FROM factor_values_evo WHERE trade_date = ? LIMIT ?"
                    cur = conn.execute(q, (resolved_date, top_n * 3))
                    cols = [d[0] for d in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            finally:
                conn.close()
        except Exception as _e:
            _logger.warning(f"[Factors/Cross] 查询失败（属正常：表可能还未写入）: {_e}")

    return clean_nan_inf({
        "trade_date": resolved_date or None,
        "enabled_factors": enabled,
        "count": len(rows),
        "data": rows[:top_n],
        "note": "空列表=进化因子 pipeline 尚未运行；非空=src/feature_engineering_evo.py 已产出数据。",
    })


# ───────────────────────────────────────────────────────────
# ④ 拥挤度监控（P0-3）
# ───────────────────────────────────────────────────────────

@router.get("/crowding/status")
def evo_crowding_status() -> Dict[str, Any]:
    """各因子当日拥挤度评分 + 动作建议（src/evo_monitors.py 每日写入）"""
    rows: List[Dict[str, Any]] = []
    try:
        from services.evo import get_db_connection
        conn = get_db_connection()
        try:
            last = conn.execute("SELECT MAX(trade_date) FROM evo_crowding_log").fetchone()
            if last and last[0]:
                cur = conn.execute(
                    "SELECT trade_date, factor_name, crowding_score, action FROM evo_crowding_log "
                    "WHERE trade_date = ? ORDER BY crowding_score DESC", (str(last[0]),)
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as _e:
        _logger.warning(f"[Crowding] 查日志失败: {_e}")

    n_disable = sum(1 for r in rows if r.get("action") == "disable")
    n_half = sum(1 for r in rows if r.get("action") == "half_weight")
    return clean_nan_inf({
        "enabled": EvoConfig.get("crowding_monitor.enabled", False),
        "date": rows[0]["trade_date"] if rows else None,
        "count": len(rows),
        "factors": rows,
        "summary": {"n_disable": n_disable, "n_half_weight": n_half, "n_normal": len(rows) - n_disable - n_half},
        "thresholds": {
            "half_weight": EvoConfig.get("crowding_monitor.half_weight_threshold", 0.70),
            "disable":     EvoConfig.get("crowding_monitor.disable_threshold", 0.85),
        },
    })


@router.get("/crowding/history")
def evo_crowding_history(factor_name: str = "", days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
    """拥挤度历史曲线（用于 UI 折线图）"""
    try:
        from services.evo import get_db_connection
        conn = get_db_connection()
        try:
            q = "SELECT trade_date, factor_name, crowding_score, action FROM evo_crowding_log "
            params: List[Any] = []
            if factor_name:
                q += "WHERE factor_name = ? "
                params.append(factor_name)
            q += "ORDER BY trade_date DESC LIMIT ?"
            params.append(days * 15)
            cur = conn.execute(q, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as _e:
        rows = []
        _logger.warning(f"[Crowding/Hist] 查失败: {_e}")
    return clean_nan_inf({"factor": factor_name, "days": days, "count": len(rows), "series": rows})


# ───────────────────────────────────────────────────────────
# ⑤ Graham 价值雷达（P2-7）
# ───────────────────────────────────────────────────────────

@router.get("/graham/screen")
def evo_graham_screen(
    min_checks: int = Query(4, ge=0, le=7),
    top_n: int = Query(30, ge=5, le=200),
    trade_date: str = "",
) -> Dict[str, Any]:
    """
    满足 Graham 条件 ≥ min_checks 项的股票池（阶段 1 起有 factor_values_evo 后真实）
    """
    rows: List[Dict[str, Any]] = []
    resolved_date = trade_date
    if EvoConfig.get("graham_filter.enabled", False):
        try:
            from services.evo import get_db_connection
            conn = get_db_connection()
            try:
                if not resolved_date:
                    last = conn.execute(
                        "SELECT MAX(trade_date) FROM factor_values_evo WHERE graham_score IS NOT NULL"
                    ).fetchone()
                    if last and last[0]:
                        resolved_date = str(last[0])
                if resolved_date:
                    sql = (
                        "SELECT ts_code, graham_score, graham_detail_json "
                        "FROM factor_values_evo "
                        "WHERE trade_date = ? AND graham_score >= ? "
                        "ORDER BY graham_score DESC, ts_code LIMIT ?"
                    )
                    cur = conn.execute(sql, (resolved_date, min_checks, top_n))
                    cols = [d[0] for d in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            finally:
                conn.close()
        except Exception as _e:
            _logger.warning(f"[Graham/Screen] 查询失败: {_e}")

    return clean_nan_inf({
        "enabled": EvoConfig.get("graham_filter.enabled", False),
        "trade_date": resolved_date or None,
        "min_checks": min_checks,
        "total": len(rows),
        "count": len(rows),
        "data": rows,
    })


@router.get("/graham/score/{ts_code}")
def evo_graham_score_detail(ts_code: str, trade_date: str = "") -> Dict[str, Any]:
    """单股 Graham 7 项雷达图数据"""
    resolved_date = trade_date
    row = None
    try:
        from services.evo import get_db_connection
        conn = get_db_connection()
        try:
            if not resolved_date:
                last = conn.execute(
                    "SELECT MAX(trade_date) FROM factor_values_evo WHERE ts_code = ? "
                    "AND graham_score IS NOT NULL", (ts_code,)
                ).fetchone()
                if last and last[0]:
                    resolved_date = str(last[0])
            if resolved_date:
                cur = conn.execute(
                    "SELECT ts_code, trade_date, graham_score, graham_detail_json "
                    "FROM factor_values_evo WHERE ts_code = ? AND trade_date = ?",
                    (ts_code, resolved_date)
                )
                one = cur.fetchone()
                if one:
                    # ⚠️ sqlite3 默认返回 tuple，dict(tuple) 会抛异常被吞掉 → 手动按列名组 dict
                    row = dict(zip([d[0] for d in cur.description], one))
        finally:
            conn.close()
    except Exception as _e:
        _logger.warning(f"[Graham/Detail] {ts_code} 查询失败: {_e}")

    if row is None:
        return clean_nan_inf({
            "ts_code": ts_code,
            "trade_date": resolved_date or None,
            "score": None,
            "detail": None,
            "note": "Graham 评分暂不可用：或为 EVO 表尚未写入，或为代码不在池中。",
        })

    detail = {}
    try:
        if row.get("graham_detail_json"):
            detail = json.loads(row["graham_detail_json"])
    except Exception:
        detail = {}
    return clean_nan_inf({
        "ts_code": row.get("ts_code"),
        "trade_date": row.get("trade_date"),
        "score": row.get("graham_score"),
        "detail": detail,
    })


# ───────────────────────────────────────────────────────────
# ⑥ ML 排序学习（P1-4，阶段 5 实现）
# ───────────────────────────────────────────────────────────

@router.get("/ml/portfolio")
def evo_ml_portfolio(top_n: int = Query(30, ge=5, le=100)) -> Dict[str, Any]:
    """LambdaRank 推理 Top N（lambdarank 未启用时返回状态而非空列表）"""
    if not EvoConfig.get("lambdarank.enabled", False):
        return {
            "enabled": False,
            "top_n": top_n,
            "stocks": [],
            "note": "lambdarank 模块在 evo.yaml 中为关闭状态；数据积累后可开启。",
        }
    rows: List[Dict[str, Any]] = []
    try:
        from services.evo import get_db_connection
        conn = get_db_connection()
        try:
            last = conn.execute(
                "SELECT MAX(trade_date) FROM evo_ml_predictions"
            ).fetchone()
            if last and last[0]:
                cur = conn.execute(
                    "SELECT ts_code, rank_score, shap_json FROM evo_ml_predictions "
                    "WHERE trade_date = ? ORDER BY rank_score DESC LIMIT ?",
                    (str(last[0]), top_n))
                _cols = [d[0] for d in cur.description]
                rows = [dict(zip(_cols, r)) for r in cur.fetchall()]
                for row in rows:  # shap_json 字符串 → 对象（前端免 parse）
                    try:
                        row["shap_json"] = json.loads(row["shap_json"]) if row.get("shap_json") else None
                    except Exception:
                        pass
        finally:
            conn.close()
    except Exception as _e:
        _logger.warning(f"[ML/Port] 查失败: {_e}")
    return clean_nan_inf({
        "enabled": True,
        "trade_date": str(last[0]) if last and last[0] else None,
        "top_n": top_n,
        "count": len(rows),
        "stocks": rows,
    })


@router.get("/ml/shap/{ts_code}")
def evo_ml_shap(ts_code: str, trade_date: str = "") -> Dict[str, Any]:
    """单股 SHAP 因子贡献拆解（雷达图/条形图用）"""
    resolved_date = trade_date
    shap_json = None
    try:
        from services.evo import get_db_connection
        conn = get_db_connection()
        try:
            if not resolved_date:
                last = conn.execute(
                    "SELECT MAX(trade_date) FROM evo_ml_predictions WHERE ts_code = ?", (ts_code,)
                ).fetchone()
                if last and last[0]:
                    resolved_date = str(last[0])
            if resolved_date:
                one = conn.execute(
                    "SELECT shap_json FROM evo_ml_predictions "
                    "WHERE ts_code = ? AND trade_date = ?", (ts_code, resolved_date)
                ).fetchone()
                if one and one[0]:
                    shap_json = json.loads(one[0])
        finally:
            conn.close()
    except Exception as _e:
        _logger.warning(f"[ML/SHAP] {ts_code} 查失败: {_e}")
    return clean_nan_inf({
        "ts_code": ts_code,
        "trade_date": resolved_date or None,
        "enabled": EvoConfig.get("lambdarank.enabled", False),
        "shap": shap_json,
    })


# ───────────────────────────────────────────────────────────
# ⑦ 预期差因子（P1-5）
# ───────────────────────────────────────────────────────────

@router.get("/surprise/top")
def evo_surprise_top(top_n: int = Query(20, ge=5, le=100), trade_date: str = "") -> Dict[str, Any]:
    """超预期因子 Top N"""
    resolved_date = trade_date
    rows: List[Dict[str, Any]] = []
    if EvoConfig.get("surprise_factors.enabled", False):
        try:
            from services.evo import get_db_connection
            conn = get_db_connection()
            try:
                cols = ["surprise_price_vote", "surprise_earnings_gap", "surprise_roe_qoq"]
                if not resolved_date:
                    last = conn.execute(
                        "SELECT MAX(trade_date) FROM factor_values_evo "
                        "WHERE COALESCE(surprise_price_vote, surprise_earnings_gap, surprise_roe_qoq) IS NOT NULL"
                    ).fetchone()
                    if last and last[0]:
                        resolved_date = str(last[0])
                if resolved_date:
                    sel = "ts_code, " + ", ".join(cols)
                    cur = conn.execute(
                        f"SELECT {sel} FROM factor_values_evo "
                        f"WHERE trade_date = ? ORDER BY (COALESCE(surprise_price_vote,0)+COALESCE(surprise_roe_qoq,0)) DESC LIMIT ?",
                        (resolved_date, top_n)
                    )
                    # ⚠️ sqlite3 默认返回 tuple，dict(tuple) 会抛异常被吞掉 → 手动按列名组 dict
                    _cols = [d[0] for d in cur.description]
                    rows = [dict(zip(_cols, r)) for r in cur.fetchall()]
            finally:
                conn.close()
        except Exception as _e:
            _logger.warning(f"[Surprise/Top] 查失败: {_e}")

    return clean_nan_inf({
        "enabled": EvoConfig.get("surprise_factors.enabled", False),
        "trade_date": resolved_date or None,
        "count": len(rows),
        "stocks": rows,
    })


# ───────────────────────────────────────────────────────────
# ⑧ 因子衰减预警（P3-8）
# ───────────────────────────────────────────────────────────

@router.get("/decay/alerts")
def evo_decay_alerts() -> Dict[str, Any]:
    """当前因子衰减警告清单（黄/红两级，src/evo_monitors.py 每日写入）"""
    alerts: List[Dict[str, Any]] = []
    try:
        from services.evo import get_db_connection
        conn = get_db_connection()
        try:
            last = conn.execute("SELECT MAX(alert_date) FROM evo_decay_alerts").fetchone()
            if last and last[0]:
                cur = conn.execute(
                    "SELECT alert_date, factor_name, level, rolling_ic, description "
                    "FROM evo_decay_alerts WHERE alert_date = ? ORDER BY level, factor_name",
                    (str(last[0]),)
                )
                cols = [d[0] for d in cur.description]
                alerts = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as _e:
        _logger.warning(f"[Decay/Alerts] 查失败: {_e}")
    n_red = sum(1 for a in alerts if a.get("level") == "red")
    return clean_nan_inf({
        "enabled": EvoConfig.get("decay_monitor.enabled", False),
        "count": len(alerts),
        "n_red": n_red,
        "n_yellow": len(alerts) - n_red,
        "alerts": alerts,
        "yellow_threshold_ic": EvoConfig.get("decay_monitor.yellow_ic_min", 0.01),
        "red_neg_days":       EvoConfig.get("decay_monitor.red_consecutive_negative_days", 5),
    })


@router.get("/decay/history")
def evo_decay_history(factor_name: str = "", days: int = Query(60, ge=1, le=720)) -> Dict[str, Any]:
    """各因子每日 RankIC 曲线（读 evo_factor_ic_daily，衰减分析图数据源）"""
    series: List[Dict[str, Any]] = []
    try:
        from services.evo import get_db_connection
        conn = get_db_connection()
        try:
            q = "SELECT trade_date, factor_name, rank_ic FROM evo_factor_ic_daily "
            params: List[Any] = []
            if factor_name:
                q += "WHERE factor_name = ? "
                params.append(factor_name)
            q += "ORDER BY trade_date DESC LIMIT ?"
            params.append(days * len(EvoConfig.get("cross_factors.factors", {}) or {}) + 200)
            cur = conn.execute(q, params)
            cols = [d[0] for d in cur.description]
            series = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as _e:
        series = []
        _logger.warning(f"[Decay/Hist] 查失败: {_e}")
    return clean_nan_inf({
        "enabled": EvoConfig.get("decay_monitor.enabled", False),
        "factor": factor_name,
        "days": days,
        "count": len(series),
        "series": series,
        "note": "有值=src/evo_monitors.py 已在每日管线运行；空=尚未产出。",
    })


# ───────────────────────────────────────────────────────────
# ⑨ EVO 核心业务接口（阶段 N 逐步替换经典路由调用）
# ───────────────────────────────────────────────────────────

@router.get("/portfolio")
def evo_portfolio(top_n: int = Query(10, ge=5, le=30)) -> Dict[str, Any]:
    """
    EVO 版今日推荐（核心）：
    按 portfolio_mixer 融合 = 动态权重 × α + ML × β + Graham调整 + 预期差奖励 - 拥挤度惩罚
    未实现的模块自动跳过；最终结果返回 + 每只股票标明"哪些 EVO 模块贡献了打分"。
    """
    flags = {
        "dynamic_weight": EvoConfig.get("dynamic_weights.enabled", False),
        "ml_rank":        EvoConfig.get("lambdarank.enabled", False),
        "graham":         EvoConfig.get("graham_filter.enabled", False),
        "surprise":       EvoConfig.get("surprise_factors.enabled", False),
        "crowding_filter": EvoConfig.get("crowding_monitor.enabled", False),
    }

    # 阶段 2+：直接调用 portfolio_evo.calc_evo_portfolio（与 /compare/portfolio 同源）
    try:
        from services.evo.portfolio_evo import calc_evo_portfolio
        evo_result = calc_evo_portfolio(top_n=top_n)
        stocks = evo_result.get("stocks") or []
        date = evo_result.get("factor_date")
        note = evo_result.get("note") or "EVO 完整 mixer：动态权重+ML+惊喜度+Graham（拥挤度过滤）"
    except Exception as _e:
        _logger.warning(f"[EvoPort] EVO 组合计算失败: {_e}")
        stocks, date = [], None
        note = f"EVO 组合计算暂不可用: {_e}"

    return clean_nan_inf({
        "date": date,
        "stocks": stocks,
        "engine_flags": flags,
        "mixer_weights": EvoConfig.get("portfolio_mixer", {}),
        "note": note,
    })


@router.get("/scan-opportunities")
def evo_scan_opportunities(top_n: int = Query(30, ge=5, le=200)) -> Dict[str, Any]:
    """EVO 版建仓扫描（阶段 3 起融合交叉/拥挤/动态权重）"""
    try:
        from services import get_build_position_opportunities as _csf
        base = _csf() or {}
    except Exception as _e:
        base = {"stocks": [], "meta": {}}
    return clean_nan_inf({
        "classic_overlay": base,
        "evo_enrichments": [],
        "note": "阶段 3 起：每只扫描股附带 ①交叉因子排名 ②Graham得分 ③拥挤度评分 ④ML rank_score 四列增强信息。",
    })


@router.get("/portrait/position-pick")
def evo_portrait_pick(
    top_n: int = Query(30, ge=10, le=60),
    strategy: str = Query("left", pattern="^(left|right)$"),
) -> Dict[str, Any]:
    """EVO 版画像建仓三层漏斗（阶段 3+ 融合）"""
    try:
        from services import get_portrait_position_pick as _cppf
        base = _cppf(top_n=top_n, strategy=strategy) or {}
    except Exception as _e:
        _logger.warning(f"[EvoPick] 经典兜底失败: {_e}")
        base = {"stocks": [], "funnel": {}}
    return clean_nan_inf({
        "strategy": strategy,
        "classic_overlay": base,
        "evo_adjustments": {
            "graham_bonus_points":  EvoConfig.get("graham_filter.scoring.bonus_points", 0),
            "graham_penalty_points": EvoConfig.get("graham_filter.scoring.penalty_points", 0),
            "crowding_penalty_enabled": EvoConfig.get("crowding_monitor.enabled", False),
        },
        "note": "阶段 3 起：在层一画像分上自动叠加 Graham ±分，层二/三叠加拥挤度降权。",
    })


# ───────────────────────────────────────────────────────────
# ⑨ EVO 每日调度（阶段 2.5：独立调度器，app.py 零改动）
# ───────────────────────────────────────────────────────────

# 模块 import 时启动 EVO 独立调度器（app.py 已 include_router → 自动生效）
# 经典层 18:30/20:30 数据链之后 → EVO 19:30/21:30 跑 因子计算+动态权重
try:
    from services.evo import scheduler_evo as _evo_sched_mod
    _evo_sched_mod.start_evo_scheduler()
except Exception as _e:
    _logger.error(f"[EvoRouter] EVO 调度器启动失败（接口不受影响）: {_e}")


@router.get("/scheduler/status")
def evo_scheduler_status() -> Dict[str, Any]:
    """EVO 每日调度器状态：cron、注册 jobs、上次运行结果"""
    try:
        state = _evo_sched_mod.get_state()
    except Exception as _e:
        _logger.warning(f"[Sched/Status] 读取失败: {_e}")
        state = {"enabled": False, "jobs": [], "last_run": {}, "error": str(_e)}
    return clean_nan_inf(state)


@router.post("/scheduler/run")
def evo_scheduler_run() -> Dict[str, Any]:
    """手动触发一次 EVO 管线（因子计算 + 动态权重；防重入）"""
    try:
        return _evo_sched_mod.trigger_manual()
    except Exception as _e:
        _logger.warning(f"[Sched/Run] 触发失败: {_e}")
        return {"ok": False, "message": f"触发失败: {_e}"}
