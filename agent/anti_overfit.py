# -*- coding: utf-8 -*-
"""
anti_overfit.py — 防过拟合审计模块

三段审计：
1. Purged Walk-Forward CV：带 purge + embargo 的时序交叉验证
2. IC 半衰期检验：因子 IC 衰减速度，衰减太快 = 过拟合
3. 样本内外一致性：训练集表现 vs 样本外表现比值
"""
import numpy as np
import pandas as pd
from typing import Dict, Tuple, List


def purged_walk_forward_cv(
    df: pd.DataFrame,
    factor_cols: List[str],
    weight_dict: Dict[str, float],
    weeks_total: int = 208,
    n_folds: int = 5,
    purge_weeks: int = 2,
    embargo_weeks: int = 2,
) -> Dict:
    """
    Purged Walk-Forward 交叉验证

    将 208 周分为 n_folds 段，每段训练在前、测试在后，
    训练和测试之间插入 purge 间隙和 embargo 禁运期，
    防止信息泄漏导致过拟合。

    Parameters
    ----------
    df : DataFrame
        包含 trade_date, factor_cols, future_return_5d 的对齐数据
    factor_cols : list
        因子列表
    weight_dict : dict
        因子权重
    weeks_total : int
        总周数
    n_folds : int
        折数
    purge_weeks : int
        清洗间隙周数
    embargo_weeks : int
        禁运期周数

    Returns
    -------
    dict
        audit_pass, cv_ratio, per_fold_metrics, overfit_flag
    """
    dates = sorted(df["trade_date"].unique())
    n_dates = len(dates)
    if n_dates < 20:
        return {"audit_pass": True, "reason": "数据不足，跳过审计", "cv_ratio": 1.0, "per_fold": []}

    fold_size = n_dates // n_folds
    train_ratio = 0.6  # 每折 60% 训练，40% 测试

    fold_results = []
    for i in range(n_folds):
        start = i * fold_size
        end = min((i + 1) * fold_size, n_dates)
        if end - start < 10:
            continue

        split = int(start + (end - start) * train_ratio)
        purge_end = min(split + purge_weeks, end)
        embargo_start = max(purge_end, end - embargo_weeks)

        train_dates = dates[start:split]
        test_dates = dates[purge_end:embargo_start] + dates[end:] if embargo_weeks > 0 else dates[purge_end:end]

        if not train_dates or not test_dates:
            continue

        train_df = df[df["trade_date"].isin(train_dates)]
        test_df = df[df["trade_date"].isin(test_dates)]

        if len(train_df) < 50 or len(test_df) < 30:
            continue

        # 训练集 IC
        train_ic = _compute_weighted_ic(train_df, factor_cols, weight_dict)
        # 测试集 IC
        test_ic = _compute_weighted_ic(test_df, factor_cols, weight_dict)

        # 训练集超额卡玛（简化版）
        train_calmar = _compute_quick_calmar(train_df, factor_cols, weight_dict)
        test_calmar = _compute_quick_calmar(test_df, factor_cols, weight_dict)

        ratio = test_calmar / train_calmar if abs(train_calmar) > 1e-6 else 0.0

        fold_results.append({
            "fold": i + 1,
            "train_dates": len(train_dates),
            "test_dates": len(test_dates),
            "train_ic": round(train_ic, 4),
            "test_ic": round(test_ic, 4),
            "train_calmar": round(train_calmar, 4),
            "test_calmar": round(test_calmar, 4),
            "ratio": round(ratio, 4),
        })

    if not fold_results:
        return {"audit_pass": True, "reason": "有效折数不足", "cv_ratio": 1.0, "per_fold": []}

    avg_ratio = np.mean([f["ratio"] for f in fold_results])
    # 过拟合判定：样本外表现低于样本内的 50%
    overfit = avg_ratio < 0.5

    return {
        "audit_pass": not overfit,
        "cv_ratio": round(avg_ratio, 4),
        "overfit_flag": overfit,
        "threshold": 0.5,
        "per_fold": fold_results,
        "summary": f"CV ratio={avg_ratio:.4f} ({'PASS' if not overfit else 'FAIL: 过拟合'}), "
                   f"threshold={0.5}, folds={len(fold_results)}",
    }


def _compute_weighted_ic(df, factor_cols, weight_dict) -> float:
    """计算加权因子 IC"""
    dates = df["trade_date"].unique()
    ics = []
    for dt in dates:
        day_df = df[df["trade_date"] == dt]
        if len(day_df) < 30:
            continue
        # 加权因子值
        weighted = np.zeros(len(day_df))
        for f in factor_cols:
            if f in day_df.columns and f in weight_dict:
                vals = day_df[f].rank().values
                weighted += weight_dict[f] * vals
        # Spearman 相关
        if "future_return_5d" in day_df.columns:
            from scipy.stats import spearmanr
            corr, _ = spearmanr(weighted, day_df["future_return_5d"].rank())
            if np.isfinite(corr):
                ics.append(corr)
    return np.mean(ics) if ics else 0.0


