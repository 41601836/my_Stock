# -*- coding: utf-8 -*-
"""
services.scanner —— 建仓机会扫描 & 自适应持有期 & 画像过滤器共享
* get_build_position_opportunities()        Top 10 画像+热度+行业三层漏斗
* get_scan_history()                        扫描历史近 30 天
* get_recommendation_history()              历史推荐 + 连续上榜统计
* get_timing_alerts()                       多周期择时警报
* record_alerts_feedback()                  警报反馈日志
"""

import os
import sys
import json
import logging
import datetime
import collections
import numpy as np
import pandas as pd

from ._common import PROJECT_ROOT, get_db_connection, DB_PATH, clean_nan_inf
from ._common import (
    _get_factor_date, _get_restricted_stocks,
    _ensure_scan_history_table, _save_and_calc_recommendation_stats,
    get_scanner_cfg,
)
from .performance import determine_adaptive_hold_period
from .market_regime import get_market_status

_logger = logging.getLogger(__name__)


def get_build_position_opportunities(use_portrait_router=True, regime_hint=None, sector_filter=None, top_n=10):
    """
    画像建仓机会扫描：
      因子列显式 SELECT → pkl 权重加权合成 factor_score → 扩大候选池 →
      winner_rate 前置过滤 → 画像过滤 → 热度过滤 → 行业分散 → MVO 权重。
    兼容前端 Scanner.jsx 字段契约（stocks + meta.{scan_date,factor_date,cyq_date,mf_date,total_scanned,after_filter,final_count}）
    并保留 backward-compat：opportunities / stats / scan_date 顶层字段，save_scan_history 可正常写入。
    """
    try:
        from portrait_router import apply_portrait_filter, PORTRAIT_CONFIG
        _portrait_enabled = True
    except ImportError:
        _portrait_enabled = False

    conn = get_db_connection(DB_PATH, timeout=60.0)
    try:
        # ── 0. 读取 4 张核心表的"近全量"最新日期（Data Lineage Tracker 直接消费）──
        # 背景：factor_values 最新"MAX 日期"通常只有几条"写入溢出"脏行，真实全市场快照在 20260806 附近（~5400 行）。
        # 策略：对 4 张表独立计算 LATEST 日期：优先取 MAX, 若其行数 < min_rows 阈值 → 回退到"行数最多"的最近交易日。
        try:
            dp_density = int(pd.read_sql("SELECT COUNT(*) FROM daily_prices WHERE trade_date = ("
                                         "SELECT MAX(trade_date) FROM daily_prices)", conn).iloc[0, 0])
        except Exception:
            dp_density = 4000
        COVERAGE_FACTOR = 0.80  # 因子表覆盖率门槛（相对于当日价格表行数）—— 必须 ≥80% 才算"全市场快照"
        MIN_ROWS_ABS = 1000

        def _max_date(table, date_col="trade_date", min_rows_factor=1.0):
            threshold_rows = max(int(dp_density * min_rows_factor), MIN_ROWS_ABS)
            try:
                df = pd.read_sql(
                    f"SELECT {date_col} AS d, COUNT(*) AS c FROM {table} GROUP BY {date_col} "
                    f"ORDER BY {date_col} DESC", conn)
                if df.empty: return ""
                # ① LATEST 是否满足阈值？
                latest_row = df.iloc[0]
                if int(latest_row["c"]) >= threshold_rows:
                    return str(latest_row["d"])
                # ② 取最近（按日期 DESC）一条满足阈值的
                good = df[df["c"] >= threshold_rows]
                if not good.empty:
                    return str(good.iloc[0]["d"])
                # ③ 兜底取行数最多的那天
                best = df.sort_values("c", ascending=False).iloc[0]
                return str(best["d"])
            except Exception:
                return ""

        scan_date_dp = _max_date("daily_prices",        min_rows_factor=0.90)
        factor_date   = _max_date("factor_values",      min_rows_factor=COVERAGE_FACTOR)
        cyq_date      = _max_date("stock_cyq_perf",     min_rows_factor=0.90)
        mf_date       = _max_date("moneyflow",          min_rows_factor=0.90)
        latest_date   = scan_date_dp or factor_date or _get_factor_date(conn)
        if not latest_date:
            return {
                "error": "No factor data for today", "stocks": [], "opportunities": [],
                "scan_date": None, "stats": {},
                "meta": {"scan_date": "", "factor_date": factor_date, "cyq_date": cyq_date, "mf_date": mf_date,
                         "total_scanned": 0, "after_filter": 0, "final_count": 0},
            }

        # ── 1. 从 factor_values 读取全部可用因子列（兼容旧表无 pe_ttm 情况）
        try:
            fac_cols_exist = [r[1] for r in conn.execute("PRAGMA table_info(factor_values)").fetchall()]
        except Exception:
            fac_cols_exist = []
        fac_cols_base = ["stock_code", "trade_date",
            "return_5d", "return_10d", "return_20d", "return_60d", "excess_return_20d",
            "turnover_rate_20d", "volatility_20d", "volatility_60d", "vol_ratio",
            "north_net_inflow_ratio", "profit_ratio_estimate",
            "chip_concentration", "hot_money_score"]
        if "pe_ttm" in fac_cols_exist:
            fac_cols_base.append("pe_ttm")
        fac_cols = [c for c in fac_cols_base if c in fac_cols_exist or c in ("stock_code","trade_date")]
        col_sql = ",".join(fac_cols)

        # 因子读取：以「全量快照阈值」选出的 factor_date 为准（最新 MAX 日期一般只有 10~14 条写入溢出脏行）
        factor_query_date = factor_date or latest_date
        df_fv = pd.read_sql(
            f"SELECT {col_sql} FROM factor_values WHERE trade_date = ?",
            conn, params=(factor_query_date,)
        )
        scan_date_use = latest_date
        if df_fv.empty:
            # 兜底：回退 latest_date；仍空则报错
            df_fv = pd.read_sql(
                f"SELECT {col_sql} FROM factor_values WHERE trade_date = ?",
                conn, params=(latest_date,)
            )
            if df_fv.empty:
                return {
                    "error": "No factor score data", "stocks": [], "opportunities": [],
                    "scan_date": latest_date, "stats": {},
                    "meta": {"scan_date": latest_date, "factor_date": factor_date, "cyq_date": cyq_date, "mf_date": mf_date,
                             "total_scanned": 0, "after_filter": 0, "final_count": 0},
                }

        restricted = _get_restricted_stocks(conn)
        total_scanned = len(df_fv)
        if restricted:
            df_fv = df_fv[~df_fv["stock_code"].isin(restricted)]
            total_scanned = len(df_fv)

        # 根据 regime_hint 选 Range vs Bull 权重
        from ._common import _load_pkl_weights
        from ._common import WEIGHTS_PATH, BULL_WEIGHTS_PATH
        rw = None
        weights_label = "Range(fallback.yaml)"
        if regime_hint and str(regime_hint).upper() == "BULL":
            _, rw = _load_pkl_weights(BULL_WEIGHTS_PATH)
            weights_label = "Bull(pkl)"
        if not rw:  # 兜底 Range 权重
            ok_pkl, pkl_rw = _load_pkl_weights(WEIGHTS_PATH)
            if ok_pkl and pkl_rw:
                rw = pkl_rw
                weights_label = "Range(pkl)"
            else:
                _scanner_cfg = get_scanner_cfg()
                rw = dict(_scanner_cfg["regime_weights_fallback"]["Range"])
                weights_label = "Range(fallback.yaml)"

        # 【因子有效性自检】pkl 权重可能引用了未实现的因子列，或者权重和为负数（全反转模型）
        missing_factors = [f for f in rw.keys() if f not in df_fv.columns and f not in ("stock_code", "trade_date")]
        raw_w_sum = sum(rw[f] for f in rw.keys() if f in df_fv.columns or f in ("stock_code", "trade_date") or True)
        eff_w_sum = sum(rw[f] for f in rw.keys() if f in df_fv.columns)
        if missing_factors or abs(abs(eff_w_sum) - 1.0) > 0.3:
            _logger.warning(
                "[Scanner 因子有效性] 权重=%s | 缺失因子=%s | 配置权重和=%.4f | 实际生效权重和=%.4f | 参考因子列=%s",
                weights_label, missing_factors, raw_w_sum, eff_w_sum,
                [c for c in df_fv.columns if c not in ("stock_code", "trade_date")]
            )

        # 加权合成 factor_score（对应原版 1071-1082 行）
        df_fv["factor_score"] = 0.0
        for f, w in rw.items():
            if f in df_fv.columns:
                df_fv[f"_r_{f}"] = df_fv[f].rank(pct=True, na_option="bottom")
                df_fv["factor_score"] += w * df_fv[f"_r_{f}"]
        fs_min = df_fv["factor_score"].min()
        fs_max = df_fv["factor_score"].max()
        fs_rng = fs_max - fs_min if (fs_max - fs_min) > 1e-9 else 1.0
        df_fv["factor_score_norm"] = (df_fv["factor_score"] - fs_min) / fs_rng
        # 【前端显示】把 0-1 归一化值再映射成 全市场百分位(0~100 分)，消除 RAW 小数/负值语义混乱
        #   _factor_rk = factor_score_norm.rank(ascending=True, pct=True) * 100
        #   选出股票时按降序取 _factor_rk 最大者 → 分值 90~100 分才是真正的好股
        df_fv["factor_score_pct"] = df_fv["factor_score_norm"].rank(pct=True, ascending=True) * 100.0

        target_top_n = max(1, int(top_n or 10))
        expand_ratio = PORTRAIT_CONFIG.get("expand_ratio", 3) if _portrait_enabled and use_portrait_router else 1.0
        pre_candidate_n = max(int(target_top_n * expand_ratio), target_top_n * 2)

        # sector_filter：在全量打分之后立刻按 industry 过滤（避免后续空漏斗）
        if sector_filter:
            sl = pd.read_sql("SELECT ts_code, industry FROM stock_list", conn)
            kw = str(sector_filter).strip()
            mask = sl["industry"].fillna("").str.contains(kw, regex=False, case=False)
            codes_sub = set(sl[mask]["ts_code"].tolist())
            if codes_sub:
                df_fv = df_fv[df_fv["stock_code"].isin(codes_sub)]

        df_fv["_factor_rk"] = df_fv["factor_score_norm"].rank(pct=True, ascending=True)
        pre_filter_size = max(pre_candidate_n * 2, 50)
        df_pre = df_fv.sort_values("_factor_rk", ascending=False).head(pre_filter_size).copy()

        cyq_date_q = cyq_date if cyq_date else scan_date_use
        mf_date_q  = mf_date  if mf_date  else scan_date_use
        dp_date_q  = scan_date_use
        cyq_sql = f"SELECT ts_code, trade_date, winner_rate, chips_peak_pct FROM stock_cyq_perf WHERE trade_date = ?"
        # 【单位修正】moneyflow.net_mf_amount 真实单位 = 万元 → 亿元 = ÷ 10000 (之前错误 ÷1e8 导致 10000x 下取整 → 0.00亿)
        mf_sql  = f"SELECT ts_code, trade_date, (net_mf_amount / 10000.0) AS net_mf_yi FROM moneyflow WHERE trade_date = ?"
        dp_sql  = f"SELECT ts_code, trade_date, close, pct_chg FROM daily_prices WHERE trade_date = ?"
        sl_sql  = "SELECT ts_code, name, market, industry FROM stock_list"

        df_cyq = pd.read_sql(cyq_sql, conn, params=(cyq_date_q,))
        df_mf  = pd.read_sql(mf_sql,  conn, params=(mf_date_q,))
        df_dp  = pd.read_sql(dp_sql,  conn, params=(dp_date_q,))
        df_sl  = pd.read_sql(sl_sql,  conn)

        # Merge：cyq/mf/dp 可能是各自的表日期，避免 trade_date 列冲突 → 合并前删掉右表 trade_date
        #        df_fv/df_pre 已含 factor_values 的 trade_date（已重命名为 ts_code 那一侧）
        df_cyq_r = df_cyq.drop(columns=[c for c in ("trade_date",) if c in df_cyq.columns], errors="ignore")
        df_mf_r  = df_mf.drop(columns=[c for c in ("trade_date",)  if c in df_mf.columns], errors="ignore")
        df_dp_r  = df_dp.drop(columns=[c for c in ("trade_date",)  if c in df_dp.columns], errors="ignore")

        df_pre = df_pre.rename(columns={"stock_code": "ts_code"}).merge(df_cyq_r, on=["ts_code"], how="left")
        df_pre = df_pre.merge(df_mf_r,  on=["ts_code"], how="left")
        df_pre = df_pre.merge(df_dp_r,  on=["ts_code"], how="left")
        df_pre = df_pre.merge(df_sl,    on="ts_code",             how="left")

        for c in ["winner_rate", "chips_peak_pct", "net_mf_yi", "pct_chg"]:
            if c not in df_pre.columns:
                df_pre[c] = np.nan

        # S2：从配置读取 winner_rate 过滤阈值
        _scanner_cfg = get_scanner_cfg()
        _pf = _scanner_cfg["prefilter"]
        _wr_lo = float(_pf.get("winner_rate_lo", 25.0))
        _wr_hi = float(_pf.get("winner_rate_hi", 85.0))
        df_pre = df_pre[
            (df_pre["winner_rate"].fillna(50) >= _wr_lo) &
            (df_pre["winner_rate"].fillna(50) <= _wr_hi)
        ].copy()
        after_filter = len(df_pre)
        if df_pre.empty:
            return {
                "error": "Candidate pool empty after winner_rate filtering",
                "stocks": [], "opportunities": [], "scan_date": scan_date_use, "stats": {
                    "candidate_pool": total_scanned, "pre_filter": pre_filter_size,
                    "after_winner_rate": 0, "sector_filter": sector_filter,
                },
                "meta": {
                    "scan_date": scan_date_use, "factor_date": factor_date,
                    "cyq_date": cyq_date, "mf_date": mf_date,
                    "total_scanned": total_scanned, "after_filter": 0, "final_count": 0,
                    "sector_filter": sector_filter,
                }
            }

        df_pre["_wr_rk"]  = df_pre["winner_rate"].rank(pct=True,   ascending=True)
        df_pre["_cp_rk"]  = df_pre["chips_peak_pct"].rank(pct=True, ascending=True)
        df_pre["_mf_rk"]  = df_pre["net_mf_yi"].rank(pct=True,      ascending=True)
        df_pre["_pc_rk"]  = 1.0 - (df_pre["pct_chg"].clip(lower=-5, upper=5) + 5.0) / 10.0

        # S2：从配置读取 scanner_score 合成权重（5因子加权总和=1.0）
        _sw = _scanner_cfg["scoring_weights"]
        _w_factor  = float(_sw.get("factor_rank",       0.28))
        _w_wr      = float(_sw.get("winner_rate_rank",  0.23))
        _w_cp      = float(_sw.get("chip_peak_rank",    0.19))
        _w_mf      = float(_sw.get("inflow_rank",       0.23))
        _w_pc_inv  = float(_sw.get("pct_chg_inv_rank",  0.07))
        df_pre["_scanner_score"] = (
            df_pre["_factor_rk"].fillna(0.5) * _w_factor +
            df_pre["_wr_rk"].fillna(0.5)     * _w_wr +
            df_pre["_cp_rk"].fillna(0.5)     * _w_cp +
            df_pre["_mf_rk"].fillna(0.5)     * _w_mf +
            df_pre["_pc_rk"].fillna(0.5)     * _w_pc_inv
        )

        df_pre = df_pre.sort_values("_scanner_score", ascending=False).head(max(pre_candidate_n, 20)).copy()

        if _portrait_enabled and use_portrait_router:
            try:
                df_pre = apply_portrait_filter(
                    df_top      = df_pre,
                    df_fv       = df_fv.rename(columns={"stock_code": "ts_code"}),
                    conn        = conn,
                    filter_mode = True,
                )
            except Exception as _pe:
                print(f"⚠️ [PortraitRouter] 画像路由层异常，降级跳过: {_pe}")

        df_top = df_pre.head(target_top_n).copy()

        def sector(s):
            if pd.isna(s): return "未分类"
            return str(s).split(" | ")[-1]
        df_top["_sector"] = df_top["industry"].apply(sector)

        # S2：从配置读取行业分散度（同细分行业最多保留N只）
        _scanner_cfg = get_scanner_cfg()
        max_per_sector = int(_scanner_cfg["sector_diversify"].get("max_per_sector", 2))
        sector_counter = collections.Counter()
        final_rows = []
        for _, r in df_top.iterrows():
            s = r["_sector"]
            if sector_counter[s] < max_per_sector:
                sector_counter[s] += 1
                final_rows.append(r)
            if len(final_rows) >= target_top_n:
                break

        df_top = pd.DataFrame(final_rows).reset_index(drop=True)
        df_top["__rank"] = np.arange(1, len(df_top) + 1)
        df_top["build_score"] = (df_top["_scanner_score"] * 100).round(2)
        df_top["sector_sorted"] = df_top["_sector"]

        codes = df_top["ts_code"].tolist()
        expected_returns = {r["ts_code"]: float(r["build_score"]) / 100.0 for _, r in df_top.iterrows()}
        industries = {r["ts_code"]: r["_sector"] for _, r in df_top.iterrows()}

        # ── S3：Phase 3 组合构建（先因子+画像过滤，再等权目标，再多周滚动平滑） ──
        #   作为 scanner 的主仓位方案（替代直接 MVO 的"全仓替换"，多周稳定调仓）
        _s3_scan_meta = {"phase": "Phase 3 NOT RUN (default path)"}
        try:
            import sys as _sys, os as _os
            # services/scanner.py 深度 3 层：root / web / backend / services / scanner.py → dirname × 4 才能到 PROJECT ROOT
            _proj_root_scan = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__)))))
            _src_path_scan  = _os.path.join(_proj_root_scan, "src")
            if _src_path_scan  not in _sys.path: _sys.path.insert(0, _src_path_scan)
            if _proj_root_scan not in _sys.path: _sys.path.insert(0, _proj_root_scan)
            from portfolio_constructor import construct_portfolio

            df_s3_in = df_top.copy()
            # 对齐 construct_portfolio 的列
            if "factor_score_norm" not in df_s3_in.columns:
                # scanner 上下文里没有显式 factor_score_norm，但是有 _factor_rk（0~1，等同于归一化排名）
                df_s3_in["factor_score_norm"] = pd.to_numeric(
                    df_s3_in.get("_factor_rk", 0.5), errors="coerce"
                ).fillna(0.5)
            # 如果 portrait_router 没给 portrait_* 列，使用 _scanner_score 作为过滤兜底
            if "portrait_score" not in df_s3_in.columns:
                df_s3_in["portrait_score"] = (
                    pd.to_numeric(df_s3_in.get("_scanner_score", 0.6), errors="coerce")
                    .fillna(0.6) * 100.0
                ).clip(0, 100)
            if "portrait_grade" not in df_s3_in.columns:
                # 用 build_score 粗映射等级（没有画像就按综合分兜底）
                bs = pd.to_numeric(df_s3_in.get("build_score", 60), errors="coerce").fillna(60)
                df_s3_in["portrait_grade"] = pd.cut(
                    bs, bins=[-1, 40, 55, 75, 101], labels=["D", "C", "B", "A"], right=False
                ).astype(str).fillna("C")
            if "build_score" not in df_s3_in.columns:
                df_s3_in["build_score"] = (
                    pd.to_numeric(df_s3_in.get("_scanner_score", 0), errors="coerce").fillna(0.0) * 100
                )

            df_s3_out, s3_meta = construct_portfolio(
                df_s3_in,
                max_turnover         = 0.50,
                max_weight           = 0.30,
                conn                 = conn,
                current_date         = str(scan_date_use),
                strategy             = "scan",
                drop_grade_d         = True,
                factor_tail_quantile = 0.05,
                min_portfolio_size   = max(2, target_top_n - 2),
                final_max_size       = target_top_n,
            )

            # 只保留 Phase 3 通过行（blended_weight > 0）
            df_kept = df_s3_out[
                (df_s3_out["dropped_reason"].fillna("") == "") &
                (pd.to_numeric(df_s3_out["blended_weight"], errors="coerce").fillna(0) > 0)
            ].copy()

            if not df_kept.empty:
                # 重新按 _scanner_score（或画像分）排序并重新排名
                sort_key = "portrait_score" if "portrait_score" in df_kept.columns else "_scanner_score"
                df_kept = df_kept.sort_values(sort_key, ascending=False).reset_index(drop=True)
                df_kept["__rank"] = range(1, len(df_kept) + 1)
                # Phase 3 主方案：blended_weight_pct 为仓位百分比（1/N + 多周滚动）
                df_kept["mvo_weight"] = pd.to_numeric(
                    df_kept["blended_weight_pct"], errors="coerce"
                ).fillna(round(100.0 / max(len(df_kept), 1), 2))
                # 保留 S3 元信息
                for col in ["target_weight", "prev_weight", "blended_weight", "delta_weight"]:
                    df_kept[f"s3_{col}"] = pd.to_numeric(df_kept[col], errors="coerce").round(6)
                df_kept["_s3_applied"] = True
                df_top = df_kept
                _s3_scan_meta = s3_meta
            else:
                # Phase 3 过滤后全部出局，走原始 MVO 老路
                _s3_scan_meta = {"phase": "Phase 3 scanner fallback (全部过滤后空，退回 MVO)", **(s3_meta or {})}
                try:
                    from scripts.portfolio_optimizer import optimize_portfolio
                    wts = optimize_portfolio(codes, expected_returns, industries, scan_date_use)
                    df_top["mvo_weight"] = df_top["ts_code"].apply(
                        lambda c: round(float(wts.get(c, 1.0 / len(codes))) * 100, 2)
                    )
                except Exception as e:
                    print(f"⚠️ [Scanner MVO Error] {e}")
                    df_top["mvo_weight"] = round(100.0 / max(len(codes), 1), 2)
        except Exception as _s3e:
            _s3_scan_meta = {"phase": "Phase 3 EXCEPTION fallback (MVO)", "error": str(_s3e)}
            print(f"⚠️ [Scanner S3] 组合构建异常，降级 MVO：{_s3e}")
            try:
                from scripts.portfolio_optimizer import optimize_portfolio
                wts = optimize_portfolio(codes, expected_returns, industries, scan_date_use)
                df_top["mvo_weight"] = df_top["ts_code"].apply(
                    lambda c: round(float(wts.get(c, 1.0 / len(codes))) * 100, 2)
                )
            except Exception as e:
                print(f"⚠️ [Scanner MVO Error] {e}")
                df_top["mvo_weight"] = round(100.0 / max(len(codes), 1), 2)

        _ensure_scan_history_table(conn)
        for _, r in df_top.iterrows():
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO scan_history "
                    "(scan_date, ts_code, name, industry, rank, build_score, factor_score, "
                    " winner_rate, big_net_inflow, close, pct_chg, mvo_weight, regime, reason) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(scan_date_use), r["ts_code"],
                     str(r.get("name", "未知")), str(r.get("_sector", "未分类")),
                     int(r["__rank"]), float(r["build_score"]),
                     round(float(r.get("factor_score_pct", r.get("_factor_rk", 0.5) * 100)), 2),
                     round(float(r.get("winner_rate", 0.0)), 2),
                     # scan_history big_net_inflow 列存储约定 = 万元（与 get_scan_history line 525: /1e4 还原亿对应）
                     round(float(r.get("net_mf_yi", 0.0)) * 10000.0, 4),
                     round(float(r.get("close", 0.0)), 2),
                     round(float(r.get("pct_chg", 0.0)), 2),
                     float(r.get("mvo_weight", 0.0)),
                     str(regime_hint or "AUTO"),
                     "画像建仓三层漏斗筛选"),
                )
            except Exception:
                pass
        conn.commit()

        stats_map = _save_and_calc_recommendation_stats(df_top, scan_date_use)

        opp = []
        for _, r in df_top.iterrows():
            # turnover_rate：优先取因子表的 turnover_rate_20d，兜底从 df_pre 的列读取
            _tr_raw = r.get("turnover_rate_20d", r.get("turnover_rate", np.nan))
            try:
                turnover_rate = round(float(_tr_raw), 2) if pd.notna(_tr_raw) else None
            except Exception:
                turnover_rate = None

            _stats = stats_map.get(r["ts_code"], {"total_recommends": 1, "consecutive_days": 1, "ever_top_3": int(r["__rank"]) <= 3})
            # 【显示修正】factor_score_display：使用百分位(0~100分)，消除 RAW 小数/负数语义
            _fs_display = r.get("factor_score_pct")
            if _fs_display is None or (isinstance(_fs_display, float) and np.isnan(_fs_display)):
                _f_rk_v = r.get("_factor_rk")
                _fs_display = round(float(_f_rk_v) * 100.0, 2) if _f_rk_v is not None and not (isinstance(_f_rk_v, float) and np.isnan(_f_rk_v)) else 50.0
            # big_net_inflow(亿)：保留 4 位小数，可精准表达 ±1万元级别（0.0001 亿）
            _mfy = r.get("net_mf_yi", 0.0)
            try:
                _mfy_f = float(_mfy) if _mfy is not None and not (isinstance(_mfy, float) and np.isnan(_mfy)) else 0.0
            except Exception:
                _mfy_f = 0.0
            _reason_arr = [
                f"因子分排名前 {max(1, int(len(df_fv) * 0.05)) / max(1, len(df_fv)) * 100:.1f}%",
                f"筹码获利盘 {r.get('winner_rate', 0):.1f}% / 集中度 {r.get('chips_peak_pct', 0):.1f}%",
                f"当日净流入 {_mfy_f:.4f} 亿",
                f"画像分 {r.get('portrait_score', 0):.1f} ({r.get('portrait_grade', '—')})",
            ]
            row = {
                "ts_code": str(r["ts_code"]),
                "name": str(r.get("name", "未知")),
                "industry": f"{str(r.get('market',''))} | {r.get('_sector','未分类')}",
                "rank": int(r["__rank"]),
                "build_score": float(r["build_score"]),
                "factor_score": round(float(_fs_display), 2),
                "winner_rate": round(float(r.get("winner_rate", 0.0)), 2),
                "chips_peak_pct": round(float(r.get("chips_peak_pct", 0.0)), 2),
                "big_net_inflow": round(_mfy_f, 4),
                "close": round(float(r.get("close", 0.0)), 2),
                "pct_chg": round(float(r.get("pct_chg", 0.0)), 2),
                "turnover_rate": turnover_rate,
                "sector_sorted": r["_sector"],
                "mvo_weight": float(r.get("mvo_weight", 0.0)),
                "portrait_score": round(float(r.get("portrait_score", 0.0)), 1),
                "portrait_grade": str(r.get("portrait_grade", "—")),
                "portrait_label": str(r.get("portrait_label", "—")),
                "portrait_details": r.get("portrait_details", {}) if not pd.isna(r.get("portrait_details")) else {},
                "reason": "；".join(_reason_arr),
                "build_reason": _reason_arr,
                "stats": _stats,
                "historic_stats": _stats,
                # S3 Phase 3 附加列（非破坏向后兼容扩展）
                "s3_target_weight":  round(float(r.get("s3_target_weight",  0.0) or 0.0), 6),
                "s3_prev_weight":    round(float(r.get("s3_prev_weight",    0.0) or 0.0), 6),
                "s3_blended_weight": round(float(r.get("s3_blended_weight", 0.0) or 0.0), 6),
                "s3_delta_weight":   round(float(r.get("s3_delta_weight",   0.0) or 0.0), 6),
                "s3_applied":        bool(r.get("_s3_applied", False)),
            }
            opp.append(row)

        final_count = len(opp)
        # 注入 S3 Phase 3 元信息（若成功运行过）
        meta = {
            "scan_date":     scan_date_use,
            "factor_date":   factor_date,
            "cyq_date":      cyq_date,
            "mf_date":       mf_date,
            "total_scanned": int(total_scanned),
            "after_filter":  int(after_filter),
            "final_count":   int(final_count),
            "sector_filter": sector_filter,
            "portfolio":     _s3_scan_meta,
        }
        stats = {
            "candidate_pool":       int(total_scanned),
            "pre_filter":           pre_filter_size,
            "after_winner_rate":    int(after_filter),
            "portrait_used":        bool(_portrait_enabled and use_portrait_router),
            "expand_ratio":         expand_ratio,
            "sectors_used":         len(sector_counter),
            "adaptive_hold_days":   determine_adaptive_hold_period(),
        }
        return {
            "scan_date": str(scan_date_use),
            "stocks":       opp,        # Scanner.jsx 消费：data.stocks
            "opportunities": opp,       # backward-compat：save_scan_history + 其他路由
            "meta":         meta,       # Scanner.jsx 消费：data.meta
            "stats":        stats,      # backward-compat：顶层 stats
        }
    except Exception as e:
        import traceback
        return {"error": f"Scanner error: {e}", "trace": traceback.format_exc(),
                "stocks": [], "opportunities": [], "scan_date": None,
                "meta": {"scan_date":"","factor_date":"","cyq_date":"","mf_date":"","total_scanned":0,"after_filter":0,"final_count":0},
                "stats": {}}
    finally:
        conn.close()


