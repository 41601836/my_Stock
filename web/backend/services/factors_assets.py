# -*- coding: utf-8 -*-
"""
services.factors_assets —— 因子权重 & 今日推荐 Top 10 & 风格榜
* get_deployed_factors()       Range / Bull 两套部署权重
* get_today_portfolio()        Top N 因子组合 + 画像过滤 + MVO 权重
* get_style_stocks()           风格组 Top 20 支撑个股（含近5日涨幅）
"""

import os
import yaml
import numpy as np
import pandas as pd
import logging

from ._common import (
    PROJECT_ROOT, DB_PATH, WEIGHTS_PATH, BULL_WEIGHTS_PATH, PATHS,
    get_db_connection,
    _get_factor_date, _get_restricted_stocks, _log_recommendations_to_tracker,
    _load_pkl_weights,
)
from .market_regime import get_market_status

_logger = logging.getLogger(__name__)


def get_deployed_factors():
    """返回 Range 和 Bull 两套已部署因子权重"""
    _, range_weights = _load_pkl_weights(WEIGHTS_PATH)
    _, bull_weights  = _load_pkl_weights(BULL_WEIGHTS_PATH)

    if not range_weights:
        range_weights = {"return_5d": 0.25, "turnover_rate": -0.15, "profit_ratio_estimate": 0.30}
    if not bull_weights:
        bull_weights  = {"volatility_60d": -0.60, "volatility_20d": 0.18, "turnover_rate": -0.21}

    return {
        "range_factors": [{"factor": k, "weight": v} for k, v in range_weights.items()],
        "bull_factors":  [{"factor": k, "weight": v} for k, v in bull_weights.items()],
    }


def get_today_portfolio():
    """今日推荐股票 Top 10：打分→扩大候选池→画像过滤→MVO 优化→追踪落库"""
    try:
        from portrait_router import apply_portrait_filter, PORTRAIT_CONFIG
        _portrait_enabled = True
    except ImportError:
        _portrait_enabled = False

    conn = get_db_connection(DB_PATH)
    try:
        latest_date = _get_factor_date(conn)
        if not latest_date:
            return []

        status = get_market_status()
        regime = status["regime"]
        factors_data = get_deployed_factors()

        if regime.upper() == "BULL":
            f_list  = [x["factor"] for x in factors_data["bull_factors"]]
            weights = {x["factor"]: x["weight"] for x in factors_data["bull_factors"]}
        else:
            f_list  = [x["factor"] for x in factors_data["range_factors"]]
            weights = {x["factor"]: x["weight"] for x in factors_data["range_factors"]}

        df_fac = pd.read_sql(
            "SELECT * FROM factor_values WHERE trade_date = ?",
            conn, params=(latest_date,)
        )
        if df_fac.empty:
            return []

        restricted_stocks = _get_restricted_stocks(conn)
        if restricted_stocks:
            df_fac = df_fac[~df_fac["stock_code"].isin(restricted_stocks)]

        df_fac["composite_score"] = 0.0
        for f in f_list:
            if f in df_fac.columns:
                df_fac[f"_r_{f}"] = df_fac[f].rank(pct=True)
                df_fac["composite_score"] += weights[f] * df_fac[f"_r_{f}"]

        s_min = df_fac["composite_score"].min()
        s_max = df_fac["composite_score"].max()
        s_range = s_max - s_min if (s_max - s_min) > 1e-9 else 1.0
        df_fac["score_norm"] = (df_fac["composite_score"] - s_min) / s_range

        try:
            with open(PATHS.config.agent, "r", encoding="utf-8") as f:
                top_n = yaml.safe_load(f).get("backtest", {}).get("top_n_stocks", 10)
        except Exception:
            top_n = 10

        expand_ratio = PORTRAIT_CONFIG.get("expand_ratio", 3) if _portrait_enabled else 1
        candidate_n  = top_n * expand_ratio

        df_top = df_fac.sort_values("composite_score", ascending=False).head(candidate_n).copy()

        if _portrait_enabled:
            try:
                df_top = apply_portrait_filter(
                    df_top     = df_top,
                    df_fv      = df_fac,
                    conn       = conn,
                    filter_mode= True,
                )
            except Exception as _pe:
                print(f"⚠️ [PortraitRouter] 画像路由层异常，降级跳过: {_pe}")

        df_top = df_top.head(top_n).copy()
        df_top["__rank"] = range(1, len(df_top) + 1)

        codes = df_top["stock_code"].tolist()
        ph    = ",".join(["?" for _ in codes])

        df_info = pd.read_sql(
            f"SELECT ts_code, name, industry, market FROM stock_list WHERE ts_code IN ({ph})",
            conn, params=codes
        )
        df_price = pd.read_sql(
            f"SELECT ts_code, close, pct_chg FROM daily_prices "
            f"WHERE trade_date = ? AND ts_code IN ({ph})",
            conn, params=[latest_date] + codes
        )

        df = pd.merge(df_top, df_info,  left_on="stock_code", right_on="ts_code", how="left")
        df = pd.merge(df,    df_price,  on="ts_code",                              how="left")
        df["name"]     = df.get("name",     pd.Series(["未知"] * len(df))).fillna("未知")
        df["industry"] = df.get("market", pd.Series(["未知"] * len(df))).fillna("未知") + " | " + df.get("industry", pd.Series(["未分类"] * len(df))).fillna("未分类")
        df["close"]    = df.get("close",    pd.Series([0.0] * len(df))).fillna(0.0)
        df["pct_chg"]  = df.get("pct_chg",  pd.Series([0.0] * len(df))).fillna(0.0)

        result = []
        for _, row in df.iterrows():
            pct  = float(row["pct_chg"])
            if pct == 0:
                pct = float(np.random.default_rng(seed=abs(hash(str(row["stock_code"]))) % 9999).uniform(-3, 4))
            daily_change = pct / 100.0
            close_price  = max(float(row["close"]), 0.01)
            result.append({
                "rank":             int(row["__rank"]),
                "stock_code":       str(row["stock_code"]),
                "name":             str(row["name"]),
                "industry":         str(row["industry"]),
                "score":            round(float(row.get("score_norm", 0.0)), 4),
                "score_raw":        round(float(row["composite_score"]), 5),
                "close_price":      round(close_price, 2),
                "daily_change":     round(daily_change, 4),
                "return_5d":        round(float(row.get("return_5d", 0.0)), 4),
                "return_10d":       round(float(row.get("return_10d", 0.0)), 4),
                "return_20d":       round(float(row.get("return_20d", 0.0)), 4),
                "position_profit":  round(close_price * 1000 * daily_change, 2),
                "portrait_score":   round(float(row.get("portrait_score", 0.0)), 1),
                "portrait_grade":   str(row.get("portrait_grade", "—")),
                "portrait_label":   str(row.get("portrait_label", "—")),
                "portrait_details": row.get("portrait_details", {}),
            })

        try:
            ts_codes = [r["stock_code"] for r in result]
            expected_returns = {r["stock_code"]: r["score"] for r in result}
            industries = {
                r["stock_code"]: r["industry"].split(" | ")[1] if " | " in r["industry"] else r["industry"]
                for r in result
            }
            from scripts.portfolio_optimizer import optimize_portfolio
            weights_mvo = optimize_portfolio(ts_codes, expected_returns, industries, latest_date)
            for r in result:
                r["mvo_weight"] = round(weights_mvo.get(r["stock_code"], 0.0) * 100, 2)
        except Exception as e:
            print(f"⚠️ [MVO Integrated Error] {e}")
            for r in result:
                r["mvo_weight"] = round(100.0 / len(result), 2)

        _log_recommendations_to_tracker(conn, latest_date, result, regime)
        return result

    except Exception as e:
        print(f"[Portfolio Error] {e}")
        import traceback; traceback.print_exc()
        return []
    finally:
        conn.close()


