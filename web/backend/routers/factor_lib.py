# -*- coding: utf-8 -*-
"""
routers.factor_lib —— 因子库路由（前缀 /api/factor-lib，零侵入）
================================================================

⚠️ 零侵入原则：
1. 本路由只读取 factor_ranking 表，不修改任何现有数据
2. 不影响 /api/factors 等现有路由
3. 删除本文件 + 移除注册即回滚
"""

import sys
import os
import logging
from typing import Optional

from fastapi import APIRouter, Query

_logger = logging.getLogger("routers.factor_lib")

router = APIRouter(
    prefix="/api/factor-lib",
    tags=["factor-lib"],
)


# ═══════════════════════════════════════════════════════════
# 懒加载 service（避免启动时循环依赖）
# ═══════════════════════════════════════════════════════════

def _svc():
    from services.factor_lib_service import (
        get_factor_ranking,
        get_factor_detail,
        get_category_stats,
        get_independent_factors,
        get_factor_library_overview,
    )
    return {
        "ranking": get_factor_ranking,
        "detail": get_factor_detail,
        "categories": get_category_stats,
        "independent": get_independent_factors,
        "overview": get_factor_library_overview,
    }


# ═══════════════════════════════════════════════════════════
# API Endpoints
# ═══════════════════════════════════════════════════════════

@router.get("/overview")
def api_overview():
    """因子库总览统计"""
    try:
        return _svc()["overview"]()
    except Exception as e:
        _logger.error(f"/overview error: {e}")
        return {"success": False, "error": str(e)}


@router.get("/ranking")
def api_ranking(
    grade: Optional[str] = Query(None, description="按等级过滤: S/A+/A/B+/B/C+/C/D"),
    category: Optional[str] = Query(None, description="按分类过滤"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """因子评级排名（可按等级/分类过滤，分页）"""
    try:
        return _svc()["ranking"](grade=grade, category=category, limit=limit, offset=offset)
    except Exception as e:
        _logger.error(f"/ranking error: {e}")
        return {"success": False, "error": str(e), "total": 0, "count": 0, "data": []}


@router.get("/factor/{factor_name}")
def api_factor_detail(factor_name: str):
    """单因子详细信息"""
    try:
        return _svc()["detail"](factor_name)
    except Exception as e:
        _logger.error(f"/factor/{factor_name} error: {e}")
        return {"success": False, "error": str(e), "data": {}}


@router.get("/categories")
def api_categories():
    """按分类统计因子"""
    try:
        return _svc()["categories"]()
    except Exception as e:
        _logger.error(f"/categories error: {e}")
        return {"success": False, "error": str(e), "categories": [], "total_categories": 0}


@router.get("/independent-factors")
def api_independent_factors():
    """独立因子池（聚类代表因子）"""
    try:
        return _svc()["independent"]()
    except Exception as e:
        _logger.error(f"/independent-factors error: {e}")
        return {"success": False, "error": str(e), "data": [], "count": 0}
