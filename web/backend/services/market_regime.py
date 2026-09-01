# -*- coding: utf-8 -*-
"""
services.market_regime —— 市场状态实时判定板块
* compute_live_regime()         基于全市场最新60日行情动态判定 Bull/Range/Bear/Dark
* get_market_status()           对外暴露：状态/DB健康/收益基准，含 LIVE vs CSV 兜底切换
* get_regime_dashboard()        可解释路由层：触发指标+阈值+仓位建议+近8周历史
* get_theme_stocks()            游资题材下具体活跃股（含近5日累计涨幅）
"""

import os
import json
import logging
import pandas as pd

from ._common import (
    PROJECT_ROOT, DB_PATH, RESULTS_PATH,
    get_db_connection, clean_nan_inf,
    get_live_regime_cfg, get_hot_money_tracker_cfg,
)

_logger = logging.getLogger(__name__)


def compute_live_regime():
    """
    基于数据库最新全市场行情，实时动态计算当前 Regime (Bull/Range/Bear/Dark)。
    返回: dict = {regime, model_used, return_20d, return_5d, mdd_5d, vol_20d, up_ratio, vol_50pct, vol_75pct, triggers, db_latest_date}
    """
    try:
        conn = get_db_connection(DB_PATH)
        df_bench = pd.read_sql(
            "SELECT trade_date, "
            "  AVG(pct_chg) as pct_chg, "
            "  SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as up_ratio "
            "FROM daily_prices "
            "GROUP BY trade_date "
            "ORDER BY trade_date DESC LIMIT 60",
            conn
        )
        conn.close()

        if df_bench.empty or len(df_bench) < 6:
            return None

        df_bench = df_bench.sort_values("trade_date").reset_index(drop=True)
        df_bench["nav"] = (1.0 + df_bench["pct_chg"] / 100.0).cumprod()
        df_bench["return_20d"] = df_bench["nav"] / df_bench["nav"].shift(20) - 1.0
        df_bench["return_5d"]  = df_bench["nav"] / df_bench["nav"].shift(5)  - 1.0
        df_bench["vol_20d"]    = df_bench["pct_chg"].rolling(20).std()
        roll_max_5d = df_bench["nav"].rolling(5).max()
        df_bench["mdd_5d"]     = (df_bench["nav"] - roll_max_5d) / roll_max_5d

        valid_vol = df_bench["vol_20d"].dropna()
        vol_50pct = float(valid_vol.quantile(0.50)) if len(valid_vol) > 0 else 1.5
        vol_75pct = float(valid_vol.quantile(0.75)) if len(valid_vol) > 0 else 2.0

        last   = df_bench.iloc[-1]
        ret20  = float(last["return_20d"]) if not pd.isna(last["return_20d"]) else 0.0
        ret5w  = float(last["return_5d"])  if not pd.isna(last["return_5d"])  else 0.0
        vol20  = float(last["vol_20d"])    if not pd.isna(last["vol_20d"])    else 0.0
        mdd5   = float(last["mdd_5d"])     if not pd.isna(last["mdd_5d"])     else 0.0
        up_r   = float(last["up_ratio"])   if not pd.isna(last["up_ratio"])   else 0.5

        triggers = []
        dark_trigger = False
        bear_trigger = False
        bull_trigger = False

        # S2：从配置读取 Dark/Bull/Bear 触发阈值
        _regime_cfg = get_live_regime_cfg()
        _dark_cfg = _regime_cfg["dark"]
        _bull_cfg = _regime_cfg["bull"]
        _bear_cfg = _regime_cfg["bear"]

        _dark_ret5w    = float(_dark_cfg.get("return_5d_below",     -0.045))
        _dark_mdd5     = float(_dark_cfg.get("mdd_5d_below",        -0.050))
        _dark_up_ratio = float(_dark_cfg.get("up_ratio_below",       0.30))
        _dark_vol_q    = float(_dark_cfg.get("vol_above_quantile",   0.75))
        _bull_ret20    = float(_bull_cfg.get("return_20d_above",     0.05))
        _bull_vol_q    = float(_bull_cfg.get("vol_below_quantile",   0.50))
        _bear_ret20    = float(_bear_cfg.get("return_20d_below",    -0.03))
        _bear_vol_q    = float(_bear_cfg.get("vol_above_quantile",   0.50))

        _dark_vol_threshold = float(valid_vol.quantile(_dark_vol_q)) if len(valid_vol) > 0 else vol_75pct
        _bull_vol_threshold = float(valid_vol.quantile(_bull_vol_q)) if len(valid_vol) > 0 else vol_50pct
        _bear_vol_threshold = float(valid_vol.quantile(_bear_vol_q)) if len(valid_vol) > 0 else vol_50pct

        if ret5w < _dark_ret5w:
            dark_trigger = True
            triggers.append({"name": "周收益率触发Dark", "value": f"{ret5w:.2%}", "threshold": f"< {_dark_ret5w:.2%}", "color": "red"})
        if mdd5 < _dark_mdd5:
            dark_trigger = True
            triggers.append({"name": "5日最大回撤触发Dark", "value": f"{mdd5:.2%}", "threshold": f"< {_dark_mdd5:.2%}", "color": "red"})
        if vol20 > _dark_vol_threshold:
            triggers.append({"name": "波动率过热", "value": f"{vol20:.3f}%", "threshold": f"> {_dark_vol_threshold:.3f}%", "color": "orange"})
        if up_r < _dark_up_ratio:
            dark_trigger = True
            triggers.append({"name": "上涨家数占比过低", "value": f"{up_r:.1%}", "threshold": f"< {_dark_up_ratio:.0%}", "color": "red"})

        if not dark_trigger:
            if ret20 > _bull_ret20 and vol20 < _bull_vol_threshold:
                bull_trigger = True
                triggers.append({"name": "20日稳步上涨+Bull", "value": f"{ret20:.2%}", "threshold": f"> {_bull_ret20:+.2%} & 低波动", "color": "green"})
            elif ret20 < _bear_ret20 and vol20 > _bear_vol_threshold:
                bear_trigger = True
                triggers.append({"name": "20日下跌+高波动 Bear", "value": f"{ret20:.2%}", "threshold": f"< {_bear_ret20:.2%} & 高波动", "color": "rose"})

        if dark_trigger:
            regime, model = "Dark", "Dark_Model"
        elif bull_trigger:
            regime, model = "Bull", "Bull_Model"
        elif bear_trigger:
            regime, model = "Bear", "Bear_Model"
        else:
            regime, model = "Range", "Range_Model"

        return {
            "regime": regime,
            "model_used": model,
            "return_20d": ret20,
            "return_5d": ret5w,
            "mdd_5d": mdd5,
            "vol_20d": vol20,
            "up_ratio": up_r,
            "vol_50pct": vol_50pct,
            "vol_75pct": vol_75pct,
            "triggers": triggers,
            "db_latest_date": int(last["trade_date"]),
        }
    except Exception as e:
        _logger.error(f"compute_live_regime failed: {e}")
        return None


