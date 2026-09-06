# -*- coding: utf-8 -*-
"""
services.resonance_service —— 四重共振策略服务层
===================================================
基于筹码 / 资金 / 板块 / 情绪 四维的共振评分、信号池、
股票池分层、卖出铁律的后端服务。

⚠️ 零侵入原则：
1. 只读 factor_values / factor_values_evo / daily_prices / stock_list 表
   仅写入 resonance_history 表
2. 不 import 任何经典层扫描器代码
3. 删除本文件 + 路由注册即回滚

API:
- get_resonance_scan()       最新截面共振扫描（Top-N）
- get_resonance_detail()     单股票四维详情 + 雷达图数据
- get_sell_signals()         单股票 3 条卖出信号检查
- get_resonance_history()    近 N 天共振扫描历史
- get_dimension_ic()         四维各自的 IC 表现对比
"""

import os
import sys
import yaml
import logging
import datetime
from typing import Optional, Dict, Any, List

import sqlite3
import pandas as pd
import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from factor_lib.resonance import ResonanceEngine, StockPool, SellSignalEngine
from factor_lib.signal_pool import SignalPool
from factor_lib.registry import FACTOR_REGISTRY
from factor_lib.loader import FactorDataLoader

_logger = logging.getLogger("services.resonance_service")

CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "resonance.yaml")
DB_PATH = os.path.join(_PROJECT_ROOT, "db", "stock_data.db")

_HISTORY_TABLE = "resonance_history"


def _load_config() -> Dict[str, Any]:
    """加载共振策略配置"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _safe_load_factors(engine, loader, start_date, end_date=None):
    """安全加载因子：只加载表中实际存在的因子列，避免 SQL 报错"""
    avail_factors = engine._get_available_factors("factor_values")
    avail_factors_evo = engine._get_available_factors("factor_values_evo")
    factors_to_load = [f for f in engine.all_factors if f in avail_factors or f in avail_factors_evo]

    if not factors_to_load:
        return pd.DataFrame(), []

    df = loader.load_factor_values(factors_to_load, start_date=start_date, end_date=end_date)
    return df, factors_to_load


def _clean_nan(obj):
    """递归清理 NaN/Inf"""
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    if isinstance(obj, float):
        if pd.isna(obj) or obj == float('inf') or obj == float('-inf'):
            return None
        return round(obj, 6)
    if isinstance(obj, (pd.Timestamp, np.integer)):
        return int(obj) if not pd.isna(obj) else None
    if isinstance(obj, (np.floating,)):
        return float(obj) if not pd.isna(obj) else None
    return obj


# ── 选日逻辑（与 mf202609 一致） ─────────

_SCAN_DATE_LOOKBACK_DAYS = 120


def _resolve_scan_date(factors: List[str]) -> str:
    """轻量定位最新全量截面日期"""
    tables: List[str] = []
    for f in factors:
        meta = FACTOR_REGISTRY.get(f)
        if meta and meta.table not in tables:
            tables.append(meta.table)
    if not tables:
        return ""

    cutoff = (
        datetime.datetime.now() - datetime.timedelta(days=_SCAN_DATE_LOOKBACK_DAYS)
    ).strftime("%Y%m%d")

    conn = sqlite3.connect(DB_PATH)
    try:
        series = []
        for t in tables:
            df_c = pd.read_sql(
                f"SELECT trade_date, COUNT(*) AS cnt FROM {t} "
                f"WHERE trade_date >= ? GROUP BY trade_date",
                conn, params=[cutoff],
            )
            if not df_c.empty:
                series.append(df_c.set_index("trade_date")["cnt"])
        if not series:
            row = conn.execute(f"SELECT MAX(trade_date) FROM {tables[0]}").fetchone()
            return str(row[0]) if row and row[0] else ""
    finally:
        conn.close()

    if len(series) == 1:
        counts = series[0]
    else:
        counts = pd.concat(series, axis=1).dropna().min(axis=1)
    counts = counts.sort_index()
    max_cnt = counts.max()
    good = counts[counts >= max_cnt * 0.8]
    return str(good.index[-1]) if len(good) else str(counts.index[-1])


# ═══════════════════════════════════════════
#  历史记录表
# ═══════════════════════════════════════════

def _ensure_history_table(conn):
    """确保 resonance_history 表存在"""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_HISTORY_TABLE} (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date       TEXT    NOT NULL,
            ts_code         TEXT    NOT NULL,
            name            TEXT,
            industry        TEXT,
            market          TEXT,
            rank            INTEGER,
            resonance_score REAL,
            resonance_level TEXT,
            chip_score      REAL,
            capital_score   REAL,
            sector_score    REAL,
            sentiment_score REAL,
            position_low    REAL,
            position_high   REAL,
            UNIQUE(scan_date, ts_code)
        )
    """)
    conn.commit()


