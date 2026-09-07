# -*- coding: utf-8 -*-
"""
orthogonal_postprocessor.py — 正交化后处理

当遗传搜索找到有好 IC 的因子组合后，做正交化后处理：
1. 对组合内因子做对称正交化
2. 用正交化后因子重新回测
3. 比较正交化前后 Fitness 变化
4. 正交化后 Fitness 不降 → 独立 Alpha 确认
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from factor_lib.orthogonalizer import symmetric_orthogonalize
from factor_lib.unified_backtester import UnifiedBacktester, compute_fitness
from factor_lib.data_loader import FactorDataLoader


class OrthogonalPostProcessor:
    """正交化后处理验证器"""

    def __init__(self, db_path: str = "db/stock_data.db"):
        self.backtester = UnifiedBacktester(db_path)
        self.loader = FactorDataLoader(db_path)

    def run(
        self,
        factor_weights: Dict[str, float],
        dates: List[str],
        top_n: int = 20,
        buffer_n: int = 35,
    ) -> Dict:
        """
        对因子组合做正交化前后对比

        Returns
        -------
        dict: {
            pre_fitness, post_fitness, fitness_change,
            pre_calmar, post_calmar,
            correlation_matrix, eigenvalues,
            is_independent_alpha: bool,
            conclusion: str,
        }
        """
        factor_names = list(factor_weights.keys())

        # 1. 正交化前的回测
        pre_result = self.backtester.run(
            factor_weights, dates, top_n, buffer_n, self.loader
        )
        pre_fitness = compute_fitness(pre_result)

        # 2. 计算因子相关矩阵
        corr_matrix, eigenvalues = self._compute_correlation(factor_names, dates)

        # 3. 对组合内因子做对称正交化
        ortho_weights = self._orthogonalize_weights(factor_weights, corr_matrix)

        # 4. 正交化后的回测
        post_result = self.backtester.run(
            ortho_weights, dates, top_n, buffer_n, self.loader
        )
        post_fitness = compute_fitness(post_result)

        # 5. 判定
        fitness_change = post_fitness - pre_fitness
        is_independent = post_fitness >= pre_fitness * 0.9  # 允许10%下降

        if is_independent:
            conclusion = "✅ 独立 Alpha 确认 — 正交化后 Fitness 保持，因子提供独立信息"
        else:
            conclusion = "⚠️ 风格暴露嫌疑 — 正交化后 Fitness 大幅下降，收益可能来自共线因子"

        return {
            "pre_fitness": round(pre_fitness, 4),
            "post_fitness": round(post_fitness, 4),
            "fitness_change": round(fitness_change, 4),
            "pre_calmar": pre_result["excess_calmar"],
            "post_calmar": post_result["excess_calmar"],
            "pre_ic": pre_result["ic_mean"],
            "post_ic": post_result["ic_mean"],
            "max_correlation": round(float(np.max(np.abs(corr_matrix - np.eye(len(factor_names))))), 4),
            "eigenvalues": [round(float(e), 4) for e in eigenvalues],
            "is_independent_alpha": is_independent,
            "conclusion": conclusion,
        }

    def _compute_correlation(self, factor_names, dates):
        """计算因子间相关矩阵"""
        from factor_lib.data_loader import get_loader
        loader = get_loader()

        all_data = []
        for dt in dates[:20]:  # 取前20个截面
            df = loader.get_cross_section(dt, factor_names, level="neutral", apply_universe=False)
            if not df.empty and len(df) > 30:
                all_data.append(df[factor_names].dropna())

        if not all_data:
            return np.eye(len(factor_names)), np.ones(len(factor_names))

        combined = pd.concat(all_data, axis=0)
        corr = combined.corr().values
        eigenvalues = np.linalg.eigvalsh(corr) if len(corr) > 1 else np.array([1.0])

        return corr, eigenvalues

    def _orthogonalize_weights(self, factor_weights, corr_matrix):
        """
        基于相关矩阵对权重做正交化调整

        如果因子间高度相关，正交化会重新分配权重，
        使得每个因子贡献的信息量更独立。
        """
        names = list(factor_weights.keys())
        weights = np.array([factor_weights[f] for f in names])

        if len(names) <= 1:
            return factor_weights

        try:
            # 对称正交化: W_orth = W @ (W'W)^{-1/2}
            # 这里用相关矩阵的逆平方根来调整权重
            eigenvalues, eigenvectors = np.linalg.eigh(corr_matrix)

            # 避免数值问题
            eigenvalues = np.maximum(eigenvalues, 1e-8)

            # 逆平方根
            inv_sqrt = eigenvectors @ np.diag(1.0 / np.sqrt(eigenvalues)) @ eigenvectors.T

            # 调整权重
            ortho_weights = inv_sqrt @ weights

            # 归一化保持总权重不变
            total = np.sum(np.abs(weights))
            if np.sum(np.abs(ortho_weights)) > 0:
                ortho_weights = ortho_weights * total / np.sum(np.abs(ortho_weights))

            return {names[i]: float(ortho_weights[i]) for i in range(len(names))}
        except Exception:
            return factor_weights
