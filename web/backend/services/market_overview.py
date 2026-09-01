# -*- coding: utf-8 -*-
"""
services.market_overview —— 市场概览 & 搜索 & 个股诊断 & 访客
* get_market_overview_data()   赚钱效应 + 板块资金流向 Top/Bottom 10 + 题材热度 Top10 + 行情快照
* search_stock()               ts_code / name / 拼音 模糊搜索
* diagnose_stock()             多维诊断：估值 / 技术 / 筹码 / 画像 / 近5日涨跌
* record_visitor()             访客日志（IP+UA+日期）
* get_visitor_stats()          访客计数 + 去重 IP
"""

import os
import json
import time
import math
import logging
import datetime
import pandas as pd
import numpy as np

from ._common import PROJECT_ROOT, DB_PATH, get_db_connection, clean_nan_inf
from ._common import _get_factor_date, get_diagnose_grade_cfg, get_hot_money_tracker_cfg  # S2：统一阈值
from .scanner import get_build_position_opportunities
from .market_regime import get_market_status
from .factors_assets import get_deployed_factors

_logger = logging.getLogger(__name__)


def safe_float(v, default=0.0):
    """模块级安全浮点转换（diagnose_stock 内另有局部同名函数，行为一致）"""
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _theme_signal(score: float) -> dict:
    """基于真实指标分数输出操盘信号标签（score 为真实数据的确定性映射）"""
    if score >= 80:
        return {"signal": "强烈追涨", "signal_color": "red"}
    if score >= 60:
        return {"signal": "可小仓位跟进", "signal_color": "orange"}
    if score >= 40:
        return {"signal": "重点关注", "signal_color": "green"}
    if score >= 20:
        return {"signal": "观察名单", "signal_color": "yellow"}
    return {"signal": "低波动", "signal_color": "gray"}