def get_scan_history(days: int = 30, top_n_per_day: int = 0,
                     ts_code: str = "", min_appear: int = 1) -> dict:
    """
    查询建仓扫描历史累计数据。

    参数：
        days          -- 查询最近 N 天（默认30天）
        top_n_per_day -- 只取每日 rank <= N 的记录（0 表示不限）
        ts_code       -- 按股票代码过滤（空字符串表示全部）
        min_appear    -- 最少出现 N 次才纳入频率排行（默认1）

    返回：
        {
            "summary": 上榜频率排行（按出现次数降序），
            "daily":   按日期分组的每日快照，
            "streak":  当前连续上榜天数排行,
            "meta":    {date_range, total_records, ...},
            "timing":  建仓时机预警（alerts/summary/regime/scan_date）
        }
    """
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    try:
        _ensure_scan_history_table(conn)

        date_from = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")

        where_clauses = ["scan_date >= ?"]
        params = [date_from]
        if top_n_per_day and int(top_n_per_day) > 0:
            where_clauses.append(f"rank <= {int(top_n_per_day)}")
        if ts_code:
            where_clauses.append("ts_code = ?")
            params.append(ts_code)
        where_sql = " AND ".join(where_clauses)

        df = pd.read_sql(
            f"SELECT * FROM scan_history WHERE {where_sql} ORDER BY scan_date DESC, rank ASC",
            conn, params=params
        )

        if df.empty:
            return {
                "summary": [], "daily": {}, "streak": [],
                "meta": {
                    "days": days, "total_records": 0, "date_from": date_from,
                    "date_latest": "", "unique_stocks": 0, "scan_days": 0
                },
                "timing": {"alerts": [], "summary": {}, "regime": "UNKNOWN", "scan_date": ""}
            }

        # B. 频率汇总（Summary）
        grp = df.groupby("ts_code").agg(
            name=("name", "last"),
            industry=("industry", "last"),
            appear_count=("scan_date", "count"),
            avg_rank=("rank", "mean"),
            avg_score=("build_score", "mean"),
            avg_factor=("factor_score", "mean"),
            avg_inflow=("big_net_inflow", "mean"),
            last_date=("scan_date", "max"),
        ).reset_index()
        def _safe_last_rank(sub):
            try:
                m = sub["scan_date"].idxmax()
                return int(sub.loc[m, "rank"])
            except Exception:
                return int(sub["rank"].min() if len(sub) else 0)
        last_rank_rows = []
        for c, sub in df.groupby("ts_code"):
            last_rank_rows.append({"ts_code": c, "last_rank": _safe_last_rank(sub)})
        lr_df = pd.DataFrame(last_rank_rows)
        if not lr_df.empty:
            grp = grp.merge(lr_df, on="ts_code", how="left")
        else:
            grp["last_rank"] = 0

        grp = grp[grp["appear_count"] >= int(min_appear)]
        grp = grp.sort_values(["appear_count", "avg_rank"], ascending=[False, True])
        grp["avg_rank"]   = grp["avg_rank"].round(1)
        grp["avg_score"]  = grp["avg_score"].round(1)
        grp["avg_factor"] = grp["avg_factor"].round(1)
        grp["avg_inflow"] = (grp["avg_inflow"].fillna(0) / 1e4).round(2)  # 万
        summary = grp.to_dict(orient="records")

        # C. 按日期分组快照（Daily）
        all_dates = sorted(df["scan_date"].unique(), reverse=True)
        daily = {}
        for d in all_dates:
            rows = df[df["scan_date"] == d].copy()
            rows["big_net_inflow"] = (rows["big_net_inflow"].fillna(0) / 1e4).round(2)
            rows["factor_score"]   = rows["factor_score"].fillna(0).round(1)
            daily[d] = rows.to_dict(orient="records")

        # D. 连续上榜天数排行（Streak）
        sorted_dates = sorted(df["scan_date"].unique(), reverse=True)
        streak_map = {}
        for stock in df["ts_code"].unique():
            dates_of_stock = set(df[df["ts_code"] == stock]["scan_date"].tolist())
            streak = 0
            for d in sorted_dates:
                if d in dates_of_stock:
                    streak += 1
                else:
                    break
            streak_map[stock] = streak

        streak_df = df[["ts_code", "name", "industry"]].drop_duplicates("ts_code").copy()
        streak_df["streak_days"] = streak_df["ts_code"].map(streak_map)
        streak_df = streak_df.sort_values("streak_days", ascending=False)
        streak_list = streak_df[streak_df["streak_days"] >= 2].to_dict(orient="records")

        # E. 建仓时机预警（Timing）
        timing = _build_timing_alerts(df, conn)

        return {
            "summary": summary,
            "daily":   daily,
            "streak":  streak_list,
            "meta": {
                "days":          days,
                "total_records": len(df),
                "date_from":     date_from,
                "date_latest":   sorted_dates[0] if sorted_dates else "",
                "unique_stocks": df["ts_code"].nunique(),
                "scan_days":     len(all_dates),
            },
            "timing": timing
        }
    except Exception as e:
        import traceback
        return {
            "summary": [], "daily": {}, "streak": [],
            "meta": {"days": days, "total_records": 0, "date_from": "", "error": str(e)},
            "timing": {"alerts": [], "summary": {}, "regime": "UNKNOWN", "scan_date": "", "error": str(e)},
            "trace": traceback.format_exc()
        }
    finally:
        conn.close()


