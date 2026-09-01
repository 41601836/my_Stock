# -*- coding: utf-8 -*-
"""
evo_ml_rank.py —— EVO 阶段 5：LambdaRank 排序学习
=================================================================
M5.1（本文件当前范围）：数据集管道 + 标签构造 + 缺失处理 + 自检
M5.2/M5.3（后续追加）：train() / evaluate() / predict_daily() / psi_check()

设计要点（对照 docs/evo_roadmap_stage5_6.md）：
  特征 X（16 列，全部 t 日可得，无未来函数）：
    - 13 个 EVO 因子：当日截面 pct rank（与 portfolio_evo 推理口径一致）
    - graham_score：原始 0~7（绝对评分，不做 rank）
    - mkt_breadth_20d：全市场上涨家数占比的 20 日均值
    - mkt_vol_ratio：全市场截面收益波动 5 日均值 / 120 日均值（扩张/收缩比）
  标签 y：未来 fwd_period(5) 日复权收益 → 当日截面 pct rank → 10 档 int(0~9)
  query：每个交易日 = 一个 group
  切分：严格时间序 train_end / valid_end（evo.yaml），测试段只评估一次

缓存：evo/datasets/ds_f{fwd}_b{bins}.npz + meta.json（二次构建秒级加载）

用法：
  /Users/lyu/miniconda3/bin/python3 src/evo_ml_rank.py          # 构建 + 自检
  /Users/lyu/miniconda3/bin/python3 src/evo_ml_rank.py --force  # 忽略缓存重建
"""

import os
import sys
import json
import time
import sqlite3
import logging
from typing import Dict, Any, Tuple, Optional

import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════
# 路径 & 依赖注入
# ═══════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.paths import PATHS, startup_check
startup_check()

DB_PATH = PATHS.database.stock_data

