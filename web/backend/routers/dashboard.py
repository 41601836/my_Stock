# -*- coding: utf-8 -*-
"""
dashboard.py — 指挥中心 API 路由
GET  /api/dashboard           — 总览数据
POST /api/dashboard/run       — 手动触发每日闭环
POST /api/dashboard/verify    — 验证未验证记录
GET  /api/dashboard/trend     — 命中率趋势
GET  /api/dashboard/feedback  — 权重反馈状态
POST /api/dashboard/feedback/adjust — 自动调整权重
"""
from fastapi import APIRouter, Query
from typing import Optional

from web.backend.services.dashboard_service import (
    get_dashboard,
    run_daily_loop,
    verify_previous_selections,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
@router.get("/")
def dashboard():
    """指挥中心总览"""
    return get_dashboard()


@router.post("/run")
def run_daily(
    top_n: int = Query(20, ge=5, le=100),
    pool: str = Query("all"),
):
    """手动触发每日闭环：验证昨日 + 今日选股"""
    return run_daily_loop(top_n=top_n, pool=pool)


@router.post("/verify")
def verify():
    """手动触发验证未验证的选股记录"""
    return verify_previous_selections()


@router.get("/trend")
def trend(days: int = Query(30, ge=1, le=120)):
    """命中率趋势"""
    from web.backend.services.dashboard_service import ensure_tables
    import sqlite3, os

    ensure_tables()
    db = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "db", "stock_data.db")
    conn = sqlite3.connect(db)
    try:
        import pandas as pd
        df = pd.read_sql("""
            SELECT selection_date,
                   COUNT(*) as total,
                   SUM(is_hit) as hits,
                   AVG(excess_return) as avg_excess,
                   AVG(pct_chg) as avg_return
            FROM performance_log
            GROUP BY selection_date
            ORDER BY selection_date DESC
            LIMIT ?
        """, conn, params=[days])
        return {"success": True, "trend": df.to_dict("records")}
    except Exception as e:
        return {"success": False, "error": str(e), "trend": []}
    finally:
        conn.close()


@router.get("/feedback")
def feedback_status():
    """获取权重反馈机制状态"""
    from web.backend.services.weight_feedback import get_feedback_status
    return get_feedback_status()


@router.post("/feedback/adjust")
def feedback_adjust(
    learning_rate: float = Query(0.05, ge=0.01, le=0.3),
    min_samples: int = Query(10, ge=3, le=100),
):
    """根据历史命中率自动调整维度权重"""
    from web.backend.services.weight_feedback import update_resonance_weights
    return update_resonance_weights(learning_rate=learning_rate, min_samples=min_samples)