def _build_timing_alerts(df_all: pd.DataFrame, conn) -> dict:
    """根据 scan_history 生成建仓时机预警（简化版评分逻辑，避免重依赖）"""
    try:
        if df_all.empty:
            return {"alerts": [], "summary": {"golden": 0, "good": 0, "watch": 0, "risk": 0},
                    "regime": "UNKNOWN", "scan_date": ""}
        latest_dates = sorted(df_all["scan_date"].unique(), reverse=True)
        today_date = latest_dates[0]
        df_today = df_all[df_all["scan_date"] == today_date].copy()
        prev_dates = latest_dates[1:]
        df_prev = df_all[df_all["scan_date"].isin(prev_dates)]
        last_seen = {}
        rank_jump_map = {}
        if not df_prev.empty:
            for c, sub in df_prev.groupby("ts_code"):
                last_seen[c] = sub["scan_date"].max()
                prev_rank = sub[sub["scan_date"] == last_seen[c]]["rank"].min()
                rank_jump_map[c] = float(prev_rank)

        trade_dates_sorted = sorted(latest_dates, reverse=True)
        gaps_map = {}
        for c, sub in df_all.groupby("ts_code"):
            dts = sorted(sub["scan_date"].unique(), reverse=True)
            if len(dts) == 1:
                gaps_map[c] = 99
                continue
            gaps_map[c] = len([d for d in trade_dates_sorted
                               if d > dts[0] and d not in set(dts)])

        regime_val = str(df_today["regime"].dropna().iloc[0]) if "regime" in df_today.columns and not df_today["regime"].dropna().empty else "AUTO"
        regime_boost = 1.8 if regime_val in ("BEAR", "DARK", "BEAR_SIDE", "震荡下跌") else 1.0

        alerts = []
        for _, r in df_today.iterrows():
            code = r["ts_code"]
            score = 50.0
            signals = []

            gap_since_last = gaps_map.get(code, 0)
            if gap_since_last >= 3:
                score += 25; signals.append({"type":"fresh","label":"初次入榜","desc":f"断档 {gap_since_last} 个交易日，新鲜信号","points":25})
            elif gap_since_last >= 2:
                score += 12; signals.append({"type":"reentry","label":"二次回踩","desc":f"消失 {gap_since_last} 天后重新出现","points":12})

            prev_rank = rank_jump_map.get(code)
            cur_rank  = int(r["rank"])
            if prev_rank is not None and prev_rank > 10 and cur_rank <= 5:
                score += 20; signals.append({"type":"momentum","label":"排名跃升","desc":f"昨日排名 {int(prev_rank)} → 今日 {cur_rank}，动能加速","points":20})

            appear_count = int((df_all["ts_code"] == code).sum())
            if appear_count == 3:
                score += 15; signals.append({"type":"confirm","label":"连续第3天","desc":"连续上榜 3 日，信号已验证","points":15})
            elif appear_count > 7:
                score -= 15; signals.append({"type":"tired","label":"信号透支","desc":f"连续 {appear_count} 天在榜，谨防追高","points":-15})

            f_score = float(r.get("factor_score") or 0)
            if f_score >= 90:
                score += 10; signals.append({"type":"strong","label":"模型高分","desc":f"因子分 {f_score:.1f}，模型信心极强","points":10})

            score *= regime_boost
            if regime_boost > 1.0:
                signals.append({"type":"regime","label":"主场加持","desc":f"Regime={regime_val}，策略权重翻倍","points":int(score - score/regime_boost)})

            pct = float(r.get("pct_chg") or 0)
            if pct > 5:
                score -= 8; signals.append({"type":"hot","label":"高追风险","desc":f"当日涨幅 {pct:.2f}% 过大","points":-8})
            elif pct > 3:
                score -= 10; signals.append({"type":"hot","label":"追涨风险","desc":f"当日涨幅 {pct:.2f}%，不建议追高","points":-10})

            score = max(0, min(100, score))

            if score >= 78: level = "golden"
            elif score >= 60: level = "good"
            elif score >= 45: level = "watch"
            else: level = "risk"

            big_inf_wan = round(float(r.get("big_net_inflow") or 0) / 1e4, 2)
            alerts.append({
                "ts_code": code,
                "name": str(r.get("name") or ""),
                "industry": str(r.get("industry") or ""),
                "score": round(score, 1),
                "level": level,
                "rank": cur_rank,
                "factor_score": round(f_score, 1),
                "pct_chg": round(pct, 2),
                "big_net_inflow": big_inf_wan,
                "appear": appear_count,
                "streak": appear_count,
                "signals": signals
            })

        alerts.sort(key=lambda x: x["score"], reverse=True)
        summary = {
            "golden": sum(1 for a in alerts if a["level"]=="golden"),
            "good":   sum(1 for a in alerts if a["level"]=="good"),
            "watch":  sum(1 for a in alerts if a["level"]=="watch"),
            "risk":   sum(1 for a in alerts if a["level"]=="risk"),
        }
        return {"alerts": alerts, "summary": summary,
                "regime": regime_val, "scan_date": today_date}
    except Exception as e:
        import traceback
        return {"alerts": [], "summary": {"golden":0,"good":0,"watch":0,"risk":0},
                "regime": "UNKNOWN", "scan_date": "", "error": str(e),
                "trace": traceback.format_exc()}