def get_market_overview_data():
    """Dashboard 主页：快照 + 赚钱效应 + 板块资金 + 题材热度 + 游资情绪"""
    start = time.time()
    result = {"error": None}
    try:
        conn = get_db_connection(DB_PATH)

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = {r[0] for r in cursor.fetchall()}

            def _max_date(table):
                if table in existing_tables:
                    try:
                        cursor.execute(f"SELECT MAX(trade_date) FROM {table}")
                        r = cursor.fetchone()
                        return str(r[0]) if r and r[0] else ""
                    except Exception:
                        return ""
                return ""

            latest_dates = {
                "daily_prices":       _max_date("daily_prices"),
                "daily_basic":        _max_date("daily_basic"),
                "moneyflow":          _max_date("moneyflow"),
                "factor_values":      _max_date("factor_values"),
                "stock_cyq_perf":     _max_date("stock_cyq_perf"),
                "limit_list_stocks":  _max_date("limit_list_stocks"),
            }
            result["latest_dates"] = latest_dates
            latest_price = latest_dates.get("daily_prices") or ""
            latest_factor = latest_dates.get("factor_values") or ""

            prev_dates = pd.read_sql(
                "SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 2", conn
            )["trade_date"].tolist()
            prev_price = prev_dates[1] if len(prev_dates) >= 2 else (prev_dates[0] if prev_dates else None)

            rows_list = []
            try:
                if latest_price:
                    mkt_snap = pd.read_sql("""
                        SELECT
                            COUNT(*) AS total_stocks,
                            SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END)    up_count,
                            SUM(CASE WHEN pct_chg = 0 THEN 1 ELSE 0 END)    flat_count,
                            SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END)    down_count,
                            SUM(CASE WHEN pct_chg >= 9.8 THEN 1 ELSE 0 END) up_limit_count,
                            SUM(CASE WHEN pct_chg <= -9.8 THEN 1 ELSE 0 END) down_limit_count,
                            SUM(CASE WHEN name LIKE '%ST%' AND pct_chg <= -4.9 THEN 1
                                     WHEN name LIKE '%ST%' AND pct_chg >= 4.9 THEN 0
                                     WHEN pct_chg <= -9.8 THEN 1 ELSE 0 END) AS real_down_limit,
                            AVG(pct_chg) avg_pct,
                            CAST(SUM(amount) AS FLOAT) total_amount
                        FROM (
                            SELECT d.*, s.name FROM daily_prices d
                            LEFT JOIN stock_list s ON d.ts_code = s.ts_code
                            WHERE d.trade_date = ?
                        )
                    """, conn, params=(latest_price,))
                    mr = mkt_snap.iloc[0]
                    total_stocks    = int(mr["total_stocks"])
                    up_count        = int(mr["up_count"])
                    flat_count      = int(mr["flat_count"])
                    down_count      = int(mr["down_count"])
                    up_limit_count  = int(mr["up_limit_count"])
                    down_limit_count= int(mr["real_down_limit"])
                    avg_pct         = float(mr["avg_pct"]) if mr["avg_pct"] else 0.0
                    # 【单位修正】daily_prices.amount 真实单位 = 千元 → 亿元 = ÷ 100000 (之前错误 ÷1e8 → 偏小1000x)
                    total_amount_yi = float(mr["total_amount"]) / 100000.0 if mr["total_amount"] else 0.0
                    total_rows_list = []
                    rows_list.append({
                        "date": latest_price,
                        "up_count": up_count,
                        "flat_count": flat_count,
                        "down_count": down_count,
                        "up_limit_count": up_limit_count,
                        "down_limit_count": down_limit_count,
                        "avg_pct": avg_pct,
                        "total_amount_yi": total_amount_yi,
                        "up_ratio":   (up_count / total_stocks * 100)    if total_stocks else 0.0,
                        "flat_ratio": (flat_count / total_stocks * 100)  if total_stocks else 0.0,
                        "down_ratio": (down_count / total_stocks * 100)  if total_stocks else 0.0,
                        "up_limit_ratio":   (up_limit_count / total_stocks * 100)   if total_stocks else 0.0,
                        "down_limit_ratio": (down_limit_count / total_stocks * 100) if total_stocks else 0.0,
                    })
            except Exception as e:
                print(f"[overview] market snapshot query failed: {e}")
                rows_list = []

            if rows_list:
                today_row = rows_list[0]
            else:
                today_row = {
                    "date": latest_price, "up_count": 0, "flat_count": 0, "down_count": 0,
                    "up_limit_count": 0, "down_limit_count": 0, "avg_pct": 0.0,
                    "total_amount_yi": 0.0, "up_ratio": 0.0, "flat_ratio": 0.0, "down_ratio": 0.0,
                    "up_limit_ratio": 0.0, "down_limit_ratio": 0.0,
                }

            date_range_sql = """
                SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 60
            """
            recent_dates_df = pd.read_sql(date_range_sql, conn)
            recent_dates = recent_dates_df["trade_date"].tolist()

            latest_6_dates = recent_dates[:6] if len(recent_dates) >= 6 else recent_dates

            earning_effect_6 = []
            for rd in latest_6_dates:
                try:
                    df_6 = pd.read_sql("""
                        SELECT
                            COUNT(*) t,
                            SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) u,
                            SUM(CASE WHEN pct_chg = 0 THEN 1 ELSE 0 END) f,
                            SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END) d,
                            AVG(pct_chg) avg_p,
                            SUM(amount)/100000.0 amt
                        FROM daily_prices WHERE trade_date = ?
                    """, conn, params=(rd,))
                    r = df_6.iloc[0]
                    earning_effect_6.append({
                        "date": str(rd) if rd else "",
                        "up_ratio": round(float(r["u"]) / max(1, int(r["t"])) * 100, 2),
                        "down_ratio": round(float(r["d"]) / max(1, int(r["t"])) * 100, 2),
                        "avg_pct": round(float(r["avg_p"] or 0.0), 3),
                        "amount_yi": round(float(r["amt"] or 0.0), 2),
                    })
                except Exception as _e:
                    print(f"[overview] earning_effect date={rd} err: {_e}")

            sector_flow = []
            # S2：从统一阈值加载（config/thresholds.yaml → hot_money_tracker.sector_money_flow/theme_popularity）
            _hmt = get_hot_money_tracker_cfg()
            _smf = _hmt["sector_money_flow"]
            _thm = _hmt["theme_popularity"]
            sector_top_n = int(_smf["top_n"])
            sector_min_count = int(_smf["min_stock_count"])
            theme_top_n = int(_thm["top_n"])
            theme_lookback = int(_thm["limit_dates_lookback"])
            theme_fallback_top_n = int(_thm["fallback_top_n"])

            if latest_price:
                try:
                    # 【口径修复 2026-09-01】净流入改真实主力口径：SUM(net_mf_amount)（万元→亿元 ÷10000）
                    #   修前: SUM(d.amount × sign(net_mf_amount)) 符号法，把个股全部成交额按主力方向归类，夸大 ~9.5 倍
                    #   修前: buy/sell_yi 分子 = m.buy/sell_{lg,elg}_amount 万元 → 亿元 = ÷10000
                    # chips_avg = 板块内个股筹码集中度（stock_cyq_perf 当日均值），真实"锁仓度"数据源
                    _cyq_join = ""
                    _cyq_col = "NULL AS chips_avg"
                    _cyq_param_latest = None
                    if "stock_cyq_perf" in existing_tables:
                        _cyq_join = "LEFT JOIN stock_cyq_perf cyq ON cyq.ts_code = m.ts_code AND cyq.trade_date = ?"
                        _cyq_col = "AVG(cyq.chips_peak_pct) AS chips_avg"
                        _cyq_param_latest = latest_price

                    sf_sql = f"""
                        SELECT
                            s.industry,
                            COUNT(*) AS count,
                            CAST(SUM(m.net_mf_amount) AS FLOAT) / 10000.0 AS net_mf_yi,
                            CAST(SUM(m.buy_lg_amount + m.buy_elg_amount) AS FLOAT) / 10000.0 AS buy_yi,
                            CAST(SUM(m.sell_lg_amount + m.sell_elg_amount) AS FLOAT) / 10000.0 AS sell_yi,
                            AVG(d.pct_chg) AS avg_pct,
                            {_cyq_col}
                        FROM moneyflow m
                        JOIN stock_list s ON m.ts_code = s.ts_code
                        JOIN daily_prices d ON m.ts_code = d.ts_code AND m.trade_date = d.trade_date
                        {_cyq_join}
                        WHERE m.trade_date = ? AND s.industry IS NOT NULL
                        GROUP BY s.industry
                        HAVING count >= ?
                        ORDER BY net_mf_yi DESC
                        LIMIT ?
                    """
                    _sf_params = ([_cyq_param_latest] if _cyq_param_latest else []) + [latest_price, sector_min_count, sector_top_n]
                    sector_flow_top = pd.read_sql(sf_sql, conn, params=_sf_params)
                    sector_flow_bottom_sql = f"""
                        SELECT
                            s.industry,
                            COUNT(*) AS count,
                            CAST(SUM(m.net_mf_amount) AS FLOAT) / 10000.0 AS net_mf_yi,
                            CAST(SUM(m.buy_lg_amount + m.buy_elg_amount) AS FLOAT) / 10000.0 AS buy_yi,
                            CAST(SUM(m.sell_lg_amount + m.sell_elg_amount) AS FLOAT) / 10000.0 AS sell_yi,
                            AVG(d.pct_chg) AS avg_pct,
                            {_cyq_col}
                        FROM moneyflow m
                        JOIN stock_list s ON m.ts_code = s.ts_code
                        JOIN daily_prices d ON m.ts_code = d.ts_code AND m.trade_date = d.trade_date
                        {_cyq_join}
                        WHERE m.trade_date = ? AND s.industry IS NOT NULL
                        GROUP BY s.industry
                        HAVING count >= ?
                        ORDER BY net_mf_yi ASC
                        LIMIT ?
                    """
                    sector_flow_bottom = pd.read_sql(sector_flow_bottom_sql, conn, params=_sf_params)

                    # 板块主力净流入连续天数（真实回溯最近 10 个交易日，Σnet_mf>0 连续计数）
                    _streak_map = {}
                    try:
                        _streak_days = 10
                        _dates_desc = pd.read_sql(
                            "SELECT DISTINCT trade_date FROM moneyflow ORDER BY trade_date DESC LIMIT ?",
                            conn, params=(_streak_days,)
                        )["trade_date"].tolist()
                        if _dates_desc:
                            _ph = ",".join("?" * len(_dates_desc))
                            ms_df = pd.read_sql(f"""
                                SELECT s.industry AS ind, m.trade_date AS td, SUM(m.net_mf_amount) AS net
                                FROM moneyflow m JOIN stock_list s ON m.ts_code = s.ts_code
                                WHERE m.trade_date IN ({_ph}) AND s.industry IS NOT NULL
                                GROUP BY s.industry, m.trade_date
                            """, conn, params=tuple(str(x) for x in _dates_desc))
                            _net_map = {(str(r.ind), str(r.td)): float(r.net) for r in ms_df.itertuples()}
                            for _ind in ms_df["ind"].unique():
                                _st = 0
                                for _d in _dates_desc:
                                    if _net_map.get((_ind, str(_d)), 0.0) > 0:
                                        _st += 1
                                    else:
                                        break
                                _streak_map[_ind] = _st
                    except Exception as _e:
                        print(f"[overview] net streak calc err: {_e}")

                    # 板块 20 日换手率均值（真实，来自 factor_values.turnover_rate_20d）
                    _to_map = {}
                    try:
                        if latest_factor:
                            to_df = pd.read_sql("""
                                SELECT s.industry AS ind, AVG(f.turnover_rate_20d) AS avg_to
                                FROM factor_values f JOIN stock_list s ON f.stock_code = s.ts_code
                                WHERE f.trade_date = ? AND s.industry IS NOT NULL
                                GROUP BY s.industry
                            """, conn, params=(latest_factor,))
                            _to_map = {str(r.ind): safe_float(r.avg_to, 0.0) for r in to_df.itertuples()}
                    except Exception as _e:
                        print(f"[overview] sector turnover calc err: {_e}")

                    def _sf_row(row):
                        _ind_full = str(row["industry"])
                        buy_v = safe_float(row["buy_yi"], 0.0)
                        sell_v = safe_float(row["sell_yi"], 0.0)
                        net_v = safe_float(row["net_mf_yi"], 0.0)
                        denom = buy_v + sell_v
                        net_ratio = max(-100.0, min(100.0, net_v / denom * 100.0)) if denom > 1e-9 else 0.0
                        return {
                            "sector": _ind_full.split(" | ")[-1] if " | " in _ind_full else _ind_full,
                            "net_inflow_yi": round(net_v, 2),
                            "avg_pct": round(safe_float(row["avg_pct"], 0.0), 2),
                            "stock_count": int(row["count"]),
                            "net_ratio": round(net_ratio, 1),
                            "net_streak": int(_streak_map.get(_ind_full, 0)),
                            "chips_avg": round(safe_float(row["chips_avg"], 0.0), 1),
                            "avg_turnover_20d": round(_to_map.get(_ind_full, 0.0), 2),
                        }

                    sf_rows = [_sf_row(row) for _, row in sector_flow_top.iterrows()]
                    sector_flow.append({"type": "top", "sectors": sf_rows})
                    sf_rows_bottom = [_sf_row(row) for _, row in sector_flow_bottom.iterrows()]
                    sector_flow.append({"type": "bottom", "sectors": sf_rows_bottom})
                except Exception as e:
                    print(f"[overview] sector flow error: {e}")
                    sector_flow = []

            themes = []
            limit_latest = None
            if "limit_list_stocks" in existing_tables:
                try:
                    limit_dates = pd.read_sql(
                        "SELECT DISTINCT trade_date FROM limit_list_stocks ORDER BY trade_date DESC LIMIT ?", conn,
                        params=(theme_lookback,)
                    )["trade_date"].tolist()
                    limit_latest = limit_dates[0] if limit_dates else None
                except Exception:
                    limit_latest = None

            if limit_latest:
                try:
                    theme_df = pd.read_sql("""
                        SELECT reason, COUNT(*) as hit_count
                        FROM limit_list_stocks
                        WHERE trade_date = ? AND reason IS NOT NULL
                        GROUP BY reason
                        ORDER BY hit_count DESC
                        LIMIT ?
                    """, conn, params=(limit_latest, theme_top_n))
                    for _, r in theme_df.iterrows():
                        themes.append({
                            "sector":   str(r["reason"]),
                            "hit_count": int(r["hit_count"]),
                        })
                except Exception as e:
                    print(f"[overview] theme popularity error: {e}")
                    themes = []
            if not themes:
                try:
                    sector_df = pd.read_sql("""
                        SELECT s.industry, COUNT(*) c, AVG(d.pct_chg) ap
                        FROM daily_prices d JOIN stock_list s ON d.ts_code = s.ts_code
                        WHERE d.trade_date = ? AND s.industry IS NOT NULL
                        GROUP BY s.industry ORDER BY ap DESC LIMIT ?
                    """, conn, params=(latest_price, theme_fallback_top_n))
                    for _, r in sector_df.iterrows():
                        ind = r["industry"]
                        ind_short = ind.split(" | ")[-1] if " | " in str(ind) else str(ind)
                        themes.append({"sector": ind_short, "hit_count": int(r["c"])})
                except Exception as _e2:
                    pass

            result["today"] = today_row
            result["earning_effect_history"] = earning_effect_6
            result["sector_money_flow"] = sector_flow
            result["theme_popularity"] = themes
            result["price_latest_date"] = latest_price
            result["factor_latest_date"] = latest_factor

            # ===== 题材排行三卡（2026-09-01 修复：全部真实数据，替代前端启发式合成）=====
            _top_sectors = sector_flow[0]["sectors"] if sector_flow and sector_flow[0].get("type") == "top" else []
            _bot_sectors = sector_flow[1]["sectors"] if len(sector_flow) > 1 and sector_flow[1].get("type") == "bottom" else []

            # 游资题材 Top5（hot_score = 净流入 + 连续天数 + 涨幅，真实输入确定性映射）
            hot_money_themes = []
            for s in _top_sectors[:5]:
                _hs = (min(40, max(0.0, s["net_inflow_yi"]) * 2)
                       + min(35, s["net_streak"] * 7)
                       + min(25, max(0.0, s["avg_pct"]) * 5))
                hot_money_themes.append({
                    "sector": s["sector"],
                    "hit_count": s["stock_count"],
                    "streak_days": s["net_streak"],
                    "net_inflow": s["net_inflow_yi"],
                    "avg_turnover": s["avg_turnover_20d"],
                    "avg_pct": s["avg_pct"],
                    "hot_score": round(_hs),
                    **_theme_signal(_hs),
                })

            # 机构强庄控盘排行（按真实筹码集中度 chips_avg 降序）
            _inst_src = sorted(
                [s for s in _top_sectors if s["chips_avg"] > 0],
                key=lambda x: (-x["chips_avg"], -x["net_inflow_yi"])
            )[:10]
            inst_themes = [{
                "sector": s["sector"],
                "streak_days": s["net_streak"],
                "chips_peak": s["chips_avg"],
                "net_inflow": s["net_inflow_yi"],
                "avg_pct": s["avg_pct"],
                "stock_count": s["stock_count"],
                **_theme_signal(s["chips_avg"]),
            } for s in _inst_src]

            # 主力扫货排行（净流入降序，inflow_ratio = 净流入/主力成交 真实比例）
            _main_src = sorted(_top_sectors, key=lambda x: -x["net_inflow_yi"])[:10]
            main_cap_themes = [{
                "sector": s["sector"],
                "streak_days": s["net_streak"],
                "net_inflow": s["net_inflow_yi"],
                "inflow_ratio": s["net_ratio"],
                "avg_pct": s["avg_pct"],
                "stock_count": s["stock_count"],
                **_theme_signal(max(0.0, s["net_ratio"])),
            } for s in _main_src]

            result["hot_money_themes"] = hot_money_themes
            result["inst_themes"] = inst_themes
            result["main_cap_themes"] = main_cap_themes
            result["inflow_rank"] = [
                {"sector": s["sector"], "flow_value": s["net_inflow_yi"], "pct_chg": s["avg_pct"]}
                for s in _top_sectors[:5]
            ]
            result["outflow_rank"] = [
                {"sector": s["sector"], "flow_value": s["net_inflow_yi"], "pct_chg": s["avg_pct"]}
                for s in _bot_sectors[:5]
            ]

            # ===== S3 补齐：style_rotation / adv_dec / temperature / regime =====
            # 1) adv_dec：今日涨跌比（直接从 today_row 或 DB 提取）
            if rows_list:
                _tr = rows_list[0]
                result["adv_dec"] = {
                    "up":   int(_tr.get("up_count", 0)),
                    "down": int(_tr.get("down_count", 0)),
                    "flat": int(_tr.get("flat_count", 0)),
                    "up_limit":   int(_tr.get("up_limit_count", 0)),
                    "down_limit": int(_tr.get("down_limit_count", 0)),
                }
            else:
                result["adv_dec"] = {"up": 0, "down": 0, "flat": 0, "up_limit": 0, "down_limit": 0}

            # 2) temperature：筹码获利中位数 + 超买超卖比例
            cyq_date = ""
            try:
                if latest_price and "stock_cyq_perf" in existing_tables:
                    cursor.execute(
                        "SELECT MAX(trade_date) FROM stock_cyq_perf WHERE trade_date <= ?",
                        (latest_price,)
                    )
                    _cyq_r = cursor.fetchone()
                    cyq_date = str(_cyq_r[0]) if _cyq_r and _cyq_r[0] else ""
            except Exception:
                cyq_date = ""
            median_winner, overbought, oversold = 40.0, 0.35, 0.15
            if cyq_date:
                try:
                    df_cyq = pd.read_sql(
                        "SELECT winner_rate FROM stock_cyq_perf WHERE trade_date = ?",
                        conn, params=(cyq_date,)
                    )
                    if not df_cyq.empty:
                        median_winner = float(df_cyq["winner_rate"].median())
                        overbought = float((df_cyq["winner_rate"] >= 50.0).mean())
                        oversold = float((df_cyq["winner_rate"] < 10.0).mean())
                except Exception as _e:
                    print(f"[overview] temperature calc err: {_e}")
            result["temperature"] = {
                "median_winner":   round(median_winner, 1),
                "overbought_ratio": round(overbought * 100, 1),
                "oversold_ratio":   round(oversold * 100, 1),
            }

            # 3) regime：复用 market_regime.get_market_status() 与内核一致
            try:
                _ms = get_market_status()
                raw_reg = str(_ms.get("regime", "RANGE")).upper()
                if raw_reg in ("BULL", "RANGE", "BEAR", "DARK"):
                    # UI 只显示三种图标，将 DARK 归入 BEAR（已由 regime_dashboard 细分）
                    result["regime"] = "BEAR" if raw_reg == "DARK" else raw_reg
                else:
                    result["regime"] = "RANGE"
            except Exception as _e:
                print(f"[overview] regime err (fallback RANGE): {_e}")
                result["regime"] = "RANGE"

            # 4) style_rotation：近 5 日三风格（高换手 / 筹码锁仓 / 大资金）收益时序
            style_series = []
            try:
                df_dates = pd.read_sql(
                    "SELECT DISTINCT trade_date FROM daily_prices WHERE trade_date <= ? "
                    "ORDER BY trade_date DESC LIMIT 5", conn, params=(latest_price,)
                )
                recent_5 = sorted(df_dates["trade_date"].tolist())
                if len(recent_5) >= 2:
                    have_cyq = "stock_cyq_perf" in existing_tables
                    have_mf  = "moneyflow" in existing_tables
                    have_db  = "daily_basic" in existing_tables
                    for dt in recent_5:
                        cols = ["dp.pct_chg"]
                        joins = ""
                        params = [dt]
                        if have_cyq:
                            cols.append("cyq.chips_peak_pct")
                            joins += " LEFT JOIN stock_cyq_perf cyq ON dp.ts_code = cyq.ts_code AND cyq.trade_date = dp.trade_date"
                        if have_db:
                            cols.append("db.turnover_rate")
                            joins += " LEFT JOIN daily_basic db ON dp.ts_code = db.ts_code AND db.trade_date = dp.trade_date"
                        if have_mf:
                            cols.append("mf.net_mf_amount")
                            joins += " LEFT JOIN moneyflow mf ON dp.ts_code = mf.ts_code AND mf.trade_date = dp.trade_date"
                        df_slice = pd.read_sql(
                            f"SELECT {', '.join(cols)} FROM daily_prices dp {joins} WHERE dp.trade_date = ?",
                            conn, params=params
                        )
                        if df_slice.empty:
                            continue
                        ret_turn = None
                        ret_chip = None
                        ret_inf = None
                        if have_db and "turnover_rate" in df_slice.columns:
                            _s = df_slice["turnover_rate"].dropna()
                            if len(_s) > 0:
                                q80 = _s.quantile(0.8)
                                mask = df_slice["turnover_rate"] >= q80
                                if mask.any():
                                    v = df_slice.loc[mask, "pct_chg"].mean()
                                    ret_turn = round(float(v), 2) if not pd.isna(v) else None
                        if have_cyq and "chips_peak_pct" in df_slice.columns:
                            _s = df_slice["chips_peak_pct"].dropna()
                            if len(_s) > 0:
                                q80 = _s.quantile(0.8)
                                mask = df_slice["chips_peak_pct"] >= q80
                                if mask.any():
                                    v = df_slice.loc[mask, "pct_chg"].mean()
                                    ret_chip = round(float(v), 2) if not pd.isna(v) else None
                        if have_mf and "net_mf_amount" in df_slice.columns:
                            _s = df_slice["net_mf_amount"].dropna()
                            if len(_s) > 0:
                                q80 = _s.quantile(0.8)
                                mask = df_slice["net_mf_amount"] >= q80
                                if mask.any():
                                    v = df_slice.loc[mask, "pct_chg"].mean()
                                    ret_inf = round(float(v), 2) if not pd.isna(v) else None
                        if ret_turn is None and have_cyq and "chips_peak_pct" in df_slice.columns:
                            _pct = df_slice["pct_chg"].dropna()
                            if len(_pct) > 0:
                                mid = len(_pct) // 3 or 1
                                sorted_pct = _pct.sort_values()
                                v_hot = sorted_pct.iloc[-mid:].mean() if mid > 0 else sorted_pct.mean()
                                v_cold = sorted_pct.iloc[:mid].mean() if mid > 0 else sorted_pct.mean()
                                v_norm = sorted_pct.mean()
                                ret_turn = round(float(v_hot), 2) if not pd.isna(v_hot) else None
                                ret_chip = round(float(v_norm), 2) if not pd.isna(v_norm) else None
                                ret_inf  = round(float(v_cold), 2) if not pd.isna(v_cold) else None
                        raw_d = str(dt)
                        style_series.append({
                            "date": f"{raw_d[4:6]}/{raw_d[6:]}",
                            "高换手风格 (Turnover)": ret_turn,
                            "筹码锁仓风格 (Chips)":  ret_chip,
                            "大单大市风格 (Inflow)": ret_inf,
                        })
            except Exception as _e:
                print(f"[overview] style_rotation calc err: {_e}")
                import traceback; traceback.print_exc()
            result["style_rotation"] = style_series

        except Exception as e:
            print(f"[overview] secondary query error: {e}")
            import traceback; traceback.print_exc()
            result["error"] = str(e)
        finally:
            conn.close()

    except Exception as e:
        print(f"[overview] top level error: {e}")
        import traceback; traceback.print_exc()
        result["error"] = str(e)

    build_positions_rv = get_build_position_opportunities(use_portrait_router=True)
    result["build_position_opportunities"] = build_positions_rv
    result["_elapsed"] = round(time.time() - start, 3)
    return clean_nan_inf(result, default=0.0)


