# -*- coding: utf-8 -*-
"""
feature_engineering_evo.py —— EVO 进化层专属特征计算工程
=================================================================
完全独立于 feature_engineering.py（经典层）：
  经典层写 factor_values（列名 stock_code）
  进化层写 factor_values_evo（列名 ts_code，DDL 在 services.evo._common）

本模块计算：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  P0-2 ✅ 10 个交叉/交互因子（按日截面 rank 相乘，IC 提升最大增量源）
  P1-5 ✅ 3  个预期差代理因子（surprise_*）
  P2-7 ✅ 1  个 Graham 7 项防御得分 + detail JSON
  P2-6 🔲 文本因子（后续 text_factors.py 实现，此处先留空列）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

输入依赖：
  1. factor_values（经典 26 因子表，已通过 feature_engineering.py 生成）
  2. daily_basic（pe_ttm / pb / circ_mv → Graham 代理）

设计原则：
  * 绝不 DROP factor_values（经典层表）；只读 + 写独立 _evo 表
  * 所有交叉因子先按日截面做百分比 rank（0~1，对齐量纲）再相乘/加减
  * 每只因子做独立开关（读 evo.yaml cross_factors.factors），可逐个验证
  * 若 factor_values_evo 表已存在：UPSERT（INSERT OR REPLACE），增量覆盖
"""

import os
import sys
import json
import time
import sqlite3
import logging
from typing import Dict, List, Any

import pandas as pd
import numpy as np

# ═══════════════════════════════════════════════════════════
# 路径 & 依赖注入
# ═══════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.paths import PATHS, startup_check
startup_check()

DB_PATH = PATHS.database.stock_data

# EVO 层工具：ensure_evo_tables / EvoConfig / graham_proxy_scores
sys.path.insert(0, os.path.join(PROJECT_ROOT, "web", "backend"))
from services.evo import (  # noqa: E402
    ensure_evo_tables,
    EvoConfig,
    graham_proxy_scores,
)

logger = logging.getLogger("feature_engineering_evo")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


# ═══════════════════════════════════════════════════════════
# 10 个交叉因子定义（名称 + 计算表达式）
#   所有输入：按 trade_date 分组后的 percent rank [0,1]
#   rank_x(*cols) 是工具函数：按日截面做 pct rank
# ═══════════════════════════════════════════════════════════

def _pct_rank(series: pd.Series) -> pd.Series:
    """按传入 Series 做 pct rank；NaN → 0.5 居中（中性）"""
    return series.rank(pct=True).fillna(0.5)


# ── 交叉因子配方 ──────────────────────────────────────────
# 命名约定：
#   +rank(a) × +rank(b)  → 「a 高且 b 高」双高有利
#   +rank(a) × (1 - rank(b))  → 「a 高且 b 低」高低有利
#   最后都归一化回 [0,1] pct rank（按日截面），确保量纲一致
CROSS_FACTOR_FORMULAS: Dict[str, Any] = {
    # 1. 质量 × 动量：ROE 高 + 20日上涨强 = 优质向上趋势
    "inter_quality_momentum": lambda rk: (
        rk("roe") * rk("return_20d")
    ),
    # 2. 价值 × 超额：低 PB（倒数大）+ 跑赢市场 = 价值修复启动
    "inter_value_excess": lambda rk: (
        # pb 越低越好 → 用 1 - rank(pb) 映射
        (1.0 - rk("pb")) * rk("excess_return_20d")
    ),
    # 3. 筹码集中 × 放量：价格在均线附近（集中度指标越小越集中）+ 量比放大
    #    chip_concentration 越小越集中 → 用 1 - rank(cc)
    "inter_chip_volume": lambda rk: (
        (1.0 - rk("chip_concentration")) * rk("vol_ratio")
    ),
    # 4. 聪明钱 × 防御：北向持续流入 × 低换手（非拥挤）
    "inter_smart_defense": lambda rk: (
        rk("north_net_inflow_ratio") * rk("low_turnover_flag")
    ),
    # 5. 低位 × 超跌反转：获利盘在低位（profit_ratio 小）× 5 日负收益（超跌）
    #    两者都是低 → 同时低 = 反弹候选
    "inter_overshoot_reversal": lambda rk: (
        # profit_ratio 越小 → 越在 60 日低位；return_5d 越小 → 近期超跌
        (1.0 - rk("profit_ratio_estimate")) * (1.0 - rk("return_5d"))
    ),
    # 6. 三重：价值 × 动量 × 质量（PB倒数 × 20日动量 × ROE）
    "triple_value_mom_quality": lambda rk: (
        (1.0 - rk("pb")) * rk("return_20d") * rk("roe")
    ),
    # 7. 正动量 × 负偏度肥尾（上涨 + 分布左偏 → 涨多跌少）
    #    skewness 越小（越负）越好 → 1 - rank(skew)
    "inter_mom_skew_neg": lambda rk: (
        rk("return_10d") * (1.0 - rk("skewness_20d"))
    ),
    # 8. 低波动 × 高获利盘（稳+筹码舒适，即"稳中有升"）
    #    volatility 越小越好 → 1 - rank(volatility_20d)
    "inter_lowvol_profit": lambda rk: (
        (1.0 - rk("volatility_20d")) * rk("profit_ratio_estimate")
    ),
    # 9. 高换手 × 超跌（放量恐慌砸坑 → 反弹候选）
    "inter_turnover_reversal": lambda rk: (
        rk("turnover_rate_5d") * (1.0 - rk("return_5d"))
    ),
    # 10. 高获利盘 × 大单净流入（突破筹码密集区 + 资金确认）
    "inter_chip_break_right": lambda rk: (
        rk("profit_ratio_estimate") * rk("main_force_score")
    ),
}


