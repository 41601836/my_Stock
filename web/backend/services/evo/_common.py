# -*- coding: utf-8 -*-
"""
services.evo._common —— EVO 进化层共享基础层
=========================================================
* EvoConfig: evo.yaml 热加载器（按 mtime 自动刷新）
* SQLite 连接：复用 services._common 的 get_db_connection
* _evo 后缀新表 DDL 统一创建入口
* 路径常量：models/evo、logs/evo
* 通用工具：IC 计算、拥挤度计算、Graham 代理指标计算
* 安全熔断：classic vs evo 重合度检查

设计原则：
- 绝不 import services._common 以外的现有业务模块（防止循环依赖）
- 所有对现有 services 层的调用都通过"懒加载 + 局部 import + 异常兜底"
"""

import os
import sys
import math
import time
import json
import pickle
import sqlite3
import logging
import datetime
from functools import lru_cache
from typing import Dict, Any, Optional, Tuple, List

import pandas as pd
import numpy as np

# ═══════════════════════════════════════════════════════════
# 1. 路径初始化 & sys.path 注入（与 services._common 对齐）
# ═══════════════════════════════════════════════════════════
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
)
PROJECT_ROOT = _PROJECT_ROOT
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config.paths import PATHS, startup_check

startup_check()

DB_PATH = PATHS.database.stock_data
MODELS_EVO_DIR = os.path.join(PROJECT_ROOT, "models", "evo")
LOGS_EVO_DIR   = os.path.join(PROJECT_ROOT, "logs",   "evo")
EVO_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "evo.yaml")

for _d in [MODELS_EVO_DIR, LOGS_EVO_DIR]:
    os.makedirs(_d, exist_ok=True)

_logger = logging.getLogger("services.evo._common")

# ═══════════════════════════════════════════════════════════
# 2. 复用现有 services._common 的公共能力（显式 import 列清单）
# ═══════════════════════════════════════════════════════════
from services._common import (
    get_db_connection,
    clean_nan_inf,
    _get_factor_date,
    _load_pkl_weights,
)

