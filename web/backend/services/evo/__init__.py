# -*- coding: utf-8 -*-
"""
services.evo —— EVO 进化层专属 services 包
=======================================================
与 services 包（经典系统）完全平行，职责完全隔离：
    _common.py          基础：EvoConfig / 新表 / 统计工具 / 熔断
    factors_evo.py      交叉因子 + 拥挤度 + 衰减 + 动态权重接口
    portfolio_evo.py    EVO 版组合推荐（融合 8 大模块）
    scanner_evo.py      EVO 版建仓扫描（叠加拥挤度/Graham/动态权重）
    ml_predict.py       LambdaRank 训练 + 推理 + SHAP
    graham_evo.py       Graham 价值筛选 + 单股雷达图
    comparison.py       经典 vs 进化 A/B 对比数据
本 __init__.py 作为统一转发层（router 直接 from services.evo import xxx）。
"""
from ._common import (
    EvoConfig,
    ensure_evo_tables,
    calc_rank_ic,
    calc_crowding_score,
    graham_proxy_scores,
    check_overlap_and_maybe_fallback,
    get_db_connection,
    clean_nan_inf,
    PROJECT_ROOT, DB_PATH, MODELS_EVO_DIR, LOGS_EVO_DIR,
)

__all__ = [
    "EvoConfig",
    "ensure_evo_tables",
    "calc_rank_ic", "calc_crowding_score",
    "graham_proxy_scores", "check_overlap_and_maybe_fallback",
    "get_db_connection", "clean_nan_inf",
    "PROJECT_ROOT", "DB_PATH", "MODELS_EVO_DIR", "LOGS_EVO_DIR",
]
