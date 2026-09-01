# -*- coding: utf-8 -*-
"""
services.portrait —— T+1 画像分析 & 画像建仓决策（三层过滤漏斗）

* get_portrait_analysis(days=10)
    T+1 上涨画像分析：从最近 N 天推荐记录中，统计上涨/下跌组的因子/画像差异分布

* _batch_portrait_score(ts_codes)     [内部工具]
    对输入的 ts_code 列表批量输出画像分（无候选池前置过滤）

* get_portrait_position_pick(top_n=30, strategy="left")
    T+1 画像三层过滤漏斗：
      层一：portrait_score >= 50（右 45）
      层二：涨幅防追高 + 上影线防骗线 + 20日涨幅防透支
      层三：同细分行业保留最高一支（分散原则）
    返回 picks / funnel / meta，与原 services.py 签名完全一致。
"""

import logging
import pandas as pd
import numpy as np

from ._common import get_db_connection, DB_PATH, WEIGHTS_PATH, clean_nan_inf
from ._common import _get_factor_date, _get_restricted_stocks, _load_pkl_weights
from ._common import get_position_funnel_cfg, get_pick_reason_cfg   # S2：统一阈值
from .market_overview import get_market_overview_data

_logger = logging.getLogger(__name__)


def _safe_f(val, default=0.0):
    if val is None:
        return default
    try:
        v = float(val)
        return default if pd.isna(v) or np.isinf(v) else v
    except Exception:
        return default


