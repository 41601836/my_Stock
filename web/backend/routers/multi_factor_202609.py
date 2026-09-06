# -*- coding: utf-8 -*-
"""
routers.multi_factor_202609 —— 202609 多因子分析路由（零侵入）
================================================================

⚠️ 零侵入原则：
1. 前缀 /api/mf202609/*，与经典路由完全隔离
2. 仅写入 mf202609_history 表，不影响其他业务表
3. 删除本文件 + 移除注册即回滚
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query

_logger = logging.getLogger("routers.multi_factor_202609")

router = APIRouter(
    prefix="/api/mf202609",
    tags=["mf202609"],
)


def _svc():
    from services.multi_factor_202609 import (
        get_model_config,
        run_multi_factor_scan,
        get_stock_factor_detail,
        get_history_daily,
        get_history_streak,
        get_history_frequency,
        get_history_cumulative,
    )
    return {
        "config": get_model_config,
        "scan": run_multi_factor_scan,
        "stock_detail": get_stock_factor_detail,
        "history_daily": get_history_daily,
        "history_streak": get_history_streak,
        "history_frequency": get_history_frequency,
        "history_cumulative": get_history_cumulative,
    }


@router.get("/config")
def api_config():
    """获取模型配置（因子列表、合成方法、Top-N等）"""
    try:
        return _svc()["config"]()
    except Exception as e:
        _logger.error(f"/config error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/scan")
def api_scan(
    top_n: int = Query(20, ge=1, le=100, description="返回股票数量"),
):
    """多因子截面扫描：基于最新因子数据，返回 Top-N 股票列表及各因子明细"""
    try:
        return _svc()["scan"](top_n=top_n)
    except Exception as e:
        _logger.error(f"/scan error: {e}")
        return {"success": False, "error": str(e), "stocks": [], "meta": {}}


@router.get("/stock/{ts_code}")
def api_stock_detail(ts_code: str):
    """获取单只股票的因子明细"""
    try:
        return _svc()["stock_detail"](ts_code)
    except Exception as e:
        _logger.error(f"/stock/{ts_code} error: {e}")
        return {"success": False, "error": str(e), "data": {}}


# ── 历史记录接口 ──────────────────────────────────────────

@router.get("/history/daily")
def api_history_daily(
    days: int = Query(30, ge=1, le=365, description="查询最近 N 天"),
    top_n_per_day: int = Query(0, ge=0, le=100, description="每日只取前 N 名（0=不限）"),
):
    """每日快照：按日期分组的上榜股票列表"""
    try:
        return _svc()["history_daily"](days=days, top_n_per_day=top_n_per_day)
    except Exception as e:
        _logger.error(f"/history/daily error: {e}")
        return {"success": False, "error": str(e), "daily": {}, "dates": [], "meta": {}}


@router.get("/history/streak")
def api_history_streak(
    days: int = Query(30, ge=1, le=365, description="查询最近 N 天"),
    min_streak: int = Query(2, ge=1, le=365, description="最少连续天数"),
):
    """连续上榜天数排行"""
    try:
        return _svc()["history_streak"](days=days, min_streak=min_streak)
    except Exception as e:
        _logger.error(f"/history/streak error: {e}")
        return {"success": False, "error": str(e), "stocks": [], "meta": {}}


@router.get("/history/frequency")
def api_history_frequency(
    days: int = Query(30, ge=1, le=365, description="查询最近 N 天"),
    min_appear: int = Query(1, ge=1, le=365, description="最少上榜次数"),
):
    """上榜频率排行"""
    try:
        return _svc()["history_frequency"](days=days, min_appear=min_appear)
    except Exception as e:
        _logger.error(f"/history/frequency error: {e}")
        return {"success": False, "error": str(e), "stocks": [], "meta": {}}


@router.get("/history/cumulative")
def api_history_cumulative(
    days: int = Query(30, ge=1, le=365, description="统计最近 N 天"),
):
    """累计统计：整体扫描情况汇总"""
    try:
        return _svc()["history_cumulative"](days=days)
    except Exception as e:
        _logger.error(f"/history/cumulative error: {e}")
        return {"success": False, "error": str(e), "stats": {}, "rank_distribution": {}, "industry_top": [], "meta": {}}
