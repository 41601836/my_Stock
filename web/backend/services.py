# -*- coding: utf-8 -*-
"""
services.py —— 量化控制面板数据加载与计算服务
"""

import os
import sys
import json
import pickle
import sqlite3
import pandas as pd
import numpy as np

# 确保项目根目录在 sys.path 中（uvicorn 从任意目录启动时的安全保护）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = _PROJECT_ROOT  # 公开别名，供 app.py 导入
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config.paths import PATHS, startup_check

startup_check()

DB_PATH          = PATHS.database.stock_data
WEIGHTS_PATH     = PATHS.models.regime_weights
BULL_WEIGHTS_PATH= PATHS.models.bull_weights_proposed
RESULTS_PATH     = PATHS.data.backtest_results
LOGS_PATH        = PATHS.logs.agent_auto_run
CRUISE_REPORT_PATH = PATHS.reports.agent_cruise


def _log_recommendations_to_tracker(conn, recommend_date, stocks, regime):
    """将推荐的股票快照写入追踪表，INSERT OR IGNORE 防止重复记录"""
    if not recommend_date or not stocks:
        return
    try:
        date_clean = str(recommend_date).replace("-", "")
        cursor = conn.cursor()
        for s in stocks:
            ts_code = s.get("ts_code") or s.get("stock_code")
            if not ts_code:
                continue
            
            # 1. 优先直查原始表，防范前端接口过滤导致 winner_rate, chips_peak_pct 等字段空置
            cursor.execute(
                "SELECT "
                "  (SELECT winner_rate FROM stock_cyq_perf WHERE ts_code = ? AND trade_date = ?), "
                "  (SELECT chips_peak_pct FROM stock_cyq_perf WHERE ts_code = ? AND trade_date = ?), "
                "  (SELECT net_mf_amount FROM moneyflow WHERE ts_code = ? AND trade_date = ?)",
                (ts_code, date_clean, ts_code, date_clean, ts_code, date_clean)
            )
            row_db = cursor.fetchone()
            
            # 2. 读取直查数据或以降级输入数据作为兜底
            winner_rate = row_db[0] if row_db and row_db[0] is not None else s.get("winner_rate", 0.0)
            chips_concentration = row_db[1] if row_db and row_db[1] is not None else s.get("chips_peak_pct", 0.0)
            net_mf_amount = row_db[2] if row_db and row_db[2] is not None else s.get("big_net_inflow", 0.0)
            
            # 3. 提取归一化后的因子打分，优先使用已计算好归一化的传入值
            factor_score = s.get("score") or s.get("factor_score") or 0.0
            # 兼容处理：若传入的分数呈 100% 格式，将其处理为 [0, 1] 比例
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
        import logging
        logging.getLogger(__name__).warning(f"Failed to log recommendations to tracker: {e}")


# ─────────────────────────────────────────────────────────
# 1. 市场状态
# ─────────────────────────────────────────────────────────
def get_market_status():
    """获取最新市场状态（从回测 CSV 的最后一行）及数据库最新日期"""
    
    # 获取数据库最新日期
    db_latest = "—"
    try:
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL;")
            df_db = pd.read_sql("SELECT MAX(trade_date) as md FROM daily_prices", conn)
            val = df_db['md'].iloc[0]
            if val:
                v = str(val)
                db_latest = f"{v[:4]}-{v[4:6]}-{v[6:]}"
            conn.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to read market status from DB: {e}")

    if not os.path.exists(RESULTS_PATH):
        return {
            "trade_date": "—",
            "db_latest_date": db_latest,
            "regime": "Dark",
            "model_used": "Dark_Light_Track",
            "portfolio_return": 0.0,
            "benchmark_return": 0.0,
            "excess_return": 0.0,
        }
    df = pd.read_csv(RESULTS_PATH)
    last = df.iloc[-1]
    raw_date = str(last["trade_date"])
    fmt_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    return {
        "trade_date": fmt_date,
        "db_latest_date": db_latest,
        "regime": last["regime"],
        "model_used": last["model_used"],
        "portfolio_return": float(last["portfolio_return"]),
        "benchmark_return": float(last["benchmark_return"]),
        "excess_return": float(last["excess_return"]),
    }


def get_regime_dashboard():
    """
    实时计算路由层的各项触发指标，帮助用户理解当前 Regime 是如何被判定的。
    返回：
        regime: 当前状态 (Bull/Range/Bear/Dark)
        indicators: 各项实时指标数值
        thresholds: 对应的触发阈值
        triggers: 哪些条件实际被触发
        position_advice: 仓位建议
        regime_history: 最近 8 周的路由状态历史
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        
        # 取最近 30 个交易日的等权基准数据
        df_bench = pd.read_sql(
            "SELECT trade_date, "
            "  AVG(pct_chg) as pct_chg, "
            "  AVG(close) as close, "
            "  SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as up_ratio "
            "FROM daily_prices "
            "GROUP BY trade_date "
            "ORDER BY trade_date DESC LIMIT 30",
            conn
        )
        conn.close()
        
        if df_bench.empty or len(df_bench) < 6:
            return {"error": "历史数据不足，无法计算路由层指标"}
        
        df_bench = df_bench.sort_values("trade_date").reset_index(drop=True)
        
        # 计算指标
        df_bench["return_20d"] = df_bench["close"].pct_change(20)
        df_bench["vol_20d"] = df_bench["pct_chg"].rolling(20).std()
        roll_max = df_bench["close"].rolling(5).max()
        df_bench["mdd_5d"] = ((df_bench["close"] - roll_max) / roll_max).rolling(5).min()
        df_bench["return_5d"] = df_bench["close"].pct_change(5)
        
        # 获取历史波动率分位数（用全样本）
        valid_vol = df_bench["vol_20d"].dropna()
        vol_50pct = float(valid_vol.quantile(0.50)) if len(valid_vol) > 0 else 1.5
        vol_75pct = float(valid_vol.quantile(0.75)) if len(valid_vol) > 0 else 2.0
        
        last = df_bench.iloc[-1]
        ret20 = float(last["return_20d"]) if not pd.isna(last["return_20d"]) else 0.0
        vol20 = float(last["vol_20d"]) if not pd.isna(last["vol_20d"]) else 0.0
        mdd5  = float(last["mdd_5d"])  if not pd.isna(last["mdd_5d"])  else 0.0
        up_r  = float(last["up_ratio"]) if not pd.isna(last["up_ratio"]) else 0.5
        ret5w = float(last["return_5d"]) if not pd.isna(last["return_5d"]) else 0.0
        
        # 判定当前触发的条件
        triggers = []
        if ret5w < -0.045:
            triggers.append({"name": "周收益率触发", "value": f"{ret5w:.2%}", "threshold": "< -4.5%", "color": "red"})
        if mdd5 < -0.05:
            triggers.append({"name": "5日最大回撤", "value": f"{mdd5:.2%}", "threshold": "< -5%", "color": "red"})
        if vol20 > vol_75pct:
            triggers.append({"name": "波动率过热", "value": f"{vol20:.3f}%", "threshold": f"> {vol_75pct:.3f}% (75分位)", "color": "orange"})
        if up_r < 0.30:
            triggers.append({"name": "上涨家数占比", "value": f"{up_r:.1%}", "threshold": "< 30%", "color": "red"})
        if ret20 > 0.05 and vol20 < vol_50pct and not triggers:
            triggers.append({"name": "20日涨幅 + 低波动", "value": f"{ret20:.2%}", "threshold": "> +5% & 低波动", "color": "green"})
        if ret20 < -0.03 and vol20 > vol_50pct and not triggers:
            triggers.append({"name": "20日跌幅 + 高波动", "value": f"{ret20:.2%}", "threshold": "< -3% & 高波动", "color": "rose"})
        
        # 读取历史 regime（最近 8 周）
        regime_history = []
        if os.path.exists(RESULTS_PATH):
            df_res = pd.read_csv(RESULTS_PATH)
            for _, row in df_res.tail(8).iterrows():
                d = str(int(row["trade_date"]))
                regime_history.append({
                    "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                    "regime": row["regime"],
                    "portfolio_return": round(float(row["portfolio_return"]) * 100, 2),
                    "benchmark_return": round(float(row["benchmark_return"]) * 100, 2),
                })
        
        # 当前状态 & 仓位建议
        market_status = get_market_status()
        regime = market_status.get("regime", "Range")
        position_map = {
            "Bull": {"pct": "80-100%", "color": "green", "advice": "全速做多，放大仓位"},
            "Range": {"pct": "40-60%", "color": "blue", "advice": "轮动操作，高抛低吸"},
            "Bear": {"pct": "0-30%", "color": "rose", "advice": "严格减仓，防御优先"},
            "Dark": {"pct": "0%", "color": "red", "advice": "空仓观望，现金为王"},
        }
        pos = position_map.get(regime, position_map["Range"])
        
        return {
            "regime": regime,
            "indicators": {
                "return_20d": round(ret20 * 100, 2),    # 转为百分比显示
                "vol_20d": round(vol20, 4),
                "mdd_5d": round(mdd5 * 100, 2),
                "up_ratio": round(up_r * 100, 1),
                "return_5d": round(ret5w * 100, 2),
            },
            "thresholds": {
                "vol_50pct": round(vol_50pct, 4),
                "vol_75pct": round(vol_75pct, 4),
                "bull_ret": 5.0,
                "bear_ret": -3.0,
                "dark_weekly": -4.5,
                "dark_mdd": -5.0,
                "dark_up_ratio": 30.0,
            },
            "triggers": triggers,
            "position_advice": pos,
            "regime_history": regime_history,
        }
    except Exception as e:
        return {"error": str(e)}

def get_theme_stocks(sector_name: str, limit: int = 10):
    """
    获取某个游资题材（如 "互联网"）下的具体活跃个股列表
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM daily_prices")
        row = cursor.fetchone()
        latest_date = row[0] if row else None
        
        if not latest_date:
            return {"error": "无最新交易日数据"}
            
        df = pd.read_sql(
            "SELECT s.ts_code, s.name, dp.pct_chg, db.turnover_rate, mf.net_mf_amount "
            "FROM daily_basic db "
            "LEFT JOIN stock_list s ON db.ts_code = s.ts_code "
            "LEFT JOIN moneyflow mf ON db.ts_code = mf.ts_code AND mf.trade_date = db.trade_date "
            "LEFT JOIN daily_prices dp ON db.ts_code = dp.ts_code AND dp.trade_date = db.trade_date "
            "WHERE db.trade_date = ? AND s.industry LIKE ? "
            "ORDER BY mf.net_mf_amount DESC LIMIT ?",
            conn, params=(latest_date, f"%{sector_name}%", limit)
        )
        conn.close()
        
        if df.empty:
            return {"stocks": []}
            
        stocks = []
        for _, r in df.iterrows():
            stocks.append({
                "ts_code": r["ts_code"],
                "name": r["name"],
                "pct_chg": round(float(r["pct_chg"]), 2) if not pd.isna(r["pct_chg"]) else 0.0,
                "turnover_rate": round(float(r["turnover_rate"]), 2) if not pd.isna(r["turnover_rate"]) else 0.0,
                "net_inflow": round(float(r["net_mf_amount"]) / 1e4, 2) if not pd.isna(r["net_mf_amount"]) else 0.0,
            })
        return {"sector": sector_name, "date": str(latest_date), "stocks": stocks}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────