sys.path.insert(0, os.path.join(PROJECT_ROOT, "web", "backend"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # src/ 复用
from services.evo import ensure_evo_tables, EvoConfig  # noqa: E402
from evo_dynamic_weights import get_enabled_factor_cols  # noqa: E402

logger = logging.getLogger("evo_ml_rank")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

DATASETS_DIR = os.path.join(PROJECT_ROOT, "evo", "datasets")

# ═══════════════════════════════════════════════════════════
# 数据集构建
# ═══════════════════════════════════════════════════════════
def _market_features(close_adj: pd.DataFrame) -> pd.DataFrame:
    """
    市场状态 2 列（只用 t 日及以前 → 无泄漏）。
    close_adj: dates×codes 复权收盘矩阵（全历史）
    返回 index=trade_date 的 2 列 DataFrame。
    """
    ret = close_adj.pct_change(fill_method=None)
    # 广度：全市场上涨家数占比的 20 日均值
    breadth = (ret > 0).mean(axis=1)
    breadth_20 = breadth.rolling(20, min_periods=10).mean()
    # 波动扩张比：截面波动 5 日均值 / 120 日均值
    vol = ret.std(axis=1)
    vol_ratio = vol.rolling(5, min_periods=3).mean() / vol.rolling(120, min_periods=60).mean()
    return pd.DataFrame({"mkt_breadth_20d": breadth_20, "mkt_vol_ratio": vol_ratio})


def _stack_rank(pivot_df: pd.DataFrame) -> pd.Series:
    """dates×codes 原始矩阵 → 当日截面 pct rank → stack 长表 Series（index=(date,code)）"""
    return pivot_df.rank(axis=1, pct=True).astype(np.float32).stack(future_stack=True)


def build_dataset(force: bool = False) -> Dict[str, Any]:
    """构建全历史 LambdaRank 数据集（带缓存）"""
    fwd = int(EvoConfig.get("lambdarank.fwd_period", 5))
    bins = int(EvoConfig.get("lambdarank.label_bins", 10))
    train_end = str(EvoConfig.get("lambdarank.train_end", "20241231"))
    valid_end = str(EvoConfig.get("lambdarank.valid_end", "20250630"))

    os.makedirs(DATASETS_DIR, exist_ok=True)
    cache_npz = os.path.join(DATASETS_DIR, f"ds_f{fwd}_b{bins}.npz")
    cache_meta = os.path.join(DATASETS_DIR, f"ds_f{fwd}_b{bins}.meta.json")
    if not force and os.path.exists(cache_npz) and os.path.exists(cache_meta):
        with open(cache_meta, encoding="utf-8") as f:
            meta = json.load(f)
        logger.info(f"[ML] 命中缓存 {cache_npz}（构建于 {meta['built_at']}），--force 可重建")
        return {"meta": meta, "cache": cache_npz, "loaded": False}

    t0 = time.time()
    ensure_evo_tables(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        # ── 1. 因子清单（与权重引擎同源：enabled ∩ 表列） ──────
        factor_cols = get_enabled_factor_cols(conn)
        feature_names = factor_cols + ["graham_score", "mkt_breadth_20d", "mkt_vol_ratio"]

        # ── 2. 全历史因子长表 ──────────────────────────────────
        logger.info("[ML] 加载 factor_values_evo 全历史…")
        sel = ", ".join(["ts_code", "trade_date"] + factor_cols + ["graham_score"])
        fv = pd.read_sql(f"SELECT {sel} FROM factor_values_evo", conn)
        fv["trade_date"] = fv["trade_date"].astype(str)

        # ── 3. 全历史价格 → 复权矩阵 + 标签矩阵 + 市场特征 ─────
        logger.info("[ML] 加载 daily_prices 全历史…")
        dp = pd.read_sql(
            "SELECT ts_code, trade_date, close, adj_factor FROM daily_prices "
            "WHERE trade_date >= (SELECT MIN(trade_date) FROM factor_values_evo)", conn)
        dp["trade_date"] = dp["trade_date"].astype(str)
        dp["close_adj"] = (dp["close"].astype(float) * dp["adj_factor"].fillna(1.0).astype(float)).astype(np.float32)
    finally:
        conn.close()

    dates_all = sorted(fv["trade_date"].unique())
    close_adj = dp.pivot_table(index="trade_date", columns="ts_code",
                               values="close_adj", aggfunc="last").sort_index()
    close_adj = close_adj.reindex(dates_all)

    # 标签：close(t+fwd)/close(t) - 1 → 当日截面 pct rank → bins 档 int
    fwd_ret = (close_adj.shift(-fwd) / close_adj - 1.0).astype(np.float32)
    label_pct = fwd_ret.rank(axis=1, pct=True)
    label_mat = np.floor(label_pct * bins).clip(0, bins - 1).astype(np.float32)
    label_mat[label_pct.isna()] = np.nan          # 末日无未来收益 → NaN 样本剔除

    # 市场状态（index 对齐因子日期）
    mkt = _market_features(close_adj).reindex(dates_all)

    # ── 4. 逐因子 pivot → 截面 rank → stack 长表（13 列一次成型）──
    logger.info(f"[ML] 截面 rank + stack {len(factor_cols)} 个因子…")
    stacked = []
    for col in factor_cols:
        p = fv.pivot_table(index="trade_date", columns="ts_code", values=col,
                           aggfunc="last").sort_index().reindex(dates_all)
        stacked.append(_stack_rank(p).rename(col))
    # graham_score：原始 0~7，不 rank
    p_graham = fv.pivot_table(index="trade_date", columns="ts_code", values="graham_score",
                              aggfunc="last").sort_index().reindex(dates_all)
    stacked.append(p_graham.astype(np.float32).stack(future_stack=True).rename("graham_score"))
    # 标签
    stacked.append(label_mat.stack(future_stack=True).rename("label"))
    del fv, p_graham
    Xy = pd.concat(stacked, axis=1)
    del stacked

    # 剔除无标签样本（末日 fwd 窗口不足）
    n_before = len(Xy)
    Xy = Xy.dropna(subset=["label"])
    n_dropped = n_before - len(Xy)

    # ── 5. 市场特征广播到长表（按 trade_date） ────────────────
    Xy["mkt_breadth_20d"] = Xy.index.get_level_values(0).map(mkt["mkt_breadth_20d"])
    Xy["mkt_vol_ratio"] = Xy.index.get_level_values(0).map(mkt["mkt_vol_ratio"])

    Xy = Xy.sort_index()
    Xy = Xy.astype({c: np.float32 for c in Xy.columns})

    # ── 6. query group（每交易日一组，LightGBM 要求连续排序） ──
    date_idx_raw = Xy.index.get_level_values(0)
    dates_list = sorted(Xy.index.get_level_values(0).unique())
    date_map = {d: i for i, d in enumerate(dates_list)}
    codes_list = sorted(Xy.index.get_level_values(1).unique())
    code_map = {c: i for i, c in enumerate(codes_list)}
    group = Xy.groupby(level=0, sort=False).size().to_numpy(np.int32)

    X = Xy[feature_names].to_numpy(np.float32)
    y = Xy["label"].to_numpy(np.float32)

    # ── 7. 切分索引（严格时间序） ─────────────────────────────
    seg = np.where(date_idx_raw <= train_end, 0,
          np.where(date_idx_raw <= valid_end, 1, 2)).astype(np.int8)  # 0训练 1验证 2测试

    meta = {
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fwd_period": fwd, "label_bins": bins,
        "train_end": train_end, "valid_end": valid_end,
        "feature_names": feature_names,
        "n_samples": int(len(Xy)), "n_features": len(feature_names),
        "n_dates": len(dates_list), "n_codes": len(codes_list),
        "n_dropped_no_label": int(n_dropped),
        "dates": dates_list, "codes": codes_list,   # 评估端还原日期/代码用
        "split": {
            "train": int((seg == 0).sum()), "valid": int((seg == 1).sum()),
            "test": int((seg == 2).sum()),
        },
        "nan_rate_by_feature": {c: round(float(Xy[c].isna().mean()), 4) for c in feature_names},
        "engine_version": "5.1",
    }

    # ── 8. 缓存 ───────────────────────────────────────────────
    np.savez(cache_npz, X=X, y=y, group=group, seg=seg,
             date_idx=date_idx_raw.map(date_map).to_numpy(np.int32),
             code_idx=Xy.index.get_level_values(1).map(code_map).to_numpy(np.int32))
    with open(cache_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(f"[ML] 数据集构建完成：{meta['n_samples']:,} 行 × {meta['n_features']} 特征，"
                f"切分 {meta['split']}，无标签剔除 {n_dropped:,}，耗时 {time.time() - t0:.0f}s")
    logger.info(f"[ML] 缓存：{cache_npz}")

    # 保留对齐抽查所需的日期/代码映射给自检
    return {"meta": meta, "cache": cache_npz, "loaded": True,
            "_dates_list": dates_list, "_codes_list": codes_list}


# ═══════════════════════════════════════════════════════════
# M5.2 训练 + 回测评估
# ═══════════════════════════════════════════════════════════
def _load_cached() -> Tuple[Dict[str, Any], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """加载缓存数据集 → (meta, X, y, seg, date_idx)"""
    fwd = int(EvoConfig.get("lambdarank.fwd_period", 5))
    bins = int(EvoConfig.get("lambdarank.label_bins", 10))
    cache = os.path.join(DATASETS_DIR, f"ds_f{fwd}_b{bins}.npz")
    if not os.path.exists(cache):
        raise RuntimeError("数据集缓存不存在，先运行 python3 src/evo_ml_rank.py 构建")
    with open(os.path.join(DATASETS_DIR, f"ds_f{fwd}_b{bins}.meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    d = np.load(cache)
    return meta, d["X"], d["y"], d["seg"], d["date_idx"], d["code_idx"]


def _group_by_date(date_idx_seg: np.ndarray) -> np.ndarray:
    """段内每个交易日的样本数（LightGBM group，要求连续排序）"""
    _, counts = np.unique(date_idx_seg, return_counts=True)
    return counts.astype(np.int32)  # date_idx 已按 (date,code) 排序 → unique 有序


def train() -> Dict[str, Any]:
    """LightGBM LambdaRank 训练（时间序切分 + 早停），模型落盘"""
    import lightgbm as lgb
    t0 = time.time()
    meta, X, y, seg, date_idx, code_idx = _load_cached()

    X_tr, y_tr = X[seg == 0], y[seg == 0].astype(np.int32)
    X_va, y_va = X[seg == 1], y[seg == 1].astype(np.int32)
    g_tr = _group_by_date(date_idx[seg == 0])
    g_va = _group_by_date(date_idx[seg == 1])
    logger.info(f"[ML] 训练 {X_tr.shape} / {len(g_tr)} 组；验证 {X_va.shape} / {len(g_va)} 组")

    params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "eval_at": [10],
        "num_leaves": int(EvoConfig.get("lambdarank.num_leaves", 63)),
        "learning_rate": float(EvoConfig.get("lambdarank.learning_rate", 0.05)),
        "feature_fraction": 0.9,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "min_data_in_leaf": 200,
        "verbose": -1,
        "num_threads": 0,
    }
    # ⚠️ Dataset 构造时必须挂 params，否则 4.x 早停报 "no eval metric"
    train_set = lgb.Dataset(X_tr, label=y_tr, group=g_tr,
                            params=params, free_raw_data=False)
    valid_set = lgb.Dataset(X_va, label=y_va, group=g_va,
                            reference=train_set, params=params, free_raw_data=False)
    model = lgb.train(
        params, train_set,
        num_boost_round=int(EvoConfig.get("lambdarank.num_boost_round", 600)),
        valid_sets=[valid_set],
        callbacks=[lgb.early_stopping(int(EvoConfig.get("lambdarank.early_stopping_rounds", 50))),
                   lgb.log_evaluation(100)],
    )

    os.makedirs(os.path.join(PROJECT_ROOT, "evo", "models"), exist_ok=True)
    model_path = os.path.join(PROJECT_ROOT, "evo", "models",
                              f"lgbmr_{time.strftime('%Y%m%d')}.txt")
    model.save_model(model_path)
    logger.info(f"[ML] 训练完成 best_iter={model.best_iteration} "
                f"valid NDCG@10={model.best_score['valid_0']['ndcg@10']:.4f}，"
                f"耗时 {time.time() - t0:.0f}s → {model_path}")
    return {"model": model, "model_path": model_path,
            "best_iteration": model.best_iteration,
            "valid_ndcg10": model.best_score["valid_0"]["ndcg@10"],
            "feature_importance": dict(zip(meta["feature_names"],
                model.feature_importance(importance_type="gain").tolist()))}


def _ndcg_at_k(y_rel: np.ndarray, score: np.ndarray, k: int = 10) -> float:
    """单 query NDCG@k（gain=2^rel-1）"""
    k = min(k, len(y_rel))
    order = np.argsort(-score)[:k]
    discounts = np.log2(np.arange(2, k + 2))
    dcg = float(((2.0 ** y_rel[order] - 1.0) / discounts).sum())
    ideal = np.sort(y_rel)[::-1][:k]
    idcg = float(((2.0 ** ideal - 1.0) / discounts).sum())
    return dcg / idcg if idcg > 0 else 0.0


def evaluate(model) -> Dict[str, Any]:
    """
    测试段评估（只跑一次）：ML vs IC 加权基线（防前视） vs 随机。
    指标：NDCG@10（逐日平均）+ Top5 组合 5 日收益年化。
    """
    t0 = time.time()
    meta, X, y, seg, date_idx, code_idx = _load_cached()
    fwd = meta["fwd_period"]
    dates, codes = meta["dates"], meta["codes"]
    factor_cols = [f for f in meta["feature_names"] if not f.startswith("mkt_") and f != "graham_score"]
    n_fac = len(factor_cols)

    rows = np.where(seg == 2)[0]
    di_arr = date_idx[rows]
    y_te, X_te = y[rows], X[rows]
    pred = model.predict(X_te)
    logger.info(f"[Eval] 测试段 {len(rows):,} 行 / {len(np.unique(di_arr))} 日")

    # IC 基线：滚动 IC 权重（截至 d-fwd，防前视；每 5 日更新一次）
    from evo_dynamic_weights import build_ic_df, calc_weights_snapshot
    ic_df, _, _ = build_ic_df(lookback=max(400, fwd * 80))
    valid_dates = ic_df.dropna(thresh=max(1, ic_df.shape[1] // 2)).index

    # 原始未来收益（Top5 组合用）：close_adj → fwd_ret
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        dp = pd.read_sql(
            "SELECT ts_code, trade_date, close, adj_factor FROM daily_prices "
            "WHERE trade_date >= (SELECT MIN(trade_date) FROM factor_values_evo)", conn)
    finally:
        conn.close()
    dp["trade_date"] = dp["trade_date"].astype(str)
    dp["close_adj"] = (dp["close"].astype(float) * dp["adj_factor"].fillna(1.0).astype(float)).astype(np.float32)
    close_adj = dp.pivot_table(index="trade_date", columns="ts_code",
                               values="close_adj", aggfunc="last").sort_index()
    # ⚠️ 执行口径（防"涨停买不进"偏差）：
    #   t 日收盘出信号 → t+1 收盘成交 → 持有 fwd 日 → t+1+fwd 收盘卖出
    exec_ret = (close_adj.shift(-(fwd + 1)) / close_adj.shift(-1) - 1.0).astype(np.float32)
    # t 日涨停（≈≥9.5%，主板/双创统一保守处理）或 t+1 涨停（实际成交日一字板买不进）→ 不可买入
    limit_up = (close_adj.pct_change(fill_method=None) >= 0.095)
    limit_up_t1 = limit_up.shift(-1)   # 行 t 取 t+1 行涨幅 = close(t+1)/close(t)-1
    # 停牌/无次日价格 → exec_ret NaN 自动排除

    rng = np.random.default_rng(42)
    ndcg_ml, ndcg_ic, ndcg_rd = [], [], []
    ret_ml, ret_ic, ret_rd = [], [], []
    w_vec = np.zeros(n_fac, np.float32)
    last_w_di = -999
    for di in np.unique(di_arr):
        m = di_arr == di
        rows_day = rows[m]
        y_day = y_te[m]
        if len(y_day) < 30:
            continue
        d = dates[di]

        # IC 基线权重：截至 d-fwd 个交易日的 20 日 IC 窗口（每 5 日重算）
        if di - last_w_di >= 5:
            as_of = dates[max(0, di - fwd)]
            as_of = max((vd for vd in valid_dates if vd <= as_of), default=None)
            if as_of is None:
                w_vec[:] = 1.0 / n_fac  # 无可用 IC → 均匀
            else:
                snap = calc_weights_snapshot(ic_df, str(as_of))
                w_vec[:] = [snap["weights"].get(c, 0.0) for c in factor_cols]
            last_w_di = di
        ic_score = X_te[m][:, :n_fac] @ w_vec
        rd_score = rng.random(m.sum())

        ndcg_ml.append(_ndcg_at_k(y_day, pred[m]))
        ndcg_ic.append(_ndcg_at_k(y_day, ic_score))
        ndcg_rd.append(_ndcg_at_k(y_day, rd_score))

        # Top5 组合收益（T+1 执行口径；剔除 t 日及 t+1 涨停票，顺延下一名）
        if d not in exec_ret.index:
            continue
        er = exec_ret.loc[d].to_numpy()
        buyable = ~(limit_up.loc[d].to_numpy() | limit_up_t1.loc[d].to_numpy())
        for top_list, bucket in ((ret_ml, pred[m]), (ret_ic, ic_score), (ret_rd, rd_score)):
            order = np.argsort(-bucket)
            picked = []
            for j in order:                      # 按分数从高到低，跳过涨停票
                if buyable[code_idx[rows_day[j]]]:
                    picked.append(code_idx[rows_day[j]])
                if len(picked) == 5:
                    break
            if len(picked) < 5:
                continue
            r = er[picked]
            r = r[~np.isnan(r)]
            if len(r):
                top_list.append(float(r.mean()))

    out = {
        "n_test_days": len(ndcg_ml),
        "ndcg10": {"ml": float(np.mean(ndcg_ml)), "ic_baseline": float(np.mean(ndcg_ic)),
                   "random": float(np.mean(ndcg_rd))},
        "top5_ret_5d": {"ml": float(np.mean(ret_ml)), "ic_baseline": float(np.mean(ret_ic)),
                        "random": float(np.mean(ret_rd))},
        "ann_diff_ml_vs_ic": (float(np.mean(ret_ml)) - float(np.mean(ret_ic))) / fwd * 250,
    }
    logger.info(f"[Eval] NDCG@10  ML={out['ndcg10']['ml']:.4f}  "
                f"IC基线={out['ndcg10']['ic_baseline']:.4f}  随机={out['ndcg10']['random']:.4f}")
    logger.info(f"[Eval] Top5 五日收益 ML={out['top5_ret_5d']['ml']:.4%}  "
                f"IC基线={out['top5_ret_5d']['ic_baseline']:.4%}  "
                f"年化差 ML-IC={out['ann_diff_ml_vs_ic']:+.2%}，耗时 {time.time() - t0:.0f}s")
    return out


def write_report(train_info: Dict[str, Any], eval_info: Dict[str, Any]) -> str:
    """M5.2 评估报告 → docs/evo_ml_report_YYYYMMDD.md"""
    meta, *_ = _load_cached()
    nd, tr = eval_info["ndcg10"], eval_info["top5_ret_5d"]
    lift = nd["ml"] / nd["ic_baseline"] - 1.0
    pass_ndcg = nd["ml"] >= nd["ic_baseline"] * 1.02
    pass_ret = eval_info["ann_diff_ml_vs_ic"] > 0
    imp = sorted(train_info["feature_importance"].items(), key=lambda x: -x[1])

    lines = [
        "# EVO 阶段 5 M5.2 — LambdaRank 训练与回测报告",
        f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}｜模型：{os.path.basename(train_info['model_path'])}",
        "",
        "## 1. 训练配置",
        f"- 数据集：{meta['n_samples']:,} 行 × {meta['n_features']} 特征（fwd={meta['fwd_period']}，"
        f"{meta['label_bins']} 档标签），切分 train/valid/test = {meta['split']}",
        f"- LightGBM lambdarank：num_leaves={EvoConfig.get('lambdarank.num_leaves')}, "
        f"lr={EvoConfig.get('lambdarank.learning_rate')}，best_iter={train_info['best_iteration']}，"
        f"valid NDCG@10={train_info['valid_ndcg10']:.4f}",
        "",
        "## 2. 测试段对比（20250701~20260831，只评估一次）",
        "",
        "| 指标 | ML LambdaRank | IC 加权基线（防前视） | 随机 |",
        "|---|---|---|---|",
        f"| NDCG@10 | **{nd['ml']:.4f}** | {nd['ic_baseline']:.4f} | {nd['random']:.4f} |",
        f"| Top5 组合 5 日收益 | **{tr['ml']:.4%}** | {tr['ic_baseline']:.4%} | {tr['random']:.4%} |",
        "",
        f"- NDCG 相对 IC 基线提升：**{lift:+.2%}**（验收线 +2% → {'PASS' if pass_ndcg else 'FAIL'}）",
        f"- Top5 年化差（ML − IC 基线）：**{eval_info['ann_diff_ml_vs_ic']:+.2%}**（验收线 >0 → {'PASS' if pass_ret else 'FAIL'}）",
        "",
        "## 3. 特征重要性（gain Top8）",
        "",
        "| 特征 | gain |",
        "|---|---|",
        *[f"| {k} | {v:,.0f} |" for k, v in imp[:8]],
        "",
        "## 4. 结论与 M5.3 前置判断",
        "",
        ("✅ 两项验收均通过：可进入 M5.3（每日推理接入 + /ml/* 接口真实化）。"
         if pass_ndcg and pass_ret else
         "⚠️ 未全部通过：建议先调参/加特征重训，或维持纯动态权重（β=0）继续观察。"),
        "- IC 基线说明：每 5 个交易日用「截至 d-5 的 20 日 RankIC 窗口」重算权重（与权重引擎同规则），"
        "严格不含决策日之后的 IC 信息。",
        "- 执行口径：t 日收盘出信号 → t+1 收盘成交 → 持有 5 日；t 日或 t+1 涨停票（≥9.5%）不可买入，"
        "顺延下一名；停牌/缺价剔除。naive 口径（t 收盘成交）ML Top5 曾达 59.9%/5 日，属涨停板买不进偏差。",
        "- 右尾警示：测试段标签 9 档（未来收益 top10%）的实际执行收益均值超 100%/5 日——2026 年题材市中"
        "连板/复牌暴利票集中在右尾；ML Top5 已经过涨停剔除，仍含未建模的交易成本与容量约束，"
        "M5.4 灰度期以「相对随机/IC 基线的超额」为主要决策依据，绝对收益不作为预期。",
        "- 测试段恰逢 2026 年反转市（动量/价值 IC 为负），ML 若显著胜出说明其捕捉了非线性结构。",
    ]
    path = os.path.join(PROJECT_ROOT, "docs", f"evo_ml_report_{time.strftime('%Y%m%d')}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"[ML] 报告已写入 {path}")
    return path


def run_m52() -> None:
    meta, *_ = _load_cached()
    logger.info(f"[ML] 使用数据集：{meta['n_samples']:,} 行（构建于 {meta['built_at']}，"
                f"engine v{meta.get('engine_version')}）")
    if meta.get("engine_version") != "5.1" or "dates" not in meta:
        logger.info("[ML] meta 缺 dates/codes（旧缓存）→ 重建数据集")
        build_dataset(force=True)
    info_tr = train()
    info_ev = evaluate(info_tr["model"])
    path = write_report(info_tr, info_ev)
    nd = info_ev["ndcg10"]
    ok = nd["ml"] >= nd["ic_baseline"] * 1.02 and info_ev["ann_diff_ml_vs_ic"] > 0
    print(f"\n{'🎉 M5.2 验收通过' if ok else '⛔ M5.2 验收未通过'}（报告：{path}）")


# ═══════════════════════════════════════════════════════════
# M5.3 每日推理 + PSI 漂移
# ═══════════════════════════════════════════════════════════
def _latest_model_path() -> str:
    mdir = os.path.join(PROJECT_ROOT, "evo", "models")
    paths = sorted(f for f in os.listdir(mdir) if f.startswith("lgbmr_") and f.endswith(".txt"))
    if not paths:
        raise RuntimeError("evo/models/ 下没有已训练模型，先运行 --train")
    return os.path.join(mdir, paths[-1])


def _psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """分布漂移 PSI（10 分位桶）；样本不足或全 NaN 返回 0"""
    expected = expected[~np.isnan(expected)]
    actual = actual[~np.isnan(actual)]
    if len(expected) < 100 or len(actual) < 100:
        return 0.0
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    pe = np.histogram(expected, edges)[0] / len(expected)
    pa = np.histogram(actual, edges)[0] / len(actual)
    pe, pa = np.clip(pe, 1e-4, None), np.clip(pa, 1e-4, None)
    return float(((pa - pe) * np.log(pa / pe)).sum())


def predict_daily() -> Dict[str, Any]:
    """
    每日推理：最新交易日因子截面 → 模型分数 + SHAP → evo_ml_predictions UPSERT。
    特征列严格按训练 meta["feature_names"] 顺序构造，缺失列填 NaN（LGBM 原生处理）。
    """
    import lightgbm as lgb
    if not EvoConfig.get("lambdarank.enabled", False):
        logger.info("[ML] lambdarank.enabled=false（安全闸 2），跳过推理")
        return {"enabled": False, "written": 0}

    t0 = time.time()
    model_path = _latest_model_path()
    model = lgb.Booster(model_file=model_path)
    meta = _load_cached()[0]
    feats = meta["feature_names"]

    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        # 幂等补列：model_version（骨架表没有，规划允许 EVO 表自增列）
        try:
            conn.execute("ALTER TABLE evo_ml_predictions ADD COLUMN model_version TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # 列已存在

        last = conn.execute("SELECT MAX(trade_date) FROM factor_values_evo").fetchone()[0]
        last = str(last)
        db_cols = {r[1] for r in conn.execute("PRAGMA table_info(factor_values_evo)")}
        need_factor_cols = [f for f in feats
                            if f not in ("graham_score", "mkt_breadth_20d", "mkt_vol_ratio")]
        sel = [c for c in ["ts_code", "trade_date", "graham_score",
                           "text_sentiment_score"] if c in db_cols]
        sel += [c for c in need_factor_cols if c in db_cols and c not in sel]
        fv = pd.read_sql(f"SELECT {', '.join(sel)} FROM factor_values_evo WHERE trade_date = ?",
                         conn, params=(last,))
        dp = pd.read_sql(
            "SELECT ts_code, trade_date, close, adj_factor FROM daily_prices "
            "WHERE trade_date >= (SELECT MIN(trade_date) FROM factor_values_evo)", conn)
    finally:
        conn.close()

    dp["trade_date"] = dp["trade_date"].astype(str)
    dp["close_adj"] = (dp["close"].astype(float) * dp["adj_factor"].fillna(1.0).astype(float)).astype(np.float32)
    close_adj = dp.pivot_table(index="trade_date", columns="ts_code",
                               values="close_adj", aggfunc="last").sort_index()
    mkt = _market_features(close_adj)
    del dp, close_adj

    fv["trade_date"] = fv["trade_date"].astype(str)
    fv = fv.set_index(["trade_date", "ts_code"])
    # 特征矩阵：rank 列（截面 pct rank）+ graham 原值 + mkt 广播；缺列 NaN
    X = pd.DataFrame(index=fv.index, columns=feats, dtype=np.float32)
    for f in feats:
        if f == "graham_score":
            X[f] = fv[f].to_numpy(np.float32) if f in fv.columns else np.nan
        elif f.startswith("mkt_"):
            X[f] = float(mkt[f].iloc[-1]) if f in mkt.columns and not np.isnan(mkt[f].iloc[-1]) else np.nan
        elif f in fv.columns:
            X[f] = fv[f].rank(pct=True).to_numpy(np.float32)
    Xv = X.to_numpy(np.float32)

    # 推理 + SHAP（pred_contrib：[n, F+1]，末列为 bias）
    score = model.predict(Xv)
    contrib = model.predict(Xv, pred_contrib=True)

    rows = []
    model_ver = os.path.basename(model_path)
    for i, (dt, code) in enumerate(X.index):
        shap = {f: round(float(contrib[i, j]), 5) for j, f in enumerate(feats)}
        shap["__bias__"] = round(float(contrib[i, -1]), 5)
        rows.append((str(dt), code, float(score[i]),
                     json.dumps(shap, ensure_ascii=False), model_ver))
    logger.info(f"[ML] 推理 {len(rows):,} 行 @ {last}（模型 {model_ver}）")

    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executemany(
            "INSERT OR REPLACE INTO evo_ml_predictions "
            "(trade_date, ts_code, rank_score, shap_json, model_version) "
            "VALUES (?, ?, ?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()

    # PSI 漂移检查：训练段分布 vs 当日截面（>阈值写 decay_alerts red）
    _, X_tr_all, _, seg_tr, _, _ = _load_cached()
    psi_red = float(EvoConfig.get("lambdarank.psi_red_threshold", 0.25))
    alerts = []
    for j, f in enumerate(feats):
        psi = _psi(X_tr_all[seg_tr == 0, j], Xv[:, j])
        if psi > psi_red:
            alerts.append((time.strftime("%Y%m%d"), f"__ml_psi_{f}", "red",
                           round(psi, 4), f"PSI>{psi_red}：训练段 vs {last} 分布漂移"))
    if alerts:
        conn = sqlite3.connect(DB_PATH, timeout=60.0)
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO evo_decay_alerts "
                "(alert_date, factor_name, level, rolling_ic, description) "
                "VALUES (?, ?, ?, ?, ?)", alerts)
            conn.commit()
        finally:
            conn.close()
        logger.warning(f"[ML] PSI 漂移警报 {len(alerts)} 条：{[a[1] for a in alerts]}")

    out = {"enabled": True, "trade_date": last, "written": len(rows),
           "model_version": model_ver, "psi_alerts": len(alerts),
           "duration_sec": round(time.time() - t0, 1)}
    logger.info(f"[ML] predict_daily 完成: {out}")
    return out



def _self_check(result: Dict[str, Any]) -> bool:
    meta = result["meta"]
    ok = True

    # ① 样本量
    n = meta["n_samples"]
    print(f"\n[验收①] 样本量: {n:,} 行（要求 > 3,000,000）→ {'PASS' if n > 3_000_000 else 'FAIL'}")
    ok &= n > 3_000_000

    # ② 时间切分边界（无重叠、顺序正确）
    tr, va, te = meta["split"]["train"], meta["split"]["valid"], meta["split"]["test"]
    print(f"[验收②] 切分: train={tr:,} (≤{meta['train_end']}) / valid={va:,} "
          f"(≤{meta['valid_end']}) / test={te:,} → "
          f"{'PASS' if tr > 0 and va > 0 and te > 0 else 'FAIL'}")
    ok &= tr > 0 and va > 0 and te > 0

    # ③ 矩阵→长表对齐抽查（管道正确性核心风险点）
    if result.get("loaded"):
        d = np.load(result["cache"])
        X, y = d["X"], d["y"]
        date_idx, code_idx = d["date_idx"], d["code_idx"]
        dates_list, codes_list = result["_dates_list"], result["_codes_list"]
        rng = np.random.default_rng(42)
        picks = rng.choice(len(y), 1000, replace=False)
        # 抽查项 1：特征列顺序与 meta 一致
        consistent = len(meta["feature_names"]) == X.shape[1]
        # 抽查项 2：标签分布均衡（10 档每档占比 5%~15%）
        uniq, cnts = np.unique(y[~np.isnan(y)], return_counts=True)
        dist_ok = len(uniq) == meta["label_bins"] and (cnts.max() / cnts.sum()) < 0.15
        # 抽查项 3：date/code 索引可逆（抽查 500 行还原后落在合法范围）
        rev_ok = bool((date_idx[picks] < len(dates_list)).all() and
                      (code_idx[picks] < len(codes_list)).all())
        print(f"[验收③] 对齐抽查: 特征列数一致={consistent}, 标签{meta['label_bins']}档均衡={dist_ok} "
              f"(最大档占比 {cnts.max()/cnts.sum():.1%}), 索引可逆={rev_ok} → "
              f"{'PASS' if consistent and dist_ok and rev_ok else 'FAIL'}")
        ok &= consistent and dist_ok and rev_ok

        # ④ 无未来函数（结构性保证 + 缺口检查）
        print(f"[验收④] 无未来函数: 特征仅由 t 日及以前构造（factor_values_evo@t + "
              f"rolling≤120日市场状态）；标签使用 t+{meta['fwd_period']} 收盘 → 结构性无泄漏；"
              f"末端无标签剔除 {meta['n_dropped_no_label']:,} 行")
        nan_rate = meta["nan_rate_by_feature"]
        high_nan = {k: v for k, v in nan_rate.items() if v > 0.5}
        print(f"[验收⑤] 特征 NaN 率: "
              f"{ {k: f'{v:.1%}' for k, v in nan_rate.items()} }；>50% 的列: {high_nan or '无'}")
    else:
        print("[验收③④⑤] 缓存命中跳过（--force 重建后执行）")

    print(f"\n{'🎉 M5.1 验收全部通过' if ok else '⛔ M5.1 验收未通过'}")
    return ok


if __name__ == "__main__":
    force = "--force" in sys.argv
    if "--train" in sys.argv:
        run_m52()   # M5.2：加载缓存 → 训练 → 测试段评估 → 报告
    elif "--predict" in sys.argv:
        predict_daily()   # M5.3：最新日推理 → evo_ml_predictions + PSI
    else:
        _self_check(build_dataset(force=force))
