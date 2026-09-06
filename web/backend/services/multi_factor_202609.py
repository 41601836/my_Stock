# -*- coding: utf-8 -*-
"""
services.multi_factor_202609 —— 202609 多因子分析服务
=====================================================
基于 5 个独立因子 + 排名平均法的截面扫描服务。

⚠️ 零侵入原则：
1. 只读 factor_values / daily_prices / stock_list 表，仅写入 mf202609_history 表
2. 不 import 任何经典层扫描器代码
3. 删除本文件 + 路由注册即回滚

API:
- /api/mf202609/scan              最新截面多因子扫描（Top-N，自动写历史）
- /api/mf202609/config            模型配置信息
- /api/mf202609/stock/{code}      单股票因子明细
- /api/mf202609/history/daily     每日快照（按日期分组）
- /api/mf202609/history/streak    连续上榜天数排行
- /api/mf202609/history/frequency 上榜频率排行
- /api/mf202609/history/cumulative 累计统计
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

from factor_lib.registry import FACTOR_REGISTRY
from factor_lib.multi_factor import MultiFactorCombiner
from factor_lib.loader import FactorDataLoader

_logger = logging.getLogger("services.multi_factor_202609")

CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "multi_factor_202609.yaml")
DB_PATH = os.path.join(_PROJECT_ROOT, "db", "stock_data.db")


def _load_config() -> Dict[str, Any]:
    """加载模型配置"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# 选日回看窗口：只在近期找"全量截面"日期（与旧全量加载后 groupby 选日的口径一致）
_SCAN_DATE_LOOKBACK_DAYS = 120


def _resolve_scan_date(factors: List[str]) -> str:
    """
    轻量定位最新"全量"截面日期（性能优化，替代全量加载后的选日）。

    旧逻辑：全量加载 300 万+ 行 → groupby(trade_date).size() → 取行数 ≥ 80%*最大值 的最新日期。
    新逻辑：直接对因子源表按 trade_date 单列 GROUP BY 计数（毫秒级），
    多表时按日期 inner 对齐取 min 计数，口径与 INNER JOIN 合并后一致。
    """
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


def get_model_config() -> Dict[str, Any]:
    """获取模型配置信息"""
    try:
        cfg = _load_config()
        factor_list = []
        for f in cfg.get("factors", []):
            meta = FACTOR_REGISTRY.get(f["name"])
            f_info = dict(f)
            if meta:
                f_info["direction"] = meta.direction
                f_info["data_source"] = meta.table
            factor_list.append(f_info)

        return _clean_nan({
            "success": True,
            "model_name": cfg.get("model_name", ""),
            "model_version": cfg.get("model_version", ""),
            "method": cfg.get("method", ""),
            "top_n": cfg.get("top_n", 20),
            "factors": factor_list,
            "factor_count": len(factor_list),
        })
    except Exception as e:
        _logger.error(f"get_model_config error: {e}")
        return {"success": False, "error": str(e)}


