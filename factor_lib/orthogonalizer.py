# -*- coding: utf-8 -*-
"""
orthogonalizer.py — 对称正交化引擎
=================================================
对一组因子做对称正交化（Symmetric Orthogonalization），
消除因子间的线性相关性，同时最大程度保留各自的原始信息。

方法:
  给定已标准化的因子矩阵 F (N_stocks × K_factors)
  协方差矩阵 cov = F.T @ F / (N-1)
  正交化: F_orth = F @ cov^{-1/2}
  其中 cov^{-1/2} 通过矩阵平方根的逆得到（scipy.linalg.sqrtm + pinv）

特性:
  - 对称正交化后所有因子两两正交（相关系数=0）
  - 正交化后自动保持因子方向（与原始因子相关性为负则取反）
  - 支持按分组正交化（组内正交，组间不动）
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from scipy.linalg import sqrtm
from scipy.linalg import pinv


def symmetric_orthogonalize(F: np.ndarray) -> np.ndarray:
    """
    对称正交化核心函数。

    参数:
        F: (N_stocks, K_factors) 矩阵，假设已标准化（每列均值≈0，标准差≈1）

    返回:
        F_orth: (N_stocks, K_factors) 正交化后的因子矩阵
                列顺序与输入一致，每列与原始因子方向保持一致
    """
    N, K = F.shape

    if K == 0:
        return F
    if K == 1:
        # 单因子无需正交化，但仍标准化
        std = F[:, 0].std(ddof=1)
        if std > 1e-12:
            return (F - F[:, 0].mean()) / std
        return F

    # 1. 计算协方差矩阵
    cov = (F.T @ F) / (N - 1)

    # 2. 计算矩阵平方根
    sqrt_cov = sqrtm(cov)

    # 3. 取实部，再求伪逆（即 cov^{-1/2}）
    sqrt_cov_real = sqrt_cov.real
    inv_sqrt_cov = pinv(sqrt_cov_real)

    # 4. 正交化变换
    F_orth = F @ inv_sqrt_cov

    # 5. 保持方向：检查每列与原始因子的相关性，若为负则取反
    for k in range(K):
        orig = F[:, k]
        orth = F_orth[:, k]
        # 去掉 NaN
        mask = np.isfinite(orig) & np.isfinite(orth)
        if mask.sum() < 2:
            continue
        corr = np.corrcoef(orig[mask], orth[mask])[0, 1]
        if corr < 0:
            F_orth[:, k] = -F_orth[:, k]

    return F_orth


def group_orthogonalize(
    factor_df: pd.DataFrame,
    groups: Dict[str, List[str]],
    date_col: str = "trade_date",
    code_col: str = "ts_code",
) -> pd.DataFrame:
    """
    按因子分组做截面正交化。

    组内对称正交化，组间保持独立（不动）。
    逐日循环，对每个交易日的截面分别处理。

    参数:
        factor_df: 长格式 DataFrame，含 ts_code, trade_date, 各因子列
        groups: 分组字典，如 {"momentum": ["return_5d", "return_20d"], ...}
        date_col: 日期列名
        code_col: 股票代码列名

    返回:
        新 DataFrame，在原始列基础上新增 <factor>_orth 列
    """
    result = factor_df.copy()

    # 收集所有需要正交化的因子列
    all_factor_cols = []
    for g_factors in groups.values():
        all_factor_cols.extend(g_factors)

    # 为每个正交化因子创建结果列（初始 NaN）
    for f in all_factor_cols:
        result[f"{f}_orth"] = np.nan

    # 逐日处理
    trade_dates = sorted(factor_df[date_col].unique())

    for td in trade_dates:
        day_mask = factor_df[date_col] == td
        day_data = factor_df[day_mask]

        for group_name, factor_cols in groups.items():
            # 取该组因子在当日的矩阵
            group_data = day_data[factor_cols].copy()

            # 替换 inf 为 NaN
            group_data = group_data.replace([np.inf, -np.inf], np.nan)

            # 去掉有 NaN 的行（所有因子必须同时有值才能正交化）
            valid_mask = group_data.notna().all(axis=1)
            if valid_mask.sum() < len(factor_cols) + 1:
                # 样本太少，跳过
                continue

            # 标准化（z-score）
            group_arr = group_data[valid_mask].values.astype(float)
            means = np.nanmean(group_arr, axis=0)
            stds = np.nanstd(group_arr, axis=0, ddof=1)
            stds = np.where(stds > 1e-12, stds, 1.0)
            group_norm = (group_arr - means) / stds

            # 对称正交化
            try:
                orth_arr = symmetric_orthogonalize(group_norm)
            except Exception as e:
                print(f"⚠️ [Orthogonalizer] {td} 组 {group_name} 正交化失败: {e}")
                continue

            # 写回结果
            for j, f in enumerate(factor_cols):
                col_name = f"{f}_orth"
                # 找到当日 valid 的行索引
                valid_indices = day_data.index[valid_mask]
                result.loc[valid_indices, col_name] = orth_arr[:, j]

    return result


def orthogonalize_cross_section(
    factor_df: pd.DataFrame,
    factor_cols: List[str],
) -> pd.DataFrame:
    """
    单日截面对角化（便捷接口）。

    参数:
        factor_df: 单日截面 DataFrame，index=ts_code，列=因子名
        factor_cols: 需要正交化的因子列名

    返回:
        DataFrame，新增 <factor>_orth 列
    """
    result = factor_df.copy()

    # 提取矩阵（替换 inf 并去掉含 NaN 的行）
    valid_data = factor_df[factor_cols].replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid_data) < len(factor_cols) + 1:
        for f in factor_cols:
            result[f"{f}_orth"] = np.nan
        return result

    # 标准化
    arr = valid_data.values.astype(float)
    means = arr.mean(axis=0)
    stds = arr.std(axis=0, ddof=1)
    stds = np.where(stds > 1e-12, stds, 1.0)
    arr_norm = (arr - means) / stds

    # 正交化
    orth_arr = symmetric_orthogonalize(arr_norm)

    # 写回
    for j, f in enumerate(factor_cols):
        result[f"{f}_orth"] = np.nan
        result.loc[valid_data.index, f"{f}_orth"] = orth_arr[:, j]

    return result