def get_recommendation_history(days=30):
    try:
        archive_csv = os.path.join(PROJECT_ROOT, "archives", "recommended_history.csv")
        if not os.path.exists(archive_csv):
            return {"dates": [], "records": [], "stats": {}}
        df = pd.read_csv(archive_csv, dtype={"date": str, "ts_code": str})
        if df.empty:
            return {"dates": [], "records": [], "stats": {}}

        df = df.sort_values("date")
        days_lim = max(1, int(days))
        dates = sorted(df["date"].unique().tolist())[-days_lim:]
        df = df[df["date"].isin(dates)].copy()

        df["__rank"] = df.groupby("date")["build_score"].rank(method="first", ascending=False).astype(int)

        stats_map = {}
        all_dates = sorted(df["date"].unique())
        date_to_idx = {d: i for i, d in enumerate(all_dates)}
        today_idx = date_to_idx.get(str(dates[-1]), -1)
        for ts_code, group in df.groupby("ts_code"):
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
                "ever_top_3": ever_top_3,
            }

        records = []
        for _, r in df.iterrows():
            records.append({
                "date": str(r["date"]),
                "ts_code": str(r["ts_code"]),
                "name": str(r.get("name", "未知")),
                "industry": str(r.get("industry", "未分类")),
                "build_score": round(float(r.get("build_score", 0.0)), 2),
                "rank": int(r["__rank"]),
                "historic_stats": stats_map.get(r["ts_code"], {"total_recommends": 1, "consecutive_days": 1, "ever_top_3": False}),
            })
        return {"dates": [str(d) for d in dates], "records": records, "stats": stats_map}
    except Exception as e:
        import traceback
        return {"dates": [], "records": [], "stats": {}, "error": str(e), "trace": traceback.format_exc()}