def run_multi_factor_scan(top_n: Optional[int] = None) -> Dict[str, Any]:
    """
    运行多因子截面扫描，返回 Top-N 股票列表。

    流程:
    1. 读取配置 → 获取 5 个因子
    2. 从 factor_values 加载最新截面因子值
    3. 关联 stock_list 获取股票名称、行业
    4. MultiFactorCombiner.rank_average 合成得分
    5. 排序取 Top-N
    6. 返回 JSON
    """
    try:
        cfg = _load_config()
        factors = [f["name"] for f in cfg.get("factors", [])]
        method = cfg.get("method", "rank_average")
        config_top_n = cfg.get("top_n", 20)
        top_n = top_n or config_top_n

        # 1. 使用 factor_lib loader 统一加载因子值（自动处理 factor_values + factor_values_evo）
        # 性能优化：先轻量定位最新全量截面日期，再单日加载（避免全量加载 300 万+ 行）
        loader = FactorDataLoader()
        trade_date = _resolve_scan_date(factors)
        if not trade_date:
            return {"success": False, "error": "无因子数据", "stocks": [], "meta": {}}

        all_df = loader.load_factor_values(factors, start_date=trade_date, end_date=trade_date)
        if all_df.empty:
            return {"success": False, "error": "无因子数据", "stocks": [], "meta": {}}

        df = all_df.copy()
        total_scanned = len(df)

        if df.empty:
            return {"success": False, "error": f"{trade_date} 无因子数据", "stocks": [], "meta": {}}

        # 2. 过滤：至少 min_valid_factors 个因子有值
        min_valid = cfg.get("min_valid_factors", 3)
        valid_counts = df[factors].notna().sum(axis=1)
        df = df[valid_counts >= min_valid].copy()
        after_filter = len(df)

        # 3. 加载股票名称和行业
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

        # 4. 多因子合成（rank_average 方法：方向对齐 → 排名归一化 → 等权求和 → 再次排名）
        factor_metas = {f: FACTOR_REGISTRY[f] for f in factors if f in FACTOR_REGISTRY}
        combiner = MultiFactorCombiner(factor_metas, method=method)

        # 添加伪收益列（rank_average 不依赖收益，但 compute_weights 会用到）
        # 对于 rank_average，权重是等权的，所以收益列不影响结果
        df["_dummy_ret"] = 0.0

        df = combiner.combine(df, factors, return_col="_dummy_ret", output_col="composite_score")
        weights = combiner.get_weights()

        # 5. 排序取 Top-N
        df = df.sort_values("composite_score", ascending=False).head(top_n).copy()
        df["rank"] = range(1, len(df) + 1)

        # 6. 构造返回列表
        stocks = []
        for _, row in df.iterrows():
            # 各因子原始值 + 排名百分位
            factor_details = {}
            for f in factors:
                raw_val = row.get(f)
                factor_details[f] = {
                    "raw": round(float(raw_val), 6) if pd.notna(raw_val) else None,
                    "direction": factor_metas[f].direction if f in factor_metas else 1,
                    "weight": round(weights.get(f, 0), 4),
                }

            stock_item = {
                "ts_code": str(row["ts_code"]),
                "name": str(row["name"]),
                "industry": str(row.get("industry", "未分类")),
                "market": str(row.get("market", "")),
                "rank": int(row["rank"]),
                "composite_score": round(float(row["composite_score"]), 6),
                "factor_details": factor_details,
            }
            stocks.append(stock_item)

        meta = {
            "model_name": cfg.get("model_name", ""),
            "model_version": cfg.get("model_version", ""),
            "method": method,
            "scan_date": str(trade_date),
            "factor_date": str(trade_date),
            "total_scanned": int(total_scanned),
            "after_filter": int(after_filter),
            "final_count": len(stocks),
            "top_n": top_n,
            "factor_count": len(factors),
            "factors": factors,
            "weights": {k: round(v, 4) for k, v in weights.items()},
        }

        # 7. 写入历史表（异步不影响主流程，异常静默）
        try:
            written = _save_scan_history(stocks, str(trade_date))
            meta["history_written"] = written
        except Exception:
            meta["history_written"] = 0

        return _clean_nan({
            "success": True,
            "stocks": stocks,
            "meta": meta,
        })

    except Exception as e:
        _logger.error(f"run_multi_factor_scan error: {e}", exc_info=True)
        import traceback
        return {
            "success": False,
            "error": str(e),
            "trace": traceback.format_exc(),
            "stocks": [],
            "meta": {},
        }


# ═══════════════════════════════════════════════════════════
# 历史记录：建表 + 保存 + 查询
# ═══════════════════════════════════════════════════════════

_HISTORY_TABLE = "mf202609_history"


