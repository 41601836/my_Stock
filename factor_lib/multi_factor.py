#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
factor_lib.multi_factor
========================
多因子合成引擎

支持的合成方法:
1. equal_weight       - 等权合成 (基准)
2. icir_weighted      - ICIR 加权 (因子 ICIR 绝对值为权重)
3. ic_weighted        - IC 加权 (因子 IC 绝对值为权重)
4. max_ic             - 最大化 IC (基于 IC 协方差的均值-方差优化)
5. risk_parity        - 风险平价 (因子波动率倒数加权)
6. rank_average       - 排名平均 (先排名再平均，减少量纲影响)

所有方法都先对因子做方向对齐（乘以 direction），确保方向一致。
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple


class MultiFactorCombiner:
    """多因子合成引擎

    Parameters
    ----------
    factor_metas : dict
        因子元数据字典 {factor_name: FactorMeta}
    method : str
        合成方法: equal_weight / icir_weighted / ic_weighted /
                   max_ic / risk_parity / rank_average
    weights : dict, optional
        自定义权重 {factor_name: weight}，仅用于 custom 方法
    """

    VALID_METHODS = [
        "equal_weight",
        "icir_weighted",
        "ic_weighted",
        "max_ic",
        "risk_parity",
        "rank_average",
        "custom",
    ]

    def __init__(self, factor_metas: dict, method: str = "equal_weight",
                 weights: Optional[Dict[str, float]] = None):
        if method not in self.VALID_METHODS:
            raise ValueError(f"不支持的合成方法: {method}，可选: {self.VALID_METHODS}")

        self.factor_metas = factor_metas
        self.method = method
        self.custom_weights = weights or {}

        # 运行时计算的权重
        self.computed_weights_ = None  # {factor_name: weight}
        self.ic_history_ = None        # 用于 max_ic 的 IC 协方差估计

    def _align_direction(self, df: pd.DataFrame, factors: List[str]) -> pd.DataFrame:
        """方向对齐：所有因子乘以 direction，使高值=好"""
        df = df.copy()
        for f in factors:
            meta = self.factor_metas.get(f)
            direction = meta.direction if meta else 1
            df[f] = df[f] * direction
        return df

    def _rank_normalize(self, df: pd.DataFrame, factors: List[str]) -> pd.DataFrame:
        """截面排名归一化到 [0, 1]"""
        df = df.copy()
        for f in factors:
            df[f] = df.groupby("trade_date")[f].rank(pct=True)
        return df

    def _compute_weights(self, df: pd.DataFrame, factors: List[str],
                         return_col: str = "fwd_ret_5d",
                         ic_history: Optional[pd.DataFrame] = None) -> Dict[str, float]:
        """根据方法计算因子权重"""
        n = len(factors)

        if self.method == "equal_weight":
            return {f: 1.0 / n for f in factors}

        if self.method == "custom":
            w = self.custom_weights
            total = sum(w.get(f, 0) for f in factors)
            if total == 0:
                return {f: 1.0 / n for f in factors}
            return {f: w.get(f, 0) / total for f in factors}

        # 需要 IC 数据的方法
        ic_values = {}
        ic_std_values = {}
        for f in factors:
            # 截面 IC 时序
            daily_ic = df.groupby("trade_date").apply(
                lambda g: g[f].corr(g[return_col], method="spearman")
            )
            ic_values[f] = daily_ic.mean()
            ic_std_values[f] = daily_ic.std() if daily_ic.std() > 0 else 1e-6

        if self.method == "icir_weighted":
            weights = {f: abs(ic_values[f] / ic_std_values[f]) for f in factors}
            total = sum(weights.values())
            if total == 0:
                return {f: 1.0 / n for f in factors}
            return {f: w / total for f, w in weights.items()}

        if self.method == "ic_weighted":
            weights = {f: abs(ic_values[f]) for f in factors}
            total = sum(weights.values())
            if total == 0:
                return {f: 1.0 / n for f in factors}
            return {f: w / total for f, w in weights.items()}

        if self.method == "risk_parity":
            # 用因子自身的截面波动率作为风险度量
            # 更常用的是因子 IC 的波动率，这里用 IC 标准差
            weights = {f: 1.0 / ic_std_values[f] for f in factors}
            total = sum(weights.values())
            return {f: w / total for f, w in weights.items()}

        if self.method == "max_ic":
            # 最大化 IC / sqrt(IC 方差) ≈ 最大化 IR
            # 简化版：用 IC 均值向量和 IC 协方差矩阵做均值-方差
            ic_vec = np.array([ic_values[f] for f in factors])

            # 估计 IC 协方差矩阵（用因子收益的相关系数近似）
            ic_cov = np.zeros((n, n))
            for i, fi in enumerate(factors):
                for j, fj in enumerate(factors):
                    ic_i = df.groupby("trade_date").apply(
                        lambda g: g[fi].corr(g[return_col], method="spearman")
                    )
                    ic_j = df.groupby("trade_date").apply(
                        lambda g: g[fj].corr(g[return_col], method="spearman")
                    )
                    ic_cov[i, j] = np.cov(ic_i.values, ic_j.values)[0, 1] if len(ic_i) > 2 else 0

            # 确保正定
            ic_cov = ic_cov + np.eye(n) * 1e-6

            # Markowitz 解析解: w = Sigma^{-1} * mu / (1' Sigma^{-1} mu)
            try:
                inv_cov = np.linalg.inv(ic_cov)
                raw_w = inv_cov @ ic_vec
                # 取绝对值（因为方向已对齐）
                raw_w = np.abs(raw_w)
                total = raw_w.sum()
                if total == 0:
                    return {f: 1.0 / n for f in factors}
                return {f: raw_w[i] / total for i, f in enumerate(factors)}
            except np.linalg.LinAlgError:
                return {f: 1.0 / n for f, w in weights.items()}

        if self.method == "rank_average":
            # 排名平均等价于等权（因为都做了排名归一化）
            # 权重本身还是等权，区别在合成前的变换
            return {f: 1.0 / n for f in factors}

        return {f: 1.0 / n for f in factors}

    def combine(self, df: pd.DataFrame, factors: List[str],
                return_col: str = "fwd_ret_5d",
                output_col: str = "composite_score") -> pd.DataFrame:
        """合成多因子得分

        Parameters
        ----------
        df : DataFrame
            包含 trade_date + 各因子列 + 收益列的面板数据
        factors : list of str
            要合成的因子名称列表
        return_col : str
            未来收益率列名（用于计算 ICIR 等权重）
        output_col : str
            输出的合成得分列名

        Returns
        -------
        DataFrame : 新增 output_col 列的原数据
        """
        if len(factors) < 2:
            raise ValueError("至少需要 2 个因子才能合成")

        # 方向对齐
        df = self._align_direction(df, factors)

        # rank_average 方法：先做排名归一化
        if self.method == "rank_average":
            df = self._rank_normalize(df, factors)

        # 计算权重
        weights = self._compute_weights(df, factors, return_col)
        self.computed_weights_ = weights

        # 加权求和
        df[output_col] = 0.0
        for f in factors:
            w = weights.get(f, 0)
            df[output_col] += df[f].fillna(0) * w

        # 归一化到 [0, 1]（截面排名百分比）
        df[output_col] = df.groupby("trade_date")[output_col].rank(pct=True)

        return df

    def get_weights(self) -> Dict[str, float]:
        """获取计算出的权重"""
        if self.computed_weights_ is None:
            raise ValueError("请先调用 combine() 计算权重")
        return self.computed_weights_