def get_timing_alerts(use_portrait_router=True, regime_hint=None):
    """多周期择时警报：10日动量 / 30日趋势 / 60日波动率 / 画像整体分"""
    conn = get_db_connection(DB_PATH, timeout=60.0)
    try:
        opp = get_build_position_opportunities(use_portrait_router=use_portrait_router, regime_hint=regime_hint)
        opps = opp.get("opportunities", [])

        today = datetime.date.today().isoformat()
        alerts = []
        codes = [o["ts_code"] for o in opps[:5]]

        if codes:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 120")
            all_dates = sorted([r[0] for r in cursor.fetchall()])

            ph = ",".join(["?" for _ in codes])
            dp_df = pd.read_sql(
                f"SELECT ts_code, trade_date, close, pct_chg FROM daily_prices "
                f"WHERE ts_code IN ({ph}) ORDER BY ts_code, trade_date",
                conn, params=codes
            )

        opp_map = {o["ts_code"]: o for o in opps[:5]}

        # S2：从配置读取信号阈值
        _sig_cfg = get_scanner_cfg().get("signal_thresholds", {})
        _m10_hi = float(_sig_cfg.get("mom_10_strong_above", 3.0))
        _m10_lo = float(_sig_cfg.get("mom_10_weak_below", -3.0))
        _m30_hi = float(_sig_cfg.get("mom_30_strong_above", 10.0))
        _m30_lo = float(_sig_cfg.get("mom_30_weak_below", 0.0))
        _vol_lo = float(_sig_cfg.get("vol_60_low_below", 1.5))
        _vol_hi = float(_sig_cfg.get("vol_60_high_above", 3.0))
        _ps_excellent = float(_sig_cfg.get("portrait_excellent", 70.0))
        _ps_pass = float(_sig_cfg.get("portrait_pass", 50.0))
        _ps_marginal = float(_sig_cfg.get("portrait_marginal", 45.0))
        _green_min = int(_sig_cfg.get("overall_green_min", 3))
        _red_min = int(_sig_cfg.get("overall_red_min", 3))

        for code, o in opp_map.items():
            code_data = dp_df[dp_df["ts_code"] == code].sort_values("trade_date").copy() if codes else pd.DataFrame()
            if code_data.empty:
                continue
            closes = code_data["close"].astype(float).values
            pct_chgs = code_data["pct_chg"].astype(float).values

            mom_10 = (closes[-1] / closes[-10] - 1) * 100 if len(closes) >= 10 else 0.0
            mom_30 = (closes[-1] / closes[-30] - 1) * 100 if len(closes) >= 30 else 0.0

            ma_5  = np.mean(closes[-5:])  if len(closes) >= 5  else 0
            ma_10 = np.mean(closes[-10:]) if len(closes) >= 10 else 0
            ma_20 = np.mean(closes[-20:]) if len(closes) >= 20 else 0
            ma_30 = np.mean(closes[-30:]) if len(closes) >= 30 else 0
            trend_score = 0
            if ma_5  > ma_10: trend_score += 1
            if ma_10 > ma_20: trend_score += 1
            if ma_20 > ma_30: trend_score += 1

            vol_60 = (np.std(pct_chgs[-60:]) if len(pct_chgs) >= 60 else np.std(pct_chgs)) * 100

            portrait_score = float(o.get("portrait_score", 50.0))

            signals = []
            if mom_10 > _m10_hi:   signals.append(("10日动量强势", "green"))
            elif mom_10 < _m10_lo: signals.append(("10日动量弱势", "red"))
            else:               signals.append(("10日动量中性", "grey"))

            if mom_30 > _m30_hi:  signals.append(("30日趋势强势", "green"))
            elif mom_30 < _m30_lo:   signals.append(("30日趋势弱势", "red"))
            else:              signals.append(("30日趋势中性", "grey"))

            if trend_score == 3: signals.append(("均线多头排列", "green"))
            elif trend_score == 0: signals.append(("均线空头排列", "red"))
            else:                 signals.append((f"均线趋势中性({trend_score}/3)", "blue"))

            if vol_60 < _vol_lo:     signals.append(("波动率较低-稳", "blue"))
            elif vol_60 > _vol_hi:   signals.append(("波动率较高-慎", "orange"))
            else:                    signals.append(("波动率适中", "grey"))

            if portrait_score >= _ps_excellent: signals.append(("画像分优秀-可关注", "green"))
            elif portrait_score >= _ps_pass: signals.append(("画像分达标-可观察", "blue"))
            elif portrait_score >= _ps_marginal: signals.append(("画像分临线-需谨慎", "orange"))
            else:                     signals.append(("画像分偏低-慎参与", "red"))

            overall_green = sum(1 for _, c in signals if c == "green")
            overall_red = sum(1 for _, c in signals if c == "red")
            if overall_green >= _green_min:     overall_status = "建仓机会"
            elif overall_red >= _red_min:     overall_status = "观望/减仓"
            else:                      overall_status = "观察"

            alerts.append({
                "ts_code": code,
                "name": o["name"],
                "date": today,
                "signals": signals,
                "overall_status": overall_status,
                "indicators": {
                    "momentum_10d": round(mom_10, 2),
                    "momentum_30d": round(mom_30, 2),
                    "trend_score": trend_score,
                    "volatility_60d_pct": round(vol_60, 3),
                    "portrait_score": round(portrait_score, 1),
                }
            })
        return {"alerts": alerts}
    except Exception as e:
        import traceback
        return {"alerts": [], "error": str(e), "trace": traceback.format_exc()}
    finally:
        conn.close()