def _ensure_history_table(conn):
    """确保 mf202609_history 表存在（首次运行自动创建）"""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_HISTORY_TABLE} (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date       TEXT    NOT NULL,
            ts_code         TEXT    NOT NULL,
            name            TEXT,
            industry        TEXT,
            market          TEXT,
            rank            INTEGER,
            composite_score REAL,
            UNIQUE(scan_date, ts_code)
        )
    """)
    conn.commit()


def _save_scan_history(stocks: list, scan_date: str) -> int:
    """
    将扫描结果写入历史表（同日同股去重，INSERT OR IGNORE）。
    返回写入条数。
    """
    if not stocks:
        return 0
    conn = sqlite3.connect(DB_PATH)
    try:
        _ensure_history_table(conn)
        rows = []
        for s in stocks:
            rows.append((
                scan_date,
                s.get("ts_code", ""),
                s.get("name", ""),
                s.get("industry", ""),
                s.get("market", ""),
                int(s.get("rank", 0)),
                float(s.get("composite_score", 0.0)),
            ))
        conn.executemany(
            f"INSERT OR IGNORE INTO {_HISTORY_TABLE} "
            f"(scan_date, ts_code, name, industry, market, rank, composite_score) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows
        )
        conn.commit()
        return conn.total_changes
    except Exception as e:
        _logger.error(f"save history error: {e}")
        return 0
    finally:
        conn.close()


def get_history_daily(days: int = 30, top_n_per_day: int = 0) -> Dict[str, Any]:
    """
    每日快照：按日期分组的上榜股票列表（从新到旧）。

    参数:
        days: 查询最近 N 天
        top_n_per_day: 只取每日 rank <= N 的记录（0 = 不限）
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            _ensure_history_table(conn)

            date_from = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")

            where_clauses = ["scan_date >= ?"]
            params = [date_from]
            if top_n_per_day and int(top_n_per_day) > 0:
                where_clauses.append(f"rank <= {int(top_n_per_day)}")
            where_sql = " AND ".join(where_clauses)

            df = pd.read_sql(
                f"SELECT * FROM {_HISTORY_TABLE} WHERE {where_sql} "
                f"ORDER BY scan_date DESC, rank ASC",
                conn, params=params
            )

            if df.empty:
                return _clean_nan({
                    "success": True,
                    "daily": {},
                    "dates": [],
                    "meta": {
                        "days": days, "top_n_per_day": top_n_per_day,
                        "total_records": 0, "scan_days": 0,
                        "unique_stocks": 0, "date_latest": "",
                    },
                })

            all_dates = sorted(df["scan_date"].unique().tolist(), reverse=True)
            daily = {}
            for d in all_dates:
                day_df = df[df["scan_date"] == d].copy()
                daily[d] = day_df.to_dict(orient="records")

            return _clean_nan({
                "success": True,
                "daily": daily,
                "dates": all_dates,
                "meta": {
                    "days": days,
                    "top_n_per_day": top_n_per_day,
                    "total_records": len(df),
                    "scan_days": len(all_dates),
                    "unique_stocks": int(df["ts_code"].nunique()),
                    "date_latest": str(all_dates[0]) if all_dates else "",
                },
            })
        finally:
            conn.close()
    except Exception as e:
        _logger.error(f"get_history_daily error: {e}")
        return {"success": False, "error": str(e), "daily": {}, "dates": [], "meta": {}}


