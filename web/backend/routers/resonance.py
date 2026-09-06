# -*- coding: utf-8 -*-
"""
routers.resonance —— 四重共振策略路由（零侵入）
=================================================

⚠️ 零侵入原则：
1. 前缀 /api/resonance/*，与经典路由完全隔离
2. 仅写入 resonance_history 表，不影响其他业务表
3. 删除本文件 + 移除注册即回滚
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query

_logger = logging.getLogger("routers.resonance")

router = APIRouter(
    prefix="/api/resonance",
    tags=["resonance"],
)


def _svc():
    from services.resonance_service import (
        get_resonance_scan,
        get_resonance_detail,
        get_sell_signals,
        get_resonance_history,
        get_dimension_ic,
    )
    return {
        "scan": get_resonance_scan,
        "detail": get_resonance_detail,
        "sell_signals": get_sell_signals,
        "history": get_resonance_history,
        "dimension_ic": get_dimension_ic,
    }


@router.get("/scan")
def api_scan(
    top_n: int = Query(50, ge=1, le=200, description="返回股票数量"),
    pool: str = Query("all", description="股票池：all/large/mid/small/micro"),
    date: Optional[str] = Query(None, description="扫描日期（YYYYMMDD）"),
):
    """四重共振截面扫描：返回 Top-N 股票列表 + 四维分数 + 共振等级 + 建议仓位"""
    try:
        return _svc()["scan"](top_n=top_n, pool=pool, date=date)
    except Exception as e:
        _logger.error(f"/scan error: {e}")
        return {"success": False, "error": str(e), "stocks": [], "meta": {}}


@router.get("/stock/{ts_code}")
def api_stock_detail(ts_code: str, date: Optional[str] = None):
    """单只股票的四维详情 + 雷达图数据 + 历史共振等级变化"""
    try:
        return _svc()["detail"](ts_code, date=date)
    except Exception as e:
        _logger.error(f"/stock/{ts_code} error: {e}")
        return {"success": False, "error": str(e), "data": {}}


@router.get("/sell-signals/{ts_code}")
def api_sell_signals(ts_code: str, date: Optional[str] = None):
    """单只股票的 3 条卖出铁律信号检查结果"""
    try:
        return _svc()["sell_signals"](ts_code, date=date)
    except Exception as e:
        _logger.error(f"/sell-signals/{ts_code} error: {e}")
        return {"success": False, "error": str(e), "data": {}}


@router.get("/history")
def api_history(
    days: int = Query(30, ge=1, le=365, description="查询最近 N 天"),
):
    """近 N 天的共振扫描历史（按日期分组）"""
    try:
        return _svc()["history"](days=days)
    except Exception as e:
        _logger.error(f"/history error: {e}")
        return {"success": False, "error": str(e), "daily": {}, "dates": [], "meta": {}}


@router.get("/dimension-ic")
def api_dimension_ic(
    days: int = Query(60, ge=10, le=365, description="回看天数"),
):
    """四维各自的 IC 表现对比（IC 均值 / ICIR / 胜率）"""
    try:
        return _svc()["dimension_ic"](days=days)
    except Exception as e:
        _logger.error(f"/dimension-ic error: {e}")
        return {"success": False, "error": str(e), "data": {}, "meta": {}}