def _save_scan_history(stocks: list, scan_date: str) -> int:
    """将扫描结果写入历史表，返回写入条数"""
    if not stocks:
        return 0
    conn = sqlite3.connect(DB_PATH)
    try:
        _ensure_history_table(conn)
        rows = []
        for s in stocks:
            dims = s.get("dimension_scores", {})
            rows.append((
                scan_date,
                s.get("ts_code", ""),
                s.get("name", ""),
                s.get("industry", ""),
                s.get("market", ""),
                int(s.get("rank", 0)),
                float(s.get("resonance_score", 0.0)),
                s.get("resonance_level", ""),
                float(dims.get("chip", 0) or 0),
                float(dims.get("capital", 0) or 0),
                float(dims.get("sector", 0) or 0),
                float(dims.get("sentiment", 0) or 0),
                float(s.get("position_low", 0.0)),
                float(s.get("position_high", 0.0)),
            ))
        conn.executemany(
            f"INSERT OR IGNORE INTO {_HISTORY_TABLE} "
            f"(scan_date, ts_code, name, industry, market, rank, "
            f"resonance_score, resonance_level, chip_score, capital_score, "
            f"sector_score, sentiment_score, position_low, position_high) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows
        )
        conn.commit()
        return conn.total_changes
    except Exception as e:
        _logger.error(f"save resonance history error: {e}")
        return 0
    finally:
        conn.close()


# ═══════════════════════════════════════════
#  共振扫描
# ═══════════════════════════════════════════

