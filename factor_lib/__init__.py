# -*- coding: utf-8 -*-
"""
factor_lib — 公共因子库
=================================================
两套入口共享的因子定义、数据加载、IC/分层/回测/防过拟合引擎。
零侵入：不引用 agent/ 或 web/backend/ 任何代码。
"""

from factor_lib.registry import FACTOR_REGISTRY, FactorMeta, get_factor, get_factors_by_table, get_factors_by_category
from factor_lib.config import FactorTestConfig
from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine
from factor_lib.stratified_tester import StratifiedTester, StratifiedTestResult
from factor_lib.backtester import FactorBacktester, BacktestResult
from factor_lib.anti_overfit import AntiOverfitChecker
from factor_lib.reporter import FactorReporter

# 以下模块为可选依赖（statsmodels / scipy），懒加载避免阻塞核心功能
_FactorNeutralizer = None
_symmetric_orthogonalize = None
_group_orthogonalize = None
_orthogonalize_cross_section = None

def __getattr__(name):
    global _FactorNeutralizer, _symmetric_orthogonalize, _group_orthogonalize, _orthogonalize_cross_section
    if name == "FactorNeutralizer":
        if _FactorNeutralizer is None:
            from factor_lib.neutralizer import FactorNeutralizer as _FactorNeutralizer
        return _FactorNeutralizer
    if name == "symmetric_orthogonalize":
        if _symmetric_orthogonalize is None:
            from factor_lib.orthogonalizer import symmetric_orthogonalize as _symmetric_orthogonalize
        return _symmetric_orthogonalize
    if name == "group_orthogonalize":
        if _group_orthogonalize is None:
            from factor_lib.orthogonalizer import group_orthogonalize as _group_orthogonalize
        return _group_orthogonalize
    if name == "orthogonalize_cross_section":
        if _orthogonalize_cross_section is None:
            from factor_lib.orthogonalizer import orthogonalize_cross_section as _orthogonalize_cross_section
        return _orthogonalize_cross_section
    raise AttributeError(f"module 'factor_lib' has no attribute '{name}'")

__all__ = [
    "FACTOR_REGISTRY",
    "FactorMeta",
    "get_factor",
    "get_factors_by_table",
    "get_factors_by_category",
    "FactorTestConfig",
    "FactorDataLoader",
    "ICEngine",
    "StratifiedTester",
    "StratifiedTestResult",
    "FactorBacktester",
    "BacktestResult",
    "AntiOverfitChecker",
    "FactorReporter",
    "FactorNeutralizer",
    "symmetric_orthogonalize",
    "group_orthogonalize",
    "orthogonalize_cross_section",
]
