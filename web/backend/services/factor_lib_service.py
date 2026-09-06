# -*- coding: utf-8 -*-
"""
services.factor_lib —— 因子库公共服务
========================================
factor_lib 的后端适配层，提供因子库查询 API。

⚠️ 零侵入原则：
1. 本文件只读 factor_ranking / factor_values 表，不修改任何现有数据
2. 不 import 任何经典层路由函数实现
3. 删除本文件 + 路由注册即回滚

API 列表:
- /api/factor-lib/ranking       因子评级排名
- /api/factor-lib/factor/{name}  单因子详情
- /api/factor-lib/categories    分类统计
- /api/factor-lib/independence  独立因子池
"""

import sys
import os
import logging
from typing import Optional, List, Dict, Any

import sqlite3
import pandas as pd

# 确保能 import 项目根的 factor_lib
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from factor_lib.registry import FACTOR_REGISTRY, get_all_factor_names, get_factors_by_category

_logger = logging.getLogger("services.factor_lib")

DB_PATH = os.path.join(_PROJECT_ROOT, "db", "stock_data.db")


def _get_db():
    """获取数据库连接（只读模式）"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _clean_nan(obj):
    """递归清理 NaN/Inf，确保 JSON 安全"""
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    if isinstance(obj, float):
        if pd.isna(obj) or obj == float('inf') or obj == float('-inf'):
            return None
        return round(obj, 6)
    if isinstance(obj, (pd.Timestamp,)):
        return str(obj)
    return obj


# ═══════════════════════════════════════════════════════════
# 因子评级排名
# ═══════════════════════════════════════════════════════════

def get_factor_ranking(grade: Optional[str] = None,
                       category: Optional[str] = None,
                       limit: int = 50,
                       offset: int = 0) -> Dict[str, Any]:
    """获取因子评级排名

    Parameters
    ----------
    grade : str, optional
        按等级过滤: S / A+ / A / B+ / B / C+ / C / D
    category : str, optional
        按分类过滤
    limit : int
        返回数量
    offset : int
        偏移量
    """
    try:
        conn = _get_db()
        query = "SELECT * FROM factor_ranking WHERE 1=1"
        params = []

        if grade:
            query += " AND grade = ?"
            params.append(grade)
        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY total_score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        df = pd.read_sql(query, conn, params=params)

        # 总数
        cnt_query = "SELECT COUNT(*) as cnt FROM factor_ranking WHERE 1=1"
        cnt_params = []
        if grade:
            cnt_query += " AND grade = ?"
            cnt_params.append(grade)
        if category:
            cnt_query += " AND category = ?"
            cnt_params.append(category)
        total = pd.read_sql(cnt_query, conn, params=cnt_params).iloc[0, 0]

        conn.close()

        # 补充因子元数据
        for _, row in df.iterrows():
            meta = FACTOR_REGISTRY.get(row["factor"])
            if meta:
                row["description"] = meta.description
                row["data_source"] = meta.table
            else:
                row["description"] = ""
                row["data_source"] = "unknown"

        data = df.to_dict(orient="records")
        return {
            "success": True,
            "total": int(total),
            "count": len(data),
            "data": _clean_nan(data),
        }

    except Exception as e:
        _logger.error(f"get_factor_ranking error: {e}")
        return {"success": False, "error": str(e), "total": 0, "count": 0, "data": []}


# ═══════════════════════════════════════════════════════════
# 单因子详情
# ═══════════════════════════════════════════════════════════

def get_factor_detail(factor_name: str) -> Dict[str, Any]:
    """获取单个因子的详细信息"""
    try:
        meta = FACTOR_REGISTRY.get(factor_name)
        if not meta:
            return {"success": False, "error": f"因子不存在: {factor_name}"}

        # 评级数据
        conn = _get_db()
        df_ranking = pd.read_sql(
            "SELECT * FROM factor_ranking WHERE factor = ?",
            conn, params=[factor_name]
        )
        conn.close()

        ranking = df_ranking.iloc[0].to_dict() if len(df_ranking) > 0 else {}

        result = {
            "factor": factor_name,
            "category": meta.category,
            "direction": meta.direction,
            "table": meta.table,
            "description": meta.description,
            "ranking": _clean_nan(ranking),
        }

        return {"success": True, "data": _clean_nan(result)}

    except Exception as e:
        _logger.error(f"get_factor_detail error: {e}")
        return {"success": False, "error": str(e), "data": {}}


# ═══════════════════════════════════════════════════════════
# 分类统计
# ═══════════════════════════════════════════════════════════

def get_category_stats() -> Dict[str, Any]:
    """按分类统计因子"""
    try:
        conn = _get_db()
        df = pd.read_sql(
            """
            SELECT category,
                   COUNT(*) as n_factors,
                   AVG(total_score) as avg_score,
                   AVG(ABS(icir)) as avg_icir,
                   AVG(sharpe) as avg_sharpe
            FROM factor_ranking
            GROUP BY category
            ORDER BY avg_score DESC
            """,
            conn
        )
        conn.close()

        # 每类最佳因子
        best_factors = {}
        for cat in df["category"].tolist():
            cat_ranking = get_factor_ranking(category=cat, limit=1)
            if cat_ranking["data"] and len(cat_ranking["data"]) > 0:
                best_factors[cat] = cat_ranking["data"][0]

        data = df.to_dict(orient="records")
        for item in data:
            cat = item["category"]
            if cat in best_factors:
                item["best_factor"] = best_factors[cat].get("factor")
                item["best_grade"] = best_factors[cat].get("grade")

        return {
            "success": True,
            "categories": _clean_nan(data),
            "total_categories": len(data),
        }

    except Exception as e:
        _logger.error(f"get_category_stats error: {e}")
        return {"success": False, "error": str(e), "categories": [], "total_categories": 0}


# ═══════════════════════════════════════════════════════════
# 独立因子池
# ═══════════════════════════════════════════════════════════

def get_independent_factors() -> Dict[str, Any]:
    """获取独立因子池（聚类代表因子）"""
    try:
        import csv
        csv_path = os.path.join(_PROJECT_ROOT, "factor_test_reports", "independent_factors.csv")
        if not os.path.exists(csv_path):
            return {
                "success": True,
                "data": [],
                "count": 0,
                "note": "请先运行因子聚类分析: scripts/factor_correlation.py",
            }

        df = pd.read_csv(csv_path)

        # 补充评级信息
        conn = _get_db()
        for _, row in df.iterrows():
            factor = row["representative"]
            rdf = pd.read_sql(
                "SELECT total_score, grade, icir, sharpe, annual_return, max_drawdown FROM factor_ranking WHERE factor = ?",
                conn, params=[factor]
            )
            if len(rdf) > 0:
                r = rdf.iloc[0]
                row["total_score"] = r["total_score"]
                row["grade"] = r["grade"]
                row["icir"] = r["icir"]
                row["sharpe"] = r["sharpe"]
                row["annual_return"] = r["annual_return"]
                row["max_drawdown"] = r["max_drawdown"]
        conn.close()

        data = df.to_dict(orient="records")
        return {
            "success": True,
            "data": _clean_nan(data),
            "count": len(data),
        }

    except Exception as e:
        _logger.error(f"get_independent_factors error: {e}")
        return {"success": False, "error": str(e), "data": [], "count": 0}


# ═══════════════════════════════════════════════════════════
# 因子库总览
# ═══════════════════════════════════════════════════════════

def get_factor_library_overview() -> Dict[str, Any]:
    """因子库总览统计"""
    try:
        conn = _get_db()
        df = pd.read_sql("SELECT * FROM factor_ranking", conn)
        conn.close()

        total = len(df)
        grade_counts = df["grade"].value_counts().to_dict()
        cat_counts = df["category"].value_counts().to_dict()
        avg_score = df["total_score"].mean()
        s_count = int(grade_counts.get("S", 0))
        a_count = int(grade_counts.get("A+", 0) + grade_counts.get("A", 0))
        b_count = int(grade_counts.get("B+", 0) + grade_counts.get("B", 0) + grade_counts.get("C+", 0))
        c_count = int(grade_counts.get("C", 0))
        d_count = int(grade_counts.get("D", 0))

        # Top 5
        top5 = df.nlargest(5, "total_score")[
            ["factor", "grade", "total_score", "icir", "sharpe", "category"]
        ].to_dict(orient="records")

        return {
            "success": True,
            "total_factors": total,
            "avg_score": round(float(avg_score), 3),
            "grade_distribution": {k: int(v) for k, v in grade_counts.items()},
            "category_count": len(cat_counts),
            "s_count": s_count,
            "a_count": a_count,
            "b_count": b_count,
            "c_count": c_count,
            "d_count": d_count,
            "top_5": _clean_nan(top5),
            "registry_total": len(FACTOR_REGISTRY),
        }

    except Exception as e:
        _logger.error(f"get_factor_library_overview error: {e}")
        return {"success": False, "error": str(e)}