def search_stock(keyword: str, limit: int = 15):
    """股票搜索：ts_code / name / 拼音"""
    if not keyword:
        return {"results": []}
    keyword_stripped = keyword.strip()
    try:
        conn = get_db_connection(DB_PATH)
        try:
            # pinyin_full=全拼(如 guizhoumaotai)、pinyin_simp=首字母简拼(如 gzmt)
            # 名称中的非汉字部分（TCL/C前缀/数字）原样保留在拼音列中
            sql = """
                SELECT ts_code, name, industry, market, list_date
                FROM stock_list
                WHERE ts_code LIKE ?
                   OR name LIKE ?
                   OR symbol LIKE ?
                   OR pinyin_full LIKE ?
                   OR pinyin_simp LIKE ?
                LIMIT ?
            """
            kw_like = f"%{keyword_stripped}%"
            df = pd.read_sql(sql, conn, params=(kw_like, kw_like, kw_like, kw_like, kw_like, limit))
            if df.empty:
                return {"results": []}
            results = []
            for _, r in df.iterrows():
                industry_raw = str(r["industry"]) if not pd.isna(r["industry"]) else ""
                industry_short = industry_raw.split(" | ")[-1] if industry_raw else "--"
                results.append({
                    "ts_code": str(r["ts_code"]),
                    "name": str(r["name"]),
                    "market": str(r["market"]) if not pd.isna(r["market"]) else "--",
                    "industry": industry_short,
                    "industry_full": industry_raw,
                    "list_date": str(r["list_date"]) if not pd.isna(r["list_date"]) else "--",
                })
            return {"keyword": keyword_stripped, "results": results}
        finally:
            conn.close()
    except Exception as e:
        return {"keyword": keyword_stripped, "results": [], "error": str(e)}