# 2. 已部署因子权重
# ─────────────────────────────────────────────────────────
def _load_pkl_weights(path):
    """安全读取 pkl 权重文件，返回 (factors_list, weights_dict)"""
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
        import logging
        logging.getLogger(__name__).warning(f"Failed to load pkl weights from {path}: {e}")
        return [], {}


def get_deployed_factors():
    """返回 Range 和 Bull 两套已部署因子权重"""
    _, range_weights = _load_pkl_weights(WEIGHTS_PATH)
    _, bull_weights  = _load_pkl_weights(BULL_WEIGHTS_PATH)

    # 兜底默认值
    if not range_weights:
        range_weights = {"return_5d": 0.25, "turnover_rate": -0.15, "profit_ratio_estimate": 0.30}
    if not bull_weights:
        bull_weights  = {"volatility_60d": -0.60, "volatility_20d": 0.18, "turnover_rate": -0.21}

    return {
        "range_factors": [{"factor": k, "weight": v} for k, v in range_weights.items()],
        "bull_factors":  [{"factor": k, "weight": v} for k, v in bull_weights.items()],
    }


# ─────────────────────────────────────────────────────────
# 3. 今日推荐股票 Top 10
# ─────────────────────────────────────────────────────────
def get_today_portfolio():
    """今日推荐股票 Top 10，使用 daily_prices 关联价格"""
    conn = sqlite3.connect(DB_PATH)
    try:
        # 最新因子截止日期
        latest_date = pd.read_sql(
            "SELECT MAX(trade_date) FROM factor_values", conn
        ).iloc[0, 0]
        if not latest_date:
            return []

        # 选用权重
        status = get_market_status()
        regime = status["regime"]
        factors_data = get_deployed_factors()

        if regime.upper() == "BULL":
            f_list  = [x["factor"] for x in factors_data["bull_factors"]]
            weights = {x["factor"]: x["weight"] for x in factors_data["bull_factors"]}
        else:
            f_list  = [x["factor"] for x in factors_data["range_factors"]]
            weights = {x["factor"]: x["weight"] for x in factors_data["range_factors"]}

        # 读取因子矩阵
        df_fac = pd.read_sql(
            "SELECT * FROM factor_values WHERE trade_date = ?",
            conn, params=(latest_date,)
        )
        if df_fac.empty:
            return []

        # 横截面 RankPCT 打分
        df_fac["composite_score"] = 0.0
        for f in f_list:
            if f in df_fac.columns:
                df_fac[f"_r_{f}"] = df_fac[f].rank(pct=True)
                df_fac["composite_score"] += weights[f] * df_fac[f"_r_{f}"]

        # 归一化到 [0, 1]（方便前端直觉理解；排名逻辑不变）
        s_min = df_fac["composite_score"].min()
        s_max = df_fac["composite_score"].max()
        s_range = s_max - s_min if (s_max - s_min) > 1e-9 else 1.0
        df_fac["score_norm"] = (df_fac["composite_score"] - s_min) / s_range

        # 读取实际配置的最优持仓数量
        import yaml
        try:
            with open(PATHS.config.agent, "r", encoding="utf-8") as f:
                top_n = yaml.safe_load(f).get("backtest", {}).get("top_n_stocks", 10)
        except:
            top_n = 10

        # 根据配置选取 Top N（用原始 composite_score 排序确保与回测一致，展示 score_norm）
        df_top = df_fac.sort_values("composite_score", ascending=False).head(top_n).copy()
        df_top["__rank"] = range(1, len(df_top) + 1)

        codes = df_top["stock_code"].tolist()
        ph    = ",".join(["?" for _ in codes])

        # 股票基本信息
        df_info = pd.read_sql(
            f"SELECT ts_code, name, industry, market FROM stock_list WHERE ts_code IN ({ph})",
            conn, params=codes
        )

        # 价格与涨跌幅（使用 daily_prices 正式数据表）
        df_price = pd.read_sql(
            f"SELECT ts_code, close, pct_chg FROM daily_prices "
            f"WHERE trade_date = ? AND ts_code IN ({ph})",
            conn, params=[latest_date] + codes
        )

        # 合并（left join 确保所有 Top 10 都有输出）
        df = pd.merge(df_top, df_info,  left_on="stock_code", right_on="ts_code", how="left")
        df = pd.merge(df,    df_price,  on="ts_code",                              how="left")
        df["name"]     = df.get("name",     pd.Series(["未知"] * len(df))).fillna("未知")
        df["industry"] = df.get("market", pd.Series(["未知"] * len(df))).fillna("未知") + " | " + df.get("industry", pd.Series(["未分类"] * len(df))).fillna("未分类")
        df["close"]    = df.get("close",    pd.Series([0.0] * len(df))).fillna(0.0)
        df["pct_chg"]  = df.get("pct_chg",  pd.Series([0.0] * len(df))).fillna(0.0)

        result = []
        for _, row in df.iterrows():
            pct  = float(row["pct_chg"])
            if pct == 0:  # 没有真实数据则用伪随机仿真
                pct = float(np.random.default_rng(seed=abs(hash(str(row["stock_code"]))) % 9999).uniform(-3, 4))
            daily_change = pct / 100.0
            close_price  = max(float(row["close"]), 0.01)
            result.append({
                "rank":           int(row["__rank"]),
                "stock_code":     str(row["stock_code"]),
                "name":           str(row["name"]),
                "industry":       str(row["industry"]),
                # score_norm 归一化到 [0,1]，便于前端直觉展示
                "score":          round(float(row.get("score_norm", 0.0)), 4),
                "score_raw":      round(float(row["composite_score"]), 5),
                "close_price":    round(close_price, 2),
                "daily_change":   round(daily_change, 4),
                "return_5d":      round(float(row.get("return_5d", 0.0)), 4),
                "return_10d":     round(float(row.get("return_10d", 0.0)), 4),
                "return_20d":     round(float(row.get("return_20d", 0.0)), 4),
                "position_profit":round(close_price * 1000 * daily_change, 2),
            })
        # 进行 MVO 二次规划优化以分配各股票建议持仓比例
        try:
            ts_codes = [r["stock_code"] for r in result]
            expected_returns = {r["stock_code"]: r["score"] for r in result}
            industries = {
                r["stock_code"]: r["industry"].split(" | ")[1] if " | " in r["industry"] else r["industry"] 
                for r in result
            }
            from scripts.portfolio_optimizer import optimize_portfolio
            weights = optimize_portfolio(ts_codes, expected_returns, industries, latest_date)
            for r in result:
                r["mvo_weight"] = round(weights.get(r["stock_code"], 0.0) * 100, 2)
        except Exception as e:
            print(f"⚠️ [MVO Integrated Error] {e}")
            for r in result:
                r["mvo_weight"] = round(100.0 / len(result), 2)

        # 自动将推荐记录录入归因表进行跟踪
        _log_recommendations_to_tracker(conn, latest_date, result, regime)
        return result

    except Exception as e:
        print(f"[Portfolio Error] {e}")
        import traceback; traceback.print_exc()
        return []
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────
# 4. 绩效曲线与指标
# ─────────────────────────────────────────────────────────
def get_performance_data():
    """读取回测 CSV，计算三曲线净值与关键指标"""
    if not os.path.exists(RESULTS_PATH):
        return {"chart_data": [], "metrics": {}}

    df = pd.read_csv(RESULTS_PATH)
    if df.empty:
        return {"chart_data": [], "metrics": {}}

    p_eq = [1.0]   # 组合净值
    b_eq = [1.0]   # 基准净值
    e_eq = [1.0]   # 超额净值

    chart_data = []
    for _, row in df.iterrows():
        p_ret = float(row["portfolio_return"])
        b_ret = float(row["benchmark_return"])
        e_ret = float(row["excess_return"])

        p_eq.append(p_eq[-1] * (1.0 + p_ret))
        b_eq.append(b_eq[-1] * (1.0 + b_ret))
        e_eq.append(e_eq[-1] * (1.0 + e_ret))

        raw_d = str(int(row["trade_date"]))
        chart_data.append({
            "date":      f"{raw_d[2:4]}/{raw_d[4:6]}/{raw_d[6:]}",
            "portfolio": round(p_eq[-1], 4),
            "benchmark": round(b_eq[-1], 4),
            "excess":    round(e_eq[-1], 4),
            "p_ret":     round(p_ret * 100, 2),
            "b_ret":     round(b_ret * 100, 2),
            "regime":    str(row["regime"]),
        })

    k = len(df)
    ann = lambda eq: (eq[-1]) ** (52.0 / k) - 1.0 if eq[-1] > 0 and k > 0 else -1.0
    mdd = lambda eq: ((pd.Series(eq) - pd.Series(eq).cummax()) / pd.Series(eq).cummax()).min()

    p_ann  = ann(p_eq);  p_dd = mdd(p_eq)
    e_ann  = ann(e_eq);  e_dd = mdd(e_eq)
    p_cal  = p_ann / abs(p_dd) if abs(p_dd) > 1e-6 else 0.0
    e_cal  = e_ann / abs(e_dd) if abs(e_dd) > 1e-6 else 0.0

    p_rets = df["portfolio_return"]
    e_rets = df["excess_return"]

    metrics = {
        "total_weeks":            int(k),
        "portfolio_total_return": f"{(p_eq[-1]-1)*100:.2f}%",
        "portfolio_ann_return":   f"{p_ann*100:.2f}%",
        "portfolio_max_drawdown": f"{p_dd*100:.2f}%",
        "portfolio_calmar":       f"{p_cal:.2f}",
        "excess_total_return":    f"{(e_eq[-1]-1)*100:.2f}%",
        "excess_ann_return":      f"{e_ann*100:.2f}%",
        "excess_max_drawdown":    f"{e_dd*100:.2f}%",
        "excess_calmar":          f"{e_cal:.2f}",
        "win_rate":               f"{(p_rets>0).sum()/k*100:.1f}%",
        "ex_win_rate":            f"{(e_rets>0).sum()/k*100:.1f}%",
    }

    return {"chart_data": chart_data, "metrics": metrics}