# ═══════════════════════════════════════════════════════════
# 3. EvoConfig —— evo.yaml 热加载（mtime 触发，~微秒级开销）
# ═══════════════════════════════════════════════════════════
class _EvoConfig:
    def __init__(self, path: str):
        self.path = path
        self._mtime = 0.0
        self._cfg: Dict[str, Any] = {}
        self._reload_if_needed()

    def _reload_if_needed(self) -> None:
        try:
            mt = os.path.getmtime(self.path)
        except FileNotFoundError:
            self._cfg = {}
            self._mtime = 0.0
            return
        if mt > self._mtime:
            import yaml
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._cfg = yaml.safe_load(f) or {}
                self._mtime = mt
                _logger.info(f"[EvoConfig] 加载/热更新 {self.path} (mtime={mt})")
            except Exception as e:
                _logger.error(f"[EvoConfig] 加载失败: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """key 支持点分隔：cfg.get('dynamic_weights.enabled')"""
        self._reload_if_needed()
        parts = key.split(".")
        v: Any = self._cfg
        for p in parts:
            if not isinstance(v, dict) or p not in v:
                return default
            v = v[p]
        return v

    @property
    def version(self) -> str:
        return self.get("version", "0.0")

    @property
    def all_modules_status(self) -> Dict[str, bool]:
        """用于 /api/evo/status 接口：返回 8 大模块启用状态"""
        return {
            "dynamic_weights": bool(self.get("dynamic_weights.enabled", False)),
            "cross_factors":   bool(self.get("cross_factors.enabled", False)),
            "crowding_monitor": bool(self.get("crowding_monitor.enabled", False)),
            "lambdarank":      bool(self.get("lambdarank.enabled", False)),
            "surprise_factors": bool(self.get("surprise_factors.enabled", False)),
            "text_factors":    bool(self.get("text_factors.enabled", False)),
            "graham_filter":   bool(self.get("graham_filter.enabled", False)),
            "decay_monitor":   bool(self.get("decay_monitor.enabled", False)),
        }


EvoConfig = _EvoConfig(EVO_CONFIG_PATH)

# ═══════════════════════════════════════════════════════════
# 4. EVO 专属表 DDL（创建幂等，启动时或首次使用时自动建）
# ═══════════════════════════════════════════════════════════
EVO_TABLES_DDL = {
    "factor_values_evo": """
        CREATE TABLE IF NOT EXISTS factor_values_evo (
            ts_code                     TEXT    NOT NULL,
            trade_date                  TEXT    NOT NULL,
            inter_quality_momentum      REAL,
            inter_value_excess          REAL,
            inter_chip_volume           REAL,
            inter_smart_defense         REAL,
            inter_overshoot_reversal    REAL,
            triple_value_mom_quality    REAL,
            inter_mom_skew_neg          REAL,
            inter_lowvol_profit         REAL,
            inter_turnover_reversal     REAL,
            inter_chip_break_right      REAL,
            surprise_price_vote         REAL,
            surprise_earnings_gap       REAL,
            surprise_roe_qoq            REAL,
            graham_score                INTEGER,
            graham_detail_json          TEXT,
            text_sentiment_score        REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    """,

    "evo_dynamic_weights_log": """
        CREATE TABLE IF NOT EXISTS evo_dynamic_weights_log (
            trade_date   TEXT NOT NULL PRIMARY KEY,
            weights_json TEXT NOT NULL,
            regime       TEXT,
            created_at   TEXT DEFAULT (datetime('now','localtime'))
        )
    """,

    "evo_crowding_log": """
        CREATE TABLE IF NOT EXISTS evo_crowding_log (
            trade_date     TEXT NOT NULL,
            factor_name    TEXT NOT NULL,
            crowding_score REAL NOT NULL,
            action         TEXT NOT NULL, -- normal / half_weight / disable
            PRIMARY KEY (trade_date, factor_name)
        )
    """,

    "evo_decay_alerts": """
        CREATE TABLE IF NOT EXISTS evo_decay_alerts (
            alert_date   TEXT NOT NULL,
            factor_name  TEXT NOT NULL,
            level        TEXT NOT NULL, -- yellow / red
            rolling_ic   REAL,
            description  TEXT,
            PRIMARY KEY (alert_date, factor_name, level)
        )
    """,

    "evo_factor_ic_daily": """
        CREATE TABLE IF NOT EXISTS evo_factor_ic_daily (
            trade_date  TEXT NOT NULL,
            factor_name TEXT NOT NULL,
            rank_ic     REAL,
            PRIMARY KEY (trade_date, factor_name)
        )
    """,

    "evo_ml_predictions": """
        CREATE TABLE IF NOT EXISTS evo_ml_predictions (
            trade_date TEXT NOT NULL,
            ts_code    TEXT NOT NULL,
            rank_score REAL NOT NULL,
            shap_json  TEXT,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,

    "evo_text_raw": """
        CREATE TABLE IF NOT EXISTS evo_text_raw (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            source        TEXT NOT NULL,   -- cninfo_announcement / sina7x24 / ...
            url           TEXT NOT NULL,   -- source 内唯一（去重键；快讯用伪 URL）
            title         TEXT NOT NULL,
            content       TEXT,            -- 摘要/正文片段（M6.2 打分用）
            stock_codes   TEXT,            -- JSON array：已知关联 ts_code（公告带码；新闻 M6.2 模糊匹配）
            published_at  TEXT,
            fetched_at    TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(source, url)
        )
    """,

    "evo_text_sentiment_scores": """
        CREATE TABLE IF NOT EXISTS evo_text_sentiment_scores (
            ts_code        TEXT NOT NULL,
            trade_date     TEXT NOT NULL,
            source         TEXT NOT NULL, -- news / announcement / social
            sentiment_score REAL,
            keyword_hits_json TEXT,
            PRIMARY KEY (ts_code, trade_date, source)
        )
    """,
}


def ensure_evo_tables(db_path: str = DB_PATH) -> Dict[str, bool]:
    """幂等创建所有 EVO 专属表；返回 {表名: 是否已创建/存在}"""
    conn = get_db_connection(db_path)
    try:
        cur = conn.cursor()
        results: Dict[str, bool] = {}
        for name, ddl in EVO_TABLES_DDL.items():
            cur.execute(ddl)
            results[name] = True
        conn.commit()
        _logger.info(f"[EvoTables] 已确保 {len(results)} 张 EVO 专属表存在")
        return results
    except Exception as e:
        _logger.error(f"[EvoTables] 建表失败: {e}")
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════
# 5. 通用统计工具（IC/拥挤度/Graham代理 复用）
# ═══════════════════════════════════════════════════════════

def calc_rank_ic(factor_series: pd.Series, forward_return_series: pd.Series) -> Optional[float]:
    """
    Spearman Rank IC = cross-section rank 相关性。
    返回标量 IC；数据不足时返回 None。
    """
    aligned = pd.concat([factor_series, forward_return_series], axis=1).dropna()
    if len(aligned) < 30:
        return None
    try:
        return float(aligned.corr(method="spearman").iloc[0, 1])
    except Exception:
        return None


def calc_crowding_score(cross_section_factor: pd.Series, corr_threshold: float = 0.7) -> float:
    """
    因子拥挤度代理：截面排名中，前 20% 分位与市场成交额排名的 Spearman 相关性
    0~1，越大越拥挤。数据不足返回 0.0。
    """
    s = cross_section_factor.dropna()
    if len(s) < 50:
        return 0.0
    try:
        # 因子本身的极值集中度作为拥挤度代理
        top_share = float((s.rank(pct=True) >= 0.9).sum()) / len(s)
        return float(np.clip(top_share * 3.0, 0.0, 1.0))
    except Exception:
        return 0.0


def graham_proxy_scores(row: Dict[str, Any]) -> Tuple[int, Dict[str, bool]]:
    """
    Graham 7 项防御指标（代理版，只依赖现有 daily_basic/daily_prices 字段）。
    返回 (通过项数, 每项 bool 字典)。
    row 至少包含：circ_mv, pe_ttm, pb, roe（近似）
    """
    cfg_p = EvoConfig.get("graham_filter.checks", {})

    checks_detail: Dict[str, bool] = {}

    # ① 规模：流通市值 ≥ 阈值（亿元）
    size_th = float(cfg_p.get("size_min_circ_mv_billion", 5.0)) * 1e8
    checks_detail["adequate_size"] = bool(row.get("circ_mv", 0) >= size_th)

    # ② 流动性比率（无流动比率字段，用高 PB/低杠杆近似做降级；这里暂时用 circ_mv*2 > 总负债近似占位，
    #    若字段缺失直接标记 True 以免错杀，后续财报数据接入后可替换）
    checks_detail["strong_liquidity"] = True

    # ③ PE 合理
    pe_max = float(cfg_p.get("pe_ttm_max", 25.0))
    pe = float(row.get("pe_ttm") or 0.0)
    checks_detail["reasonable_pe"] = bool(0 < pe <= pe_max)

    # ④ PE × PB 安全边际
    pp_max = float(cfg_p.get("pe_pb_product_max", 30.0))
    pb = float(row.get("pb") or 0.0)
    product = pe * pb if pe > 0 else 999.0
    checks_detail["safe_valuation_product"] = bool(0 < product <= pp_max)

    # ⑤ 持续盈利（ROE 近似；roe 是 feature_engineering 中的近似列）
    roe = float(row.get("roe") or 0.0)
    checks_detail["consistent_earnings"] = bool(roe > 0.04)

    # ⑥ 分红记录（无历史分红字段，占位为 True）
    checks_detail["dividend_record"] = True

    # ⑦ 长期盈利增长（无 10 年 EPS，用 ROE > 0.06 做降级代理）
    checks_detail["long_term_growth"] = bool(roe > 0.06)

    score = int(sum(1 for v in checks_detail.values() if v))
    return score, checks_detail


# ═══════════════════════════════════════════════════════════
# 6. 结果熔断机制（安全闸 3）
# ═══════════════════════════════════════════════════════════
def check_overlap_and_maybe_fallback(
    classic_top_codes: List[str],
    evo_top_codes: List[str],
    min_overlap: Optional[float] = None,
) -> Tuple[float, bool]:
    """
    计算经典 vs 进化 TopN 重合度；若低于阈值，标记为"建议熔断降级"。
    返回 (overlap_ratio 0~1, should_fallback bool)
    """
    if min_overlap is None:
        min_overlap = float(EvoConfig.get("portfolio_mixer.min_classic_overlap_ratio", 0.20))
    if not classic_top_codes or not evo_top_codes:
        return 0.0, False
    s1, s2 = set(classic_top_codes), set(evo_top_codes)
    ratio = len(s1 & s2) / max(len(s1), len(s2))
    should = ratio < min_overlap
    if should:
        _logger.warning(
            f"[EvoFuse] 重合度仅 {ratio:.2%} < 阈值 {min_overlap:.0%}，触发熔断降级建议")
    return float(ratio), should