def _apply_cross_factors(fv: pd.DataFrame, enabled_map: Dict[str, bool]) -> pd.DataFrame:
    """
    对 fv（factor_values 全量数据）计算 10 个交叉因子列。
    未启用的列留 NaN（SQLite 写入时为 NULL），后续查询会 COALESCE。
    """
    gb = fv.groupby("trade_date", group_keys=False)

    # 先缓存所有输入列的日截面 pct rank
    input_cols = [
        "roe", "return_20d", "pb", "excess_return_20d",
        "chip_concentration", "vol_ratio", "north_net_inflow_ratio",
        "low_turnover_flag", "profit_ratio_estimate", "return_5d",
        "return_10d", "skewness_20d", "volatility_20d",
        "turnover_rate_5d", "main_force_score",
    ]
    rank_cache: Dict[str, pd.Series] = {}
    for col in input_cols:
        if col in fv.columns:
            rank_cache[col] = gb[col].apply(_pct_rank).astype(np.float32)
        else:
            rank_cache[col] = pd.Series(0.5, index=fv.index, dtype=np.float32)

    def rk(col: str) -> pd.Series:
        return rank_cache.get(col, pd.Series(0.5, index=fv.index, dtype=np.float32))

    # 按 enabled_map 计算
    for name, formula in CROSS_FACTOR_FORMULAS.items():
        if not enabled_map.get(name, True):
            fv[name] = np.nan
            continue
        try:
            raw = formula(rk)  # 0~1 之间的值（非严格）
            # 再做一次日截面 rank，确保输出严格 [0,1]，量纲对齐；
            # include_groups=False：适配 pandas 2.3+，消除 grouping columns 的 FutureWarning
            fv[name] = (
                gb.apply(lambda g, s=raw: _pct_rank(s.loc[g.index]), include_groups=False)
                .astype(np.float32)
            )
        except Exception as e:
            logger.warning(f"[Cross] 因子 {name} 计算失败（置 NaN）: {e}")
            fv[name] = np.nan
    return fv


# ═══════════════════════════════════════════════════════════
# 3 个预期差代理因子
# ═══════════════════════════════════════════════════════════