def get_market_status():
    """获取最新市场状态（动态实时计算 + 回测CSV兜底）及数据库最新日期"""
    db_latest = "—"
    db_latest_int = 0
    db_health = "UNKNOWN"
    health_issues = []

    try:
        if os.path.exists(DB_PATH):
            conn = get_db_connection(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(trade_date) FROM daily_prices")
            d = cursor.fetchone()[0]
            if d:
                db_latest_int = int(d)
                v = str(int(d))
                db_latest = f"{v[:4]}-{v[4:6]}-{v[6:]}"
            conn.close()

        health_report_path = os.path.join(os.path.dirname(DB_PATH), "health_report.json")
        if os.path.exists(health_report_path):
            with open(health_report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
                if report.get("status") == "ERROR":
                    db_health = "ERROR"
                    health_issues = report.get("issues", [])
                elif report.get("status") == "WARNING":
                    db_health = "PARTIAL_DATA"
                    health_issues = report.get("issues", [])
                else:
                    db_health = "HEALTHY"
        else:
            db_health = "PARTIAL_DATA"
            health_issues = ["未找到数据体检报告，等待后台哨兵扫描..."]
    except Exception as e:
        _logger.error(f"Failed to read market status from DB: {e}")

    live_info = compute_live_regime()

    base_port_ret = 0.0
    base_bench_ret = 0.0
    base_excess_ret = 0.0
    csv_trade_date = "—"
    csv_regime = None
    csv_model = None
    csv_last_date_int = 0

    if os.path.exists(RESULTS_PATH):
        df = pd.read_csv(RESULTS_PATH)
        if len(df) > 0:
            last = df.iloc[-1]
            raw_date = str(last["trade_date"])
            csv_last_date_int = int(float(last["trade_date"])) if isinstance(last["trade_date"], (int, float)) else int(str(last["trade_date"]))
            csv_trade_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            csv_regime = last["regime"]
            csv_model  = last["model_used"]
            base_port_ret  = float(last["portfolio_return"])
            base_bench_ret = float(last["benchmark_return"])
            base_excess_ret = float(last["excess_return"])

    if live_info is not None and db_latest_int > 0 and db_latest_int > csv_last_date_int:
        final_regime     = live_info["regime"]
        final_model      = live_info["model_used"]
        final_trade_date = db_latest
        regime_source_tag = " (LIVE 动态)"
    else:
        final_regime     = csv_regime if csv_regime else "Dark"
        final_model      = csv_model  if csv_model  else "Dark_Light_Track"
        final_trade_date = csv_trade_date if csv_trade_date != "—" else db_latest
        regime_source_tag = " (CSV 归档)"

    return {
        "trade_date": final_trade_date,
        "db_latest_date": db_latest,
        "db_health": db_health,
        "health_issues": health_issues,
        "regime": final_regime,
        "model_used": final_model,
        "portfolio_return": base_port_ret,
        "benchmark_return": base_bench_ret,
        "excess_return": base_excess_ret,
        "_debug": {
            "csv_last_date_int": csv_last_date_int,
            "db_latest_int": db_latest_int,
            "regime_source": ("LIVE 动态" if live_info and db_latest_int > csv_last_date_int else "CSV 归档"),
            "csv_regime": csv_regime,
            "live_regime": live_info["regime"] if live_info else None,
            "live_triggers": live_info["triggers"] if live_info else [],
        }
    }


def get_regime_dashboard():
    """
    实时计算路由层的各项触发指标，复用 compute_live_regime() 保证与 Dashboard 主状态 100% 一致。
    """
    try:
        live = compute_live_regime()
        if live is None:
            return {"error": "数据不足，无法实时计算市场状态，请先更新日线数据"}

        regime   = live["regime"]
        ret20    = live["return_20d"]
        ret5w    = live["return_5d"]
        vol20    = live["vol_20d"]
        mdd5     = live["mdd_5d"]
        up_r     = live["up_ratio"]
        vol_50pct = live["vol_50pct"]
        vol_75pct = live["vol_75pct"]
        triggers  = live["triggers"]

        regime_history = []
        csv_latest_int = 0
        if os.path.exists(RESULTS_PATH):
            df_res = pd.read_csv(RESULTS_PATH)
            for _, row in df_res.tail(8).iterrows():
                d_int = int(float(row["trade_date"])) if isinstance(row["trade_date"], (int, float)) else int(str(row["trade_date"]))
                csv_latest_int = max(csv_latest_int, d_int)
                d_str = str(d_int)
                regime_history.append({
                    "date": f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}",
                    "regime": row["regime"],
                    "portfolio_return": round(float(row["portfolio_return"]) * 100, 2),
                    "benchmark_return": round(float(row["benchmark_return"]) * 100, 2),
                })

        db_int = live["db_latest_date"]
        if db_int > csv_latest_int:
            db_s = str(db_int)
            live_market = get_market_status()
            regime_history.append({
                "date": f"{db_s[:4]}-{db_s[4:6]}-{db_s[6:]}",
                "regime": live["regime"],
                "portfolio_return": round(float(live_market.get("portfolio_return", 0.0)) * 100, 2),
                "benchmark_return": round(float(live_market.get("benchmark_return", 0.0)) * 100, 2),
                "_live": True,
            })

        position_map = {
            "Bull":  {"pct": "80-100%", "color": "green",  "advice": "全速做多，放大仓位"},
            "Range": {"pct": "40-60%",  "color": "blue",   "advice": "轮动操作，高抛低吸"},
            "Bear":  {"pct": "0-30%",   "color": "rose",   "advice": "严格减仓，防御优先"},
            "Dark":  {"pct": "0%",      "color": "red",    "advice": "空仓观望，现金为王"},
        }
        pos = position_map.get(regime, position_map["Range"])

        # S2：从配置读取仪表盘展示阈值
        _regime_cfg = get_live_regime_cfg()
        _dark_cfg_d = _regime_cfg["dark"]
        _bull_cfg_d = _regime_cfg["bull"]
        _bear_cfg_d = _regime_cfg["bear"]
        _dash_cfg_d = _regime_cfg.get("dashboard", {})
        _bull_ret_th    = round(float(_bull_cfg_d.get("return_20d_above", 0.05)) * 100, 2)
        _bear_ret_th    = round(float(_bear_cfg_d.get("return_20d_below", -0.03)) * 100, 2)
        _dark_week_th   = round(float(_dark_cfg_d.get("return_5d_below", -0.045)) * 100, 2)
        _dark_mdd_th    = round(float(_dark_cfg_d.get("mdd_5d_below", -0.050)) * 100, 2)
        _dark_upratio_th = round(float(_dash_cfg_d.get("dark_up_ratio_pct",
            _dark_cfg_d.get("up_ratio_below", 0.30) * 100)), 1)

        return {
            "regime": regime,
            "indicators": {
                "return_20d": round(ret20 * 100, 2),
                "vol_20d":    round(vol20, 4),
                "mdd_5d":     round(mdd5 * 100, 2),
                "up_ratio":   round(up_r * 100, 1),
                "return_5d":  round(ret5w * 100, 2),
            },
            "thresholds": {
                "vol_50pct":   round(vol_50pct, 4),
                "vol_75pct":   round(vol_75pct, 4),
                "bull_ret":    _bull_ret_th,
                "bear_ret":    _bear_ret_th,
                "dark_weekly": _dark_week_th,
                "dark_mdd":    _dark_mdd_th,
                "dark_up_ratio": _dark_upratio_th,
            },
            "triggers": triggers,
            "position_advice": pos,
            "regime_history": regime_history,
        }
    except Exception as e:
        _logger.error(f"get_regime_dashboard failed: {e}")
        return {"error": str(e)}


def get_theme_stocks(sector_name: str, limit=None, sort_order: str = "DESC", sort_by=None):
    """某游资题材下的具体活跃个股列表，含板块和近5日涨幅
    
    S2 统一阈值：limit/sort_by 默认值从 config/thresholds.yaml.hot_money_tracker.theme_stocks_drill 读取
    """
    try:
        conn = get_db_connection(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM daily_prices")
        row = cursor.fetchone()
        latest_date = row[0] if row else None
        if not latest_date:
            return {"error": "无最新交易日数据"}

        # S2：从统一阈值加载默认值（仅调用者未传时使用）
        _hmt_cfg = get_hot_money_tracker_cfg()
        _drill = _hmt_cfg["theme_stocks_drill"]
        if limit is None:
            limit = int(_drill["default_limit"])
        if sort_by is None:
            sort_by = _drill["sort_by"] or "net_mf_amount"

        # sort_by 白名单，防 SQL 注入
        _sort_whitelist = {
            "net_mf_amount": "mf.net_mf_amount",
            "turnover_rate": "db.turnover_rate",
            "pct_chg": "dp.pct_chg",
        }
        order_col = _sort_whitelist.get(sort_by, "mf.net_mf_amount")
        order_clause = "DESC" if sort_order.upper() == "DESC" else "ASC"
        df = pd.read_sql(
            f"SELECT s.ts_code, s.name, s.market, s.industry, dp.pct_chg, db.turnover_rate, mf.net_mf_amount "
            f"FROM daily_basic db "
            f"LEFT JOIN stock_list s ON db.ts_code = s.ts_code "
            f"LEFT JOIN moneyflow mf ON db.ts_code = mf.ts_code AND mf.trade_date = db.trade_date "
            f"LEFT JOIN daily_prices dp ON db.ts_code = dp.ts_code AND dp.trade_date = db.trade_date "
            f"WHERE db.trade_date = ? AND s.industry LIKE ? "
            f"ORDER BY {order_col} {order_clause} LIMIT ?",
            conn, params=(latest_date, f"%{sector_name}%", limit)
        )
        if df.empty:
            conn.close()
            return {"stocks": []}

        codes = tuple(df["ts_code"].tolist())
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 5")
        recent_5_dates = [r[0] for r in cursor.fetchall()]
        code_ph = ",".join(["?" for _ in codes])
        date_ph = ",".join(["?" for _ in recent_5_dates])
        df_5d = pd.read_sql(
            f"SELECT ts_code, pct_chg FROM daily_prices "
            f"WHERE ts_code IN ({code_ph}) AND trade_date IN ({date_ph}) "
            f"ORDER BY ts_code, trade_date",
            conn, params=list(codes) + recent_5_dates
        )
        conn.close()

        pct5d_map = {}
        for code, grp in df_5d.groupby("ts_code"):
            cum = 1.0
            for v in grp["pct_chg"].fillna(0):
                cum *= (1 + v / 100)
            pct5d_map[code] = round((cum - 1) * 100, 2)

        stocks = []
        for _, r in df.iterrows():
            code = r["ts_code"]
            raw_industry = str(r["industry"]) if not pd.isna(r["industry"]) else ""
            industry_short = raw_industry.split(" | ")[-1] if raw_industry else "--"
            stocks.append({
                "ts_code": code,
                "name": r["name"],
                "market": r["market"] if r["market"] else "--",
                "industry": industry_short,
                "pct_chg": round(float(r["pct_chg"]), 2) if not pd.isna(r["pct_chg"]) else 0.0,
                "pct_chg_5d": pct5d_map.get(code, 0.0),
                "turnover_rate": round(float(r["turnover_rate"]), 2) if not pd.isna(r["turnover_rate"]) else 0.0,
                "net_inflow": round(float(r["net_mf_amount"]) / 1e4, 2) if not pd.isna(r["net_mf_amount"]) else 0.0,
            })
        return {"sector": sector_name, "date": str(latest_date), "stocks": stocks}
    except Exception as e:
        return {"error": str(e)}