def record_alerts_feedback(feedback_data: dict):
    """警报反馈写入 JSONL 日志"""
    try:
        log_dir = os.path.join(PROJECT_ROOT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "alerts_feedback.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(clean_nan_inf(feedback_data), ensure_ascii=False) + "\n")
        return {"success": True, "message": "反馈已记录"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def save_scan_history(scan_result: dict) -> int:
    """
    将 get_build_position_opportunities() 的扫描结果持久化到 scan_history 表。
    兼容两种结果结构：
      1) 旧版：{"stocks": [...], "meta": {"scan_date": ...}}
      2) 新版画像路由：{"opportunities": [...], "scan_date": ...}
    返回：本次成功写入的记录数
    """
    stocks = scan_result.get("stocks") or scan_result.get("opportunities") or []
    meta   = scan_result.get("meta", {}) if isinstance(scan_result.get("meta"), dict) else {}
    if not stocks:
        return 0

    scan_date = str(scan_result.get("scan_date") or meta.get("scan_date", "")).replace("-", "")
    if not scan_date:
        scan_date = datetime.datetime.now().strftime("%Y%m%d")

    try:
        status = get_market_status()
        regime = status.get("regime", "RANGE").upper()
    except Exception:
        regime = "RANGE"

    conn = get_db_connection(DB_PATH)
    _ensure_scan_history_table(conn)

    written = 0
    try:
        for s in stocks:
            conn.execute("""
                INSERT OR IGNORE INTO scan_history
                    (scan_date, ts_code, name, industry, rank, build_score,
                     factor_score, winner_rate, big_net_inflow, close,
                     pct_chg, mvo_weight, regime, reason)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                scan_date,
                s.get("ts_code", ""),
                s.get("name", ""),
                s.get("industry", ""),
                s.get("rank", 0),
                s.get("build_score", 0.0),
                s.get("factor_score", 0.0),
                s.get("winner_rate", 0.0),
                # scan_history 列存储约定 = 万元；此处传入值来自 API 已是 亿元 → ×1e4 还原万元
                round(float(s.get("big_net_inflow", 0.0)) * 10000.0, 4),
                s.get("close", 0.0),
                s.get("pct_chg", 0.0),
                s.get("mvo_weight", 0.0),
                regime,
                s.get("reason", ""),
            ))
            if conn.execute("SELECT changes()").fetchone()[0]:
                written += 1
        conn.commit()
    except Exception as e:
        _logger.warning(f"[scan_history] 写入失败: {e}")
    finally:
        conn.close()

    return written