def get_resonance_scan(
    top_n: int = 50,
    date: Optional[str] = None,
    pool: str = "all",
    use_neutral: bool = False,
) -> Dict[str, Any]:
    """运行四重共振截面扫描，返回 Top-N 股票 + 四维分数 + 共振等级 + 建议仓位

    Parameters
    ----------
    top_n : int
        返回股票数量。
    date : str, optional
        扫描日期，默认最新有数据的日期。
    pool : str
        股票池：all / large / mid / small / micro。
    use_neutral : bool
        是否做行业中性化（预留）。
    """
    try:
        cfg = _load_config()
        engine = ResonanceEngine(config=cfg)

        # 1. 确定扫描日期
        if not date:
            date = _resolve_scan_date(engine.all_factors)
        if not date:
            return {"success": False, "error": "无因子数据", "stocks": [], "meta": {}}

        # 2. 加载因子数据（智能回退：只加载表中存在的因子）
        avail_factors = engine._get_available_factors("factor_values")
        avail_factors_evo = engine._get_available_factors("factor_values_evo")
        factors_to_load = [f for f in engine.all_factors if f in avail_factors or f in avail_factors_evo]

        if not factors_to_load:
            return {"success": False, "error": "因子表中无可用因子列", "stocks": [], "meta": {}}

        loader = FactorDataLoader()
        all_df = loader.load_factor_values(
            factors_to_load, start_date=date, end_date=date
        )
        if all_df.empty:
            return {"success": False, "error": f"{date} 无因子数据", "stocks": [], "meta": {}}

        df = all_df.copy()

        # 2b. 板块强度：如果不在表中，实时计算（简化版代理）
        if "sector_strength" in engine.all_factors and "sector_strength" not in df.columns:
            df_idx = df.set_index("ts_code")
            sector_s = engine._compute_sector_strength_online(date, df_idx)
            df = df.set_index("ts_code")
            df["sector_strength"] = sector_s
            df = df.reset_index()
            factors_to_load.append("sector_strength")

        total_scanned = len(df)

        # 3. 股票池过滤
        if pool and pool != "all":
            sp = StockPool()
            pool_codes = set(sp.get_pool_stocks(pool, date))
            if pool_codes:
                df = df[df["ts_code"].isin(pool_codes)].copy()

        after_pool = len(df)

        # 4. 过滤：至少 min_valid_factors 个因子有值
        min_valid = cfg.get("filters", {}).get("min_valid_factors", 2)
        # 只用实际加载的因子来计数（避免不存在的因子全为 NaN 导致过滤掉所有股票）
        avail_factor_cols = [f for f in factors_to_load if f in df.columns]
        if len(avail_factor_cols) < min_valid:
            # 如果可用因子太少，降低阈值
            min_valid = max(1, len(avail_factor_cols) - 1)
        valid_counts = df[avail_factor_cols].notna().sum(axis=1)
        df = df[valid_counts >= min_valid].copy()
        after_filter = len(df)

        if df.empty:
            return _clean_nan({
                "success": True,
                "stocks": [],
                "meta": {
                    "scan_date": date, "pool": pool,
                    "total_scanned": int(total_scanned),
                    "after_pool": int(after_pool),
                    "after_filter": int(after_filter),
                    "top_n": top_n, "final_count": 0,
                },
            })

        # 5. 加载股票名称和行业
        conn = sqlite3.connect(DB_PATH)
        try:
            df_names = pd.read_sql("""
                SELECT ts_code, name, industry, market
                FROM stock_list
            """, conn)
        finally:
            conn.close()
        df = df.merge(df_names, on="ts_code", how="left")
        df["name"] = df["name"].fillna("未知")
        df["industry"] = df["industry"].fillna("未分类")

        # 6. 计算共振评分
        df_idx = df.set_index("ts_code")
        res = engine.compute_resonance(df_idx)
        df_res = res.reset_index()

        # 合并回股票信息
        df_out = df_res.merge(
            df[["ts_code", "name", "industry", "market"]], on="ts_code", how="left"
        )

        # 7. 排序取 Top-N
        df_out = df_out.sort_values("resonance_score", ascending=False).head(top_n).copy()
        df_out["rank"] = range(1, len(df_out) + 1)

        # 8. 等级分布统计
        level_counts = res["resonance_level"].value_counts().to_dict()
        level_dist = {
            "strong": int(level_counts.get("strong", 0)),
            "medium": int(level_counts.get("medium", 0)),
            "weak": int(level_counts.get("weak", 0)),
            "none": int(level_counts.get("none", 0)),
        }

        # 9. 组装返回
        stocks = []
        for _, row in df_out.iterrows():
            dim_scores = {
                dim: round(float(row[f"{dim}_score"]), 6)
                if pd.notna(row[f"{dim}_score"]) else None
                for dim in engine.DIMENSION_NAMES
            }
            stock_item = {
                "ts_code": str(row["ts_code"]),
                "name": str(row.get("name", "未知")),
                "industry": str(row.get("industry", "未分类")),
                "market": str(row.get("market", "")),
                "rank": int(row["rank"]),
                "resonance_score": round(float(row["resonance_score"]), 6),
                "resonance_level": str(row["resonance_level"]),
                "position_low": round(float(row["position_low"]), 4),
                "position_high": round(float(row["position_high"]), 4),
                "dimension_scores": dim_scores,
                "dimension_labels": engine.DIMENSION_LABELS,
            }
            stocks.append(stock_item)

        meta = {
            "model_name": cfg.get("model_name", ""),
            "model_version": cfg.get("model_version", ""),
            "scan_date": str(date),
            "pool": pool,
            "total_scanned": int(total_scanned),
            "after_pool": int(after_pool),
            "after_filter": int(after_filter),
            "final_count": len(stocks),
            "top_n": top_n,
            "level_distribution": level_dist,
            "dimension_weights": engine.dimension_weights,
            "use_neutral": use_neutral,
        }

        # 10. 写入历史表
        try:
            written = _save_scan_history(stocks, str(date))
            meta["history_written"] = written
        except Exception:
            meta["history_written"] = 0

        return _clean_nan({
            "success": True,
            "stocks": stocks,
            "meta": meta,
        })

    except Exception as e:
        _logger.error(f"get_resonance_scan error: {e}", exc_info=True)
        import traceback
        return {
            "success": False,
            "error": str(e),
            "trace": traceback.format_exc(),
            "stocks": [],
            "meta": {},
        }


# ═══════════════════════════════════════════
#  单股票共振详情
# ═══════════════════════════════════════════