_FACTOR_FRIENDLY = {
    "factor_score": "综合因子", "winner_rate": "筹码胜率", "net_mf_amount": "主力净流入",
    "pct_chg": "涨跌幅", "return_5d": "5日涨幅", "return_10d": "10日涨幅",
    "return_20d": "20日涨幅", "return_60d": "60日涨幅", "return_120d": "120日涨幅",
    "excess_return_20d": "20日超额", "turnover_rate": "换手率", "turnover_rate_5d": "5日换手",
    "turnover_rate_20d": "20日换手", "volatility_10d": "10日波动", "volatility_20d": "20日波动",
    "volatility_60d": "60日波动", "volatility_120d": "120日波动", "north_net_inflow_ratio": "北向流入比",
    "profit_ratio_estimate": "预期利润率", "chip_concentration": "筹码集中度", "skewness_20d": "20日偏度",
    "max_drawdown_20d": "20日回撤", "max_drawdown_60d": "60日回撤", "atr_ratio": "ATR比率",
    "pe_ttm": "PE(TTM)", "pb": "市净率", "roe": "ROE", "beta_60d": "60日Beta", "vol_ratio": "量比",
}
_PCT_LIKE_COLS = {
    "pct_chg", "winner_rate", "turnover_rate", "turnover_rate_5d", "turnover_rate_20d",
    "return_5d", "return_10d", "return_20d", "return_60d", "return_120d", "excess_return_20d",
    "volatility_10d", "volatility_20d", "volatility_60d", "volatility_120d",
    "chip_concentration", "north_net_inflow_ratio", "profit_ratio_estimate",
}