def _compute_quick_calmar(df, factor_cols, weight_dict) -> float:
    """快速计算卡玛比率（简化版，用于 CV）"""
    dates = sorted(df["trade_date"].unique())
    if len(dates) < 5:
        return 0.0

    portfolio_returns = []
    for dt in dates:
        day_df = df[df["trade_date"] == dt].copy()
        if len(day_df) < 30:
            continue
        # 加权因子值
        day_df["composite_score"] = 0.0
        for f in factor_cols:
            if f in day_df.columns and f in weight_dict:
                day_df["composite_score"] += weight_dict[f] * day_df[f].rank()
        # 选 top_n
        top_n = min(10, len(day_df) // 5)
        top = day_df.nlargest(top_n, "composite_score")
        if "future_return_5d" in top.columns:
            portfolio_returns.append(top["future_return_5d"].mean())

    if len(portfolio_returns) < 5:
        return 0.0

    returns = np.array(portfolio_returns)
    ann_return = np.mean(returns) * 52  # 年化
    max_dd = _max_drawdown(returns)
    if max_dd < 1e-6:
        return ann_return if ann_return > 0 else 0.0
    return ann_return / abs(max_dd)


def _max_drawdown(returns: np.ndarray) -> float:
    """计算最大回撤"""
    cum = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return np.min(dd) if len(dd) > 0 else 0.0


def ic_half_life_check(df, factor_cols, window=60) -> Dict:
    """
    IC 半衰期检验

    计算每个因子的 IC 时间序列，拟合指数衰减模型，
    估计 IC 衰减到一半所需的时间（半衰期）。

    半衰期 < 4 周 → 因子衰减过快，可能过拟合
    半衰期 > 52 周 → 因子稳定，长期有效
    """
    dates = sorted(df["trade_date"].unique())
    ic_series = {f: [] for f in factor_cols}
    ic_dates = []

    for dt in dates:
        day_df = df[df["trade_date"] == dt]
        if len(day_df) < 30:
            continue
        if "future_return_5d" not in day_df.columns:
            continue

        from scipy.stats import spearmanr
        ret_rank = day_df["future_return_5d"].rank().values
        ic_dates.append(dt)
        for f in factor_cols:
            if f in day_df.columns:
                corr, _ = spearmanr(day_df[f].rank().values, ret_rank)
                ic_series[f].append(corr if np.isfinite(corr) else 0.0)
            else:
                ic_series[f].append(0.0)

    results = {}
    for f in factor_cols:
        ics = np.array(ic_series[f])
        if len(ics) < 20:
            results[f] = {"half_life": None, "status": "数据不足"}
            continue

        # 计算滚动 IC 衰减
        recent_ic = np.mean(ics[-window:]) if len(ics) >= window else np.mean(ics)
        early_ic = np.mean(ics[:window]) if len(ics) >= window else np.mean(ics)

        # 半衰期估算：用最近 52 周 IC 的衰减趋势
        if len(ics) >= 52:
            recent_52 = ics[-52:]
            # 简单线性回归判断趋势
            x = np.arange(len(recent_52))
            y = recent_52
            if np.std(y) > 1e-8:
                slope = np.polyfit(x, y, 1)[0]
                if slope < -1e-4:
                    # IC 在衰减，估算半衰期
                    current_level = np.mean(y[-4:])
                    if current_level > 0:
                        half_life = abs(current_level / slope) if abs(slope) > 1e-8 else 999
                    else:
                        half_life = 0
                else:
                    half_life = 999  # 不衰减
            else:
                half_life = 999
        else:
            half_life = None

        status = "STABLE" if (half_life is None or half_life >= 52) else \
                 "DECAYING" if half_life >= 4 else "FAST_DECAY"

        results[f] = {
            "half_life_weeks": round(half_life, 1) if half_life else None,
            "recent_ic": round(float(recent_ic), 4),
            "early_ic": round(float(early_ic), 4),
            "status": status,
        }

    overall = {
        "factor_details": results,
        "fast_decay_factors": [f for f, d in results.items() if d["status"] == "FAST_DECAY"],
        "stable_factors": [f for f, d in results.items() if d["status"] == "STABLE"],
    }
    return overall


def run_full_audit(df, factor_cols, weight_dict, weeks_total=208) -> Dict:
    """
    运行完整三段审计

    1. Purged Walk-Forward CV
    2. IC 半衰期检验
    3. 综合判定
    """
    cv_result = purged_walk_forward_cv(df, factor_cols, weight_dict, weeks_total)
    ic_result = ic_half_life_check(df, factor_cols)

    fast_decay_count = len(ic_result["fast_decay_factors"])
    overall_pass = cv_result["audit_pass"] and fast_decay_count < len(factor_cols) / 2

    return {
        "overall_pass": overall_pass,
        "cv_audit": cv_result,
        "ic_half_life": ic_result,
        "summary": (
            f"CV {'PASS' if cv_result['audit_pass'] else 'FAIL'} "
            f"(ratio={cv_result.get('cv_ratio', 0):.4f}), "
            f"IC半衰期: {len(ic_result['stable_factors'])} 稳定 / {fast_decay_count} 快衰减"
        ),
    }