def get_resonance_detail(
    ts_code: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """单只股票的四维详情 + 雷达图数据 + 历史共振等级变化

    Parameters
    ----------
    ts_code : str
        股票代码。
    date : str, optional
        参考日期，默认最新有数据的日期。
    """
    try:
        cfg = _load_config()
        engine = ResonanceEngine(config=cfg)

        # 1. 确定日期
        if not date:
            date = _resolve_scan_date(engine.all_factors)
        if not date:
            return {"success": False, "error": "无因子数据", "data": {}}

        # 2. 加载近 90 天数据（用于历史变化）—— 智能回退
        loader = FactorDataLoader()
        dt = datetime.datetime.strptime(date, "%Y%m%d")
        start = (dt - datetime.timedelta(days=90)).strftime("%Y%m%d")
        all_df, factors_loaded = _safe_load_factors(engine, loader, start, date)
        if all_df.empty:
            return {"success": False, "error": f"无 {ts_code} 的因子数据", "data": {}}

        df_stock = all_df[all_df["ts_code"] == ts_code].copy()
        if df_stock.empty:
            return {"success": False, "error": f"未找到 {ts_code} 的因子数据", "data": {}}

        # 3. 计算历史共振评分
        df_hist = df_stock.set_index(["trade_date", "ts_code"])
        # compute_resonance 支持多日面板（有 trade_date）
        df_for_res = df_stock.copy()
        res = engine.compute_resonance(df_for_res.set_index("ts_code"))

        # 处理多日数据：按日期分组计算
        daily_res = []
        for d, sub in df_stock.groupby("trade_date"):
            sub_idx = sub.set_index("ts_code")
            r = engine.compute_resonance(sub_idx)
            r["trade_date"] = d
            daily_res.append(r.reset_index())

        if daily_res:
            hist_df = pd.concat(daily_res, ignore_index=True)
            hist_df = hist_df.sort_values("trade_date")
        else:
            hist_df = pd.DataFrame()

        # 4. 最新一日的详情
        if hist_df.empty:
            return {"success": False, "error": "计算失败", "data": {}}

        latest = hist_df[hist_df["trade_date"] == date]
        if latest.empty:
            latest = hist_df.tail(1)
        latest_row = latest.iloc[0]

        # 5. 雷达图数据
        radar_data = []
        for dim in engine.DIMENSION_NAMES:
            score = latest_row.get(f"{dim}_score")
            radar_data.append({
                "dimension": dim,
                "label": engine.DIMENSION_LABELS.get(dim, dim),
                "score": round(float(score), 6) if pd.notna(score) else None,
                "fullMark": 1.0,
            })

        # 6. 历史共振等级变化（近 30 个交易日）
        history_trend = []
        if not hist_df.empty:
            recent = hist_df.tail(30)
            for _, row in recent.iterrows():
                history_trend.append({
                    "trade_date": str(row["trade_date"]),
                    "resonance_score": round(float(row["resonance_score"]), 6),
                    "resonance_level": str(row["resonance_level"]),
                })

        # 7. 股票基本信息
        conn = sqlite3.connect(DB_PATH)
        try:
            df_name = pd.read_sql(
                "SELECT ts_code, name, industry, market FROM stock_list WHERE ts_code = ?",
                conn, params=[ts_code]
            )
        finally:
            conn.close()
        name_info = df_name.iloc[0].to_dict() if not df_name.empty else {}

        # 各因子原始值
        latest_factor_df = df_stock[df_stock["trade_date"] == date]
        factor_details = {}
        if not latest_factor_df.empty:
            fr = latest_factor_df.iloc[0]
            for dim in engine.DIMENSION_NAMES:
                dim_factors = engine.dimensions[dim]["factors"]
                dim_weights = engine.dimensions[dim]["weights"]
                factor_details[dim] = []
                for f, w in zip(dim_factors, dim_weights):
                    meta = FACTOR_REGISTRY.get(f)
                    raw_val = fr.get(f) if f in fr.index else None
                    factor_details[dim].append({
                        "factor": f,
                        "raw": round(float(raw_val), 6) if pd.notna(raw_val) else None,
                        "direction": meta.direction if meta else 1,
                        "weight": round(w, 4),
                        "description": meta.description if meta else "",
                    })

        return _clean_nan({
            "success": True,
            "data": {
                "ts_code": ts_code,
                "name": name_info.get("name", "未知"),
                "industry": name_info.get("industry", "未分类"),
                "market": name_info.get("market", ""),
                "trade_date": str(date),
                "resonance_score": round(float(latest_row["resonance_score"]), 6),
                "resonance_level": str(latest_row["resonance_level"]),
                "position_low": round(float(latest_row["position_low"]), 4),
                "position_high": round(float(latest_row["position_high"]), 4),
                "dimension_scores": {
                    dim: round(float(latest_row[f"{dim}_score"]), 6)
                    if pd.notna(latest_row[f"{dim}_score"]) else None
                    for dim in engine.DIMENSION_NAMES
                },
                "dimension_labels": engine.DIMENSION_LABELS,
                "radar_data": radar_data,
                "history_trend": history_trend,
                "factor_details": factor_details,
            },
        })

    except Exception as e:
        _logger.error(f"get_resonance_detail error: {e}", exc_info=True)
        return {"success": False, "error": str(e), "data": {}}


# ═══════════════════════════════════════════
#  卖出信号检查
# ═══════════════════════════════════════════

def get_sell_signals(
    ts_code: str,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """单只股票的 3 条卖出信号检查结果

    Parameters
    ----------
    ts_code : str
        股票代码。
    date : str, optional
        检查日期，默认最新有数据的日期。
    """
    try:
        cfg = _load_config()
        engine = ResonanceEngine(config=cfg)
        sell_engine = SellSignalEngine(resonance_engine=engine)

        # 1. 确定日期
        if not date:
            date = _resolve_scan_date(engine.all_factors)
        if not date:
            return {"success": False, "error": "无因子数据", "data": {}}

        # 2. 加载近 60 天的因子 + 价格数据
        dt = datetime.datetime.strptime(date, "%Y%m%d")
        start = (dt - datetime.timedelta(days=90)).strftime("%Y%m%d")

        loader = FactorDataLoader()

        # 因子数据 —— 智能回退：只加载存在的因子
        avail_factors = engine._get_available_factors("factor_values")
        avail_factors_evo = engine._get_available_factors("factor_values_evo")
        factors_needed = [f for f in engine.all_factors if f in avail_factors or f in avail_factors_evo]
        # 额外加 surprise_earnings_gap 用于铁律①（如果存在）
        for f in ["surprise_earnings_gap"]:
            if f not in factors_needed and (f in avail_factors or f in avail_factors_evo):
                factors_needed.append(f)

        if factors_needed:
            factor_df = loader.load_factor_values(
                factors_needed, start_date=start, end_date=date
            )
        else:
            factor_df = pd.DataFrame()

        # 价格数据
        price_df = loader.load_daily_prices(start_date=start, end_date=date)
        price_df = price_df[price_df["ts_code"] == ts_code].copy()

        # 合并
        stock_factor = factor_df[factor_df["ts_code"] == ts_code].copy()
        if stock_factor.empty and price_df.empty:
            return {"success": False, "error": f"无 {ts_code} 的数据", "data": {}}

        # 合并因子和价格
        if not stock_factor.empty and not price_df.empty:
            merged = stock_factor.merge(
                price_df[["ts_code", "trade_date", "close_adj", "close", "pct_chg"]],
                on=["ts_code", "trade_date"], how="outer"
            )
        elif not stock_factor.empty:
            merged = stock_factor.copy()
            merged["close_adj"] = np.nan
            merged["close"] = np.nan
            merged["pct_chg"] = np.nan
        else:
            merged = price_df.copy()

        merged = merged.sort_values("trade_date").reset_index(drop=True)

        # 3. 检查 3 条信号
        result = sell_engine.get_all_signals(merged, date)

        # 4. 股票基本信息
        conn = sqlite3.connect(DB_PATH)
        try:
            df_name = pd.read_sql(
                "SELECT ts_code, name, industry, market FROM stock_list WHERE ts_code = ?",
                conn, params=[ts_code]
            )
        finally:
            conn.close()
        name_info = df_name.iloc[0].to_dict() if not df_name.empty else {}

        return _clean_nan({
            "success": True,
            "data": {
                "ts_code": ts_code,
                "name": name_info.get("name", "未知"),
                "industry": name_info.get("industry", "未分类"),
                "market": name_info.get("market", ""),
                "trade_date": str(date),
                "top_signal": result.get("top_signal"),
                "top_level": result.get("top_level"),
                "triggered_count": result.get("triggered_count", 0),
                "signals": result.get("signals", []),
                "details": result.get("details", {}),
            },
        })

    except Exception as e:
        _logger.error(f"get_sell_signals error: {e}", exc_info=True)
        import traceback
        return {
            "success": False,
            "error": str(e),
            "trace": traceback.format_exc(),
            "data": {},
        }


# ═══════════════════════════════════════════
#  共振扫描历史
# ═══════════════════════════════════════════

def get_resonance_history(days: int = 30) -> Dict[str, Any]:
    """近 N 天的共振扫描历史

    Parameters
    ----------
    days : int
        查询最近 N 天。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            _ensure_history_table(conn)

            date_from = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")

            df = pd.read_sql(
                f"SELECT * FROM {_HISTORY_TABLE} WHERE scan_date >= ? "
                f"ORDER BY scan_date DESC, rank ASC",
                conn, params=[date_from]
            )

            if df.empty:
                return _clean_nan({
                    "success": True,
                    "daily": {},
                    "dates": [],
                    "meta": {
                        "days": days, "total_records": 0,
                        "scan_days": 0, "unique_stocks": 0,
                    },
                })

            all_dates = sorted(df["scan_date"].unique().tolist(), reverse=True)
            daily = {}
            for d in all_dates:
                day_df = df[df["scan_date"] == d].copy()
                daily[d] = day_df.to_dict(orient="records")

            # 等级分布（按日期）
            level_by_date = {}
            for d in all_dates:
                day_df = df[df["scan_date"] == d]
                lc = day_df["resonance_level"].value_counts().to_dict()
                level_by_date[d] = {
                    "strong": int(lc.get("strong", 0)),
                    "medium": int(lc.get("medium", 0)),
                    "weak": int(lc.get("weak", 0)),
                    "none": int(lc.get("none", 0)),
                }

            return _clean_nan({
                "success": True,
                "daily": daily,
                "dates": all_dates,
                "level_by_date": level_by_date,
                "meta": {
                    "days": days,
                    "total_records": len(df),
                    "scan_days": len(all_dates),
                    "unique_stocks": int(df["ts_code"].nunique()),
                    "date_latest": str(all_dates[0]) if all_dates else "",
                },
            })
        finally:
            conn.close()
    except Exception as e:
        _logger.error(f"get_resonance_history error: {e}")
        return {"success": False, "error": str(e), "daily": {}, "dates": [], "meta": {}}


# ═══════════════════════════════════════════
#  四维 IC 表现对比
# ═══════════════════════════════════════════

def get_dimension_ic(days: int = 60) -> Dict[str, Any]:
    """四维各自的 IC 表现对比

    计算每个维度得分与未来 5 日收益的 Rank IC，
    返回各维度的 IC 均值、ICIR、胜率等指标。

    Parameters
    ----------
    days : int
        回看天数。
    """
    try:
        cfg = _load_config()
        engine = ResonanceEngine(config=cfg)

        # 1. 确定日期范围
        end_date = _resolve_scan_date(engine.all_factors)
        if not end_date:
            return {"success": False, "error": "无因子数据", "data": []}

        dt = datetime.datetime.strptime(end_date, "%Y%m%d")
        start_date = (dt - datetime.timedelta(days=days + 20)).strftime("%Y%m%d")

        # 2. 加载因子 + 价格数据 —— 智能回退
        loader = FactorDataLoader()
        df, factors_loaded = _safe_load_factors(engine, loader, start_date, end_date)
        if df.empty:
            return {"success": False, "error": "无因子数据", "data": []}

        # 3. 计算未来 5 日收益
        df = loader.compute_forward_returns(df, periods=[5])
        return_col = "fwd_ret_5d"

        if return_col not in df.columns:
            return {"success": False, "error": "无法计算未来收益", "data": []}

        # 4. 对每个维度计算维度分，然后算 IC
        dim_ic_results = {}
        for dim in engine.DIMENSION_NAMES:
            try:
                # 直接用维度内的因子合成维度分（利用 compute_dimension_scores）
                # 先构造一个临时引擎只含这一维
                dim_factors = engine.dimensions[dim]["factors"]
                dim_weights = engine.dimensions[dim]["weights"]

                # 方向对齐 + 排名归一化 + 加权
                df_dim = df.copy()
                for f in dim_factors:
                    meta = FACTOR_REGISTRY.get(f)
                    direction = meta.direction if meta else 1
                    if f in df_dim.columns:
                        df_dim[f] = df_dim[f] * direction

                # 截面排名
                for f in dim_factors:
                    if f in df_dim.columns:
                        df_dim[f] = df_dim.groupby("trade_date")[f].rank(pct=True)

                # 加权
                df_dim["_dim_score"] = 0.0
                w_sum = sum(dim_weights)
                for f, w in zip(dim_factors, dim_weights):
                    if f in df_dim.columns:
                        df_dim["_dim_score"] += df_dim[f].fillna(0) * (w / w_sum if w_sum > 0 else 1.0 / len(dim_factors))

                # 计算每日 IC
                daily_ic = df_dim.groupby("trade_date").apply(
                    lambda g: g["_dim_score"].corr(g[return_col], method="spearman")
                ).dropna()

                if len(daily_ic) > 0:
                    ic_mean = float(daily_ic.mean())
                    ic_std = float(daily_ic.std()) if daily_ic.std() > 0 else 1e-6
                    icir = ic_mean / ic_std
                    win_rate = float((daily_ic > 0).sum() / len(daily_ic))

                    dim_ic_results[dim] = {
                        "label": engine.DIMENSION_LABELS.get(dim, dim),
                        "ic_mean": round(ic_mean, 6),
                        "ic_std": round(ic_std, 6),
                        "icir": round(icir, 4),
                        "win_rate": round(win_rate, 4),
                        "sample_days": len(daily_ic),
                        "factors": dim_factors,
                    }
                else:
                    dim_ic_results[dim] = {
                        "label": engine.DIMENSION_LABELS.get(dim, dim),
                        "ic_mean": None, "ic_std": None,
                        "icir": None, "win_rate": None,
                        "sample_days": 0,
                        "factors": dim_factors,
                    }
            except Exception as e:
                dim_ic_results[dim] = {
                    "label": engine.DIMENSION_LABELS.get(dim, dim),
                    "error": str(e),
                    "factors": engine.dimensions[dim]["factors"],
                }

        # 总共振分的 IC
        try:
            df_res = engine.compute_resonance(df.set_index(["trade_date", "ts_code"]))
            # 注意：compute_resonance 在面板数据上的处理
            # 简化：直接用各维度加权
            total_score = pd.Series(0.0, index=df.index)
            for dim in engine.DIMENSION_NAMES:
                w = engine.dimension_weights.get(dim, 0)
                if dim in dim_ic_results and dim_ic_results[dim].get("ic_mean") is not None:
                    # 重新计算维度分
                    pass

            # 用更准确的方式：逐天计算
            daily_total_ic = []
            for d, sub in df.groupby("trade_date"):
                try:
                    sub_idx = sub.set_index("ts_code")
                    res_d = engine.compute_resonance(sub_idx)
                    if return_col in sub.columns:
                        # 对齐收益
                        ret_s = sub.set_index("ts_code")[return_col]
                        common = res_d.index.intersection(ret_s.index)
                        if len(common) >= 20:
                            ic_val = res_d.loc[common, "resonance_score"].corr(
                                ret_s.loc[common], method="spearman"
                            )
                            if pd.notna(ic_val):
                                daily_total_ic.append((d, ic_val))
                except Exception:
                    pass

            if daily_total_ic:
                ic_vals = [v for _, v in daily_total_ic]
                ic_mean = float(np.mean(ic_vals))
                ic_std = float(np.std(ic_vals)) if np.std(ic_vals) > 0 else 1e-6
                icir = ic_mean / ic_std
                win_rate = float(sum(1 for v in ic_vals if v > 0) / len(ic_vals))

                total_ic = {
                    "label": "共振总分",
                    "ic_mean": round(ic_mean, 6),
                    "ic_std": round(ic_std, 6),
                    "icir": round(icir, 4),
                    "win_rate": round(win_rate, 4),
                    "sample_days": len(daily_total_ic),
                }
            else:
                total_ic = {
                    "label": "共振总分",
                    "ic_mean": None, "ic_std": None,
                    "icir": None, "win_rate": None,
                    "sample_days": 0,
                }
        except Exception as e:
            total_ic = {"label": "共振总分", "error": str(e)}

        return _clean_nan({
            "success": True,
            "data": {
                "dimensions": dim_ic_results,
                "total": total_ic,
            },
            "meta": {
                "days": days,
                "start_date": start_date,
                "end_date": end_date,
                "return_period": "5d",
            },
        })

    except Exception as e:
        _logger.error(f"get_dimension_ic error: {e}", exc_info=True)
        import traceback
        return {
            "success": False,
            "error": str(e),
            "trace": traceback.format_exc(),
            "data": {},
            "meta": {},
        }
