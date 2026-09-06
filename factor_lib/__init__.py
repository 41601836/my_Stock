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
]
