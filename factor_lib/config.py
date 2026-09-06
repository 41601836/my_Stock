# -*- coding: utf-8 -*-
"""
config.py — 因子测试模块配置加载器（热加载）
=================================================
读取 config/factor_test.yaml，支持 mtime 热刷新。
db_path 默认从 config/paths.yaml 读取，确保与现有系统口径一致。
"""

import os
import yaml
import time
from typing import Any, Dict, Optional

from config.paths import PATHS, startup_check

startup_check()

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "factor_test.yaml"
)

_cache: Dict[str, Any] = {}
_cache_mtime: float = 0.0


def _load() -> Dict[str, Any]:
    global _cache, _cache_mtime
    mtime = os.path.getmtime(_CONFIG_PATH) if os.path.exists(_CONFIG_PATH) else 0
    if _cache and mtime == _cache_mtime:
        return _cache
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        _cache = yaml.safe_load(f) or {}
    _cache_mtime = mtime
    return _cache


class FactorTestConfig:
    """热加载配置访问器，属性读取时自动检查 mtime 并刷新。"""

    @staticmethod
    def _get() -> Dict[str, Any]:
        return _load()

    @staticmethod
    def get(key_path: str, default: Any = None) -> Any:
        cfg = _load()
        keys = key_path.split(".")
        val = cfg
        for k in keys:
            if not isinstance(val, dict):
                return default
            val = val.get(k)
            if val is None:
                return default
        return val

    # ── data ──
    @staticmethod
    def db_path() -> str:
        p = FactorTestConfig.get("data.db_path")
        if p:
            return p
        return PATHS.database.stock_data

    @staticmethod
    def start_date() -> str:
        return FactorTestConfig.get("data.start_date", "20200101")

    @staticmethod
    def end_date() -> Optional[str]:
        return FactorTestConfig.get("data.end_date", None)

    @staticmethod
    def exclude_st() -> bool:
        return FactorTestConfig.get("data.exclude_st", True)

    @staticmethod
    def exclude_new_stock_days() -> int:
        return FactorTestConfig.get("data.exclude_new_stock_days", 365)

    @staticmethod
    def min_cross_section_size() -> int:
        return FactorTestConfig.get("data.min_cross_section_size", 30)

    @staticmethod
    def clip_return() -> tuple:
        r = FactorTestConfig.get("data.clip_return", [-0.5, 0.8])
        return (r[0], r[1])

    # ── ic ──
    @staticmethod
    def ic_type() -> str:
        return FactorTestConfig.get("ic.type", "both")

    @staticmethod
    def return_periods() -> list:
        return FactorTestConfig.get("ic.return_periods", [1, 3, 5, 10, 20])

    @staticmethod
    def default_period() -> int:
        return FactorTestConfig.get("ic.default_period", 5)

    # ── stratified ──
    @staticmethod
    def n_groups() -> int:
        return FactorTestConfig.get("stratified.n_groups", 5)

    @staticmethod
    def strat_rebalance_freq() -> str:
        return FactorTestConfig.get("stratified.rebalance_freq", "weekly")

    @staticmethod
    def strat_cost_bps() -> float:
        return FactorTestConfig.get("stratified.cost_bps", 15.0)

    # ── backtest ──
    @staticmethod
    def top_n() -> int:
        return FactorTestConfig.get("backtest.top_n", 10)

    @staticmethod
    def bt_rebalance_freq() -> str:
        return FactorTestConfig.get("backtest.rebalance_freq", "weekly")

    @staticmethod
    def bt_cost_bps() -> float:
        return FactorTestConfig.get("backtest.cost_bps", 15.0)

    @staticmethod
    def bt_benchmark() -> str:
        return FactorTestConfig.get("backtest.benchmark", "equal_weight")

    @staticmethod
    def bt_handle_limit() -> bool:
        return FactorTestConfig.get("backtest.handle_limit", True)

    # ── anti_overfit ──
    @staticmethod
    def train_ratio() -> float:
        return FactorTestConfig.get("anti_overfit.train_ratio", 0.6)

    @staticmethod
    def wf_train() -> int:
        return FactorTestConfig.get("anti_overfit.walk_forward_train", 252)

    @staticmethod
    def wf_test() -> int:
        return FactorTestConfig.get("anti_overfit.walk_forward_test", 63)

    @staticmethod
    def n_permutations() -> int:
        return FactorTestConfig.get("anti_overfit.n_permutations", 200)

    @staticmethod
    def yearly_consistency_ratio() -> float:
        return FactorTestConfig.get("anti_overfit.yearly_consistency_ratio", 0.70)

    @staticmethod
    def ic_positive_ratio() -> float:
        return FactorTestConfig.get("anti_overfit.ic_positive_ratio", 0.60)

    @staticmethod
    def icir_min() -> float:
        return FactorTestConfig.get("anti_overfit.icir_min", 0.30)

    @staticmethod
    def significance_level() -> float:
        return FactorTestConfig.get("anti_overfit.significance_level", 0.05)

    # ── report ──
    @staticmethod
    def report_dir() -> str:
        d = FactorTestConfig.get("report.output_dir", "factor_test_reports")
        if not os.path.isabs(d):
            d = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), d
            )
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def report_language() -> str:
        return FactorTestConfig.get("report.language", "zh")

    @staticmethod
    def report_charts() -> str:
        return FactorTestConfig.get("report.charts", "echarts")

    @staticmethod
    def reload() -> None:
        """强制重新加载配置文件。"""
        global _cache, _cache_mtime
        _cache = {}
        _cache_mtime = 0.0
        _load()
