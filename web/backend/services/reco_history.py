# -*- coding: utf-8 -*-
"""
services.reco_history —— 今日策略推荐统计层（零侵入新增，不触碰 scan_history 任何逻辑）
====================================================================================
数据源：recommendation_tracker 表（get_today_portfolio() 每次调用自动落库，
        即"胜率猎手优化器"已部署策略的每日推荐名单；scripts/tracker_updater.py 回填前瞻收益）。
对外：get_reco_history()  输出结构与 /api/scan-history 对齐（summary / streak / daily / meta），
      前端可直接复用 scanner/shared.jsx 的展示组件。

字段约定（tracker 原始单位 → 输出单位）：
  factor_score  0-1 归一值        → factor_score / avg_factor = 0-100 分
  net_mf_amount 万元              → big_net_inflow = 亿元
  alpha_5d      小数超额收益      → alpha_5d_pct = 百分数（保留 2 位）
"""

import datetime
import logging

import pandas as pd

from ._common import DB_PATH

_logger = logging.getLogger(__name__)

# 策略归属标签（今日推荐名单的生成策略）
STRATEGY_LABEL = "胜率猎手优化器"


def get_reco_history(days: int = 30, min_appear: int = 1) -> dict:
    """
    今日策略推荐名单的累计统计。

    参数：
        days       -- 查询最近 N 个自然日（默认 30，上限 365）
        min_appear -- 频率排行最小上榜次数门槛（默认 1）

    返回：
        {
            "strategy": "胜率猎手优化器",
            "summary": 上榜频率排行（出现次数/均排名/均因子分/5日超额胜率/均5日超额）,
            "daily":   按日期分组的每日推荐快照,
            "streak":  当前连续上榜天数 >= 2 的排行,
            "meta":    {days, total_records, date_from, date_latest, unique_stocks,
                        reco_days, scan_days, strategy}
        }
    """
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    try:
        days = max(1, min(int(days or 30), 365))
        min_appear = max(1, int(min_appear or 1))
        date_from = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")

        empty_meta = {
            "days": days, "total_records": 0, "date_from": date_from,
            "date_latest": "", "unique_stocks": 0, "reco_days": 0, "scan_days": 0,
            "strategy": STRATEGY_LABEL,
        }
        try:
            df = pd.read_sql(
                "SELECT t.recommend_date, t.ts_code, t.regime, t.factor_score, "
                "t.winner_rate, t.net_mf_amount, t.alpha_5d, "
                "s.name, s.industry "
                "FROM recommendation_tracker t "
                "LEFT JOIN stock_list s ON t.ts_code = s.ts_code "
                "WHERE t.recommend_date >= ? "
                "ORDER BY t.recommend_date DESC, t.factor_score DESC",
                conn, params=(date_from,)
            )
        except Exception as e:
            _logger.warning(f"[reco_history] 查询失败: {e}")
            df = pd.DataFrame()

        if df.empty:
            return {"strategy": STRATEGY_LABEL, "summary": [], "daily": {}, "streak": [],
                    "meta": empty_meta}

        # ── 字段规整 ──
        df["name"] = df["name"].fillna("未知")
        df["industry"] = df["industry"].fillna("未分类")
        # factor_score 0-1 → 0-100 分（与扫描历史 factor_score_pct 同口径）
        df["factor_score"] = (pd.to_numeric(df["factor_score"], errors="coerce").fillna(0) * 100).round(1)
        # 净流入 万元 → 亿元
        df["big_net_inflow"] = (pd.to_numeric(df["net_mf_amount"], errors="coerce").fillna(0) / 1e4).round(2)
        df["winner_rate"] = pd.to_numeric(df["winner_rate"], errors="coerce")
        df["alpha_5d_pct"] = (pd.to_numeric(df["alpha_5d"], errors="coerce") * 100).round(2)

        def _none_if_nan(v):
            return None if v is None or (isinstance(v, float) and v != v) else v
        # 每日推荐排名：当日按 factor_score 降序（SQL 已排序，直接重编号）
        df["rank"] = df.groupby("recommend_date").cumcount() + 1

        all_dates = sorted(df["recommend_date"].unique(), reverse=True)

        # ── A. 上榜频率排行（Summary）──
        grp = df.groupby("ts_code").agg(
            name=("name", "last"),
            industry=("industry", "last"),
            appear_count=("recommend_date", "count"),
            avg_rank=("rank", "mean"),
            avg_factor=("factor_score", "mean"),
            avg_inflow=("big_net_inflow", "mean"),
            last_date=("recommend_date", "max"),
        ).reset_index()

        # 5 日超额：胜率与均值（仅统计已有回填结果的样本，不虚构）
        a5 = df[df["alpha_5d_pct"].notna()].groupby("ts_code")["alpha_5d_pct"].agg(["count", "mean"])
        a5_win = df[df["alpha_5d_pct"] > 0].groupby("ts_code")["alpha_5d_pct"].count()
        grp = grp.merge(a5, on="ts_code", how="left")
        grp = grp.merge(a5_win.rename("win_cnt"), on="ts_code", how="left")
        grp["alpha_5d_samples"] = grp["count"].fillna(0).astype(int)
        grp["avg_alpha_5d"] = grp["mean"].round(2)
        grp["win_rate_5d"] = [
            round(w / n * 100, 1) if n else None
            for w, n in zip(grp["win_cnt"].fillna(0), grp["alpha_5d_samples"])
        ]
        grp = grp.drop(columns=["count", "mean", "win_cnt"])

        # 最近一次上榜的排名
        def _last_rank(sub):
            try:
                m = sub["recommend_date"].idxmax()
                return int(sub.loc[m, "rank"])
            except Exception:
                return int(sub["rank"].min() if len(sub) else 0)
        lr = [{"ts_code": c, "last_rank": _last_rank(sub)} for c, sub in df.groupby("ts_code")]
        grp = grp.merge(pd.DataFrame(lr), on="ts_code", how="left")

        grp = grp[grp["appear_count"] >= min_appear]
        grp = grp.sort_values(["appear_count", "avg_rank"], ascending=[False, True])
        grp["avg_rank"] = grp["avg_rank"].round(1)
        grp["avg_factor"] = grp["avg_factor"].round(1)
        grp["avg_inflow"] = grp["avg_inflow"].round(2)
        # NaN → None 必须在 to_dict 之后的原生 dict 上做（DataFrame 列赋值会把 None 强转回 NaN）
        summary = [
            {k: _none_if_nan(v) for k, v in r.items()}
            for r in grp.to_dict(orient="records")
        ]

        # ── B. 每日推荐快照（Daily）──
        daily = {}
        for d in all_dates:
            rows = df[df["recommend_date"] == d].drop(
                columns=["recommend_date", "alpha_5d", "net_mf_amount"], errors="ignore")
            daily[d] = [
                {k: _none_if_nan(v) for k, v in r.items()}
                for r in rows.to_dict(orient="records")
            ]

        # ── C. 连续上榜天数排行（Streak，与 scan_history 同算法）──
        # 当前连续 = 从窗口内最新推荐日起向前连续；另给期内最长连续（推荐名单日度轮换快，
        # 仅看当前连续经常为空，最长连续更具统计意义）
        streak_map, max_streak_map = {}, {}
        for stock in df["ts_code"].unique():
            dates_of_stock = sorted(
                (d for d in df[df["ts_code"] == stock]["recommend_date"].unique()),
                reverse=True)
            dates_set = set(dates_of_stock)
            date_rank = {d: i for i, d in enumerate(all_dates)}
            # 当前连续：从窗口内最新推荐日起逐日核对
            streak = 0
            for d in all_dates:
                if d in dates_set:
                    streak += 1
                else:
                    break
            streak_map[stock] = streak
            # 期内最长连续（ds 为降序，后者 rank 更大 → 用后减前）
            best = cur = 1
            for j in range(1, len(dates_of_stock)):
                if date_rank[dates_of_stock[j]] - date_rank[dates_of_stock[j - 1]] == 1:
                    cur += 1
                else:
                    cur = 1
                best = max(best, cur)
            max_streak_map[stock] = best if dates_of_stock else 0
        streak_df = df[["ts_code", "name", "industry"]].drop_duplicates("ts_code").copy()
        streak_df["streak_days"] = streak_df["ts_code"].map(streak_map)
        streak_df["max_streak_days"] = streak_df["ts_code"].map(max_streak_map)
        streak_df["appear_count"] = streak_df["ts_code"].map(df.groupby("ts_code")["recommend_date"].count())
        streak_df["last_date"] = streak_df["ts_code"].map(
            df.groupby("ts_code")["recommend_date"].max())
        streak_df = streak_df.sort_values(
            ["streak_days", "max_streak_days", "appear_count"], ascending=[False, False, False])
        streak_list = [
            {k: _none_if_nan(v) for k, v in r.items()}
            for r in streak_df[streak_df["max_streak_days"] >= 2].to_dict(orient="records")
        ]

        return {
            "strategy": STRATEGY_LABEL,
            "summary": summary,
            "daily": daily,
            "streak": streak_list,
            "meta": {
                "days": days,
                "total_records": len(df),
                "date_from": date_from,
                "date_latest": all_dates[0] if all_dates else "",
                "unique_stocks": df["ts_code"].nunique(),
                "reco_days": len(all_dates),
                "scan_days": len(all_dates),  # 兼容消费方字段名（Dashboard 卡片）
                "strategy": STRATEGY_LABEL,
            },
        }
    except Exception as e:
        _logger.warning(f"[reco_history] 统计失败: {e}")
        import traceback
        _logger.debug(traceback.format_exc())
        return {"strategy": STRATEGY_LABEL, "summary": [], "daily": {}, "streak": [],
                "meta": {"days": days, "total_records": 0, "date_from": "", "date_latest": "",
                         "unique_stocks": 0, "reco_days": 0, "scan_days": 0,
                         "strategy": STRATEGY_LABEL}}
    finally:
        conn.close()