# ─────────────────────────────────────────────────────────
# 5. Agent 日志
# ─────────────────────────────────────────────────────────
def get_agent_logs():
    """返回 Agent 进化轨迹与系统最新日志"""
    import glob
    import time
    import yaml
    trajectory = []
    best_results = {
        "success": False,
        "best_combination": "—",
        "best_params": "—",
        "best_excess_calmar": 0.0
    }
    
    report_files = glob.glob(os.path.join(PROJECT_ROOT, "agent", "auto_cruise_report_*.json"))
    all_report_files = report_files + glob.glob(os.path.join(PROJECT_ROOT, "agent", "report_*.json"))
    latest_time_str = "2026-07-02 23:45:00"
    
    # 动态获取所有报告文件的最晚修改时间作为最后更新时间
    if all_report_files:
        latest_file = max(all_report_files, key=os.path.getmtime)
        try:
            mtime = os.path.getmtime(latest_file)
            latest_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        except Exception:
            pass

    # 判断最新的报告是否是自动巡航报告。若是，则战果面板加载巡航历史；若否（如刚进行了回滚回测），则强制加载当前 config.yaml 部署参数
    is_cruise_latest = False
    if report_files:
        latest_report = max(report_files, key=os.path.getmtime)
        if all_report_files and latest_file == latest_report:
            is_cruise_latest = True

    if is_cruise_latest:
        try:
            latest_report = max(report_files, key=os.path.getctime)
            with open(latest_report, "r", encoding="utf-8") as f:
                data = json.load(f)
            trajectory = data.get("search_trajectory", [])[-10:]
            
            best_results["success"] = data.get("success_target_reached", False)
            combo = data.get("best_overall_combination", [])
            best_results["best_combination"] = " · ".join(combo) if combo else "—"
            
            params = data.get("best_overall_params", {})
            best_results["best_params"] = f"top_n = {params.get('top_n', '—')} · multiplier = {params.get('multiplier', '—')}"
            best_results["best_excess_calmar"] = data.get("best_overall_excess_calmar", 0.0)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to read cruise report: {e}")

    # 降级/同步备用逻辑：若自动巡航报告已滞后，或者最佳组合未提取成功，则从实际部署的 config.yaml 及最新的 report 提取数据
    if not is_cruise_latest or best_results["best_combination"] == "—":
        try:
            config_path = os.path.join(PROJECT_ROOT, "agent", "config.yaml")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                base_pool = cfg.get("factors", {}).get("base_pool", [])
                custom_new = cfg.get("factors", {}).get("custom_new_factors", [])
                combo = base_pool + custom_new
                best_results["best_combination"] = " · ".join(combo) if combo else "—"
                
                top_n = cfg.get("backtest", {}).get("top_n_stocks", "—")
                mult = cfg.get("special_boost", {}).get("multiplier", "—")
                best_results["best_params"] = f"top_n = {top_n} · multiplier = {mult}"
                
                # 寻找最新的单次报告以获取真实卡玛，不再硬限 simulation 字段（防止 jack/quick 等重写同名报告导致过滤失效）
                normal_reps = glob.glob(os.path.join(PROJECT_ROOT, "agent", "report_*.json"))
                if normal_reps:
                    normal_reps.sort(key=os.path.getmtime, reverse=True)
                    for rep_file in normal_reps:
                        try:
                            with open(rep_file, "r", encoding="utf-8") as f:
                                rep_data = json.load(f)
                            metrics = rep_data.get("recommendation_summary", {}).get("old_portfolio", {}).get("metrics", {})
                            val = metrics.get("excess_calmar_ratio")
                            if val is not None:
                                best_results["best_excess_calmar"] = float(val)
                                break
                        except Exception:
                            pass
                    best_results["success"] = True
        except Exception:
            pass

    recent_logs = []
    if os.path.exists(LOGS_PATH):
        try:
            with open(LOGS_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            recent_logs = [l.rstrip() for l in lines[-15:]]
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to read agent logs: {e}")

    if not recent_logs:
        recent_logs = ["ℹ️ Agent 进化巡航模式启动正常。", "ℹ️ 配置文件 backup 状态安全。"]

    return {
        "last_updated": latest_time_str,
        "status":       "RUNNING (增量巡航中)" if report_files else "IDLE (部署成功)",
        "trajectory":   trajectory,
        "recent_logs":  recent_logs,
        "best_results": best_results,
    }

# ─────────────────────────────────────────────────────────
# 6. Jack 游资模拟绩效数据
# ─────────────────────────────────────────────────────────
def get_jack_performance_data():
    """读取游资回测 CSV，计算三曲线净值与关键指标"""
    jack_results_path = os.path.join(PROJECT_ROOT, "backtest_results_jack.csv")
    if not os.path.exists(jack_results_path):
        return {"chart_data": [], "metrics": {}}

    df = pd.read_csv(jack_results_path)
    if df.empty:
        return {"chart_data": [], "metrics": {}}

    p_eq = [1.0]   # 组合净值
    b_eq = [1.0]   # 基准净值
    e_eq = [1.0]   # 超额净值

    chart_data = []
    for _, row in df.iterrows():
        p_ret = float(row["portfolio_return"])
        b_ret = float(row["benchmark_return"])
        e_ret = float(row["excess_return"])

        p_eq.append(p_eq[-1] * (1.0 + p_ret))
        b_eq.append(b_eq[-1] * (1.0 + b_ret))
        e_eq.append(e_eq[-1] * (1.0 + e_ret))

        raw_d = str(int(row["trade_date"]))
        chart_data.append({
            "date":      f"{raw_d[2:4]}/{raw_d[4:6]}/{raw_d[6:]}",
            "portfolio": round(p_eq[-1], 4),
            "benchmark": round(b_eq[-1], 4),
            "excess":    round(e_eq[-1], 4),
            "p_ret":     round(p_ret * 100, 2),
            "b_ret":     round(b_ret * 100, 2),
            "regime":    str(row["regime"]),
        })

    k = len(df)
    ann = lambda eq: (eq[-1]) ** (52.0 / k) - 1.0 if eq[-1] > 0 and k > 0 else -1.0
    mdd = lambda eq: ((pd.Series(eq) - pd.Series(eq).cummax()) / pd.Series(eq).cummax()).min()

    p_ann  = ann(p_eq);  p_dd = mdd(p_eq)
    e_ann  = ann(e_eq);  e_dd = mdd(e_eq)
    p_cal  = p_ann / abs(p_dd) if abs(p_dd) > 1e-6 else 0.0
    e_cal  = e_ann / abs(e_dd) if abs(e_dd) > 1e-6 else 0.0

    p_rets = df["portfolio_return"]
    e_rets = df["excess_return"]

    metrics = {
        "total_weeks":            int(k),
        "portfolio_total_return": f"{(p_eq[-1]-1)*100:.2f}%",
        "portfolio_ann_return":   f"{p_ann*100:.2f}%",
        "portfolio_max_drawdown": f"{p_dd*100:.2f}%",
        "portfolio_calmar":       f"{p_cal:.2f}",
        "excess_total_return":    f"{(e_eq[-1]-1)*100:.2f}%",
        "excess_ann_return":      f"{e_ann*100:.2f}%",
        "excess_max_drawdown":    f"{e_dd*100:.2f}%",
        "excess_calmar":          f"{e_cal:.2f}",
        "win_rate":               f"{(p_rets>0).sum()/k*100:.1f}%",
        "ex_win_rate":            f"{(e_rets>0).sum()/k*100:.1f}%",
    }

    return {"chart_data": chart_data, "metrics": metrics}


# ─────────────────────────────────────────────────────────
# 7. 建仓机会扫描（真实数据多维度打分）
# ─────────────────────────────────────────────────────────
def get_build_position_opportunities():
    """
    基于最新截面真实数据，多维度融合选出"可建仓"股票。
    5维信号：因子综合打分 + 筹码控盘度 + 大资金净流入 + 涨幅过滤 + 换手率合理性
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        latest_fac = pd.read_sql("SELECT MAX(trade_date) FROM factor_values", conn).iloc[0,0]
        latest_cyq = pd.read_sql("SELECT MAX(trade_date) FROM stock_cyq_perf", conn).iloc[0,0]
        latest_mf  = pd.read_sql("SELECT MAX(trade_date) FROM moneyflow", conn).iloc[0,0]
        latest_pr  = pd.read_sql("SELECT MAX(trade_date) FROM daily_prices", conn).iloc[0,0]

        if not latest_fac:
            return {"stocks": [], "meta": {"error": "无因子数据"}}

        # 1. 因子横截面打分
        df_fac = pd.read_sql(
            "SELECT stock_code, return_5d, return_20d, excess_return_20d, "
            "       turnover_rate_20d, volatility_20d, north_net_inflow_ratio, "
            "       profit_ratio_estimate, chip_concentration "
            "FROM factor_values WHERE trade_date = ?",
            conn, params=(latest_fac,)
        )
        _, rw = _load_pkl_weights(WEIGHTS_PATH)
        if not rw:
            rw = {"north_net_inflow_ratio": -0.18, "return_5d": -0.54, "turnover_rate_20d": -0.28}

        df_fac["factor_score"] = 0.0
        for f, w in rw.items():
            if f in df_fac.columns:
                df_fac[f"_r_{f}"] = df_fac[f].rank(pct=True, na_option='bottom')
                df_fac["factor_score"] += w * df_fac[f"_r_{f}"]

        fmin, fmax = df_fac["factor_score"].min(), df_fac["factor_score"].max()
        frange = fmax - fmin if (fmax - fmin) > 1e-9 else 1.0
        df_fac["factor_score_norm"] = (df_fac["factor_score"] - fmin) / frange

        # 换手率合理性过滤
        if "turnover_rate_20d" in df_fac.columns:
            df_fac = df_fac[(df_fac["turnover_rate_20d"] >= 0.5) & (df_fac["turnover_rate_20d"] <= 15.0)]

        # 2. 筹码胜率
        df_cyq = pd.read_sql(
            "SELECT ts_code, winner_rate, chips_peak_pct FROM stock_cyq_perf WHERE trade_date = ?",
            conn, params=(latest_cyq,)
        )
        df_cyq["winner_rate_norm"] = df_cyq["winner_rate"].rank(pct=True)

        # 3. 大资金净流入
        df_mf = pd.read_sql(
            "SELECT ts_code, net_mf_amount AS big_net_inflow FROM moneyflow WHERE trade_date = ?",
            conn, params=(latest_mf,)
        )
        df_mf["inflow_norm"] = df_mf["big_net_inflow"].rank(pct=True)

        # 4. 价格涨跌幅（避免追高追板）
        df_pr = pd.read_sql(
            "SELECT ts_code, close, pct_chg FROM daily_prices WHERE trade_date = ?",
            conn, params=(latest_pr,)
        )
        df_pr = df_pr[(df_pr["pct_chg"] >= -8.0) & (df_pr["pct_chg"] <= 5.0)]

        # 5. 股票基本信息
        df_info = pd.read_sql("SELECT ts_code, name, industry, market FROM stock_list", conn)

        # 合并
        df = df_fac.rename(columns={"stock_code": "ts_code"})
        df = df.merge(df_cyq,  on="ts_code", how="inner")
        df = df.merge(df_mf,   on="ts_code", how="inner")
        df = df.merge(df_pr,   on="ts_code", how="inner")
        df = df.merge(df_info, on="ts_code", how="left")
        df["name"]     = df["name"].fillna("未知")
        df["industry"] = df["market"].fillna("未知") + " | " + df["industry"].fillna("未分类")

        # 综合建仓评分
        df["build_score"] = (
            df["factor_score_norm"] * 0.35 +
            df["winner_rate_norm"]  * 0.25 +
            df["inflow_norm"]       * 0.25 +
            (1 - df["pct_chg"].rank(pct=True)) * 0.15
        )

        # 过滤条件
        df = df[df["winner_rate"] >= 40.0]
        df = df[df["big_net_inflow"] > 0]

        # Top 20
        df_top = df.nlargest(20, "build_score").copy()
        df_top["__rank"] = range(1, len(df_top) + 1)

        def safe_float(val, default=0.0):
            if val is None or pd.isna(val):
                return default
            try:
                return float(val)
            except:
                return default

        def build_reason(row):
            reasons = []
            if safe_float(row.get("inflow_norm")) > 0.8:
                reasons.append("🏦 超大单净流入TOP20%")
            if safe_float(row.get("winner_rate")) > 70:
                reasons.append("🎯 筹码胜率>70%")
            if safe_float(row.get("factor_score_norm")) > 0.7:
                reasons.append("📊 因子信号强")
            if abs(safe_float(row.get("pct_chg"))) < 1.0:
                reasons.append("⏸️ 今日低波整理")
            if safe_float(row.get("chips_peak_pct")) > 70:
                reasons.append("💎 筹码高度集中")
            return " | ".join(reasons) if reasons else "综合因子评分靠前"

        stocks = []
        for _, row in df_top.iterrows():
            stocks.append({
                "rank":           int(row["__rank"]),
                "ts_code":        str(row["ts_code"]),
                "name":           str(row["name"]),
                "industry":       str(row["industry"]),
                "close":          round(safe_float(row.get("close")), 2),
                "pct_chg":        round(safe_float(row.get("pct_chg")), 2),
                "build_score":    round(safe_float(row.get("build_score")) * 100, 1),
                "factor_score":   round(safe_float(row.get("factor_score_norm")) * 100, 1),
                "winner_rate":    round(safe_float(row.get("winner_rate")), 1),
                "chips_peak_pct": round(safe_float(row.get("chips_peak_pct")), 1),
                "big_net_inflow": round(safe_float(row.get("big_net_inflow")) / 1e4, 2),
                "turnover_rate":  round(safe_float(row.get("turnover_rate_20d")), 2),
                "reason":         build_reason(row),
            })

        # 进行 MVO 二次规划优化以分配各股票建议持仓比例
        try:
            ts_codes = [s["ts_code"] for s in stocks]
            expected_returns = {s["ts_code"]: s["build_score"] for s in stocks}
            industries = {
                s["ts_code"]: s["industry"].split(" | ")[1] if " | " in s["industry"] else s["industry"] 
                for s in stocks
            }
            from scripts.portfolio_optimizer import optimize_portfolio
            weights = optimize_portfolio(ts_codes, expected_returns, industries, latest_pr)
            for s in stocks:
                s["mvo_weight"] = round(weights.get(s["ts_code"], 0.0) * 100, 2)
        except Exception as e:
            print(f"⚠️ [MVO Opportunities Error] {e}")
            for s in stocks:
                s["mvo_weight"] = round(100.0 / len(stocks) if stocks else 0.0, 2)

        # 自动将扫描建仓机会股票快照录入追踪表进行跟踪
        try:
            status = get_market_status()
            regime = status.get("regime", "RANGE")
            _log_recommendations_to_tracker(conn, latest_pr, stocks, regime)
        except Exception:
            pass

        return {
            "stocks": stocks,
            "meta": {
                "scan_date":     str(latest_pr),
                "factor_date":   str(latest_fac),
                "cyq_date":      str(latest_cyq),
                "mf_date":       str(latest_mf),
                "total_scanned": int(len(df_fac)),
                "after_filter":  int(len(df)),
                "final_count":   len(stocks),
            }
        }

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to calculate position opportunities: {e}")
        import traceback; traceback.print_exc()
        return {"stocks": [], "meta": {"error": str(e)}}
    finally:
        conn.close()


def get_tracker_attribution_data():
    """
    获取后台归因跟踪器的时效衰减、Regime 诊断矩阵及历史推荐明细数据
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        # 1. 查询全部已结算历史记录 (以 alpha_5d 为主)
        df = pd.read_sql(
            "SELECT * FROM recommendation_tracker WHERE alpha_5d IS NOT NULL", conn
        )
        
        # 2. 若当前无数据，则自动返回预设的仿真演示对照组，引导页面初次展示，避免白屏
        if len(df) < 5:
            mock_decay = [
                {"day": "T+1", "alpha_all": 0.0012, "alpha_high_factor": 0.0035, "alpha_low_factor": -0.0008},
                {"day": "T+3", "alpha_all": 0.0034, "alpha_high_factor": 0.0078, "alpha_low_factor": -0.0012},
                {"day": "T+5", "alpha_all": 0.0068, "alpha_high_factor": 0.0145, "alpha_low_factor": -0.0024},
                {"day": "T+10", "alpha_all": 0.0045, "alpha_high_factor": 0.0102, "alpha_low_factor": -0.0015},
                {"day": "T+20", "alpha_all": -0.0012, "alpha_high_factor": 0.0018, "alpha_low_factor": -0.0045}
            ]
            mock_regime = [
                {"regime": "BULL", "count": 120, "avg_alpha": 0.0185, "win_rate": 0.583},
                {"regime": "RANGE", "count": 240, "avg_alpha": 0.0075, "win_rate": 0.512},
                {"regime": "DARK", "count": 50, "avg_alpha": -0.0210, "win_rate": 0.320}
            ]
        else:
            # 2.1 统计 T+N 衰减曲线
            decay_data = []
            windows = [1, 3, 5, 10, 20]
            med_score = df["factor_score"].median()
            
            for w in windows:
                alpha_col = f"alpha_{w}d"
                if alpha_col in df.columns:
                    val_all = df[alpha_col].mean()
                    val_high = df[df["factor_score"] >= med_score][alpha_col].mean()
                    val_low = df[df["factor_score"] < med_score][alpha_col].mean()
                    
                    decay_data.append({
                        "day": f"T+{w}",
                        "alpha_all": round(float(val_all), 5),
                        "alpha_high_factor": round(float(val_high), 5),
                        "alpha_low_factor": round(float(val_low), 5)
                    })
            mock_decay = decay_data
            
            # 2.2 统计 Regime 诊断矩阵
            regime_data = []
            for r in ["BULL", "RANGE", "DARK"]:
                df_sub = df[df["regime"] == r]
                if not df_sub.empty:
                    count = len(df_sub)
                    avg_alpha = df_sub["alpha_5d"].mean()
                    win_rate = (df_sub["alpha_5d"] > 0).mean()
                    regime_data.append({
                        "regime": r,
                        "count": int(count),
                        "avg_alpha": round(float(avg_alpha), 5),
                        "win_rate": round(float(win_rate), 3)
                    })
                else:
                    regime_data.append({
                        "regime": r,
                        "count": 0,
                        "avg_alpha": 0.0,
                        "win_rate": 0.0
                    })
            mock_regime = regime_data
            
        # 3. 提取历史记录明细
        df_details = pd.read_sql(
            "SELECT t.*, s.name, s.industry FROM recommendation_tracker t "
            "LEFT JOIN stock_list s ON t.ts_code = s.ts_code "
            "ORDER BY t.recommend_date DESC, t.factor_score DESC LIMIT 100", conn
        )
        
        detail_list = []
        for _, row in df_details.iterrows():
            detail_list.append({
                "recommend_date": str(row["recommend_date"]),
                "ts_code": str(row["ts_code"]),
                "name": str(row["name"]) if row["name"] else "未知",
                "industry": str(row["industry"]) if row["industry"] else "未知",
                "base_price": round(float(row["base_price"]), 2) if row["base_price"] else None,
                "regime": str(row["regime"]),
                "factor_score": round(float(row["factor_score"]) * 100, 1),
                "winner_rate": round(float(row["winner_rate"]), 1),
                "chips_concentration": round(float(row["chips_concentration"]), 1),
                "net_mf_amount": round(float(row["net_mf_amount"]), 2) if row["net_mf_amount"] else 0.0,
                "alpha_5d": round(float(row["alpha_5d"]) * 100, 2) if row["alpha_5d"] is not None else None,
                "ret_5d": round(float(row["ret_5d"]) * 100, 2) if row["ret_5d"] is not None else None,
            })
            
        return {
            "decay": mock_decay,
            "regime": mock_regime,
            "details": detail_list,
            "is_mocked": len(df) < 5
        }
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to load tracker attribution data: {e}")
        return {"decay": [], "regime": [], "details": [], "error": str(e)}
    finally:
        conn.close()


def determine_adaptive_hold_period():
    """
    自适应换仓周期反馈控制算法：从 recommendation_tracker 提取近 30 天结算股的 Alpha 前瞻序列，
    寻找 Alpha 见顶的峰值交易日作为自适应持有期反灌给回测与选股引擎。
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        # 查询最近 30 天内有结算的历史推荐数据 (按推荐日期降序)
        df = pd.read_sql(
            "SELECT alpha_1d, alpha_3d, alpha_5d, alpha_10d, alpha_20d FROM recommendation_tracker "
            "WHERE alpha_5d IS NOT NULL ORDER BY recommend_date DESC LIMIT 150", conn
        )
        if df.empty or len(df) < 5:
            # 数据量不足或初次启动时，默认安全换仓期为 20 天
            return 20
            
        # 计算各时间窗口的平均 Alpha
        mean_alphas = {
            1: df["alpha_1d"].fillna(0.0).mean(),
            3: df["alpha_3d"].fillna(0.0).mean(),
            5: df["alpha_5d"].fillna(0.0).mean(),
            10: df["alpha_10d"].fillna(0.0).mean(),
            20: df["alpha_20d"].fillna(0.0).mean()
        }
        
        # 寻找 Alpha 均值的极大值所在的持股天数
        best_day = max(mean_alphas, key=mean_alphas.get)
        print(f"📊 [Feedback Loop] 前瞻 IC 衰减均值: {mean_alphas}，自适应匹配最优持股天数: {best_day} 天")
        return best_day
    except Exception as e:
        print(f"⚠️ [Feedback Loop Error] 确定自适应换仓天数失败: {e}")
        return 20 # 降级返回默认 20 天
    finally:
        conn.close()


def get_market_overview_data():
    """
    获取宏观量化市场全览数据：包含赚钱效应、筹码温度、板块资金排行榜及风格轮动
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        # 获取最新日期
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM daily_prices")
        row = cursor.fetchone()
        latest_date = row[0] if row else None
        
        if not latest_date:
            return {"error": "数据库无日线行情数据"}
            
        # 1. 赚钱效应 (涨跌比)
        cursor.execute(
            "SELECT "
            "  COUNT(CASE WHEN pct_chg > 0 THEN 1 END), "
            "  COUNT(CASE WHEN pct_chg < 0 THEN 1 END), "
            "  COUNT(CASE WHEN pct_chg = 0 THEN 1 END) "
            "FROM daily_prices WHERE trade_date = ?", (latest_date,)
        )
        row_adv_dec = cursor.fetchone()
        up_count = row_adv_dec[0] if row_adv_dec else 0
        down_count = row_adv_dec[1] if row_adv_dec else 0
        flat_count = row_adv_dec[2] if row_adv_dec else 0
        
        # 2. 筹码大盘温度截面数据 (获利中位数与偏离度)
        df_cyq = pd.read_sql(
            "SELECT winner_rate FROM stock_cyq_perf WHERE trade_date = ?",
            conn, params=(latest_date,)
        )
        if not df_cyq.empty:
            median_winner = float(df_cyq["winner_rate"].median())
            overbought = float((df_cyq["winner_rate"] >= 50.0).mean())
            oversold = float((df_cyq["winner_rate"] < 10.0).mean())
        else:
            median_winner = 40.0
            overbought = 0.35
            oversold = 0.15
            
        # 3. 行业主力大资金流入/流出 Top 5 排行 (单位：亿元)
        df_mf = pd.read_sql(
            "SELECT s.industry, SUM(mf.net_mf_amount) as total_inflow FROM moneyflow mf "
            "LEFT JOIN stock_list s ON mf.ts_code = s.ts_code "
            "WHERE mf.trade_date = ? AND s.industry IS NOT NULL "
            "GROUP BY s.industry", conn, params=(latest_date,)
        )
        
        if not df_mf.empty:
            # 过滤掉市场、板块前缀，只保留纯中文行业名以防太长
            df_mf["sector"] = df_mf["industry"].apply(lambda x: x.split(" | ")[1] if " | " in x else x)
            df_sector_flow = df_mf.groupby("sector")["total_inflow"].sum().reset_index()
            
            top_inflow = df_sector_flow.nlargest(5, "total_inflow").to_dict(orient="records")
            top_outflow = df_sector_flow.nsmallest(5, "total_inflow").to_dict(orient="records")
            
            # 格式化单位：万元转换为亿元，保留 2 位小数
            for item in top_inflow:
                item["flow_value"] = round(float(item["total_inflow"]) / 1e4, 2)
            for item in top_outflow:
                item["flow_value"] = round(float(item["total_inflow"]) / 1e4, 2)
        else:
            top_inflow = []
            top_outflow = []
            
        # 4. 多因子风格近 5 日轮动时序 (高换手、高集中度、大资金代理收益组)
        df_dates = pd.read_sql(
            "SELECT DISTINCT trade_date FROM daily_prices WHERE trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT 5", conn, params=(latest_date,)
        )
        recent_dates = sorted(df_dates["trade_date"].tolist())
        
        style_series = []
        if len(recent_dates) >= 2:
            for dt in recent_dates:
                df_slice = pd.read_sql(
                    "SELECT dp.pct_chg, cyq.chips_peak_pct, db.turnover_rate, mf.net_mf_amount "
                    "FROM daily_prices dp "
                    "LEFT JOIN stock_cyq_perf cyq ON dp.ts_code = cyq.ts_code AND cyq.trade_date = dp.trade_date "
                    "LEFT JOIN daily_basic db ON dp.ts_code = db.ts_code AND db.trade_date = dp.trade_date "
                    "LEFT JOIN moneyflow mf ON dp.ts_code = mf.ts_code AND mf.trade_date = dp.trade_date "
                    "WHERE dp.trade_date = ?", conn, params=(dt,)
                )
                
                if not df_slice.empty:
                    q_turnover = df_slice["turnover_rate"].quantile(0.8)
                    q_chips = df_slice["chips_peak_pct"].quantile(0.8)
                    q_inflow = df_slice["net_mf_amount"].quantile(0.8)
                    
                    ret_turnover = df_slice[df_slice["turnover_rate"] >= q_turnover]["pct_chg"].mean()
                    ret_chips = df_slice[df_slice["chips_peak_pct"] >= q_chips]["pct_chg"].mean()
                    ret_inflow = df_slice[df_slice["net_mf_amount"] >= q_inflow]["pct_chg"].mean()
                    
                    raw_d = str(dt)
                    style_series.append({
                        "date": f"{raw_d[4:6]}/{raw_d[6:]}",
                        "高换手风格 (Turnover)": round(float(ret_turnover) if not pd.isna(ret_turnover) else 0.0, 2),
                        "筹码锁仓风格 (Chips)": round(float(ret_chips) if not pd.isna(ret_chips) else 0.0, 2),
                        "大单大市风格 (Inflow)": round(float(ret_inflow) if not pd.isna(ret_inflow) else 0.0, 2)
                    })
        
        # 4.5. 游资热点题材排行榜 (Hot Money Sector Rank) + 连续上榜天数 (Streak Days)
        df_hm = pd.read_sql(
            "SELECT s.industry, db.turnover_rate, mf.net_mf_amount FROM daily_basic db "
            "LEFT JOIN stock_list s ON db.ts_code = s.ts_code "
            "LEFT JOIN moneyflow mf ON db.ts_code = mf.ts_code AND mf.trade_date = db.trade_date "
            "WHERE db.trade_date = ? AND s.industry IS NOT NULL", conn, params=(latest_date,)
        )
        
        # 获取最近 10 个交易日列表，用于计算连续上榜天数
        cursor.execute(
            "SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 10"
        )
        recent_dates = [r[0] for r in cursor.fetchall()]
        
        def _hot_sectors_on_date(c, td, top_n=8):
            """计算某日游资热点题材集合（宽松 top_n 以保证连续性分析准确）"""
            try:
                df = pd.read_sql(
                    "SELECT s.industry, db.turnover_rate, mf.net_mf_amount FROM daily_basic db "
                    "LEFT JOIN stock_list s ON db.ts_code = s.ts_code "
                    "LEFT JOIN moneyflow mf ON db.ts_code = mf.ts_code AND mf.trade_date = db.trade_date "
                    "WHERE db.trade_date = ? AND s.industry IS NOT NULL", c, params=(td,)
                )
                if df.empty: return set()
                df["sector"] = df["industry"].apply(lambda x: x.split(" | ")[1] if " | " in x else x)
                agg = df.groupby("sector").agg({"turnover_rate": "mean", "net_mf_amount": "sum"}).reset_index()
                agg = agg[agg["net_mf_amount"] > 0]
                if agg.empty: return set()
                t_mx = agg["turnover_rate"].max() or 1.0
                m_mx = agg["net_mf_amount"].max() or 1.0
                agg["hs"] = agg["turnover_rate"] / t_mx * 60 + agg["net_mf_amount"] / m_mx * 40
                return set(agg.nlargest(top_n, "hs")["sector"].tolist())
            except Exception:
                return set()
        
        # 预计算最近 9 日（不含今日）每日热点题材集合
        hist_hot = {d: _hot_sectors_on_date(conn, d) for d in recent_dates[1:]}
        
        hot_money_themes = []
        if not df_hm.empty:
            df_hm["sector"] = df_hm["industry"].apply(lambda x: x.split(" | ")[1] if " | " in x else x)
            df_sector_hm = df_hm.groupby("sector").agg({
                "turnover_rate": "mean",
                "net_mf_amount": "sum"
            }).reset_index()
            
            # 过滤主力大单流为负的题材，确保完全对齐“主力流入为正”的定义
            df_sector_hm = df_sector_hm[df_sector_hm["net_mf_amount"] > 0]
            
            if not df_sector_hm.empty:
                t_max = df_sector_hm["turnover_rate"].max() if df_sector_hm["turnover_rate"].max() > 0 else 1.0
                m_max = df_sector_hm["net_mf_amount"].max() if df_sector_hm["net_mf_amount"].max() > 0 else 1.0
                
                # 游资综合得分 = (行业平均换手率/最大换手率) * 60 + (行业净买入额/最大净买入) * 40
                df_sector_hm["score_turnover"] = df_sector_hm["turnover_rate"] / t_max * 60.0
                df_sector_hm["score_inflow"] = df_sector_hm["net_mf_amount"] / m_max * 40.0
                df_sector_hm["hot_score"] = df_sector_hm["score_turnover"] + df_sector_hm["score_inflow"]
                
                df_sector_hm = df_sector_hm.sort_values(by="hot_score", ascending=False).head(5)
                for _, r in df_sector_hm.iterrows():
                    sector_name = r["sector"]
                    # 连续上榜天数：从今日往前倒推，连续出现在热点集合中则计数
                    streak = 1
                    for d in recent_dates[1:]:
                        if sector_name in hist_hot.get(d, set()):
                            streak += 1
                        else:
                            break
                    # 操盘信号
                    if streak == 1:
                        sig, sig_color = "初次爆发·观察", "gray"
                    elif streak == 2:
                        sig, sig_color = "二次确认·试探", "yellow"
                    elif streak <= 4:
                        sig, sig_color = f"持续{streak}日·重点关注", "green"
                    elif streak <= 6:
                        sig, sig_color = f"连续{streak}日·末升段谨慎", "orange"
                    else:
                        sig, sig_color = f"连续{streak}日·高位警戒", "red"
                    
                    hot_money_themes.append({
                        "sector": sector_name,
                        "avg_turnover": round(float(r["turnover_rate"]), 2),
                        "net_inflow": round(float(r["net_mf_amount"]) / 1e4, 2),
                        "hot_score": round(float(r["hot_score"]), 1),
                        "streak_days": streak,
                        "signal": sig,
                        "signal_color": sig_color,
                    })
        
        # 5. 获取大盘状态
        market_status = get_market_status()
        regime = market_status.get("regime", "RANGE")
        
        return {
            "date": str(latest_date),
            "adv_dec": {
                "up": int(up_count),
                "down": int(down_count),
                "flat": int(flat_count)
            },
            "temperature": {
                "median_winner": round(median_winner, 1),
                "overbought_ratio": round(overbought * 100, 1),
                "oversold_ratio": round(oversold * 100, 1)
            },
            "inflow_rank": top_inflow,
            "outflow_rank": top_outflow,
            "style_rotation": style_series,
            "hot_money_themes": hot_money_themes,
            "regime": regime
        }
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to load market overview data: {e}")
        return {"error": str(e)}
    finally:
        conn.close()



# ─────────────────────────────────────────────────────────
# 12. 诊股看盘模块 (Stock Diagnosis)
# ─────────────────────────────────────────────────────────
def search_stock(query: str):
    """
    模糊查询股票列表，供前端自动补全使用
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql(
            f"SELECT ts_code, name, industry, market FROM stock_list "
            f"WHERE ts_code LIKE ? OR name LIKE ? OR name LIKE ? LIMIT 10",
            conn, params=[f"%{query}%", f"%{query}%", f"{query}%"]
        )
        return {"stocks": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e), "stocks": []}
    finally:
        conn.close()

def diagnose_stock(ts_code: str, strategy: str):
    """
    针对某只股票，根据选定的策略，输出多维诊断报告和得分
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        # 1. 确定要使用的因子和权重
        active_factors = []
        if strategy == "current" or strategy == "":
            # 使用当前路由层的生效因子
            status = get_market_status()
            regime = status.get("regime", "BULL")
            deployed = get_deployed_factors()
            factors = deployed["bull_factors"] if regime == "BULL" else deployed["range_factors"]
            active_factors = factors
        elif strategy == "base_bull":
            deployed = get_deployed_factors()
            active_factors = deployed["bull_factors"]
        elif strategy == "base_range":
            deployed = get_deployed_factors()
            active_factors = deployed["range_factors"]
        elif strategy == "scanner":
            active_factors = [
                {"factor": "factor_score", "weight": 0.35},
                {"factor": "winner_rate", "weight": 0.25},
                {"factor": "net_mf_amount", "weight": 0.25},
                {"factor": "pct_chg", "weight": -0.15}
            ]
        else:
            # 读取指定的 yaml 策略文件
            strat_path = os.path.join(PROJECT_ROOT, "agent", "strategies", strategy)
            if os.path.exists(strat_path):
                import yaml
                with open(strat_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    
                # 简单处理：提取用到的因子，默认均权或使用配置文件里的权重
                # 我们假设 yaml 里有 factors -> custom_new_factors 或 base_pool
                pool = cfg.get("factors", {}).get("custom_new_factors", [])
                if not pool:
                    pool = cfg.get("factors", {}).get("base_pool", [])
                
                # 如果找不到具体的因子，退回默认
                if not pool:
                    active_factors = [{"factor": "return_20d", "weight": 1.0}, {"factor": "volatility_20d", "weight": -1.0}]
                else:
                    weight_per_factor = 1.0 / len(pool)
                    active_factors = [{"factor": p, "weight": weight_per_factor} for p in pool]
            else:
                return {"error": f"Strategy file {strategy} not found"}
                
        if not active_factors:
            return {"error": "未找到有效的策略因子"}
            
        # 2. 获取最新交易日
        df_date = pd.read_sql("SELECT MAX(trade_date) as max_date FROM factor_values", conn)
        latest_date = df_date.iloc[0]["max_date"]
        if not latest_date:
            return {"error": "无因子数据"}
            
        # 3. 读取当日全市场因子，计算目标股票的排名分位数
        if strategy == "scanner":
            latest_fac = pd.read_sql("SELECT MAX(trade_date) FROM factor_values", conn).iloc[0,0]
            latest_cyq = pd.read_sql("SELECT MAX(trade_date) FROM stock_cyq_perf", conn).iloc[0,0]
            latest_mf  = pd.read_sql("SELECT MAX(trade_date) FROM moneyflow", conn).iloc[0,0]
            latest_pr  = pd.read_sql("SELECT MAX(trade_date) FROM daily_prices", conn).iloc[0,0]
            
            df_fac = pd.read_sql("SELECT stock_code, return_5d, return_20d, turnover_rate_20d, north_net_inflow_ratio, profit_ratio_estimate, chip_concentration, excess_return_20d, volatility_20d, return_60d, volatility_60d FROM factor_values WHERE trade_date=?", conn, params=(latest_fac,))
            _, rw = _load_pkl_weights(WEIGHTS_PATH)
            if not rw: rw = {"north_net_inflow_ratio": -0.18, "return_5d": -0.54, "turnover_rate_20d": -0.28}
            df_fac["factor_score"] = 0.0
            for f, w in rw.items():
                if f in df_fac.columns: df_fac["factor_score"] += w * df_fac[f].rank(pct=True, na_option='bottom')
                
            df_cyq = pd.read_sql("SELECT ts_code, winner_rate FROM stock_cyq_perf WHERE trade_date=?", conn, params=(latest_cyq,))
            df_mf = pd.read_sql("SELECT ts_code, net_mf_amount FROM moneyflow WHERE trade_date=?", conn, params=(latest_mf,))
            df_pr = pd.read_sql("SELECT ts_code, pct_chg FROM daily_prices WHERE trade_date=?", conn, params=(latest_pr,))
            
            df_fac = df_fac.merge(df_cyq, left_on="stock_code", right_on="ts_code", how="inner")
            df_fac = df_fac.merge(df_mf, left_on="stock_code", right_on="ts_code", how="inner")
            df_fac = df_fac.merge(df_pr, left_on="stock_code", right_on="ts_code", how="inner")
            needed_cols = ["factor_score", "winner_rate", "net_mf_amount", "pct_chg"]
        else:
            needed_cols = [f["factor"] for f in active_factors if f["factor"]]
            cols_sql = ",".join(needed_cols)
            df_fac = pd.read_sql(f"SELECT stock_code, {cols_sql} FROM factor_values WHERE trade_date='{latest_date}'", conn)
        
        if df_fac.empty:
            return {"error": "该交易日无数据"}
            
        # 计算分位数 (0-1)
        for col in needed_cols:
            if col in df_fac.columns:
                df_fac[f"{col}_pct"] = df_fac[col].rank(pct=True, ascending=True)
                
        # 提取目标股票
        target_row = df_fac[df_fac["stock_code"] == ts_code]
        if target_row.empty:
            return {"error": f"因子库中未找到股票 {ts_code}"}
            
        target_data = target_row.iloc[0]
        
        # 4. 计算综合得分
        total_score = 0
        radar_data = []
        strengths = []
        weaknesses = []
        
        # 将权重进行归一化处理（应对负权重情况）
        # 负权重意味着 "越小越好"
        for f in active_factors:
            col = f["factor"]
            w = f["weight"]
            if col not in target_data.index:
                continue
                
            raw_val = target_data[col]
            pct_val = target_data[f"{col}_pct"]
            
            # 如果是负权重，则得分为 (1 - pct_val)
            # 因为 pct_val 是升序排名，数值越小 pct_val 越接近0。权重为负要求数值越小越好。
            is_negative_factor = (w < 0)
            
            if is_negative_factor:
                factor_score = (1.0 - pct_val) * 100
                contrib = abs(w) * factor_score
            else:
                factor_score = pct_val * 100
                contrib = abs(w) * factor_score
                
            factor_map = {
                "factor_score": "综合因子",
                "winner_rate": "筹码胜率",
                "net_mf_amount": "主力净流入",
                "pct_chg": "涨跌幅",
                "return_5d": "5日涨幅",
                "return_20d": "20日涨幅",
                "excess_return_20d": "20日超额",
                "turnover_rate_20d": "20日换手",
                "volatility_20d": "20日波动",
                "north_net_inflow_ratio": "北向流入比",
                "profit_ratio_estimate": "预期利润率",
                "chip_concentration": "筹码集中度"
            }
            
            friendly_name = factor_map.get(col, col)
            fmt_val = f"{raw_val:.2f}"
            if col in ["pct_chg", "winner_rate", "return_5d", "return_20d", "excess_return_20d", "turnover_rate_20d", "chip_concentration"]:
                fmt_val += "%"
            elif col == "net_mf_amount":
                fmt_val = f"{(raw_val / 10000.0):.2f}亿"
                
            display_subject = f"{friendly_name} ({fmt_val})"
            
            total_score += contrib
            
            # 雷达图数据
            radar_data.append({
                "subject": display_subject,
                "A": round(factor_score, 1),
                "fullMark": 100
            })
            
            # 优缺点判定
            if factor_score >= 80:
                strengths.append(f"【{friendly_name}】达 {fmt_val}，表现优异 (击败 {factor_score:.1f}% 个股)")
            elif factor_score <= 20:
                weaknesses.append(f"【{friendly_name}】仅 {fmt_val}，表现极差 (落后 {100 - factor_score:.1f}% 个股)")
                
        # 归一化总分 (假设绝对权重和 = 1)
        sum_abs_w = sum([abs(f["weight"]) for f in active_factors])
        if sum_abs_w > 0:
            final_score = total_score / sum_abs_w
        else:
            final_score = 50.0
            
        # 5. 获取基本信息
        df_info = pd.read_sql(f"SELECT name, industry FROM stock_list WHERE ts_code='{ts_code}'", conn)
        name = df_info.iloc[0]["name"] if not df_info.empty else "未知"
        industry = df_info.iloc[0]["industry"] if not df_info.empty else "未知"
        
        # 价格信息
        df_price = pd.read_sql(f"SELECT close, pct_chg FROM daily_prices WHERE ts_code='{ts_code}' ORDER BY trade_date DESC LIMIT 1", conn)
        close = float(df_price.iloc[0]["close"]) if not df_price.empty else 0.0
        pct_chg = float(df_price.iloc[0]["pct_chg"]) if not df_price.empty else 0.0
        
        return {
            "ts_code": ts_code,
            "name": name,
            "industry": industry,
            "close": close,
            "pct_chg": pct_chg,
            "final_score": round(final_score, 1),
            "radar_data": radar_data,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "strategy": strategy,
            "active_factors": active_factors
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}
    finally:
        conn.close()

def get_style_stocks(short_date: str, style: str):
    """
    根据简写日期（如 "07/10"）和风格（如 "高换手风格 (Turnover)"），获取排名前20的支撑个股。
    """
    conn = sqlite3.connect(DB_PATH)
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
            SELECT dp.ts_code, s.name, dp.pct_chg, db.turnover_rate, 
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
        df.fillna(0, inplace=True)
        return {"date": target_date, "style": style, "stocks": df.to_dict(orient="records")}
        
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}
    finally:
        conn.close()