def get_history_streak(days: int = 30, min_streak: int = 2) -> Dict[str, Any]:
    """
    连续上榜天数排行：从最新日期向前数，连续出现在榜单上的天数。

    参数:
        days: 查询最近 N 天
        min_streak: 最少连续天数（默认 2 天才上榜）
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            _ensure_history_table(conn)

            date_from = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")
            df = pd.read_sql(
                f"SELECT * FROM {_HISTORY_TABLE} WHERE scan_date >= ? ORDER BY scan_date DESC, rank ASC",
                conn, params=[date_from]
            )

            if df.empty:
                return _clean_nan({
                    "success": True, "stocks": [],
                    "meta": {"days": days, "min_streak": min_streak, "total": 0},
                })

            all_dates = sorted(df["scan_date"].unique().tolist(), reverse=True)
            streak_map = {}
            for stock in df["ts_code"].unique():
                stock_dates = set(df[df["ts_code"] == stock]["scan_date"].tolist())
                streak = 0
                for d in all_dates:
                    if d in stock_dates:
                        streak += 1
                    else:
                        break
                streak_map[stock] = streak

            streak_df = df[["ts_code", "name", "industry"]].drop_duplicates("ts_code").copy()
            streak_df["streak_days"] = streak_df["ts_code"].map(streak_map)
            streak_df = streak_df[streak_df["streak_days"] >= min_streak]
            streak_df = streak_df.sort_values(["streak_days", "ts_code"], ascending=[False, True])

            # 附加：最新排名、最新得分
            latest_date = all_dates[0] if all_dates else ""
            latest_df = df[df["scan_date"] == latest_date][["ts_code", "rank", "composite_score"]].copy()
            streak_df = streak_df.merge(latest_df, on="ts_code", how="left")
            streak_df = streak_df.rename(columns={"rank": "latest_rank", "composite_score": "latest_score"})

            return _clean_nan({
                "success": True,
                "stocks": streak_df.to_dict(orient="records"),
                "meta": {
                    "days": days,
                    "min_streak": min_streak,
                    "total": len(streak_df),
                    "date_latest": latest_date,
                },
            })
        finally:
            conn.close()
    except Exception as e:
        _logger.error(f"get_history_streak error: {e}")
        return {"success": False, "error": str(e), "stocks": [], "meta": {}}


def get_history_frequency(days: int = 30, min_appear: int = 1) -> Dict[str, Any]:
    """
    上榜频率排行：按上榜次数降序排列。

    参数:
        days: 查询最近 N 天
        min_appear: 最少上榜次数才纳入
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            _ensure_history_table(conn)

            date_from = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")
            df = pd.read_sql(
                f"SELECT * FROM {_HISTORY_TABLE} WHERE scan_date >= ? ORDER BY scan_date DESC",
                conn, params=[date_from]
            )

            if df.empty:
                return _clean_nan({
                    "success": True, "stocks": [],
                    "meta": {"days": days, "min_appear": min_appear, "total": 0},
                })

            # 聚合统计
            grp = df.groupby("ts_code").agg(
                name=("name", "last"),
                industry=("industry", "last"),
                appear_count=("scan_date", "count"),
                avg_rank=("rank", "mean"),
                best_rank=("rank", "min"),
                avg_score=("composite_score", "mean"),
                last_date=("scan_date", "max"),
            ).reset_index()

            # 最新排名
            last_rank_rows = []
            for c, sub in df.groupby("ts_code"):
                m_idx = sub["scan_date"].idxmax()
                last_rank_rows.append({
                    "ts_code": c,
                    "latest_rank": int(sub.loc[m_idx, "rank"]),
                    "latest_score": float(sub.loc[m_idx, "composite_score"]),
                })
            lr_df = pd.DataFrame(last_rank_rows)
            if not lr_df.empty:
                grp = grp.merge(lr_df, on="ts_code", how="left")

            grp = grp[grp["appear_count"] >= int(min_appear)]
            grp = grp.sort_values(["appear_count", "avg_rank"], ascending=[False, True])
            grp["avg_rank"] = grp["avg_rank"].round(1)
            grp["avg_score"] = grp["avg_score"].round(4)
            grp["latest_score"] = grp["latest_score"].round(4)

            return _clean_nan({
                "success": True,
                "stocks": grp.to_dict(orient="records"),
                "meta": {
                    "days": days,
                    "min_appear": min_appear,
                    "total": len(grp),
                    "date_latest": str(df["scan_date"].max()),
                },
            })
        finally:
            conn.close()
    except Exception as e:
        _logger.error(f"get_history_frequency error: {e}")
        return {"success": False, "error": str(e), "stocks": [], "meta": {}}