def _apply_surprise_factors(df: pd.DataFrame, enabled_cfg: Dict[str, bool]) -> pd.DataFrame:
    gb = df.groupby("ts_code", group_keys=False)

    # 1. 资金预期差投票：(close / 20日均价 - 1) × 量比偏离
    if enabled_cfg.get("price_vote_gap", True):
        ma20 = gb["close_adj"].transform(lambda x: x.rolling(20, min_periods=10).mean())
        price_gap = (df["close_adj"] / (ma20 + 1e-8) - 1.0).clip(-0.5, 0.5)
        # 再乘 turnover_rate_20d 日截面 rank → 量大认可度高
        vol_rank = df.groupby("trade_date", group_keys=False)["turnover_rate_20d"].apply(_pct_rank)
        df["surprise_price_vote"] = (price_gap * vol_rank.values).astype(np.float32)
    else:
        df["surprise_price_vote"] = np.nan

    # 2. 跳空缺口标记（近似财报超预期跳空）：(今开 - 昨收)/昨收 > 3% 且量比 > 1.5
    if enabled_cfg.get("earnings_gap_flag", True):
        prev_close = gb["close_adj"].shift(1)
        gap = (df["close_adj"] - prev_close) / (prev_close + 1e-8)
        condition = (gap > 0.03) & (df["vol_ratio"].fillna(0) > 1.5)
        df["surprise_earnings_gap"] = condition.astype(np.int8)
    else:
        df["surprise_earnings_gap"] = np.nan

    # 3. ROE 环比变化 Z-Score（近似超预期程度）：按个股 120 日滚动
    if enabled_cfg.get("roe_qoq_zscore", True):
        roe = df["roe"].fillna(0.0)
        roe_mean = gb["roe"].transform(lambda x: x.rolling(120, min_periods=20).mean())
        roe_std  = gb["roe"].transform(lambda x: x.rolling(120, min_periods=20).std())
        df["surprise_roe_qoq"] = ((roe - roe_mean) / (roe_std + 1e-8)).clip(-5.0, 5.0).astype(np.float32)
    else:
        df["surprise_roe_qoq"] = np.nan
    return df


# ═══════════════════════════════════════════════════════════
# Graham 7 项防御得分（代理版）
# ═══════════════════════════════════════════════════════════