def run_multi_factor_compare(df: pd.DataFrame, factors: List[str],
                             factor_metas: dict,
                             return_col: str = "fwd_ret_5d",
                             methods: Optional[List[str]] = None) -> Dict:
    """运行多种合成方法对比

    Parameters
    ----------
    df : DataFrame
        面板数据
    factors : list of str
        因子列表
    factor_metas : dict
        因子元数据
    return_col : str
        收益列
    methods : list of str, optional
        要对比的方法，默认全部

    Returns
    -------
    dict : {method_name: {"weights": dict, "composite_series": Series, "ic": float, "icir": float}}
    """
    if methods is None:
        methods = ["equal_weight", "icir_weighted", "ic_weighted",
                   "max_ic", "risk_parity", "rank_average"]

    results = {}
    for method in methods:
        try:
            combiner = MultiFactorCombiner(factor_metas, method=method)
            df_out = combiner.combine(df, factors, return_col=return_col,
                                      output_col=f"score_{method}")

            # 计算合成因子的 IC
            daily_ic = df_out.groupby("trade_date").apply(
                lambda g: g[f"score_{method}"].corr(g[return_col], method="spearman")
            )
            ic_mean = daily_ic.mean()
            ic_std = daily_ic.std() if daily_ic.std() > 0 else 1e-6
            icir = ic_mean / ic_std

            results[method] = {
                "weights": combiner.get_weights(),
                "ic_mean": ic_mean,
                "icir": icir,
                "score_col": f"score_{method}",
            }
        except Exception as e:
            results[method] = {"error": str(e)}

    return results