def get_portrait_analysis(days: int = 10):
    """
    T+1 上涨画像分析：从最近 N 天推荐记录中，
    统计上涨/下跌组在各因子维度上的差异分布，
    供前端画像分析专属路由页面使用。

    返回：
        summary         : 汇总胜率与样本量
        daily_win_rate  : 每天胜率时序
        grade_stats     : 各画像等级（A/B/C/D）胜率分布
        factor_compare  : 上涨/下跌组关键因子均值对比
        score_buckets   : factor_score 分桶胜率
        wr_buckets      : winner_rate 分桶胜率
        chip_buckets    : chips_concentration 分桶胜率
        top_up_stocks   : 近期上涨组画像最佳股票样本
        top_dn_stocks   : 近期下跌组样本（用于反向参考）
    """
    try:
        from portrait_router import compute_portrait_score
        portrait_enabled = True
    except ImportError:
        portrait_enabled = False

    conn = get_db_connection(DB_PATH, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        df_rec = pd.read_sql(f"""
            SELECT r.recommend_date, r.ts_code,
                   r.regime, r.factor_score as score,
                   r.winner_rate, r.chips_concentration, r.net_mf_amount,
                   r.ret_1d, r.alpha_1d,
                   CASE WHEN r.ret_1d > 0 THEN 1 ELSE 0 END as is_up,
                   s.name, s.industry
            FROM recommendation_tracker r
            LEFT JOIN stock_list s ON r.ts_code = s.ts_code
            WHERE r.ret_1d IS NOT NULL
            ORDER BY r.recommend_date DESC
            LIMIT {days * 200}
        """, conn)

        if df_rec.empty:
            return {"error": "暂无结算数据，请等待推荐结算完成"}

        recent_dates = sorted(df_rec["recommend_date"].unique())[-days:]
        df_rec = df_rec[df_rec["recommend_date"].isin(recent_dates)]

        date_ph = ",".join([f"'{d}'" for d in recent_dates])
        codes   = df_rec["ts_code"].unique().tolist()
        code_ph = ",".join([f"'{c}'" for c in codes])
        df_fv = pd.read_sql(f"""
            SELECT trade_date as recommend_date, stock_code as ts_code,
                   profit_ratio_estimate, pe_ttm, hot_money_score,
                   return_5d, return_20d, return_60d,
                   chip_concentration, vol_ratio,
                   volatility_60d, north_net_inflow_ratio
            FROM factor_values
            WHERE trade_date IN ({date_ph})
              AND stock_code IN ({code_ph})
        """, conn)

        df = pd.merge(df_rec, df_fv, on=["recommend_date", "ts_code"], how="left")

        if portrait_enabled:
            portrait_scores = []
            portrait_grades = []
            for _, row in df.iterrows():
                chips_raw = float(row.get("chips_concentration") or 0)
                chips_pct = chips_raw * 100.0 if 0 < chips_raw < 1 else chips_raw
                res = compute_portrait_score(
                    factor_score           = float(row.get("score") or 0),
                    profit_ratio_estimate  = float(row.get("profit_ratio_estimate") or 0.5),
                    pe_ttm                 = float(row.get("pe_ttm") or 9999),
                    hot_money_score        = float(row.get("hot_money_score") or 0.5),
                    return_5d              = float(row.get("return_5d") or 0),
                    chips_concentration    = chips_pct,
                    volatility_60d         = float(row.get("volatility_60d") or 1.4),
                )
                portrait_scores.append(res["portrait_score"])
                portrait_grades.append(res["portrait_grade"])
            df["portrait_score"] = portrait_scores
            df["portrait_grade"] = portrait_grades
        else:
            df["portrait_score"] = 0.0
            df["portrait_grade"] = "N/A"

        total   = len(df)
        up_cnt  = int(df["is_up"].sum())
        dn_cnt  = total - up_cnt
        win_rate = round(float(df["is_up"].mean()), 4)
        avg_ret  = round(float(df["ret_1d"].mean()), 4)

        daily = df.groupby("recommend_date").agg(
            total=("is_up","count"),
            up=("is_up","sum"),
            avg_ret=("ret_1d","mean"),
            avg_score=("score","mean"),
            regime=("regime","first")
        ).reset_index()
        daily["win_rate"] = (daily["up"] / daily["total"]).round(4)
        daily["avg_ret"]  = daily["avg_ret"].round(4)
        daily_list = daily.to_dict(orient="records")

        factor_cols = ["score","winner_rate","chips_concentration",
                       "profit_ratio_estimate","pe_ttm","hot_money_score",
                       "return_5d","return_20d","return_60d",
                       "volatility_60d","north_net_inflow_ratio","vol_ratio"]
        up_df = df[df["is_up"] == 1]
        dn_df = df[df["is_up"] == 0]
        factor_compare = []
        for col in factor_cols:
            if col not in df.columns:
                continue
            up_m = float(up_df[col].mean()) if not up_df[col].isna().all() else 0.0
            dn_m = float(dn_df[col].mean()) if not dn_df[col].isna().all() else 0.0
            factor_compare.append({
                "factor": col,
                "up_mean": round(up_m, 4),
                "dn_mean": round(dn_m, 4),
                "diff":    round(up_m - dn_m, 4),
                "direction": "up_better" if up_m > dn_m else "dn_better",
            })

        grade_stats = []
        if portrait_enabled:
            for grade in ["A", "B", "C", "D"]:
                sub = df[df["portrait_grade"] == grade]
                if len(sub) == 0:
                    continue
                grade_stats.append({
                    "grade":    grade,
                    "total":    int(len(sub)),
                    "up":       int(sub["is_up"].sum()),
                    "win_rate": round(float(sub["is_up"].mean()), 4),
                    "avg_ret":  round(float(sub["ret_1d"].mean()), 4),
                })

        bins_score = [0, 0.6, 0.7, 0.8, 0.9, 1.01]
        labels_score = ["0-60%", "60-70%", "70-80%", "80-90%", "90-100%"]
        df["_score_bin"] = pd.cut(df["score"], bins=bins_score, labels=labels_score)
        score_buckets = df.groupby("_score_bin", observed=True).agg(
            total=("is_up","count"), up=("is_up","sum"), avg_ret=("ret_1d","mean")
        ).reset_index()
        score_buckets["win_rate"] = (score_buckets["up"] / score_buckets["total"]).round(4)
        score_buckets = score_buckets.rename(columns={"_score_bin": "bucket"})
        score_buckets_list = score_buckets.to_dict(orient="records")

        bins_wr = [0, 60, 70, 80, 90, 101]
        labels_wr = ["<60%", "60-70%", "70-80%", "80-90%", ">90%"]
        df["_wr_bin"] = pd.cut(df["winner_rate"], bins=bins_wr, labels=labels_wr)
        wr_buckets = df.groupby("_wr_bin", observed=True).agg(
            total=("is_up","count"), up=("is_up","sum"), avg_ret=("ret_1d","mean")
        ).reset_index()
        wr_buckets["win_rate"] = (wr_buckets["up"] / wr_buckets["total"]).round(4)
        wr_buckets = wr_buckets.rename(columns={"_wr_bin": "bucket"})
        wr_buckets_list = wr_buckets.to_dict(orient="records")

        bins_chip = [0, 75, 82, 90, 101]
        labels_chip = ["<75", "75-82", "82-90", ">90"]
        df["_chip_bin"] = pd.cut(df["chips_concentration"], bins=bins_chip, labels=labels_chip)
        chip_buckets = df.groupby("_chip_bin", observed=True).agg(
            total=("is_up","count"), up=("is_up","sum"), avg_ret=("ret_1d","mean")
        ).reset_index()
        chip_buckets["win_rate"] = (chip_buckets["up"] / chip_buckets["total"]).round(4)
        chip_buckets = chip_buckets.rename(columns={"_chip_bin": "bucket"})
        chip_buckets_list = chip_buckets.to_dict(orient="records")

        up_sample = up_df.sort_values("ret_1d", ascending=False).head(15)
        dn_sample = dn_df.sort_values("ret_1d", ascending=True).head(15)

        def to_sample_list(sub_df):
            rows = []
            for _, r in sub_df.iterrows():
                rows.append({
                    "ts_code":      str(r.get("ts_code", "")),
                    "name":         str(r.get("name", "未知")),
                    "industry":     str(r.get("industry", "")),
                    "recommend_date": str(r.get("recommend_date", "")),
                    "ret_1d":       round(float(r.get("ret_1d", 0)), 4),
                    "score":        round(float(r.get("score", 0)), 4),
                    "winner_rate":  round(float(r.get("winner_rate", 0)), 1),
                    "chips_concentration": round(float(r.get("chips_concentration", 0)), 1),
                    "profit_ratio_estimate": round(float(r.get("profit_ratio_estimate", 0)), 3),
                    "portrait_score": round(float(r.get("portrait_score", 0)), 1),
                    "portrait_grade": str(r.get("portrait_grade", "-")),
                })
            return rows

        return clean_nan_inf({
            "summary": {
                "total":    total,
                "up_count": up_cnt,
                "dn_count": dn_cnt,
                "win_rate": win_rate,
                "avg_ret_1d": avg_ret,
                "analysis_days": len(recent_dates),
                "date_range": f"{recent_dates[0]} ~ {recent_dates[-1]}" if recent_dates else "-",
            },
            "daily_win_rate":  daily_list,
            "grade_stats":     grade_stats,
            "factor_compare":  factor_compare,
            "score_buckets":   score_buckets_list,
            "wr_buckets":      wr_buckets_list,
            "chip_buckets":    chip_buckets_list,
            "top_up_stocks":   to_sample_list(up_sample),
            "top_dn_stocks":   to_sample_list(dn_sample),
            "portrait_enabled": portrait_enabled,
        }, default=0.0)
    except Exception as e:
        import traceback
        _logger.error(f"get_portrait_analysis error: {e}")
        return {"error": str(e), "traceback": traceback.format_exc()}
    finally:
        conn.close()


def _batch_portrait_score(ts_codes: list):
    """内部工具：对输入的 ts_code 列表批量输出画像分（无候选池前置过滤）"""
    if not ts_codes:
        return {"ts_codes": [], "results": {}}

    conn = get_db_connection(DB_PATH, timeout=60.0)
    try:
        try:
            from portrait_router import compute_portrait_score, compute_right_side_portrait_score
        except ImportError as e:
            return {"ts_codes": ts_codes, "results": {}, "error": f"portrait_router 导入失败: {e}"}

        factor_date = _get_factor_date(conn)
        if not factor_date:
            return {"ts_codes": ts_codes, "results": {}, "error": "无因子数据"}

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(trade_date) FROM daily_prices")
            price_date = cursor.fetchone()[0] or factor_date
            cursor.execute("SELECT MAX(trade_date) FROM stock_cyq_perf")
            cyq_date = cursor.fetchone()[0] or factor_date
        except Exception:
            price_date = factor_date
            cyq_date = factor_date

        codes_unique = list(dict.fromkeys(ts_codes))
        ph = ",".join(["?"] * len(codes_unique))

        df_fac = pd.read_sql(
            f"SELECT stock_code, return_5d, return_20d, return_60d, excess_return_20d, "
            f" turnover_rate_20d, volatility_20d, volatility_60d, vol_ratio, north_net_inflow_ratio, "
            f" profit_ratio_estimate, chip_concentration, pe_ttm, hot_money_score "
            f"FROM factor_values WHERE stock_code IN ({ph}) AND trade_date = ?",
            conn, params=codes_unique + [factor_date]
        ).rename(columns={"stock_code": "ts_code"})

        df_cyq = pd.read_sql(
            f"SELECT ts_code, winner_rate, chips_peak_pct FROM stock_cyq_perf "
            f"WHERE ts_code IN ({ph}) AND trade_date = ?",
            conn, params=codes_unique + [cyq_date]
        )

        results_map = {}
        for code in codes_unique:
            fr = df_fac[df_fac["ts_code"] == code].head(1)
            cr = df_cyq[df_cyq["ts_code"] == code].head(1)
            row_f = fr.iloc[0] if not fr.empty else pd.Series(dtype=float)
            row_c = cr.iloc[0] if not cr.empty else pd.Series(dtype=float)

            left_res = compute_portrait_score(
                factor_score          = _safe_f(row_f.get("profit_ratio_estimate"), 0.0) * 0.0
                    or _safe_f(row_f.get("return_5d"), 0.0) * 0.0 + 0.5,
                profit_ratio_estimate = _safe_f(row_f.get("profit_ratio_estimate"), 0.5),
                pe_ttm                = _safe_f(row_f.get("pe_ttm"), 9999.0),
                hot_money_score       = _safe_f(row_f.get("hot_money_score"), 0.5),
                return_5d             = _safe_f(row_f.get("return_5d"), 0.0),
                chips_concentration   = _safe_f(row_c.get("chips_peak_pct"), 0.0),
                volatility_60d        = _safe_f(row_f.get("volatility_60d"), 1.4),
            ) if not fr.empty else {
                "portrait_score": 0.0, "portrait_grade": "D", "portrait_label": "无数据", "portrait_details": {}
            }
            results_map[code] = left_res

        return clean_nan_inf({
            "factor_date": factor_date,
            "price_date":  price_date,
            "cyq_date":    cyq_date,
            "ts_codes":    codes_unique,
            "results":     results_map,
        }, default=0.0)
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# T+1 画像建仓决策路由层（三层过滤漏斗）—— 与原版 services.py 逐行对齐
# ═══════════════════════════════════════════════════════════════════
def get_portrait_position_pick(top_n: int = 30, strategy: str = "left"):
    try:
        from portrait_router import (
            compute_portrait_score, compute_right_side_portrait_score, _grade,
        )
    except ImportError as e:
        return {"picks": [], "funnel": {}, "meta": {"error": f"portrait_router 导入失败: {e}"}}

    conn = get_db_connection(DB_PATH, timeout=60.0)
    try:
        # ── 获取数据日期 ──────────────────────────────────────────────────
        latest_fac = _get_factor_date(conn)
        if not latest_fac:
            return {"picks": [], "funnel": {}, "meta": {"error": "无因子数据"}}
        latest_cyq = pd.read_sql("SELECT MAX(trade_date) FROM stock_cyq_perf", conn).iloc[0, 0]
        latest_mf  = pd.read_sql("SELECT MAX(trade_date) FROM moneyflow", conn).iloc[0, 0]
        latest_pr  = pd.read_sql("SELECT MAX(trade_date) FROM daily_prices", conn).iloc[0, 0]

        # ── 因子横截面打分（列名与 factor_values 严格对齐）──────────────────
        df_fac = pd.read_sql(
            "SELECT stock_code, return_5d, return_20d, return_60d, excess_return_20d, "
            "       turnover_rate_20d, volatility_20d, volatility_60d, vol_ratio, north_net_inflow_ratio, "
            "       profit_ratio_estimate, chip_concentration, pe_ttm, hot_money_score "
            "FROM factor_values WHERE trade_date = ?",
            conn, params=(latest_fac,)
        )

        restricted = _get_restricted_stocks(conn)
        if restricted:
            df_fac = df_fac[~df_fac["stock_code"].isin(restricted)]

        funnel_cfg = get_position_funnel_cfg()           # S2：加载统一阈值
        common_cfg = funnel_cfg["common"]

        if strategy == "right":
            rw = dict(common_cfg["default_factor_weights"])
        else:
            _, rw = _load_pkl_weights(WEIGHTS_PATH)
            if not rw:
                rw = dict(common_cfg["bear_factor_weights"])

        df_fac["factor_score"] = 0.0
        for f, w in rw.items():
            if f in df_fac.columns:
                df_fac[f"_r_{f}"] = df_fac[f].rank(pct=True, na_option="bottom")
                df_fac["factor_score"] += w * df_fac[f"_r_{f}"]

        fmin, fmax = df_fac["factor_score"].min(), df_fac["factor_score"].max()
        frange = fmax - fmin if (fmax - fmin) > 1e-9 else 1.0
        df_fac["factor_score_norm"] = (df_fac["factor_score"] - fmin) / frange

        if "turnover_rate_20d" in df_fac.columns:
            df_fac = df_fac[
                (df_fac["turnover_rate_20d"] >= 0.5) & (df_fac["turnover_rate_20d"] <= 15.0)
            ]

        df_cyq = pd.read_sql(
            "SELECT ts_code, winner_rate, chips_peak_pct FROM stock_cyq_perf WHERE trade_date = ?",
            conn, params=(latest_cyq,)
        )
        df_mf = pd.read_sql(
            "SELECT ts_code, net_mf_amount AS big_net_inflow FROM moneyflow WHERE trade_date = ?",
            conn, params=(latest_mf,)
        )
        df_pr = pd.read_sql(
            "SELECT ts_code, close, open, high, low, pct_chg FROM daily_prices WHERE trade_date = ?",
            conn, params=(latest_pr,)
        )
        df_info = pd.read_sql("SELECT ts_code, name, industry, market FROM stock_list", conn)

        df = df_fac.rename(columns={"stock_code": "ts_code"})
        df = df.merge(df_cyq,  on="ts_code", how="inner")
        df = df.merge(df_mf,   on="ts_code", how="inner")
        df = df.merge(df_pr,   on="ts_code", how="inner")
        df = df.merge(df_info, on="ts_code", how="left")

        df["name"]         = df["name"].fillna("未知")
        df["industry_raw"] = df["market"].fillna("") + " | " + df["industry"].fillna("未分类")
        df["sub_industry"] = df["industry"].fillna("未分类")

        # ── 综合建仓评分（左/右两套权重，与原硬编码 1:1 对齐） ─────────
        if strategy == "right":
            bsr = common_cfg["build_score_right"]
            df["winner_rate_score"] = df["winner_rate"].rank(pct=True)
            df["inflow_norm"]       = df["big_net_inflow"].rank(pct=True)
            df["build_score"] = (
                df["factor_score_norm"]        * float(bsr.get("factor_score_norm", 0.40)) +
                df["winner_rate_score"]        * float(bsr.get("winner_rate_rank",  0.25)) +
                df["inflow_norm"]              * float(bsr.get("inflow_norm",        0.25)) +
                df["pct_chg"].rank(pct=True)   * float(bsr.get("pct_chg_rank",      0.10))
            )
            df = df[df["winner_rate"] >= float(common_cfg.get("winner_rate_right_lo", 60.0))]
        else:
            bsl = common_cfg["build_score_left"]
            wr_dist = (df["winner_rate"] - 60.0).abs()
            df["winner_rate_score"] = (1.0 - (wr_dist / 35.0).clip(0, 1.0))
            df["inflow_norm"]       = df["big_net_inflow"].rank(pct=True)
            df["build_score"] = (
                df["factor_score_norm"]            * float(bsl.get("factor_score_norm", 0.45)) +
                df["winner_rate_score"]            * float(bsl.get("winner_rate_score", 0.25)) +
                df["inflow_norm"]                  * float(bsl.get("inflow_norm",       0.20)) +
                (1.0 - df["pct_chg"].rank(pct=True)) * float(bsl.get("pct_chg_rank_inv", 0.10))
            )
            df = df[
                (df["winner_rate"] >= float(common_cfg.get("winner_rate_lo", 25.0))) &
                (df["winner_rate"] <= float(common_cfg.get("winner_rate_hi", 85.0)))
            ]

        df = df[df["big_net_inflow"] > 0]
        df_pool = df.nlargest(top_n, "build_score").copy()
        layer0_total = len(df_pool)

        # ── 为 Top N 计算 T+1 画像分 ─────────────────────────────────────
        portrait_results = []
        for _, row in df_pool.iterrows():
            if strategy == "right":
                res = compute_right_side_portrait_score(
                    winner_rate     = _safe_f(row.get("winner_rate"), 0.0),
                    return_5d       = _safe_f(row.get("return_5d"), 0.0),
                    hot_money_score = _safe_f(row.get("hot_money_score"), 0.0),
                    inflow_norm     = _safe_f(row.get("inflow_norm"), 0.0),
                    chips_peak_pct  = _safe_f(row.get("chips_peak_pct"), 0.0),
                )
            else:
                res = compute_portrait_score(
                    factor_score          = _safe_f(row.get("factor_score_norm"), 0.0),
                    profit_ratio_estimate = _safe_f(row.get("profit_ratio_estimate"), 0.5),
                    pe_ttm                = _safe_f(row.get("pe_ttm"), 9999.0),
                    hot_money_score       = _safe_f(row.get("hot_money_score"), 0.5),
                    return_5d             = _safe_f(row.get("return_5d"), 0.0),
                    chips_concentration   = _safe_f(row.get("chips_peak_pct"), 0.0),
                    volatility_60d        = _safe_f(row.get("volatility_60d"), 1.4),
                )
            portrait_results.append(res)

        # ── 宏观大盘题材共振加分 ─────────────────────────────────────────
        macro_data = get_market_overview_data()
        hot_themes = macro_data.get("hot_money_themes", [])
        target_themes = {t["sector"]: t["streak_days"] for t in hot_themes if 2 <= t.get("streak_days", 0) <= 4}

        bonus_val     = float(common_cfg.get("portrait_bonus",     15.0))
        bonus_min_sc  = float(common_cfg.get("portrait_bonus_min", 75.0))
        for i, (idx, row) in enumerate(df_pool.iterrows()):
            sub_ind = str(row.get("sub_industry", ""))
            res = portrait_results[i]
            if sub_ind in target_themes:
                streak = target_themes[sub_ind]
                new_score = min(100.0, res["portrait_score"] + bonus_val)
                res["portrait_score"] = new_score
                grade, label = _grade(new_score)
                res["portrait_grade"] = grade
                res["portrait_label"] = label
                res["portrait_details"]["题材共振"] = f"🔥 +{bonus_val:.0f}分 ({sub_ind}连续{streak}日爆发)"

        df_pool = df_pool.copy()
        df_pool["portrait_score"]   = [r["portrait_score"]   for r in portrait_results]
        df_pool["portrait_grade"]   = [r["portrait_grade"]   for r in portrait_results]
        df_pool["portrait_label"]   = [r["portrait_label"]   for r in portrait_results]
        df_pool["portrait_details"] = [r["portrait_details"] for r in portrait_results]

        # 层一：portrait_score 阈值（S2：从 funnel_cfg 读取）
        layer1_cfg = funnel_cfg["layer1"]
        if strategy == "right":
            l1_threshold  = float(layer1_cfg.get("right_threshold",  45.0))
            grade_threshold = str(layer1_cfg.get("right_grade_label", "等级 ≥ C+"))
        else:
            l1_threshold  = float(layer1_cfg.get("left_threshold",   50.0))
            grade_threshold = str(layer1_cfg.get("left_grade_label",  "等级 ≥ B/C+"))
        mask_l1 = df_pool["portrait_score"] >= l1_threshold
        df_l1_pass   = df_pool[mask_l1].copy()
        df_l1_reject = df_pool[~mask_l1].copy()
        l1_remark    = f"portrait_score >= {l1_threshold}（{grade_threshold}）"

        # 层二：今日涨幅过滤 + K 线防骗线（S2：从 funnel_cfg 读取）
        layer2_cfg = funnel_cfg["layer2"]
        l2_cfg_s   = layer2_cfg.get(strategy, layer2_cfg["left"])
        pct_max    = float(l2_cfg_s.get("pct_chg_max",      4.5))
        ush_max    = float(l2_cfg_s.get("upper_shadow_max", 0.035))
        r20_max    = float(l2_cfg_s.get("return_20d_max",   0.25))

        df_l1_pass = df_l1_pass.copy()
        df_l1_pass["upper_shadow"] = (df_l1_pass["high"] - df_l1_pass[["open", "close"]].max(axis=1)) / df_l1_pass[["open", "close"]].max(axis=1)
        mask_l2 = (df_l1_pass["pct_chg"] <= pct_max) & (df_l1_pass["upper_shadow"] <= ush_max) & (df_l1_pass["return_20d"] <= r20_max)

        def _rr2(row, _pm=pct_max, _um=ush_max, _rm=r20_max, _s=strategy):
            if row["return_20d"] > _rm:
                return f"20日涨幅 {row['return_20d']*100:.1f}% > {_rm*100:.0f}% (高位接盘风险)" if _s=="right" \
                  else f"20日涨幅 {row['return_20d']*100:.1f}% > {_rm*100:.0f}% (中位透支风险)"
            if row["upper_shadow"] > _um:
                return f"上影线 {row['upper_shadow']*100:.1f}% > {_um*100:.1f}% (冲高回落防骗线)"
            return (f"今日涨幅 +{row['pct_chg']:.2f}% > {_pm:.1f}% (追高/烂板风险)" if _s=="right"
                   else f"今日涨幅 +{row['pct_chg']:.2f}% > {_pm:.1f}% (追高风险)")
        df_l1_pass["reject_reason_l2"] = df_l1_pass.apply(_rr2, axis=1)
        df_l2_pass   = df_l1_pass[mask_l2].copy()
        df_l2_reject = df_l1_pass[~mask_l2].copy()

        # 层三：同细分行业按 max_per_sector 控制（S2：从 funnel_cfg 读取，默认 1）
        layer3_cfg = funnel_cfg["layer3"]
        max_per_sec = int(layer3_cfg.get("max_per_sector", 1))
        final_top_n = int(layer3_cfg.get("final_pick_top_n", 5))

        df_l2_sorted = df_l2_pass.sort_values("portrait_score", ascending=False)
        if max_per_sec <= 1:
            df_l3_pass = df_l2_sorted.drop_duplicates(subset=["sub_industry"], keep="first").copy()
        else:
            df_l3_parts = []
            for _, grp in df_l2_sorted.groupby("sub_industry", sort=False):
                df_l3_parts.append(grp.head(max_per_sec))
            df_l3_pass = pd.concat(df_l3_parts).copy() if df_l3_parts else df_l2_sorted.iloc[0:0].copy()
        df_l3_reject = df_l2_sorted[~df_l2_sorted.index.isin(df_l3_pass.index)].copy()

        # ── 最终精选 Top N ──
        df_picks_pre = df_l3_pass.sort_values("portrait_score", ascending=False).head(final_top_n).copy()

        # ── S3 (Phase 3 组合构建)：因子过滤 + 等权目标 + 多周滚动换手率平滑 ──
        _s3_applied = False
        _s3_meta = None
        try:
            import sys, os
            # services/portrait.py 深度 = 3层：root → web → backend → services → portrait.py
            _src_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                "src",
            )
            _proj_root = os.path.dirname(_src_path)
            if _src_path  not in sys.path: sys.path.insert(0, _src_path)
            if _proj_root not in sys.path: sys.path.insert(0, _proj_root)
            from portfolio_constructor import construct_portfolio

            # 与 construct_portfolio 对齐列名
            df_s3_in = df_picks_pre.rename(columns={"ts_code": "ts_code"}).copy()
            if "factor_score_norm" not in df_s3_in.columns and "factor_score" in df_s3_in.columns:
                df_s3_in["factor_score_norm"] = pd.to_numeric(df_s3_in["factor_score"], errors="coerce").fillna(0.0)
            if "build_score" not in df_s3_in.columns:
                df_s3_in["build_score"] = pd.to_numeric(
                    df_s3_in.get("factor_score_norm", 0), errors="coerce"
                ).fillna(0.0)

            df_s3, s3_stats = construct_portfolio(
                df_s3_in,
                max_turnover         = 0.50,
                max_weight           = 0.30,
                conn                 = conn,
                current_date         = str(latest_pr) if latest_pr else None,
                strategy             = strategy,
                drop_grade_d         = True,
                factor_tail_quantile = 0.05,
                min_portfolio_size   = max(1, final_top_n - 2),
                final_max_size       = final_top_n,
            )

            # 对齐回 picks：只保留过滤通过且加权输出的行
            df_kept = df_s3[
                df_s3["dropped_reason"].fillna("").eq("") &
                pd.to_numeric(df_s3["blended_weight"], errors="coerce").fillna(0) > 0
            ].copy()

            if not df_kept.empty:
                df_kept = df_kept.sort_values("portrait_score", ascending=False).reset_index(drop=True)
                df_kept["pick_rank"] = range(1, len(df_kept) + 1)
                # 兼容老契约：suggested_weight 使用 blended_weight_pct (1/N + 滚动平滑)
                df_kept["suggested_weight"] = pd.to_numeric(
                    df_kept["blended_weight_pct"], errors="coerce"
                ).fillna(round(100.0 / max(len(df_kept), 1), 1))
                # 将 Phase 3 元信息追加为 pick 附加列（不破坏老契约，序列化但老 key 仍在）
                for col in ["target_weight", "prev_weight", "blended_weight", "delta_weight"]:
                    df_kept[f"s3_{col}"] = pd.to_numeric(df_kept[col], errors="coerce").round(6)
                df_kept["_s3_applied"] = True
                df_picks = df_kept
                _s3_stats_meta = s3_stats
            else:
                # Phase 3 过滤后为空 → 退回 df_picks_pre 并使用均权
                df_picks = df_picks_pre.copy()
                df_picks["pick_rank"] = range(1, len(df_picks) + 1)
                df_picks["suggested_weight"] = round(100.0 / max(len(df_picks), 1), 1)
                _s3_stats_meta = {"phase": "Phase 3 fallback (过滤后空，退回均权)", **(s3_stats or {})}

        except Exception as _s3_err:
            _logger.warning(f"[portrait_pick] Phase3 construct_portfolio 降级: {_s3_err}")
            # 降级：S3 失败则退回 df_picks_pre，使用均权（原逻辑虽然是画像分比例，但均权是更稳的默认）
            df_picks = df_picks_pre.copy()
            df_picks["pick_rank"] = range(1, len(df_picks) + 1)
            df_picks["suggested_weight"] = round(100.0 / max(len(df_picks), 1), 1)
            _s3_stats_meta = {"phase": "Phase 3 EXCEPTION fallback (均权)", "error": str(_s3_err)}

        def _reason(row):
            # S2: 从配置读取理由触发阈值
            _rc = get_pick_reason_cfg()
            _lh = float(_rc.get("left_high", 18))
            _la = float(_rc.get("left_active", 18))
            _rh = float(_rc.get("right_high", 18))
            _ra = float(_rc.get("right_active", 15))
            _ga = str(_rc.get("grade_A_reason", "A级画像"))
            _gb = str(_rc.get("grade_B_reason", "B级画像"))

            parts, grade, d = [], str(row.get("portrait_grade", "")), row.get("portrait_details") or {}
            if grade == "A": parts.append(f"🔥 {_ga}")
            elif grade == "B": parts.append(f"✅ {_gb}")
            if d.get("位置分", 0) >= _lh or d.get("突破分", 0) >= _rh:
                parts.append("上方无压" if strategy == "right" else "低位筹码")
            if d.get("动能分", 0) >= _ra: parts.append("动能强劲")
            if d.get("估值分", 0) >= _lh: parts.append("估值合理")
            if d.get("温度分", 0) >= _la or d.get("活跃分", 0) >= _ra:
                parts.append("资金活跃" if strategy == "right" else "游资未过热")
            if d.get("筹码分", 0) >= _lh or d.get("集中分", 0) >= _ra: parts.append("筹码集中")
            if d.get("因子分", 0) >= _lh or d.get("流入分", 0) >= _ra:
                parts.append("主力流入" if strategy == "right" else "因子极强")
            return " · ".join(parts) if parts else "综合画像评分靠前"

        def _to_pick(row):
            return {
                "pick_rank":        int(row["pick_rank"]),
                "ts_code":          str(row["ts_code"]),
                "name":             str(row["name"]),
                "industry":         str(row["industry_raw"]),
                "sub_industry":     str(row["sub_industry"]),
                "portrait_score":   round(_safe_f(row.get("portrait_score")), 1),
                "portrait_grade":   str(row.get("portrait_grade", "")),
                "portrait_label":   str(row.get("portrait_label", "")),
                "portrait_details": dict(row.get("portrait_details") or {}),
                "pct_chg":          round(_safe_f(row.get("pct_chg")), 2),
                "close":            round(_safe_f(row.get("close")), 2),
                "build_score":      round(_safe_f(row.get("build_score")) * 100, 1),
                "factor_score":     round(_safe_f(row.get("factor_score_norm")) * 100, 1),
                "winner_rate":      round(_safe_f(row.get("winner_rate")), 1),
                "chips_peak_pct":   round(_safe_f(row.get("chips_peak_pct")), 1),
                "big_net_inflow":   round(_safe_f(row.get("big_net_inflow")) / 1e4, 2),
                "suggested_weight": round(_safe_f(row.get("suggested_weight")), 1),
                "pick_reason":      _reason(row),
                # S3 Phase 3 附加列（非破坏性向后兼容扩展）
                "s3_target_weight":  round(_safe_f(row.get("s3_target_weight"), 0.0), 6),
                "s3_prev_weight":    round(_safe_f(row.get("s3_prev_weight"),   0.0), 6),
                "s3_blended_weight": round(_safe_f(row.get("s3_blended_weight"),0.0), 6),
                "s3_delta_weight":   round(_safe_f(row.get("s3_delta_weight"),  0.0), 6),
                "s3_applied":        bool(row.get("_s3_applied", False)),
            }

        def _to_reject(row, reject_reason):
            return {
                "ts_code":        str(row["ts_code"]),
                "name":           str(row["name"]),
                "industry":       str(row["industry_raw"]),
                "sub_industry":   str(row["sub_industry"]),
                "portrait_score": round(_safe_f(row.get("portrait_score")), 1),
                "portrait_grade": str(row.get("portrait_grade", "")),
                "pct_chg":        round(_safe_f(row.get("pct_chg")), 2),
                "reject_reason":  reject_reason,
            }

        picks      = [_to_pick(r) for _, r in df_picks.iterrows()]
        l1_rejects = [_to_reject(r, f"画像分 {round(_safe_f(r.get('portrait_score')),1)} < {l1_threshold}（低于合格线·画像不符）")
                      for _, r in df_l1_reject.iterrows()]
        l2_rejects = [_to_reject(r, r.get("reject_reason_l2", "条件不符")) for _, r in df_l2_reject.iterrows()]
        l3_rejects = [_to_reject(r, f"同行业「{r['sub_industry']}」已有更高分候选（行业分散原则）")
                      for _, r in df_l3_reject.iterrows()]

        return {
            "picks": picks,
            "funnel": {
                "layer0_total":   layer0_total,
                "layer1_pass":    len(df_l1_pass),
                "layer2_pass":    len(df_l2_pass),
                "layer3_pass":    len(df_picks),
                "layer1_threshold": l1_threshold,
                "layer1_remark":  l1_remark,
                "strategy":       strategy,
                "layer1_reject":  l1_rejects,
                "layer2_reject":  l2_rejects,
                "layer3_reject":  l3_rejects,
            },
            "meta": {
                "scan_date":     str(latest_pr),
                "factor_date":   str(latest_fac),
                "cyq_date":      str(latest_cyq),
                "top_n_scanned": layer0_total,
                "strategy":      strategy,
                "portfolio":     _s3_stats_meta,  # S3：Phase 3 过滤+等权+滚动 元信息
            }
        }
    except Exception as e:
        import traceback
        _logger.error(f"get_portrait_position_pick error: {e}")
        return {"picks": [], "funnel": {}, "meta": {"error": str(e), "traceback": traceback.format_exc()}}
    finally:
        conn.close()