def get_history_cumulative(days: int = 30) -> Dict[str, Any]:
    """
    累计统计：整体扫描情况的汇总数据。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            _ensure_history_table(conn)

            date_from = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")
            df = pd.read_sql(
                f"SELECT * FROM {_HISTORY_TABLE} WHERE scan_date >= ?",
                conn, params=[date_from]
            )

            if df.empty:
                return _clean_nan({
                    "success": True,
                    "stats": {
                        "total_records": 0, "scan_days": 0, "unique_stocks": 0,
                        "avg_per_day": 0, "top_streak": 0,
                    },
                    "rank_distribution": {},
                    "industry_top": [],
                    "meta": {"days": days},
                })

            all_dates = sorted(df["scan_date"].unique().tolist())
            total_records = len(df)
            scan_days = len(all_dates)
            unique_stocks = int(df["ts_code"].nunique())
            avg_per_day = round(total_records / scan_days, 1) if scan_days > 0 else 0

            # 最长连续上榜天数
            streak_map = {}
            for stock in df["ts_code"].unique():
                stock_dates = sorted(df[df["ts_code"] == stock]["scan_date"].unique().tolist())
                max_streak = 0
                cur_streak = 0
                prev_idx = -1
                date_set = set(stock_dates)
                # 用全部日期计算最长连续
                for i, d in enumerate(all_dates):
                    if d in date_set:
                        cur_streak += 1
                        max_streak = max(max_streak, cur_streak)
                    else:
                        cur_streak = 0
                streak_map[stock] = max_streak
            top_streak = max(streak_map.values()) if streak_map else 0

            # 排名分布（Top1 / Top3 / Top5 / Top10 / Top20）
            rank_bins = {
                "top1":   int((df["rank"] <= 1).sum()),
                "top3":   int((df["rank"] <= 3).sum()),
                "top5":   int((df["rank"] <= 5).sum()),
                "top10":  int((df["rank"] <= 10).sum()),
                "top20":  int((df["rank"] <= 20).sum()),
            }

            # 行业上榜 TOP
            industry_grp = df.groupby("industry").agg(
                appear_count=("ts_code", "count"),
                unique_stocks=("ts_code", "nunique"),
                avg_rank=("rank", "mean"),
            ).reset_index()
            industry_grp = industry_grp.sort_values("appear_count", ascending=False).head(10)
            industry_grp["avg_rank"] = industry_grp["avg_rank"].round(1)
            industry_top = industry_grp.to_dict(orient="records")

            return _clean_nan({
                "success": True,
                "stats": {
                    "total_records": total_records,
                    "scan_days": scan_days,
                    "unique_stocks": unique_stocks,
                    "avg_per_day": avg_per_day,
                    "top_streak": top_streak,
                    "date_from": str(all_dates[0]) if all_dates else "",
                    "date_latest": str(all_dates[-1]) if all_dates else "",
                },
                "rank_distribution": rank_bins,
                "industry_top": industry_top,
                "meta": {"days": days},
            })
        finally:
            conn.close()
    except Exception as e:
        _logger.error(f"get_history_cumulative error: {e}")
        return {"success": False, "error": str(e), "stats": {}, "rank_distribution": {}, "industry_top": [], "meta": {}}


def get_stock_factor_detail(ts_code: str) -> Dict[str, Any]:
    """获取单只股票的因子明细（最近截面）"""
    try:
        cfg = _load_config()
        factors = [f["name"] for f in cfg.get("factors", [])]

        # 使用 loader 加载（自动处理多表）；同 scan：先选日再单日加载
        loader = FactorDataLoader()
        trade_date = _resolve_scan_date(factors)
        if not trade_date:
            return {"success": False, "error": "无因子数据", "data": {}}

        all_df = loader.load_factor_values(factors, start_date=trade_date, end_date=trade_date)
        if all_df.empty:
            return {"success": False, "error": "无因子数据", "data": {}}

        df = all_df[all_df["ts_code"] == ts_code].copy()
        if df.empty:
            return {"success": False, "error": f"未找到 {ts_code} 的因子数据", "data": {}}

        row = df.iloc[0]
        factor_metas = {f: FACTOR_REGISTRY[f] for f in factors if f in FACTOR_REGISTRY}

        factor_data = {}
        for f in factors:
            val = row.get(f)
            meta = factor_metas.get(f)
            factor_data[f] = {
                "value": round(float(val), 6) if pd.notna(val) else None,
                "direction": meta.direction if meta else 1,
                "category": meta.category if meta else "",
                "description": meta.description if meta else "",
            }

        # 股票基本信息
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
                "trade_date": str(trade_date),
                "factors": factor_data,
            },
        })

    except Exception as e:
        _logger.error(f"get_stock_factor_detail error: {e}")
        return {"success": False, "error": str(e), "data": {}}
