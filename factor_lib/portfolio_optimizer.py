# -*- coding: utf-8 -*-
"""
portfolio_optimizer.py — 组合优化器 (Phase 3-A)
=================================================
基于凸优化的投资组合权重求解，覆盖：

  1. MVO (Mean-Variance Optimization) — 均值-方差优化
     · 目标1: max μ'w           （最大化预期收益，等价于最大化 IC 加权）
     · 目标2: max μ'w - λ w'Σw  （Markowitz 风险调整收益）
     · 约束: 权重和=1、非负、单股上限、行业偏离约束

  2. Risk Parity — 风险平价
     · 让每只股票（或每个因子）的边际风险贡献相等
     · 迭代法 / scipy 优化双实现

  3. 便捷方法
     · build_constraints() — 从 stock_info 自动构建行业偏离约束
     · apply_turnover_smoothing() — 换手率约束下的新旧仓插值平滑

依赖: scipy.optimize.minimize(method='SLSQP')
"""

from __future__ import annotations

import warnings
from typing import Optional, Dict, List, Tuple, Any

import numpy as np
import pandas as pd

try:
    from scipy.optimize import minimize
    _HAS_SCIPY = True
except ImportError:  # pragma: no cover
    _HAS_SCIPY = False


# ═══════════════════════════════════════════
#  PortfolioOptimizer
# ═══════════════════════════════════════════