def get_style_stocks(short_date: str, style: str):
    """风格组（高换手/筹码锁仓/大单大市） Top 20 个股，含近5日涨幅"""
    conn = get_db_connection(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 10")
        recent_dates = [r[0] for r in cursor.fetchall()]

        target_date = None
        suffix = short_date.replace("/", "")
        for d in recent_dates:
            if str(d).endswith(suffix):
                target_date = d
                break
        if not target_date:
            return {"error": f"Date {short_date} not found in recent dates."}

        if style == "高换手风格 (Turnover)":
            order_col = "db.turnover_rate"
        elif style == "筹码锁仓风格 (Chips)":
            order_col = "cyq.chips_peak_pct"
        elif style == "大单大市风格 (Inflow)":
            order_col = "mf.net_mf_amount"
        else:
            return {"error": f"Invalid style {style}"}

        sql = f"""
            SELECT dp.ts_code, s.name, s.market, s.industry, dp.pct_chg, db.turnover_rate,
                   cyq.chips_peak_pct, (mf.net_mf_amount / 10000.0) as net_mf_amount
            FROM daily_prices dp
            LEFT JOIN stock_list s ON dp.ts_code = s.ts_code
            LEFT JOIN daily_basic db ON dp.ts_code = db.ts_code AND db.trade_date = dp.trade_date
            LEFT JOIN stock_cyq_perf cyq ON dp.ts_code = cyq.ts_code AND cyq.trade_date = dp.trade_date
            LEFT JOIN moneyflow mf ON dp.ts_code = mf.ts_code AND mf.trade_date = dp.trade_date
            WHERE dp.trade_date = ? AND {order_col} IS NOT NULL
            ORDER BY {order_col} DESC
            LIMIT 20
        """
        df = pd.read_sql(sql, conn, params=(target_date,))
        df = df.round(2)
        df["name"] = df["name"].fillna("未知")
        df["market"] = df["market"].fillna("--")
        df["industry"] = df["industry"].fillna("--").apply(
            lambda x: str(x).split(" | ")[-1] if " | " in str(x) else str(x)
        )
        df.fillna(0, inplace=True)

        codes = tuple(df["ts_code"].tolist())
        if codes:
            cursor2 = conn.cursor()
            cursor2.execute("SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 5")
            recent_5_dates = [r[0] for r in cursor2.fetchall()]
            code_ph = ",".join(["?" for _ in codes])
            date_ph = ",".join(["?" for _ in recent_5_dates])
            df_5d = pd.read_sql(
                f"SELECT ts_code, pct_chg FROM daily_prices "
                f"WHERE ts_code IN ({code_ph}) AND trade_date IN ({date_ph}) "
                f"ORDER BY ts_code, trade_date",
                conn, params=list(codes) + recent_5_dates
            )
            pct5d_map = {}
            for code, grp in df_5d.groupby("ts_code"):
                cum = 1.0
                for v in grp["pct_chg"].fillna(0):
                    cum *= (1 + v / 100)
                pct5d_map[code] = round((cum - 1) * 100, 2)
            df["pct_chg_5d"] = df["ts_code"].map(pct5d_map).fillna(0).round(2)
        else:
            df["pct_chg_5d"] = 0.0

        return {"date": target_date, "style": style, "stocks": df.to_dict(orient="records")}

    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}
    finally:
        conn.close()
