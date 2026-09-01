# -*- coding: utf-8 -*-
"""
services 包 —— 将原先 3092 行的 services.py 单文件拆分为 7 个子模块：
    _common.py          公共基础：路径、DB、NaN清理、通用助手、权重加载、CSV 归档
    market_regime.py    市场状态实时判定：Bull/Range/Bear/Dark
    factors_assets.py   因子权重 & 今日推荐组合 & 风格榜
    performance.py      绩效曲线、Agent 日志、归因、自适应换仓
    scanner.py          建仓机会（画像路由）、扫描历史、择时警报
    market_overview.py  市场概览、搜索、个股诊断、访客
    portrait.py         T+1 画像批量打分 & 画像建仓决策

本 __init__.py 作为统一转发层：
    from services import get_market_status, get_performance_data, ...
与原先 3092 行 services.py 的 import 保持 100% 签名兼容，app.py 无需修改。
"""

from ._common import (
    PROJECT_ROOT, DB_PATH, WEIGHTS_PATH, BULL_WEIGHTS_PATH, RESULTS_PATH,
    LOGS_PATH, CRUISE_REPORT_PATH,
    get_db_connection, clean_nan_inf,
    _get_factor_date, _get_restricted_stocks, _log_recommendations_to_tracker,
    _load_pkl_weights, _ensure_scan_history_table,
    _save_and_calc_recommendation_stats,
    # ThresholdConfig 统一阈值加载器（S2 新增，config/thresholds.yaml 支持热加载）
    get_threshold_version,
    get_left_portrait_cfg, get_right_portrait_cfg,
    get_grade_map, get_position_funnel_cfg,
    get_scanner_cfg, get_live_regime_cfg,
    get_pick_reason_cfg, get_diagnose_grade_cfg,
    get_hot_money_tracker_cfg,
)
from .market_regime import (
    compute_live_regime, get_market_status, get_regime_dashboard, get_theme_stocks,
)
from .factors_assets import (
    get_deployed_factors, get_today_portfolio, get_style_stocks,
)
from .performance import (
    get_performance_data, get_jack_performance_data, get_agent_logs,
    get_tracker_attribution_data, determine_adaptive_hold_period,
)
from .scanner import (
    get_build_position_opportunities, get_scan_history,
    get_recommendation_history, get_timing_alerts, record_alerts_feedback,
    save_scan_history,
)
from .market_overview import (
    get_market_overview_data, search_stock, diagnose_stock,
    record_visitor, get_visitor_stats,
)
from .portrait import get_portrait_analysis, get_portrait_position_pick


__all__ = [
    # _common 公开常量 & 工具
    "PROJECT_ROOT", "DB_PATH", "WEIGHTS_PATH", "BULL_WEIGHTS_PATH",
    "RESULTS_PATH", "LOGS_PATH", "CRUISE_REPORT_PATH",
    "get_db_connection", "clean_nan_inf",
    # ThresholdConfig 统一阈值
    "get_threshold_version",
    "get_left_portrait_cfg", "get_right_portrait_cfg",
    "get_grade_map", "get_position_funnel_cfg",
    "get_scanner_cfg", "get_live_regime_cfg",
    "get_pick_reason_cfg", "get_diagnose_grade_cfg",
    "get_hot_money_tracker_cfg",
    # market_regime
    "compute_live_regime", "get_market_status", "get_regime_dashboard", "get_theme_stocks",
    # factors_assets
    "get_deployed_factors", "get_today_portfolio", "get_style_stocks",
    # performance
    "get_performance_data", "get_jack_performance_data", "get_agent_logs",
    "get_tracker_attribution_data", "determine_adaptive_hold_period",
    # scanner
    "get_build_position_opportunities", "get_scan_history",
    "get_recommendation_history", "get_timing_alerts", "record_alerts_feedback",
    "save_scan_history",
    # market_overview
    "get_market_overview_data", "search_stock", "diagnose_stock",
    "record_visitor", "get_visitor_stats",
    # portrait
    "get_portrait_analysis", "get_portrait_position_pick",
]