class PortfolioOptimizer:
    """均值-方差 / 风险平价 组合优化器。

    Parameters
    ----------
    asset_names : list of str
        资产名称列表（如 ts_code），用于对齐权重顺序。
    """

    def __init__(self, asset_names: List[str]):
        self.asset_names = list(asset_names)
        self.n = len(asset_names)
        if self.n == 0:
            raise ValueError("asset_names 不能为空")

    # ───────────────────────────────────────
    #  1. MVO 均值-方差优化
    # ───────────────────────────────────────

    def optimize_mvo(
        self,
        expected_returns: np.ndarray,
        cov_matrix: Optional[np.ndarray] = None,
        risk_aversion: float = 0.0,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        均值-方差组合优化。

        目标函数（最小化形式）:
          risk_aversion == 0  →  min -μ'w          （最大化预期收益）
          risk_aversion >  0  →  min -μ'w + λ w'Σw （风险调整）

        Parameters
        ----------
        expected_returns : np.ndarray, shape (n,)
            预期收益率向量（或因子得分向量，方向已对齐）。
        cov_matrix : np.ndarray, shape (n, n), optional
            收益率协方差矩阵；risk_aversion > 0 时必须提供。
        risk_aversion : float
            风险厌恶系数 λ；=0 时退化为"最大化预期收益"。
        constraints : dict, optional
            约束配置，支持的 key:
              - max_weight : float, 单股权重上限（默认 0.3）
              - min_weight : float, 单股权重下限（默认 0.0）
              - sector_weights : dict {sector_name: target_weight}, 行业基准权重
              - sector_deviation_limit : float, 行业偏离上限（默认 0.05）
              - asset_sector_map : dict {asset_name: sector_name}, 资产-行业映射

        Returns
        -------
        weights : np.ndarray, shape (n,)
            最优权重向量（sum=1）。
        stats : dict
            优化统计信息（预期收益、组合方差、收敛状态等）。
        """
        mu = np.asarray(expected_returns, dtype=float).flatten()
        if len(mu) != self.n:
            raise ValueError(f"expected_returns 长度 {len(mu)} 与资产数 {self.n} 不匹配")

        # 默认约束
        cons = constraints or {}
        max_w = float(cons.get("max_weight", 0.3))
        min_w = float(cons.get("min_weight", 0.0))

        # 边界：w_i ∈ [min_w, max_w]
        bounds = [(min_w, max_w)] * self.n

        # 等式约束：sum(w) = 1
        eq_constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        # 行业偏离约束
        sector_constraints = self._build_sector_constraints(cons)
        all_constraints = eq_constraints + sector_constraints

        # 初始值：等权
        x0 = np.ones(self.n) / self.n

        if risk_aversion > 0:
            if cov_matrix is None:
                raise ValueError("risk_aversion > 0 时必须提供 cov_matrix")
            sigma = np.asarray(cov_matrix, dtype=float)
            if sigma.shape != (self.n, self.n):
                raise ValueError(f"cov_matrix 形状 {sigma.shape} 与资产数 {self.n} 不匹配")
            # 确保对称正定
            sigma = (sigma + sigma.T) / 2.0

            def objective(w):
                port_ret = mu @ w
                port_var = w @ sigma @ w
                return -port_ret + risk_aversion * port_var

            def gradient(w):
                return -mu + 2.0 * risk_aversion * (sigma @ w)
        else:
            # 最大化预期收益 → 最小化 -mu'w
            def objective(w):
                return -(mu @ w)

            def gradient(w):
                return -mu

        # 求解
        if _HAS_SCIPY:
            result = minimize(
                objective,
                x0,
                jac=gradient,
                method="SLSQP",
                bounds=bounds,
                constraints=all_constraints,
                options={"maxiter": 500, "ftol": 1e-10, "disp": False},
            )
            weights = result.x
            success = result.success
            message = result.message
        else:
            # fallback: 简单的"预期收益排序 + 权重上限"启发式
            weights = self._greedy_max_return(mu, max_w, min_w)
            success = True
            message = "fallback: greedy (scipy 不可用)"

        # 数值校正：裁剪到边界 + 归一化
        weights = np.clip(weights, min_w, max_w)
        total = weights.sum()
        if total > 1e-12:
            weights = weights / total
        else:
            weights = np.ones(self.n) / self.n

        # 统计
        port_ret = float(mu @ weights)
        if risk_aversion > 0 and cov_matrix is not None:
            port_var = float(weights @ sigma @ weights)
            port_vol = float(np.sqrt(max(port_var, 0.0)))
        else:
            port_var = float("nan")
            port_vol = float("nan")

        stats = {
            "success": success,
            "message": str(message),
            "expected_return": port_ret,
            "portfolio_variance": port_var,
            "portfolio_volatility": port_vol,
            "max_weight": float(weights.max()),
            "min_weight": float(weights.min()),
            "weight_sum": float(weights.sum()),
            "n_assets": int((weights > 1e-6).sum()),
        }

        return weights, stats

    # ───────────────────────────────────────
    #  2. 风险平价
    # ───────────────────────────────────────

    def optimize_risk_parity(
        self,
        cov_matrix: np.ndarray,
        constraints: Optional[Dict[str, Any]] = None,
        max_iter: int = 100,
        tol: float = 1e-8,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        风险平价优化：让每个资产的边际风险贡献相等。

        风险贡献 RC_i = w_i * (Σw)_i / sqrt(w'Σw)
        目标：所有 RC_i 相等。

        使用迭代法（Spinu 2013 算法的简化版）+ SLSQP 双实现。

        Parameters
        ----------
        cov_matrix : np.ndarray, shape (n, n)
            收益率协方差矩阵（必须正定）。
        constraints : dict, optional
            约束配置（同 optimize_mvo，仅 max_weight / min_weight 生效）。
        max_iter : int
            最大迭代次数。
        tol : float
            收敛容差。

        Returns
        -------
        weights : np.ndarray
            风险平价权重。
        stats : dict
            统计信息。
        """
        sigma = np.asarray(cov_matrix, dtype=float)
        sigma = (sigma + sigma.T) / 2.0
        if sigma.shape != (self.n, self.n):
            raise ValueError(f"cov_matrix 形状 {sigma.shape} 与资产数 {self.n} 不匹配")

        cons = constraints or {}
        max_w = float(cons.get("max_weight", 1.0))
        min_w = float(cons.get("min_weight", 0.0))

        if _HAS_SCIPY:
            # 用 SLSQP 求解：min Σ(RC_i - target_RC)^2，s.t. sum(w)=1, w>=0
            # 目标风险贡献 = 组合总风险 / n
            def objective(w):
                port_vol = np.sqrt(max(w @ sigma @ w, 1e-12))
                mrc = sigma @ w  # 边际风险贡献
                rc = w * mrc / port_vol  # 总风险贡献
                target_rc = port_vol / self.n
                return np.sum((rc - target_rc) ** 2)

            x0 = np.ones(self.n) / self.n
            bounds = [(min_w, max_w)] * self.n
            eq_constraint = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}

            result = minimize(
                objective,
                x0,
                method="SLSQP",
                bounds=bounds,
                constraints=[eq_constraint],
                options={"maxiter": 500, "ftol": 1e-12, "disp": False},
            )
            weights = result.x
            success = result.success
            message = result.message
        else:
            # 迭代法：Newton 步更新
            weights = np.ones(self.n) / self.n
            success = True
            message = "iterative method"
            for _ in range(max_iter):
                sigma_w = sigma @ weights
                port_var = weights @ sigma_w
                if port_var < 1e-12:
                    break
                rc = weights * sigma_w  # 风险贡献（未归一化）
                target = rc.mean()
                # 调整：w_new = w * sqrt(target / rc)
                ratio = np.sqrt(np.maximum(target / np.maximum(rc, 1e-12), 0.0))
                weights = weights * ratio
                weights = np.clip(weights, min_w, max_w)
                total = weights.sum()
                if total > 1e-12:
                    weights = weights / total
                # 收敛检查
                if np.max(np.abs(rc / port_var - 1.0 / self.n)) < tol:
                    break

        # 数值校正
        weights = np.clip(weights, min_w, max_w)
        total = weights.sum()
        if total > 1e-12:
            weights = weights / total
        else:
            weights = np.ones(self.n) / self.n

        # 风险贡献统计
        port_var = float(weights @ sigma @ weights)
        port_vol = float(np.sqrt(max(port_var, 0.0)))
        if port_vol > 1e-12:
            risk_contrib = weights * (sigma @ weights) / port_vol
        else:
            risk_contrib = np.zeros(self.n)
        rc_std = float(risk_contrib.std())

        stats = {
            "success": success,
            "message": str(message),
            "portfolio_volatility": port_vol,
            "portfolio_variance": port_var,
            "risk_contributions": risk_contrib,
            "risk_contrib_std": rc_std,
            "max_weight": float(weights.max()),
            "min_weight": float(weights.min()),
            "weight_sum": float(weights.sum()),
        }

        return weights, stats

    # ───────────────────────────────────────
    #  3. 便捷方法
    # ───────────────────────────────────────

    @staticmethod
    def build_constraints(
        stock_info: pd.DataFrame,
        max_weight: float = 0.3,
        sector_limit: float = 0.05,
        benchmark_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        从股票信息 DataFrame 构建约束配置字典。

        Parameters
        ----------
        stock_info : DataFrame
            至少包含 ts_code, industry 两列。
        max_weight : float
            单股权重上限。
        sector_limit : float
            行业偏离基准的上限。
        benchmark_weights : dict, optional
            行业基准权重 {industry: weight}；不传则按等权估算。

        Returns
        -------
        constraints : dict
            可直接传入 optimize_mvo() 的约束配置。
        """
        required_cols = {"ts_code", "industry"}
        if not required_cols.issubset(set(stock_info.columns)):
            raise ValueError(f"stock_info 必须包含列: {required_cols}")

        asset_sector_map = dict(zip(
            stock_info["ts_code"].astype(str),
            stock_info["industry"].astype(str),
        ))

        # 行业基准权重
        sectors = stock_info["industry"].astype(str).unique().tolist()
        if benchmark_weights is not None:
            sector_weights = {s: float(benchmark_weights.get(s, 0.0)) for s in sectors}
            total = sum(sector_weights.values())
            if total > 1e-9:
                sector_weights = {s: v / total for s, v in sector_weights.items()}
        else:
            # 等权基准：每个行业 1/n_sectors
            n_sec = len(sectors)
            sector_weights = {s: 1.0 / n_sec for s in sectors}

        return {
            "max_weight": max_weight,
            "min_weight": 0.0,
            "sector_weights": sector_weights,
            "sector_deviation_limit": sector_limit,
            "asset_sector_map": asset_sector_map,
        }

    @staticmethod
    def apply_turnover_smoothing(
        new_weights: np.ndarray,
        old_weights: np.ndarray,
        max_turnover: float = 0.5,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        换手率约束下的新旧仓线性插值平滑。

        换手率定义: turnover = 0.5 * Σ|w_new - w_old|
        通过 alpha 控制：w_smooth = (1-α) * w_old + α * w_new
        反解 alpha 使得 turnover ≤ max_turnover。

        Parameters
        ----------
        new_weights : np.ndarray
            新目标权重。
        old_weights : np.ndarray
            上一期权重（形状需一致）。
        max_turnover : float
            允许的最大单边换手率（0~1）。

        Returns
        -------
        smoothed_weights : np.ndarray
            平滑后权重。
        stats : dict
            含 alpha、实际换手率等信息。
        """
        new_w = np.asarray(new_weights, dtype=float).flatten()
        old_w = np.asarray(old_weights, dtype=float).flatten()

        if len(new_w) != len(old_w):
            raise ValueError(
                f"new_weights ({len(new_w)}) 与 old_weights ({len(old_w)}) 长度不一致"
            )

        # 完全换手时的总变化量
        total_required_change = np.sum(np.abs(new_w - old_w))
        if total_required_change <= 1e-12:
            return new_w.copy(), {
                "alpha": 1.0,
                "turnover": 0.0,
                "total_required_change": 0.0,
                "smoothed": False,
            }

        # max_turnover 对应 0.5 * Σ|Δ| ≤ T → Σ|Δ| ≤ 2T
        max_abs_change = 2.0 * max_turnover
        alpha = min(1.0, max_abs_change / total_required_change)

        smoothed = old_w + alpha * (new_w - old_w)

        # 归一化到 1.0（数值误差修正）
        total = smoothed.sum()
        if total > 1e-12:
            smoothed = smoothed / total

        actual_turnover = float(0.5 * np.sum(np.abs(smoothed - old_w)))

        stats = {
            "alpha": float(alpha),
            "turnover": actual_turnover,
            "total_required_change": float(total_required_change),
            "max_turnover": float(max_turnover),
            "smoothed": alpha < 1.0,
        }

        return smoothed, stats

    # ───────────────────────────────────────
    #  内部工具
    # ───────────────────────────────────────

    def _build_sector_constraints(self, cons: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从约束配置构建行业偏离不等式约束列表。"""
        sector_map = cons.get("asset_sector_map")
        sector_targets = cons.get("sector_weights")
        sector_limit = cons.get("sector_deviation_limit")

        if not sector_map or not sector_targets or sector_limit is None:
            return []

        constraints = []
        sectors = sorted(set(sector_targets.keys()))

        for sector in sectors:
            target = float(sector_targets[sector])
            # 资产到行业的映射向量
            sector_mask = np.array([
                1.0 if sector_map.get(name) == sector else 0.0
                for name in self.asset_names
            ])

            if sector_mask.sum() == 0:
                continue

            upper = target + sector_limit
            lower = target - sector_limit

            # 上界约束: Σ(w_i * sector_mask_i) - upper <= 0
            constraints.append({
                "type": "ineq",
                "fun": lambda w, sm=sector_mask, u=upper: u - np.sum(w * sm),
            })
            # 下界约束: Σ(w_i * sector_mask_i) - lower >= 0
            constraints.append({
                "type": "ineq",
                "fun": lambda w, sm=sector_mask, l=lower: np.sum(w * sm) - l,
            })

        return constraints

    @staticmethod
    def _greedy_max_return(mu: np.ndarray, max_w: float, min_w: float) -> np.ndarray:
        """
        启发式最大化预期收益（scipy 不可用时的 fallback）。
        按收益从高到低分配权重，达到上限后分配下一个。
        """
        n = len(mu)
        order = np.argsort(-mu)  # 降序
        weights = np.full(n, min_w)
        remaining = 1.0 - min_w * n

        for idx in order:
            if remaining <= 1e-12:
                break
            add = min(max_w - min_w, remaining)
            weights[idx] += add
            remaining -= add

        return weights


# ═══════════════════════════════════════════
#  验证测试
# ═══════════════════════════════════════════

def run_optimizer_tests(seed: int = 42) -> Dict[str, Any]:
    """
    用随机数据验证优化器：
      1. MVO 收敛性 + 约束满足（权重和、单股上限、行业偏离）
      2. 风险平价风险贡献均匀性
      3. 换手率平滑有效性
    """
    np.random.seed(seed)

    results: Dict[str, Any] = {}

    # ── 生成 20 只股票的随机数据 ──
    n_stocks = 20
    asset_names = [f"STOCK_{i:02d}" for i in range(n_stocks)]
    expected_returns = np.random.normal(0.001, 0.005, n_stocks)  # 日预期收益

    # 构造协方差矩阵（随机相关 + 波动率）
    vols = np.random.uniform(0.01, 0.03, n_stocks)
    corr = np.random.uniform(0.1, 0.5, (n_stocks, n_stocks))
    corr = (corr + corr.T) / 2.0
    np.fill_diagonal(corr, 1.0)
    cov_matrix = np.outer(vols, vols) * corr
    # 确保正定
    cov_matrix += np.eye(n_stocks) * 1e-4

    # 行业分类（4 个行业）
    industries = ["金融", "科技", "消费", "医药"]
    stock_info = pd.DataFrame({
        "ts_code": asset_names,
        "industry": np.random.choice(industries, n_stocks),
    })

    opt = PortfolioOptimizer(asset_names)

    # ── 测试1: MVO 最大化收益（无风险调整）──
    constraints = PortfolioOptimizer.build_constraints(
        stock_info, max_weight=0.3, sector_limit=0.05
    )
    w, stats = opt.optimize_mvo(expected_returns, constraints=constraints)
    results["mvo_max_return"] = {
        "weights": dict(zip(asset_names, w.round(6))),
        "stats": stats,
        "check_weight_sum_ok": abs(stats["weight_sum"] - 1.0) < 1e-6,
        "check_max_weight_ok": stats["max_weight"] <= 0.3 + 1e-6,
        "check_min_weight_ok": stats["min_weight"] >= -1e-6,
    }

    # 验证行业偏离
    sector_weight_check = _check_sector_deviation(w, stock_info, constraints)
    results["mvo_max_return"]["sector_check"] = sector_weight_check

    # ── 测试2: MVO 均值-方差（风险调整）──
    w2, stats2 = opt.optimize_mvo(
        expected_returns,
        cov_matrix=cov_matrix,
        risk_aversion=1.0,
        constraints=constraints,
    )
    results["mvo_mean_variance"] = {
        "weights": dict(zip(asset_names, w2.round(6))),
        "stats": stats2,
        "check_weight_sum_ok": abs(stats2["weight_sum"] - 1.0) < 1e-6,
        "check_max_weight_ok": stats2["max_weight"] <= 0.3 + 1e-6,
        "check_min_weight_ok": stats2["min_weight"] >= -1e-6,
    }
    sector_check2 = _check_sector_deviation(w2, stock_info, constraints)
    results["mvo_mean_variance"]["sector_check"] = sector_check2

    # ── 测试3: 风险平价 ──
    w3, stats3 = opt.optimize_risk_parity(cov_matrix, constraints={"max_weight": 0.5})
    results["risk_parity"] = {
        "weights": dict(zip(asset_names, w3.round(6))),
        "stats": {k: (v if not isinstance(v, np.ndarray) else v.round(6).tolist())
                  for k, v in stats3.items()},
        "check_weight_sum_ok": abs(stats3["weight_sum"] - 1.0) < 1e-6,
        "check_rc_uniform": stats3["risk_contrib_std"] < 1e-3,
    }

    # ── 测试4: 换手率平滑 ──
    old_w = np.zeros(n_stocks)
    old_w[:5] = 0.2  # 前 5 只各 20%
    new_w = np.zeros(n_stocks)
    new_w[10:15] = 0.2  # 后 5 只各 20%（完全换仓）

    smoothed, ts = PortfolioOptimizer.apply_turnover_smoothing(
        new_w, old_w, max_turnover=0.3
    )
    results["turnover_smoothing"] = {
        "old_weights_top5": old_w[:5].tolist(),
        "new_weights_mid5": new_w[10:15].tolist(),
        "smoothed_weights": smoothed.round(6).tolist(),
        "stats": ts,
        "check_turnover_ok": ts["turnover"] <= 0.3 + 1e-6,
        "check_alpha_between_01": 0.0 < ts["alpha"] <= 1.0,
    }

    # ── 汇总 ──
    all_pass = True
    for k, v in results.items():
        for key, val in v.items():
            if key.startswith("check_") and val is False:
                all_pass = False
                break
    results["all_tests_pass"] = all_pass

    return results


def _check_sector_deviation(
    weights: np.ndarray,
    stock_info: pd.DataFrame,
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    """验证行业偏离约束是否满足。"""
    sector_map = constraints.get("asset_sector_map", {})
    sector_targets = constraints.get("sector_weights", {})
    sector_limit = constraints.get("sector_deviation_limit", 0.0)

    stock_info = stock_info.copy()
    stock_info["weight"] = weights
    sector_weights = stock_info.groupby("industry")["weight"].sum().to_dict()

    deviations = {}
    all_ok = True
    for sector, target in sector_targets.items():
        actual = sector_weights.get(sector, 0.0)
        dev = actual - target
        deviations[sector] = {
            "target": round(target, 4),
            "actual": round(actual, 4),
            "deviation": round(dev, 4),
            "limit": sector_limit,
            "ok": abs(dev) <= sector_limit + 1e-6,
        }
        if abs(dev) > sector_limit + 1e-6:
            all_ok = False

    return {"all_sectors_ok": all_ok, "deviations": deviations}