def _apply_graham(df: pd.DataFrame, enabled: bool) -> pd.DataFrame:
    if not enabled:
        df["graham_score"] = np.nan
        df["graham_detail_json"] = None
        return df

    # 取估值/质量/规模列（factor_values 里已存在：pe_ttm, pb, roe；circ_mv 来自 daily_basic）
    circ_mv = df.get("circ_mv", pd.Series(0.0, index=df.index)).fillna(0.0)
    pe_protected = df["pe_ttm"].apply(lambda x: float(x) if x and x > 0.1 else 0.1).astype(float)
    # 重新算一个 roe_fallback：pb / pe（与 feature_engineering.py 保持一致，避免列缺失）
    roe_fallback = df["roe"].fillna(0.0) if "roe" in df.columns else (
        (df["pb"] / pe_protected).clip(-0.5, 0.5).fillna(0.0)
    )

    scores: List[int] = []
    details: List[str] = []
    for tup in zip(df["pe_ttm"].tolist(), df["pb"].tolist(), roe_fallback.tolist(), circ_mv.tolist()):
        pe, pb, roe, cmv = tup
        score, detail_dict = graham_proxy_scores({
            "pe_ttm": float(pe or 0.0),
            "pb": float(pb or 0.0),
            "roe": float(roe or 0.0),
            "circ_mv": float(cmv or 0.0),
        })
        scores.append(int(score))
        details.append(json.dumps(detail_dict, ensure_ascii=False))

    df["graham_score"] = scores
    df["graham_detail_json"] = details
    return df


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def calculate_evo_factors(db_path: str = DB_PATH) -> pd.DataFrame:
    """
    1. 确保 _evo 表存在（幂等）
    2. 读取 factor_values + daily_basic（只做 SELECT，永不写经典表）
    3. 计算：10 交叉 + 3 预期差 + Graham
    4. UPSERT 写入 factor_values_evo
    """
    t0 = time.time()
    ensure_evo_tables(db_path)

    cfg_cross = EvoConfig.get("cross_factors", {}) or {}
    cross_enabled: Dict[str, bool] = cfg_cross.get("factors", {}) or {}
    cross_all_on = bool(cfg_cross.get("enabled", True))

    cfg_surp = EvoConfig.get("surprise_factors", {}) or {}
    surp_enabled = dict(cfg_surp) if bool(cfg_surp.get("enabled", True)) else {}

    graham_on = bool(EvoConfig.get("graham_filter.enabled", True))

    logger.info("=" * 72)
    logger.info("[EvoFeature] 开始计算 EVO 层 10 交叉 + 3 预期差 + Graham 因子")
    logger.info(f"[EvoFeature] 交叉因子启用开关：{cross_all_on}，预期差：{bool(cfg_surp.get('enabled',True))}，Graham：{graham_on}")

    # ── 2. 读取经典因子 + 估值基础表 ────────────────────────────
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")

    logger.info("[EvoFeature] 加载 factor_values（经典层只读）…")
    fv = pd.read_sql("SELECT * FROM factor_values", conn)
    # 统一列名：stock_code → ts_code
    if "stock_code" in fv.columns and "ts_code" not in fv.columns:
        fv = fv.rename(columns={"stock_code": "ts_code"})
    logger.info(f"[EvoFeature] factor_values 加载完成，行数={len(fv)}，日期范围={fv['trade_date'].min()}~{fv['trade_date'].max()}")

    # daily_basic 中 circ_mv 用于 Graham 规模阈值（左连接，缺失则补 0）
    need_circ = (
        ("circ_mv" not in fv.columns)
        and graham_on
    )
    if need_circ:
        logger.info("[EvoFeature] factor_values 缺 circ_mv，从 daily_basic 合并…")
        db = pd.read_sql(
            "SELECT ts_code, trade_date, circ_mv FROM daily_basic WHERE trade_date >= '20200301'",
            conn
        )
        db["trade_date"] = db["trade_date"].astype(str)
        fv["trade_date"] = fv["trade_date"].astype(str)
        fv = fv.merge(db[["ts_code", "trade_date", "circ_mv"]], how="left", on=["ts_code", "trade_date"])
    if "circ_mv" not in fv.columns:
        fv["circ_mv"] = 0.0

    # close_adj / vol_ratio：factor_values 里有 vol_ratio（实验因子）、hot_money_score 等；
    #   但 close_adj 通常不在 factor_values 里（原始行情列）。按列 **分别** 判断 & 补，
    #   merge 时用 suffixes=('', '_dp') 区分，并统一合成单列（缺失时走 _dp，已有列不被覆盖）。
    missing_cols_for_surp: List[str] = []
    if bool(cfg_surp.get("enabled", True)):
        if "close_adj" not in fv.columns: missing_cols_for_surp.append("close_adj")
        if "vol_ratio" not in fv.columns: missing_cols_for_surp.append("vol_ratio")
    if missing_cols_for_surp:
        logger.info(f"[EvoFeature] 从 daily_prices 合并缺失列: {missing_cols_for_surp}")
        need_dp = ["ts_code", "trade_date", "close", "adj_factor", "vol"]
        dp = pd.read_sql(
            f"SELECT {','.join(need_dp)} FROM daily_prices WHERE trade_date >= '20200301'",
            conn
        )
        dp["trade_date"] = dp["trade_date"].astype(str)
        merge_cols = ["ts_code", "trade_date"]
        build_cols = []
        if "close_adj" in missing_cols_for_surp:
            dp["close_adj"] = dp["close"] * dp["adj_factor"].fillna(1.0)
            build_cols.append("close_adj")
        if "vol_ratio" in missing_cols_for_surp:
            gb_v = dp.groupby("ts_code", group_keys=False)
            v5 = gb_v["vol"].transform(lambda x: x.rolling(5, min_periods=1).mean())
            v60 = gb_v["vol"].transform(lambda x: x.rolling(60, min_periods=10).mean())
            dp["vol_ratio"] = (v5 / (v60 + 1e-8)).clip(0, 20)
            build_cols.append("vol_ratio")
        fv["trade_date"] = fv["trade_date"].astype(str)
        # suffixes=('', '_dp')：如果 fv 已有列（比如 vol_ratio），merge 后保持 fv 的那列，_dp 列随后 drop
        fv = fv.merge(
            dp[merge_cols + build_cols],
            how="left", on=merge_cols, suffixes=("", "_dp")
        )
        # 防御性清理：如果出现 _dp 重复列（正常情况下不会，因为缺失才补，但避免未来 factor_values 加列时破坏）
        for c in list(fv.columns):
            if c.endswith("_dp"):
                base = c[:-3]
                if base not in fv.columns or fv[base].isna().all():
                    fv[base] = fv[c]
                fv.drop(columns=[c], inplace=True, errors="ignore")
        # 兜底：无论何种情况补齐 vol_ratio（如果全 NaN → 填 1.0，防止后续 >1.5 比较时全 False）
        if "vol_ratio" in fv.columns:
            fv["vol_ratio"] = fv["vol_ratio"].replace([np.inf, -np.inf], np.nan)
            fv["vol_ratio"] = fv["vol_ratio"].fillna(1.0)

    # 补齐 turnover_rate_20d（经典层已有，若缺失按 turnover_rate 滚动）
    if "turnover_rate_20d" not in fv.columns:
        gb = fv.groupby("ts_code", group_keys=False)
        fv["turnover_rate_20d"] = gb["turnover_rate"].transform(
            lambda x: x.rolling(20, min_periods=10).mean()
        ).fillna(0.0)

    # 若缺 low_turnover_flag（兼容老版本 factor_values）
    if "low_turnover_flag" not in fv.columns:
        q30 = fv.groupby("trade_date", group_keys=False)["turnover_rate_5d"].transform(
            lambda x: x.quantile(0.30) if len(x.dropna()) > 100 else np.nan
        )
        fv["low_turnover_flag"] = (fv["turnover_rate_5d"].fillna(0) < q30).astype(int)

    # ── 3. 计算三类因子 ────────────────────────────────────────
    logger.info("[EvoFeature] 计算 10 个交叉因子…")
    fv = _apply_cross_factors(fv, cross_enabled if cross_all_on else {})

    logger.info("[EvoFeature] 计算 3 个预期差因子…")
    fv = _apply_surprise_factors(fv, surp_enabled)

    logger.info("[EvoFeature] 计算 Graham 7 项得分与明细…")
    fv = _apply_graham(fv, graham_on)

    # text_factors 占位列（后续 text_factors.py 生成后补写）
    fv["text_sentiment_score"] = np.nan

    # ── 4. 写 factor_values_evo（UPSERT：按主键冲突替换）──────
    evo_cols = [
        "ts_code", "trade_date",
        # 10 交叉
        *CROSS_FACTOR_FORMULAS.keys(),
        # 3 预期差
        "surprise_price_vote", "surprise_earnings_gap", "surprise_roe_qoq",
        # Graham
        "graham_score", "graham_detail_json",
        # 文本因子（占位）
        "text_sentiment_score",
    ]
    # 缺列兜底（cross 被关闭时 _apply 返回 NaN 列保证存在）
    for c in evo_cols:
        if c not in fv.columns:
            fv[c] = np.nan

    save = fv[evo_cols].copy()
    # 数据起始对齐：只保存 2020-03 之后（避免 1 月数据无窗口）
    save = save[save["trade_date"] >= "20200301"]
    # 内存优化：downcast float
    for c in save.select_dtypes(include=["float32", "float64"]).columns:
        save[c] = pd.to_numeric(save[c], downcast="float")

    logger.info(f"[EvoFeature] 待写入 {len(save)} 行，开始 UPSERT 到 factor_values_evo …")

    # SQLite UPSERT 用 executemany，避免一次把 500 万行全塞进 to_sql（内存友好）
    placeholders = ",".join(["?"] * len(evo_cols))
    col_list = ",".join(evo_cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in evo_cols if c not in ("ts_code", "trade_date"))
    sql_up = (
        f"INSERT INTO factor_values_evo ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(ts_code, trade_date) DO UPDATE SET {updates}"
    )

    cur = conn.cursor()
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA cache_size=-204800;")  # 200 MB 页缓存（2 GB 上限机型安全）

    BATCH = 20000
    rows_iter = (tuple(x) for x in save.itertuples(index=False, name=None))
    batch = []
    n_ins = 0
    t_w = time.time()
    for r in rows_iter:
        batch.append(r)
        if len(batch) >= BATCH:
            cur.executemany(sql_up, batch)
            n_ins += len(batch)
            batch = []
            if n_ins % 200000 == 0:
                logger.info(f"[EvoFeature] 已写入 {n_ins}/{len(save)} 行…")
    if batch:
        cur.executemany(sql_up, batch)
        n_ins += len(batch)
    conn.commit()
    logger.info(f"[EvoFeature] UPSERT 完成：共 {n_ins} 行，写入耗时 {time.time()-t_w:.2f}s")

    # 文本因子空表预先创建一次
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS evo_text_sentiment_scores (
                ts_code TEXT, trade_date TEXT, source TEXT,
                sentiment_score REAL, keyword_hits_json TEXT,
                PRIMARY KEY (ts_code, trade_date, source)
            )
        """)
        conn.commit()
    except Exception as e:
        logger.warning(f"[EvoFeature] 文本因子表创建跳过: {e}")

    conn.close()

    dt = time.time() - t0
    latest = save["trade_date"].max()
    logger.info(f"🎉 [EvoFeature] 全部完成，最新交易日 {latest}，总行数 {len(save)}，总耗时 {dt:.2f}s")
    return save


# ═══════════════════════════════════════════════════════════
# CLI 入口：
#   PYTHONPATH=. python3 src/feature_engineering_evo.py
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    calculate_evo_factors()