def _format_factor_subject(col, val):
    """雷达图 subject：友好名(格式化值)，如 筹码胜率(35.12%) / 主力净流入(0.54亿)"""
    name = _FACTOR_FRIENDLY.get(col, col)
    try:
        v = float(val)
    except (TypeError, ValueError):
        return name
    if col == "net_mf_amount":
        return f"{name}({v / 10000:.2f}亿)"
    if col in _PCT_LIKE_COLS:
        return f"{name}({v:.2f}%)"
    return f"{name}({v:.2f})"


def _resolve_strategy_factors(strategy: str):
    """strategy 名 → [{factor, weight}]；无法识别返回 None
    * current  → 路由 regime 决定 bull/range 因子集
    * base_bull / base_range → 已部署 pkl 权重
    * scanner  → 5维纯因子分+筹码+主力+涨跌幅（含 -0.15 惩罚项）
    * 其他     → agent/strategies/<strategy> YAML（custom_new_factors 优先，均权）
    """
    if strategy in ("current", ""):
        regime = get_market_status().get("regime", "RANGE")
        deployed = get_deployed_factors()
        return deployed["bull_factors"] if str(regime).upper() == "BULL" else deployed["range_factors"]
    if strategy == "base_bull":
        return get_deployed_factors()["bull_factors"]
    if strategy == "base_range":
        return get_deployed_factors()["range_factors"]
    if strategy == "scanner":
        return [
            {"factor": "factor_score", "weight": 0.35},
            {"factor": "winner_rate", "weight": 0.25},
            {"factor": "net_mf_amount", "weight": 0.25},
            {"factor": "pct_chg", "weight": -0.15},
        ]
    strat_path = os.path.join(PROJECT_ROOT, "agent", "strategies", strategy)
    if os.path.exists(strat_path):
        import yaml
        with open(strat_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        factors_cfg = cfg.get("factors") or {}
        pool = factors_cfg.get("custom_new_factors") or factors_cfg.get("base_pool") or []
        if not pool:
            return None
        w = 1.0 / len(pool)
        return [{"factor": p, "weight": w} for p in pool]
    return None


def _build_strategy_panel(conn, active_factors, fac_date):
    """把策略所需因子从多表拼成一个全市场面板（ts_code 统一），供分位数排名。
    factor_values 为基准表；winner_rate/net_mf_amount/pct_chg 取各自表最新交易日；
    factor_score 为计算列（regime_weights pkl 加权全市场分位）。"""
    names = [f["factor"] for f in active_factors if f.get("factor")]
    panel = None

    def _merge(df, on="ts_code"):
        nonlocal panel
        panel = df.rename(columns={}) if panel is None else panel.merge(df, on=on, how="inner")

    # factor_values 基准列
    fac_cols = [c for c in names if c not in ("winner_rate", "net_mf_amount", "pct_chg", "factor_score")]
    if "factor_score" in names:
        from ._common import _load_pkl_weights, WEIGHTS_PATH
        _, rw = _load_pkl_weights(WEIGHTS_PATH)
        rw = rw or {"return_60d": -0.616, "volatility_20d": -0.150,
                    "north_net_inflow_ratio": -0.199, "volatility_60d": -0.049, "volatility_10d": 0.019}
        base_cols = [c for c in rw if c != "factor_score"]
        df = pd.read_sql(
            f"SELECT stock_code, {','.join(base_cols)} FROM factor_values WHERE trade_date=?",
            conn, params=(fac_date,))
        if not df.empty:
            df["factor_score"] = 0.0
            for fc, fw in rw.items():
                if fc in df.columns:
                    df["factor_score"] += fw * df[fc].rank(pct=True, na_option="bottom")
            _merge(df[["stock_code", "factor_score"]].rename(columns={"stock_code": "ts_code"}))
    if fac_cols:
        df = pd.read_sql(
            f"SELECT stock_code, {','.join(fac_cols)} FROM factor_values WHERE trade_date=?",
            conn, params=(fac_date,))
        if not df.empty:
            _merge(df.rename(columns={"stock_code": "ts_code"}))

    # 外部表列（各取自身最新交易日）
    ext_map = {
        "winner_rate": "stock_cyq_perf",
        "net_mf_amount": "moneyflow",
        "pct_chg": "daily_prices",
    }
    for col in names:
        if col in ext_map:
            table = ext_map[col]
            try:
                dmax = pd.read_sql(f"SELECT MAX(trade_date) AS d FROM {table}", conn).iloc[0]["d"]
                df = pd.read_sql(f"SELECT ts_code, {col} FROM {table} WHERE trade_date=?", conn, params=(dmax,))
                if not df.empty:
                    _merge(df)
            except Exception:
                continue
    return panel


def diagnose_stock(ts_code: str, strategy: str = "current"):
    """个股多维诊断：估值 + 技术 + 筹码 + 画像 + 近5日涨跌
    strategy 决定因子权重集（current/base_bull/base_range/scanner/自定义 yaml），
    按"全市场分位数排名 × 策略权重"计算 final_score / radar_data / 优缺点。
    """
    if not ts_code:
        return {"error": "缺少 ts_code"}
    conn = get_db_connection(DB_PATH, timeout=30.0)
    try:
        # S2: 从配置读取分级阈值
        _dg = get_diagnose_grade_cfg()
        _gAplus = float(_dg.get("grade_A_plus_min", 70.0))
        _gA = float(_dg.get("grade_A_min", 60.0))
        _gB = float(_dg.get("grade_B_min", 50.0))
        _gC = float(_dg.get("grade_C_min", 45.0))
        _f_exc = float(_dg.get("factor_excellent_min", 60.0))
        _f_neu = float(_dg.get("factor_neutral_min", 40.0))
        _c_safe = float(_dg.get("chips_safe_min", 70.0))
        _c_dang = float(_dg.get("chips_danger_max", 30.0))
        _pe_ok = float(_dg.get("pe_reasonable_max", 30.0))
        _pe_hi = float(_dg.get("pe_high_min", 60.0))

        df_info = pd.read_sql(
            "SELECT ts_code, name, industry, market, list_date FROM stock_list WHERE ts_code = ?",
            conn, params=(ts_code,)
        )
        if df_info.empty:
            return {"error": f"未找到股票 {ts_code}"}
        info = df_info.iloc[0]
        industry_raw = str(info["industry"]) if not pd.isna(info["industry"]) else ""
        industry_short = industry_raw.split(" | ")[-1] if industry_raw else "--"

        recent_dates_df = pd.read_sql(
            "SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 120", conn
        )
        recent_dates = recent_dates_df["trade_date"].tolist()
        if not recent_dates:
            return {"error": "行情数据为空"}
        latest_date = recent_dates[0]
        prev_5 = recent_dates[:5][::-1]

        dp_df = pd.read_sql(
            "SELECT trade_date, open, high, low, close, pct_chg, vol, amount FROM daily_prices "
            "WHERE ts_code = ? AND trade_date IN (" + ",".join(["?"] * len(recent_dates)) + ") ORDER BY trade_date",
            conn, params=[ts_code] + recent_dates
        )
        closes = dp_df["close"].astype(float).values
        pct_chgs = dp_df["pct_chg"].astype(float).values
        amounts = dp_df["amount"].astype(float).values

        def safe_float(v, default=0.0):
            if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                return default
            return float(v)

        # 估值（兼容不同 daily_basic 建表版本：存在 pe_ttm/ps_ttm/dv_ratio 时优先用，否则回退 pe / ps / 0）
        _val_cols_1 = "pe_ttm, pe, pb, ps_ttm, dv_ratio, total_mv"
        _val_cols_2 = "pe AS pe_ttm, pe, pb, ps AS ps_ttm, 0.0 AS dv_ratio, total_mv"
        db_row = None
        for _cols in (_val_cols_1, _val_cols_2):
            try:
                db_row = pd.read_sql(
                    f"SELECT {_cols} FROM daily_basic WHERE ts_code = ? AND trade_date = ?",
                    conn, params=(ts_code, latest_date)
                )
                if not db_row.empty:
                    break
            except Exception:
                db_row = None
        if db_row is None or db_row.empty:
            valuation = {k: 0.0 for k in ["pe_ttm", "pe_static", "pb", "ps_ttm", "div_yield", "market_cap_yi"]}
        else:
            br = db_row.iloc[0]
            valuation = {
                "pe_ttm":        round(safe_float(br["pe_ttm"]), 2),
                "pe_static":     round(safe_float(br["pe"]), 2),
                "pb":            round(safe_float(br["pb"]), 2),
                "ps_ttm":        round(safe_float(br["ps_ttm"]), 2),
                "div_yield":     round(safe_float(br["dv_ratio"]), 2),
                "market_cap_yi": round(safe_float(br["total_mv"]) / 1e4, 2),
            }

        # 技术面
        ma5  = np.mean(closes[-5:])  if len(closes) >= 5  else 0.0
        ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else 0.0
        ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else 0.0
        ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else 0.0
        close = float(closes[-1]) if len(closes) else 0.0
        tech_lines = []
        if close > 0:
            if close > ma5 > ma10 > ma20 > ma60: tech_lines.append(("多头发散 强势", "green"))
            elif close > ma5 > ma10 > ma20:      tech_lines.append(("短线强势排列", "blue"))
            elif close < ma5 < ma10 < ma20:      tech_lines.append(("空头排列 弱势", "red"))
            else:                                tech_lines.append(("均线纠缠 震荡", "grey"))
        pct_20  = ((closes[-1] / closes[-20]) - 1) * 100 if len(closes) >= 20 else 0.0
        pct_60  = ((closes[-1] / closes[-60]) - 1) * 100 if len(closes) >= 60 else 0.0
        vol_20  = np.std(pct_chgs[-20:]) if len(pct_chgs) >= 20 else 0.0
        technical = {
            "ma_ratios": {
                "ma5_gain":  round((close / ma5 - 1) * 100, 2) if ma5 else 0.0,
                "ma10_gain": round((close / ma10 - 1) * 100, 2) if ma10 else 0.0,
                "ma20_gain": round((close / ma20 - 1) * 100, 2) if ma20 else 0.0,
                "ma60_gain": round((close / ma60 - 1) * 100, 2) if ma60 else 0.0,
            },
            "momentum": {"pct_20d": round(pct_20, 2), "pct_60d": round(pct_60, 2)},
            "volatility_20d": round(vol_20, 3),
            "lines": tech_lines,
            "price_now": round(close, 2),
        }

        # 筹码
        cyq_row = pd.read_sql(
            "SELECT winner_rate, chips_peak_pct FROM stock_cyq_perf WHERE ts_code = ? AND trade_date = ?",
            conn, params=(ts_code, latest_date)
        )
        if not cyq_row.empty:
            cr = cyq_row.iloc[0]
            chips = {
                "winner_rate":    round(safe_float(cr["winner_rate"]), 2),
                "chips_peak_pct": round(safe_float(cr["chips_peak_pct"]), 2),
            }
        else:
            chips = {"winner_rate": 0.0, "chips_peak_pct": 0.0}

        # 画像 + 因子（兼容建表版本：旧版 factor_values 无 factor_score / alpha_5d，使用
        #  hot_money/strong_control/main_force/quality 四合一合成 factor_score，alpha_5d 用 return_5d 近似）
        factor_sql_versions = [
            ("SELECT factor_score, alpha_5d, return_5d, return_10d, return_20d "
             "FROM factor_values WHERE stock_code = ? AND trade_date = ?"),
            ("SELECT "
             "  (COALESCE(hot_money_score,0)*0.3 + COALESCE(strong_control_score,0)*0.3 "
             "   + COALESCE(main_force_score,0)*0.25 + COALESCE(quality_score,0)*0.15) AS factor_score, "
             "  return_5d AS alpha_5d, return_5d, return_10d, return_20d "
             "FROM factor_values WHERE stock_code = ? AND trade_date = ?"),
        ]
        factor_row = None
        # 兼容策略：先取基准因子日；若该股票该日无数据，则回退到该股票在 factor_values 中最新一天
        fd_base = _get_factor_date(conn)
        fallback_dates = [fd_base]
        try:
            latest_per_stock = pd.read_sql(
                "SELECT MAX(trade_date) AS d FROM factor_values WHERE stock_code = ?",
                conn, params=(ts_code,)
            ).iloc[0, 0]
            if latest_per_stock and latest_per_stock != fd_base:
                fallback_dates.append(latest_per_stock)
        except Exception:
            pass
        for _fd in fallback_dates:
            if not _fd: continue
            for _fsql in factor_sql_versions:
                try:
                    factor_row = pd.read_sql(_fsql, conn, params=(ts_code, _fd))
                    if not factor_row.empty:
                        break
                except Exception:
                    factor_row = None
            if factor_row is not None and not factor_row.empty:
                break
        factor_details = {}
        if factor_row is not None and not factor_row.empty:
            fr = factor_row.iloc[0]
            factor_details = {
                "factor_score": round(safe_float(fr.get("factor_score", 0.0)) % 100.0, 5),
                "alpha_5d":     round(safe_float(fr.get("alpha_5d", 0.0)) * 100, 2),
                "return_5d":    round(safe_float(fr.get("return_5d", 0.0))    * 100, 2),
                "return_10d":   round(safe_float(fr.get("return_10d", 0.0))   * 100, 2),
                "return_20d":   round(safe_float(fr.get("return_20d", 0.0))   * 100, 2),
            }

        position_score = round(
            min(100.0, max(0.0, (1 - min(1, max(0, technical["ma_ratios"]["ma5_gain"] / 10.0))) * 100)), 1
        )
        valuation_score = round(
            min(100.0, max(0.0, (1 - min(1, max(0, (valuation["pe_ttm"] or 0) / 100.0))) * 100)), 1
        )
        chips_score = round(min(100.0, chips["winner_rate"]), 1)
        factor_score_1 = round(min(100.0, max(0.0, (factor_details.get("factor_score", 0.0) / 100.0) * 100)), 1)
        total_4 = position_score + valuation_score + chips_score + factor_score_1
        total_score = round(total_4 / 4.0, 1)
        if total_score >= _gAplus: total_grade, total_label = "A+", "钻石级配置"
        elif total_score >= _gA: total_grade, total_label = "A",  "优秀配置"
        elif total_score >= _gB: total_grade, total_label = "B",  "正常配置"
        elif total_score >= _gC: total_grade, total_label = "C",  "观察临线"
        else:                  total_grade, total_label = "D",  "不建议配置"

        pct_dict = {}
        if len(prev_5) == 5:
            df_5 = pd.read_sql(
                "SELECT trade_date, close, pct_chg FROM daily_prices "
                "WHERE ts_code = ? AND trade_date IN (" + ",".join(["?"] * 5) + ") ORDER BY trade_date",
                conn, params=[ts_code] + prev_5
            )
            for _, r in df_5.iterrows():
                pct_dict[str(r["trade_date"])] = {
                    "close":   round(safe_float(r["close"]), 2),
                    "pct_chg": round(safe_float(r["pct_chg"]), 2),
                }

        overall_signals = []
        if factor_score_1 >= _f_exc: overall_signals.append(("因子分优秀", "green"))
        elif factor_score_1 >= _f_neu: overall_signals.append(("因子分中性", "blue"))
        else:                     overall_signals.append(("因子分偏弱", "red"))
        if chips["winner_rate"] >= _c_safe: overall_signals.append(("获利盘充足", "green"))
        elif chips["winner_rate"] <= _c_dang: overall_signals.append(("套牢盘过重", "red"))
        if valuation["pe_ttm"] and 0 < valuation["pe_ttm"] < _pe_ok: overall_signals.append(("估值合理", "blue"))
        elif valuation["pe_ttm"] and valuation["pe_ttm"] > _pe_hi:   overall_signals.append(("估值偏高", "orange"))

        # ── raw_metrics（前端 Diagnose.jsx 核心指标明细 4 项）────────────────
        # 单位契约（与全库一致）：
        #   winner_rate / chip_concentration / turnover_rate_20d = 百分比数值（前端 toFixed(2)+%）
        #   net_mf_amount = 万元（DB 原始口径，前端 ÷10000 → 亿）
        net_mf_raw = 0.0
        try:
            mf_row = pd.read_sql(
                "SELECT net_mf_amount FROM moneyflow WHERE ts_code = ? AND trade_date = ?",
                conn, params=(ts_code, latest_date)
            )
            if mf_row.empty:
                mf_row = pd.read_sql(
                    "SELECT net_mf_amount FROM moneyflow WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1",
                    conn, params=(ts_code,)
                )
            if not mf_row.empty:
                net_mf_raw = safe_float(mf_row.iloc[0]["net_mf_amount"], 0.0)
        except Exception:
            net_mf_raw = 0.0

        turn20 = 0.0
        try:
            tf_row = pd.read_sql(
                "SELECT turnover_rate_20d FROM factor_values WHERE stock_code = ? AND trade_date = ?",
                conn, params=(ts_code, fd_base)
            )
            if not tf_row.empty:
                turn20 = safe_float(tf_row.iloc[0]["turnover_rate_20d"], 0.0)
        except Exception:
            turn20 = 0.0

        raw_metrics = {
            "winner_rate":        round(safe_float(chips.get("winner_rate"), 0.0), 2),
            "chip_concentration": round(safe_float(chips.get("chips_peak_pct"), 0.0), 2),
            "net_mf_amount":      round(net_mf_raw, 2),
            "turnover_rate_20d":  round(turn20, 2),
        }

        # ── 策略感知诊断：按所选策略的因子权重 × 全市场分位数排名 ─────────────
        close_now   = safe_float(technical.get("price_now", 0.0), 0.0)
        pct_chg_now = safe_float(float(pct_chgs[-1]) if len(pct_chgs) else 0.0, 0.0)

        active_factors = _resolve_strategy_factors(strategy)
        if not active_factors:
            return {"error": f"未知策略或策略无有效因子: {strategy}",
                    "ts_code": str(ts_code), "name": str(info["name"])}
        fac_date = _get_factor_date(conn)
        panel = _build_strategy_panel(conn, active_factors, fac_date) if fac_date else None
        if panel is None or panel.empty:
            return {"error": f"策略 {strategy} 无全市场因子数据（因子日 {fac_date}）",
                    "ts_code": str(ts_code), "name": str(info["name"])}

        # 全市场分位数（0-1）
        fac_names = [f["factor"] for f in active_factors]
        for col in fac_names:
            if col in panel.columns:
                panel[f"{col}__pct"] = panel[col].rank(pct=True, ascending=True, na_option="bottom")
        row = panel[panel["ts_code"] == ts_code]
        if row.empty:
            return {"error": f"策略 {strategy} 下未找到 {ts_code} 的因子截面",
                    "ts_code": str(ts_code), "name": str(info["name"])}
        r0 = row.iloc[0]

        total_w = sum(abs(float(f["weight"])) for f in active_factors)
        radar_data, strengths, weaknesses = [], [], []
        score_sum = 0.0
        for f in active_factors:
            col, w = f["factor"], float(f["weight"])
            if col not in panel.columns or f"{col}__pct" not in panel.columns:
                continue
            pct = r0[f"{col}__pct"]
            pct = safe_float(pct, 0.5)
            fscore = (1.0 - pct) * 100.0 if w < 0 else pct * 100.0
            score_sum += abs(w) * fscore
            subject = _format_factor_subject(col, r0.get(col))
            radar_data.append({"subject": subject, "A": round(fscore, 1), "fullMark": 100})
            friendly = subject.split("(")[0]
            val_txt = subject[len(friendly):].strip("()")
            if fscore >= 80:
                strengths.append(f"【{friendly}】{val_txt}，表现优异（击败 {fscore:.1f}% 个股）")
            elif fscore <= 20:
                weaknesses.append(f"【{friendly}】{val_txt}，表现落后（仅胜 {fscore:.1f}% 个股）")
        final_score = round(score_sum / total_w, 1) if total_w > 0 else 50.0

        return {
            "ts_code": str(ts_code),
            "name":    str(info["name"]),
            "market":  str(info["market"]) if not pd.isna(info["market"]) else "--",
            "industry": industry_short,
            "industry_full": industry_raw,
            "list_date": str(info["list_date"]) if not pd.isna(info["list_date"]) else "--",
            "diagnose_date": str(latest_date),
            "close":   round(close_now, 2),
            "pct_chg": round(pct_chg_now, 2),
            "final_score": final_score,
            "strategy": str(strategy),
            "active_factors": active_factors,
            "valuation": valuation,
            "technical": technical,
            "chips":     chips,
            "factor":    factor_details,
            "portrait":  {
                "position_score":  position_score,
                "valuation_score": valuation_score,
                "chips_score":     chips_score,
                "factor_score":    factor_score_1,
                "total_score":     total_score,
                "total_grade":     total_grade,
                "total_label":     total_label,
            },
            "radar_data":   radar_data,
            "strengths":    strengths,
            "weaknesses":   weaknesses,
            "raw_metrics": raw_metrics,
            "recent_5_days": pct_dict,
            "overall_signals": overall_signals,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}
    finally:
        conn.close()


def record_visitor(ip: str, user_agent: str = ""):
    """访客日志"""
    log_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "visitors.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}\t{ip}\t{user_agent[:200]}\n")
        return True
    except Exception as e:
        _logger.warning(f"record_visitor failed: {e}")
        return False


def get_visitor_stats():
    log_path = os.path.join(PROJECT_ROOT, "logs", "visitors.log")
    total, unique = 0, set()
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        total += 1
                        unique.add(parts[1])
        except Exception:
            pass
    return {"total_visits": total, "unique_ips": len(unique)}
