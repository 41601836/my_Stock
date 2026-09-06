# -*- coding: utf-8 -*-
"""
weight_feedback.py — 维度权重自动调整反馈机制
=============================================
核心思想：根据历史命中率，自动调整四维共振的权重分配
  - 某维度高分时命中率高 → edge > 0 → 增加该维度权重
  - 某维度高分时命中率低 → edge < 0 → 降低该维度权重
  - 形成良性学习循环

零侵入：只修改 config/resonance.yaml 的 dimension_weights 字段
"""

import os, sys, json, sqlite3, logging, copy
import numpy as np
import pandas as pd
from typing import Dict, Any

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_DB_PATH = os.path.join(_PROJECT_ROOT, "db", "stock_data.db")
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "resonance.yaml")

_logger = logging.getLogger("services.weight_feedback")

# 维度名称 → 配置 key 映射
DIM_MAP = {
    "chip":      "筹码",
    "capital":   "资金",
    "sector":    "板块",
    "sentiment": "情绪",
}


def calculate_dimension_edges(min_samples: int = 10) -> Dict[str, Dict]:
    """计算各维度的预测 edge（命中均值 - 未命中均值）

    Parameters
    ----------
    min_samples : int, 最少样本数，低于此数不调整

    Returns
    -------
    dict: {dim: {hit_avg, miss_avg, edge, n_hits, n_miss, sample_size}}
    """
    from web.backend.services.dashboard_service import ensure_tables
    ensure_tables()
    conn = sqlite3.connect(_DB_PATH)
    try:
        df = pd.read_sql("""
            SELECT pl.is_hit,
                   sl.chip_score, sl.capital_score, sl.sector_score, sl.sentiment_score
            FROM performance_log pl
            JOIN selection_log sl
              ON pl.selection_date = sl.trade_date AND pl.ts_code = sl.ts_code
        """, conn)

        if len(df) < min_samples:
            return {}

        results = {}
        for dim in DIM_MAP:
            col = f"{dim}_score"
            if col not in df.columns:
                continue
            vals = df[[col, "is_hit"]].dropna()
            if len(vals) < min_samples:
                continue
            hit_mask = vals["is_hit"] == 1
            hit_avg = float(vals.loc[hit_mask, col].mean()) if hit_mask.any() else 0
            miss_avg = float(vals.loc[~hit_mask, col].mean()) if (~hit_mask).any() else 0
            results[dim] = {
                "hit_avg": hit_avg,
                "miss_avg": miss_avg,
                "edge": hit_avg - miss_avg,
                "n_hits": int(hit_mask.sum()),
                "n_miss": int((~hit_mask).sum()),
                "sample_size": len(vals),
            }
        return results
    except Exception as e:
        _logger.error(f"calculate_dimension_edges error: {e}", exc_info=True)
        return {}
    finally:
        conn.close()


def update_resonance_weights(learning_rate: float = 0.05, min_samples: int = 10) -> Dict[str, Any]:
    """根据维度 edge 自动调整 resonance.yaml 的权重

    Parameters
    ----------
    learning_rate : float, 每次调整幅度 (0.05 = 5%)
    min_samples : int, 最少验证样本数

    Returns
    -------
    dict: {old_weights, new_weights, edges, adjusted}
    """
    import yaml

    # 1. 计算维度 edge
    edges = calculate_dimension_edges(min_samples=min_samples)
    if not edges:
        return {
            "adjusted": False,
            "reason": f"样本不足（需要至少 {min_samples} 条验证记录）",
            "edges": {},
        }

    # 2. 读取当前配置
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    old_weights = dict(config.get("dimensions", {}).get("weights", {}))
    if not old_weights:
        old_weights = {"chip": 0.25, "capital": 0.25, "sector": 0.25, "sentiment": 0.25}

    # 3. 根据 edge 调整权重
    new_weights = copy.deepcopy(old_weights)
    for dim, edge_data in edges.items():
        if dim not in new_weights:
            continue
        edge = edge_data["edge"]
        # edge > 0: 维度有效，增加权重
        # edge < 0: 维度无效，降低权重
        adjustment = edge * learning_rate * 4  # 放大调整幅度
        new_weights[dim] = max(0.05, min(0.60, old_weights[dim] + adjustment))

    # 4. 归一化
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}

    # 5. 检查是否有显著变化
    max_change = max(abs(new_weights.get(d, 0) - old_weights.get(d, 0)) for d in old_weights)
    if max_change < 0.01:
        return {
            "adjusted": False,
            "reason": f"权重变化太小（max={max_change:.4f}）",
            "old_weights": old_weights,
            "new_weights": new_weights,
            "edges": edges,
        }

    # 6. 写入配置
    config.setdefault("dimensions", {})["weights"] = new_weights
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return {
        "adjusted": True,
        "old_weights": old_weights,
        "new_weights": new_weights,
        "edges": edges,
        "max_change": max_change,
    }


def get_feedback_status() -> Dict[str, Any]:
    """获取反馈机制状态"""
    edges = calculate_dimension_edges(min_samples=1)
    if not edges:
        return {
            "has_data": False,
            "message": "尚无足够验证数据",
            "edges": {},
        }

    return {
        "has_data": True,
        "edges": edges,
        "total_verified": sum(e["sample_size"] for e in edges.values()),
    }
