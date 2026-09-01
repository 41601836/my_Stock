# -*- coding: utf-8 -*-
"""
services._common —— 所有 services 子模块共享的基础层
* 路径常量 & sys.path 初始化（对应原 services.py 1-29）
* SQLite 连接器 get_db_connection()（32-44）
* NaN/Inf 清理器 clean_nan_inf()（48-67）
* 内部通用助手：_get_factor_date / _get_restricted_stocks / _log_recommendations_to_tracker
* pkl 权重加载器 _load_pkl_weights（被 factors/scanner/portrait 复用）
* 建仓历史表建表器 _ensure_scan_history_table（被 scanner + timing_alerts 复用）
* 推荐历史 CSV 归档 + 统计：_save_and_calc_recommendation_stats（被 scanner 复用）
"""

import os
import sys
import math
import json
import pickle
import sqlite3
import logging
import datetime

import pandas as pd
import numpy as np

# ═══════════════════════════════════════════════════════════
# 1. 路径初始化 & 项目根（确保从任意目录启动 uvicorn 都能 import）
# ═══════════════════════════════════════════════════════════
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PROJECT_ROOT = _PROJECT_ROOT
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config.paths import PATHS, startup_check

startup_check()

DB_PATH            = PATHS.database.stock_data
WEIGHTS_PATH       = PATHS.models.regime_weights
BULL_WEIGHTS_PATH  = PATHS.models.bull_weights_proposed
RESULTS_PATH       = PATHS.data.backtest_results
LOGS_PATH          = PATHS.logs.agent_auto_run
CRUISE_REPORT_PATH = PATHS.reports.agent_cruise

_logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 2. DB 连接
# ═══════════════════════════════════════════════════════════
def get_db_connection(db_path=DB_PATH, timeout=30.0):
    """统一安全的 SQLite 连接器：30s 超时 + WAL + busy_timeout 提升并发吞吐"""
    conn = sqlite3.connect(db_path, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        pass
    return conn


# ═══════════════════════════════════════════════════════════
# 3. NaN/Inf 清理（确保 JSON 可序列化）
# ═══════════════════════════════════════════════════════════
def clean_nan_inf(obj, default=0.0):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return default
        return obj
    elif isinstance(obj, dict):
        return {k: clean_nan_inf(v, default) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan_inf(v, default) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(clean_nan_inf(v, default) for v in obj)
    elif isinstance(obj, np.generic):
        val = obj.item()
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return default
        return val
    return obj


# ═══════════════════════════════════════════════════════════
# 4. 3 个内部通用助手（原 services.py 69-163）
# ═══════════════════════════════════════════════════════════
def _get_factor_date(conn) -> str:
    """
    智能选择因子基准日期：
    - 盘后且 factor_values 已更新至最新行情日：使用 T-0
    - 盘中（16:00 前）或因子未更新：使用 T-1
    """
    fac_dates = pd.read_sql(
        "SELECT DISTINCT trade_date FROM factor_values ORDER BY trade_date DESC LIMIT 2",
        conn
    )["trade_date"].tolist()
    if not fac_dates:
        return ""
    fac_latest = fac_dates[0]
    fac_prev   = fac_dates[1] if len(fac_dates) >= 2 else fac_dates[0]
    try:
        price_latest = pd.read_sql("SELECT MAX(trade_date) as d FROM daily_prices", conn).iloc[0, 0]
    except Exception:
        price_latest = ""
    if fac_latest and price_latest and fac_latest >= price_latest:
        return fac_latest
    else:
        return fac_prev


def _get_restricted_stocks(conn):
    """ST 股、上市不满 1 年的新股/次新股 限制名单"""
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y%m%d')
    try:
        df_restricted = pd.read_sql(
            f"SELECT ts_code FROM stock_list WHERE name LIKE '%ST%' OR list_date >= '{cutoff_date}'",
            conn
        )
        return set(df_restricted['ts_code'].tolist())
    except Exception as e:
        _logger.warning(f"Failed to get restricted stocks: {e}")
        return set()


def _log_recommendations_to_tracker(conn, recommend_date, stocks, regime):
    """推荐股票快照写入追踪表（INSERT OR IGNORE 防重）"""
    if not recommend_date or not stocks:
        return
    try:
        date_clean = str(recommend_date).replace("-", "")
        cursor = conn.cursor()
        for s in stocks:
            ts_code = s.get("ts_code") or s.get("stock_code")
            if not ts_code:
                continue
            cursor.execute(
                "SELECT "
                "  (SELECT winner_rate FROM stock_cyq_perf WHERE ts_code = ? AND trade_date = ?), "
                "  (SELECT chips_peak_pct FROM stock_cyq_perf WHERE ts_code = ? AND trade_date = ?), "
                "  (SELECT net_mf_amount FROM moneyflow WHERE ts_code = ? AND trade_date = ?)",
                (ts_code, date_clean, ts_code, date_clean, ts_code, date_clean)
            )
            row_db = cursor.fetchone()
            winner_rate = row_db[0] if row_db and row_db[0] is not None else s.get("winner_rate", 0.0)
            chips_concentration = row_db[1] if row_db and row_db[1] is not None else s.get("chips_peak_pct", 0.0)
            net_mf_amount = row_db[2] if row_db and row_db[2] is not None else s.get("big_net_inflow", 0.0)
            factor_score = s.get("score") or s.get("factor_score") or 0.0
            if factor_score > 1.0:
                factor_score /= 100.0
            cursor.execute(
                "INSERT OR IGNORE INTO recommendation_tracker "
                "(recommend_date, ts_code, base_price, regime, factor_score, winner_rate, chips_concentration, net_mf_amount) "
                "VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
                (date_clean, ts_code, str(regime).upper(), float(factor_score), float(winner_rate), float(chips_concentration), float(net_mf_amount))
            )
        conn.commit()
    except Exception as e:
        _logger.warning(f"Failed to log recommendations to tracker: {e}")


# ═══════════════════════════════════════════════════════════
# 5. pkl 权重加载器（原 529-546，被 factors/portfolio/scanner/portrait 复用）
# ═══════════════════════════════════════════════════════════
def _load_pkl_weights(path):
    """安全读取 pkl 权重，返回 (factors_list, weights_dict)"""
    if not os.path.exists(path):
        return [], {}
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        if not isinstance(data, dict):
            return [], {}
        rf = data.get("range_factors", [])
        rw = data.get("range_weights", {})
        if not rf and rw:
            rf = list(rw.keys())
        return rf, {k: float(v) for k, v in rw.items()}
    except Exception as e:
        _logger.warning(f"Failed to load pkl weights from {path}: {e}")
        return [], {}


# ═══════════════════════════════════════════════════════════
# 6. 扫描历史表 DDL（被 scanner/history/timing_alerts 三者复用）
# ═══════════════════════════════════════════════════════════
def _ensure_scan_history_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date     TEXT    NOT NULL,
            ts_code       TEXT    NOT NULL,
            name          TEXT,
            industry      TEXT,
            rank          INTEGER,
            build_score   REAL,
            factor_score  REAL,
            winner_rate   REAL,
            big_net_inflow REAL,
            close         REAL,
            pct_chg       REAL,
            mvo_weight    REAL,
            regime        TEXT,
            reason        TEXT,
            UNIQUE(scan_date, ts_code)
        )
    """)
    conn.commit()


# ═══════════════════════════════════════════════════════════
# 7. 推荐历史 CSV 归档 + 连续上榜统计（原 975-1032，被 scanner 复用）
# ═══════════════════════════════════════════════════════════
def _save_and_calc_recommendation_stats(df_top, latest_date):
    archive_dir = os.path.join(PROJECT_ROOT, "archives")
    os.makedirs(archive_dir, exist_ok=True)
    history_csv = os.path.join(archive_dir, "recommended_history.csv")

    df_today = df_top.copy()
    df_today["date"] = str(latest_date)
    cols_to_save = ["date", "ts_code", "name", "industry", "build_score", "__rank"]
    for c in cols_to_save:
        if c not in df_today.columns:
            df_today[c] = None
    df_today = df_today[cols_to_save]

    if os.path.exists(history_csv):
        try:
            df_hist = pd.read_csv(history_csv, dtype={"date": str, "ts_code": str})
            if "date" not in df_hist.columns or df_hist.empty:
                df_hist = df_today
            else:
                df_hist = df_hist[df_hist["date"] != str(latest_date)]
                df_hist = pd.concat([df_hist, df_today], ignore_index=True)
        except Exception:
            df_hist = df_today
    else:
        df_hist = df_today

    df_hist.to_csv(history_csv, index=False)

    stats_map = {}
    all_dates = sorted(df_hist["date"].unique())
    date_to_idx = {d: i for i, d in enumerate(all_dates)}
    today_idx = date_to_idx.get(str(latest_date), -1)

    for ts_code, group in df_hist.groupby("ts_code"):
        total_count = len(group)
        ever_top_3 = bool((group["__rank"] <= 3).any())
        group_dates = sorted(group["date"].unique())
        consecutive_days = 0
        curr_idx = today_idx
        for d in reversed(group_dates):
            if date_to_idx[d] == curr_idx:
                consecutive_days += 1
                curr_idx -= 1
            else:
                break
        stats_map[ts_code] = {
            "total_recommends": total_count,
            "consecutive_days": consecutive_days,
            "ever_top_3": ever_top_3
        }
    return stats_map


# ======================================================================
# ThresholdConfig —— 统一阈值加载器（支持热加载 + 默认值兜底）
# ======================================================================

_THRESHOLDS_YAML = None
_TH_CACHE = {"data": None, "mtime": 0.0}


def _thresholds_yaml_path() -> str:
    """返回 config/thresholds.yaml 的绝对路径"""
    if _THRESHOLDS_YAML is None:
        return os.path.join(PROJECT_ROOT, "config", "thresholds.yaml")
    return _THRESHOLDS_YAML


def _load_raw_thresholds() -> dict:
    """
    加载 thresholds.yaml 原始内容，支持热加载（mtime 变化时重新读取）。
    任何异常（文件缺失 / YAML 语法错）都返回 {} 由上层使用默认值兜底。
    """
    yaml_path = _thresholds_yaml_path()
    try:
        if not os.path.exists(yaml_path):
            _TH_CACHE["data"] = {}
            _TH_CACHE["mtime"] = 0.0
            return {}
        mtime = os.path.getmtime(yaml_path)
        if mtime != _TH_CACHE["mtime"] or _TH_CACHE["data"] is None:
            try:
                import yaml
                with open(yaml_path, "r", encoding="utf-8") as f:
                    _TH_CACHE["data"] = yaml.safe_load(f) or {}
            except Exception as _ye:
                print(f"[ThresholdConfig] ⚠️ YAML 解析失败，使用内置默认值: {_ye}")
                _TH_CACHE["data"] = {}
            _TH_CACHE["mtime"] = mtime
    except Exception as _e:
        print(f"[ThresholdConfig] ⚠️ 读取失败，使用内置默认值: {_e}")
        return {}
    return _TH_CACHE["data"] if _TH_CACHE["data"] else {}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 覆盖 base 的 key，其余保留 base 默认值"""
    result = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ----------------------------------------------------------------------
# 默认值（与硬编码校准版 1:1 对齐，任何 YAML 缺失键都走此兜底）
# ----------------------------------------------------------------------

_DEFAULT_LEFT_PORTRAIT = {
    "profit_ratio_full": 0.25, "profit_ratio_half": 0.55, "profit_ratio_zero": 0.85, "profit_ratio_weight": 20,
    "pe_ttm_full": 55.0, "pe_ttm_half": 95.0, "pe_ttm_zero": 160.0,
    "neg_pe_neutral_ratio": 0.5, "pe_ttm_weight": 20,
    "hot_score_safe_lo": 0.28, "hot_score_safe_hi": 0.60, "return_5d_safe": 0.045, "return_5d_max": 0.075,
    "vol_bonus_above": 1.50, "vol_bonus_points": 2.0,
    "vol_penalty_below": 1.0, "vol_penalty_points": 3.0,
    "temp_weight": 20,
    "chip_best_lo": 76.0, "chip_best_hi": 86.0, "chip_mid_lo": 70.0, "chip_mid_hi": 92.0,
    "overconcentration_ratio": 0.3, "chip_weight": 20,
    "factor_sweet_lo": 0.78, "factor_sweet_hi": 0.90, "factor_overheat": 0.94, "factor_half": 0.68, "factor_weight": 20,
    "filter_threshold": 48, "expand_ratio": 3,
}

_DEFAULT_RIGHT_PORTRAIT = {
    "winner_rate_full": 90.0, "winner_rate_half": 75.0, "winner_rate_zero": 50.0, "winner_rate_weight": 20,
    "return_5d_full_lo": 0.03, "return_5d_full_hi": 0.12,
    "return_5d_half_lo": 0.00, "return_5d_half_hi": 0.15,
    "return_5d_zero_lo": -0.05, "return_5d_zero_hi": 0.20,
    "overshoot_penalty": -10.0, "momentum_weight": 20,
    "hot_score_full_lo": 0.60, "hot_score_full_hi": 0.85,
    "hot_score_half_lo": 0.50, "hot_score_half_hi": 0.92, "hot_score_zero_hi": 0.96,
    "overshoot_penalty_activity": -5.0, "activity_weight": 20,
    "inflow_full": 0.85, "inflow_half": 0.50, "inflow_weight": 20,
    "chip_best_lo": 82.0, "chip_best_hi": 95.0, "chip_mid_lo": 75.0, "chip_weight": 20,
}

_DEFAULT_GRADE_MAP = [
    (80, "A", "🔥 强烈推荐"),
    (60, "B", "✅ 符合画像"),
    (40, "C", "⚠️ 勉强通过"),
    (0,  "D", "❌ 画像不符"),
]


def get_threshold_version() -> str:
    """返回阈值配置版本号（热加载后返回最新）"""
    data = _load_raw_thresholds()
    return str(data.get("version", "default_builtin"))


def get_left_portrait_cfg() -> dict:
    """
    返回左侧画像参数 dict，格式与 PORTRAIT_CONFIG 100% 兼容，
    可直接传给 compute_portrait_score(cfg=...) / apply_portrait_filter(cfg=...)
    """
    data = _load_raw_thresholds()
    y = data.get("portrait_score", {}).get("left", {})

    yml = {}
    # 位置分
    pos = y.get("position", {})
    yml["profit_ratio_full"] = pos.get("profit_ratio_full")
    yml["profit_ratio_half"] = pos.get("profit_ratio_half")
    yml["profit_ratio_zero"] = pos.get("profit_ratio_zero")
    yml["profit_ratio_weight"] = pos.get("weight")
    # 估值分
    val = y.get("valuation", {})
    yml["pe_ttm_full"] = val.get("pe_ttm_full")
    yml["pe_ttm_half"] = val.get("pe_ttm_half")
    yml["pe_ttm_zero"] = val.get("pe_ttm_zero")
    yml["neg_pe_neutral_ratio"] = val.get("neg_pe_neutral_ratio")
    yml["pe_ttm_weight"] = val.get("weight")
    # 温度分
    temp = y.get("temperature", {})
    yml["hot_score_safe_lo"] = temp.get("hot_safe_lo")
    yml["hot_score_safe_hi"] = temp.get("hot_safe_hi")
    yml["return_5d_safe"] = temp.get("return_5d_safe")
    yml["return_5d_max"] = temp.get("return_5d_max")
    yml["vol_bonus_above"] = temp.get("vol_bonus_above")
    yml["vol_bonus_points"] = temp.get("vol_bonus_points")
    yml["vol_penalty_below"] = temp.get("vol_penalty_below")
    yml["vol_penalty_points"] = temp.get("vol_penalty_points")
    yml["temp_weight"] = temp.get("weight")
    # 筹码分
    chip = y.get("chip", {})
    yml["chip_best_lo"] = chip.get("chip_best_lo")
    yml["chip_best_hi"] = chip.get("chip_best_hi")
    yml["chip_mid_lo"] = chip.get("chip_mid_lo")
    yml["chip_mid_hi"] = chip.get("chip_mid_hi")
    yml["overconcentration_ratio"] = chip.get("overconcentration_ratio")
    yml["chip_weight"] = chip.get("weight")
    # 因子分
    fac = y.get("factor", {})
    yml["factor_sweet_lo"] = fac.get("sweet_lo")
    yml["factor_sweet_hi"] = fac.get("sweet_hi")
    yml["factor_overheat"] = fac.get("overheat")
    yml["factor_half"] = fac.get("half")
    yml["factor_weight"] = fac.get("weight")
    # 过滤
    yml["filter_threshold"] = y.get("filter_threshold")
    yml["expand_ratio"] = y.get("expand_ratio")

    # 去掉 None 的 key，然后用默认值补全
    yml_clean = {k: v for k, v in yml.items() if v is not None}
    return _deep_merge(_DEFAULT_LEFT_PORTRAIT, yml_clean)


def get_right_portrait_cfg() -> dict:
    """
    返回右侧画像参数 dict，格式与 RIGHT_PORTRAIT_CONFIG 100% 兼容。
    """
    data = _load_raw_thresholds()
    y = data.get("portrait_score", {}).get("right", {})

    yml = {}
    br = y.get("breakout", {})
    yml["winner_rate_full"] = br.get("winner_rate_full")
    yml["winner_rate_half"] = br.get("winner_rate_half")
    yml["winner_rate_zero"] = br.get("winner_rate_zero")
    yml["winner_rate_weight"] = br.get("weight")
    mom = y.get("momentum", {})
    yml["return_5d_full_lo"] = mom.get("full_lo")
    yml["return_5d_full_hi"] = mom.get("full_hi")
    yml["return_5d_half_lo"] = mom.get("half_lo")
    yml["return_5d_half_hi"] = mom.get("half_hi")
    yml["return_5d_zero_lo"] = mom.get("zero_lo")
    yml["return_5d_zero_hi"] = mom.get("zero_hi")
    yml["overshoot_penalty"] = mom.get("overshoot_penalty")
    yml["momentum_weight"] = mom.get("weight")
    act = y.get("activity", {})
    yml["hot_score_full_lo"] = act.get("full_lo")
    yml["hot_score_full_hi"] = act.get("full_hi")
    yml["hot_score_half_lo"] = act.get("half_lo")
    yml["hot_score_half_hi"] = act.get("half_hi")
    yml["hot_score_zero_hi"] = act.get("zero_hi")
    yml["overshoot_penalty_activity"] = act.get("overshoot_penalty")
    yml["activity_weight"] = act.get("weight")
    inf = y.get("inflow", {})
    yml["inflow_full"] = inf.get("inflow_full")
    yml["inflow_half"] = inf.get("inflow_half")
    yml["inflow_weight"] = inf.get("weight")
    chip = y.get("chip", {})
    yml["chip_best_lo"] = chip.get("chip_best_lo")
    yml["chip_best_hi"] = chip.get("chip_best_hi")
    yml["chip_mid_lo"] = chip.get("chip_mid_lo")
    yml["chip_weight"] = chip.get("weight")

    yml_clean = {k: v for k, v in yml.items() if v is not None}
    return _deep_merge(_DEFAULT_RIGHT_PORTRAIT, yml_clean)


def get_grade_map():
    """返回 [(min_score, grade, label), ...] 列表，供 _grade() 使用"""
    data = _load_raw_thresholds()
    y_list = data.get("portrait_score", {}).get("grade_map")
    if not y_list:
        return list(_DEFAULT_GRADE_MAP)
    result = []
    for item in y_list:
        try:
            result.append((
                float(item["min_score"]),
                str(item["grade"]),
                str(item.get("label", "")),
            ))
        except Exception:
            continue
    return result if result else list(_DEFAULT_GRADE_MAP)


def get_position_funnel_cfg() -> dict:
    """
    返回 get_portrait_position_pick() 三层漏斗阈值。
    键名保持与代码使用一致：
      - common / layer1 / layer2 / layer3
    """
    _DEFAULTS = {
        "common": {
            "candidate_pool_top_n": 80,
            "winner_rate_lo": 25.0,
            "winner_rate_hi": 85.0,
            "winner_rate_right_lo": 60.0,
            "default_factor_weights": {
                "return_5d": 0.40, "excess_return_20d": 0.30,
                "turnover_rate_20d": 0.20, "hot_money_score": 0.10,
            },
            "bear_factor_weights": {
                "north_net_inflow_ratio": -0.18, "return_5d": -0.54,
                "turnover_rate_20d": -0.28,
            },
            "build_score_left": {
                "factor_score_norm": 0.45, "winner_rate_score": 0.25,
                "inflow_norm": 0.20, "pct_chg_rank_inv": 0.10,
            },
            "build_score_right": {
                "factor_score_norm": 0.40, "winner_rate_rank": 0.25,
                "inflow_norm": 0.25, "pct_chg_rank": 0.10,
            },
            "portrait_bonus": 15.0,
            "portrait_bonus_min": 75.0,
        },
        "layer1": {
            "left_threshold": 50.0,
            "left_grade_label": "等级 ≥ B/C+",
            "right_threshold": 45.0,
            "right_grade_label": "等级 ≥ C+",
        },
        "layer2": {
            "left":  {"pct_chg_max": 4.5, "upper_shadow_max": 0.035, "return_20d_max": 0.25},
            "right": {"pct_chg_max": 9.5, "upper_shadow_max": 0.035, "return_20d_max": 0.40},
        },
        "layer3": {
            "max_per_sector": 1,
            "final_pick_top_n": 5,
        },
    }
    data = _load_raw_thresholds()
    y = data.get("position_pick_funnel", {})
    return _deep_merge(_DEFAULTS, y)


def get_scanner_cfg() -> dict:
    """返回 get_build_position_opportunities() 扫描器参数"""
    _DEFAULTS = {
        "prefilter": {
            "winner_rate_lo": 25.0,
            "winner_rate_hi": 85.0,
            "restricted_ST": True,
        },
        "scoring_weights": {
            "factor_rank":       0.28,
            "winner_rate_rank":  0.23,
            "chip_peak_rank":    0.19,
            "inflow_rank":       0.23,
            "pct_chg_inv_rank":  0.07,
        },
        "sector_diversify": {
            "max_per_sector": 2,
        },
        "signal_thresholds": {
            "mom_10_strong_above":   3.0,
            "mom_10_weak_below":    -3.0,
            "mom_30_strong_above":  10.0,
            "mom_30_weak_below":     0.0,
            "vol_60_low_below":      1.5,
            "vol_60_high_above":     3.0,
            "portrait_excellent":   70.0,
            "portrait_pass":        50.0,
            "portrait_marginal":    45.0,
            "overall_green_min":     3,
            "overall_red_min":       3,
        },
        "regime_weights_fallback": {
            "Range": {
                "return_5d": 0.25,
                "turnover_rate_20d": -0.15,
                "profit_ratio_estimate": 0.30,
            },
        },
    }
    data = _load_raw_thresholds()
    y = data.get("scanner", {})
    return _deep_merge(_DEFAULTS, y)


def get_live_regime_cfg() -> dict:
    """返回 compute_live_regime() 市场状态判定阈值"""
    _DEFAULTS = {
        "dark": {
            "return_5d_below": -0.045,
            "mdd_5d_below": -0.050,
            "up_ratio_below": 0.30,
            "vol_above_quantile": 0.75,
        },
        "bull": {
            "return_20d_above": 0.05,
            "vol_below_quantile": 0.50,
        },
        "bear": {
            "return_20d_below": -0.03,
            "vol_above_quantile": 0.50,
        },
        "dashboard": {
            "dark_up_ratio_pct": 30.0,
        },
    }
    data = _load_raw_thresholds()
    y = data.get("market_regime_live", {})
    return _deep_merge(_DEFAULTS, y)


def get_pick_reason_cfg() -> dict:
    """返回建仓推荐理由文案触发阈值（_reason 函数）"""
    _DEFAULTS = {
        "left_high": 18,
        "left_active": 18,
        "right_high": 18,
        "right_active": 15,
        "grade_A_reason": "A级画像",
        "grade_B_reason": "B级画像",
    }
    data = _load_raw_thresholds()
    y = data.get("ui_display", {}).get("pick_reason", {})
    return _deep_merge(_DEFAULTS, y)


def get_diagnose_grade_cfg() -> dict:
    """返回单票配置诊断分级阈值（market_overview._diagnose_single）"""
    _DEFAULTS = {
        "grade_A_plus_min": 70.0,
        "grade_A_min": 60.0,
        "grade_B_min": 50.0,
        "grade_C_min": 45.0,
        "factor_excellent_min": 60.0,
        "factor_neutral_min": 40.0,
        "chips_safe_min": 70.0,
        "chips_danger_max": 30.0,
        "pe_reasonable_max": 30.0,
        "pe_high_min": 60.0,
    }
    data = _load_raw_thresholds()
    y = data.get("ui_display", {}).get("diagnose_grade", {})
    return _deep_merge(_DEFAULTS, y)


def get_hot_money_tracker_cfg() -> dict:
    """返回游资追踪模块完整配置（板块资金流/题材热度/个股下钻）"""
    _DEFAULTS = {
        "sector_money_flow": {
            "top_n": 10,
            "min_stock_count": 5,
        },
        "theme_popularity": {
            "top_n": 10,
            "limit_dates_lookback": 10,
            "fallback_top_n": 10,
        },
        "theme_stocks_drill": {
            "default_limit": 10,
            "sort_by": "net_mf_amount",
        },
    }
    data = _load_raw_thresholds()
    y = data.get("hot_money_tracker", {})
    merged = _deep_merge(_DEFAULTS, y)
    # 整数安全断言（防止 YAML 配成浮点）
    for sub_key in ["sector_money_flow", "theme_popularity", "theme_stocks_drill"]:
        if sub_key in merged:
            for k, v in list(merged[sub_key].items()):
                if k in ("top_n", "min_stock_count", "fallback_top_n", "default_limit", "limit_dates_lookback"):
                    merged[sub_key][k] = int(v)
    return merged


def get_data_integrity_cfg() -> dict:
    """返回数据完整性闸门配置（热加载）"""
    _DEFAULTS = {
        "enabled": True,
        "block_backtest_on_violation": True,
        "cross_section_return_mean_abs_max": 0.05,
        "adj_factor_jump_ratio_max": 0.20,
        "min_cross_section_size": 30,
        "clip_boundary_ratio_max": 0.10,
        "adj_factor_null_ratio_max": 0.05,
        "lookback_days": 60,
    }
    data = _load_raw_thresholds()
    y = data.get("data_integrity", {})
    merged = _deep_merge(_DEFAULTS, y)
    if "lookback_days" in merged:
        merged["lookback_days"] = int(merged["lookback_days"])
    if "min_cross_section_size" in merged:
        merged["min_cross_section_size"] = int(merged["min_cross_section_size"])
    return merged


def check_data_integrity(df_aligned, cfg=None) -> dict:
    """
    数据完整性闸门检查：在回测前验证 df_aligned 的截面质量。

    参数:
        df_aligned: validator.validate_factors 返回的对齐后 DataFrame,
                    必含 trade_date / future_return_5d / adj_factor 列
        cfg: get_data_integrity_cfg() 的返回, None 时自动获取

    返回:
        {
            "passed": bool,        # 是否通过所有闸门
            "violations": list,    # 违例详情 [{gate, trade_date, value, threshold, message}]
            "summary": str,        # 人类可读的总结
        }
    """
    if cfg is None:
        cfg = get_data_integrity_cfg()

    result = {"passed": True, "violations": [], "summary": ""}
    if not cfg.get("enabled", True):
        result["summary"] = "数据完整性闸门已关闭 (enabled=false)"
        return result

    if df_aligned is None or len(df_aligned) == 0:
        result["passed"] = False
        result["violations"].append({
            "gate": "empty_input",
            "message": "df_aligned 为空，无法执行回测"
        })
        result["summary"] = "❌ 阻断: 输入数据为空"
        return result

    import pandas as _pd

    mean_abs_max = cfg["cross_section_return_mean_abs_max"]
    jump_max = cfg["adj_factor_jump_ratio_max"]
    min_size = cfg["min_cross_section_size"]
    clip_ratio_max = cfg["clip_boundary_ratio_max"]
    null_ratio_max = cfg["adj_factor_null_ratio_max"]
    lookback = cfg["lookback_days"]

    # 取最近 lookback 个交易日
    all_dates = sorted(df_aligned["trade_date"].unique().tolist())
    check_dates = all_dates[-lookback:] if len(all_dates) > lookback else all_dates

    violations = []
    df_check = df_aligned[df_aligned["trade_date"].isin(check_dates)].copy()

    # 确保 future_return_5d 与 adj_factor 为数值
    if "future_return_5d" in df_check.columns:
        df_check["future_return_5d"] = _pd.to_numeric(
            df_check["future_return_5d"], errors="coerce"
        )
    if "adj_factor" in df_check.columns:
        df_check["adj_factor"] = _pd.to_numeric(
            df_check["adj_factor"], errors="coerce"
        )

    for d in check_dates:
        sub = df_check[df_check["trade_date"] == d]
        n = len(sub)
        if n == 0:
            continue

        # 闸门 3: 截面最小样本数
        if n < min_size:
            violations.append({
                "gate": "min_cross_section_size",
                "trade_date": d,
                "value": n,
                "threshold": min_size,
                "message": f"{d} 截面样本数 {n} < {min_size}"
            })

        # 闸门 1: 截面日收益均值绝对值
        if "future_return_5d" in sub.columns and sub["future_return_5d"].notna().any():
            mean_ret = sub["future_return_5d"].mean()
            if abs(mean_ret) > mean_abs_max:
                violations.append({
                    "gate": "cross_section_return_mean_abs_max",
                    "trade_date": d,
                    "value": round(float(mean_ret), 4),
                    "threshold": mean_abs_max,
                    "message": f"{d} 截面收益均值 {mean_ret:.4f} 超阈值 |.|>{mean_abs_max}"
                })

        # 闸门 4: 触达 clip 边界占比
        if "future_return_5d" in sub.columns and sub["future_return_5d"].notna().any():
            clipped = ((sub["future_return_5d"] >= 0.799) | (sub["future_return_5d"] <= -0.499)).sum()
            clip_ratio = clipped / n
            if clip_ratio > clip_ratio_max:
                violations.append({
                    "gate": "clip_boundary_ratio_max",
                    "trade_date": d,
                    "value": round(float(clip_ratio), 4),
                    "threshold": clip_ratio_max,
                    "message": f"{d} 触达clip边界占比 {clip_ratio:.1%} > {clip_ratio_max:.0%}"
                })

        # 闸门 5: adj_factor NULL 占比
        if "adj_factor" in sub.columns:
            null_ratio = sub["adj_factor"].isna().sum() / n
            if null_ratio > null_ratio_max:
                violations.append({
                    "gate": "adj_factor_null_ratio_max",
                    "trade_date": d,
                    "value": round(float(null_ratio), 4),
                    "threshold": null_ratio_max,
                    "message": f"{d} adj_factor NULL占比 {null_ratio:.1%} > {null_ratio_max:.0%}"
                })

    # 闸门 2: adj_factor 环比跳变 (按 ts_code 分组检测)
    if "adj_factor" in df_check.columns:
        df_sorted = df_check.sort_values(["stock_code", "trade_date"]).reset_index(drop=True) \
            if "stock_code" in df_check.columns \
            else df_check.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        code_col = "stock_code" if "stock_code" in df_sorted.columns else "ts_code"
        df_sorted["prev_af"] = df_sorted.groupby(code_col)["adj_factor"].shift(1)
        df_sorted["jump"] = (
            (df_sorted["adj_factor"] - df_sorted["prev_af"]).abs()
            / df_sorted["prev_af"].replace(0, 1.0)
        )
        jump_mask = (df_sorted["jump"] > jump_max) & df_sorted["prev_af"].notna()
        if jump_mask.any():
            jump_dates = df_sorted.loc[jump_mask, "trade_date"].unique().tolist()
            for jd in jump_dates[:5]:  # 只报前 5 个
                violations.append({
                    "gate": "adj_factor_jump_ratio_max",
                    "trade_date": jd,
                    "threshold": jump_max,
                    "message": f"{jd} 检测到 adj_factor 环比跳变 |Δ|>{jump_max}"
                })

    result["violations"] = violations
    if violations:
        result["passed"] = False
        gates = set(v["gate"] for v in violations)
        result["summary"] = (
            f"❌ 阻断: 检测到 {len(violations)} 条违例, 涉及闸门: {','.join(sorted(gates))}"
            if cfg.get("block_backtest_on_violation", True)
            else f"⚠️ 告警: 检测到 {len(violations)} 条违例 (block=false, 仅告警)"
        )
    else:
        result["summary"] = f"✅ 通过: 最近 {len(check_dates)} 个交易日截面质量正常"

    return result

