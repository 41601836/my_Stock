# -*- coding: utf-8 -*-
"""
anti_overfit.py — 防过拟合校验
=================================================
5 项独立校验，互不依赖，可单独或组合使用:
  1. 样本内外对比: 60% 训练 / 40% 测试, ICIR 衰减 < 50%
  2. Walk-Forward: 252训练 / 63测试 滚动, IC 正比例 ≥ 60%
  3. 置换检验: 打乱因子截面排名 N 次, p < 0.05
  4. 子周期稳定性: 分年度 IC 方向一致 ≥ 70%
  5. IC 自相关: lag-1 自相关, |AC(1)| > 0.1 说明有持续性
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, List

from factor_lib.config import FactorTestConfig
from factor_lib.ic_engine import ICEngine


class AntiOverfitChecker:

    def __init__(self, ic_engine: ICEngine = None, min_cross_section_size: int = None):
        self.ic_engine = ic_engine or ICEngine()
        self.min_cs = min_cross_section_size or FactorTestConfig.min_cross_section_size()

    # ═══════════════════════════════════════════
    #  1. 样本内外对比
    # ═══════════════════════════════════════════

    def check_in_sample_oos(
        self,
        df: pd.DataFrame,
        factor_name: str,
        return_col: str = "fwd_ret_5d",
        train_ratio: float = None,
    ) -> dict:
        """样本内外 IC 对比: 前段训练, 后段测试。"""
        train_ratio = train_ratio or FactorTestConfig.train_ratio()

        dates = sorted(df["trade_date"].unique())
        split_idx = int(len(dates) * train_ratio)
        train_dates = dates[:split_idx]
        test_dates = dates[split_idx:]

        df_train = df[df["trade_date"].isin(train_dates)]
        df_test = df[df["trade_date"].isin(test_dates)]

        s_train = self.ic_engine.compute_ic_summary(
            self.ic_engine.compute_ic_series(df_train, factor_name, "rank", return_col)
        )
        s_test = self.ic_engine.compute_ic_summary(
            self.ic_engine.compute_ic_series(df_test, factor_name, "rank", return_col)
        )

        train_icir = s_train["icir"]
        test_icir = s_test["icir"]
        icir_decay = 1.0 - (test_icir / train_icir) if abs(train_icir) > 1e-12 else 1.0
        direction_consistent = (
            (s_train["ic_mean"] > 0) == (s_test["ic_mean"] > 0)
        ) if abs(s_train["ic_mean"]) > 1e-12 and abs(s_test["ic_mean"]) > 1e-12 else False

        return {
            "train_n_days": s_train["n_days"],
            "train_ic_mean": s_train["ic_mean"],
            "train_icir": train_icir,
            "test_n_days": s_test["n_days"],
            "test_ic_mean": s_test["ic_mean"],
            "test_icir": test_icir,
            "icir_decay": icir_decay,
            "icir_decay_acceptable": icir_decay < 0.50,
            "direction_consistent": direction_consistent,
        }

    # ═══════════════════════════════════════════
    #  2. Walk-Forward 滚动检验
    # ═══════════════════════════════════════════

    def walk_forward(
        self,
        df: pd.DataFrame,
        factor_name: str,
        return_col: str = "fwd_ret_5d",
        train_days: int = None,
        test_days: int = None,
    ) -> dict:
        """Walk-Forward: 固定训练窗口滚动, 测试窗口不重叠。"""
        train_days = train_days or FactorTestConfig.wf_train()
        test_days = test_days or FactorTestConfig.wf_test()

        dates = sorted(df["trade_date"].unique())
        results: List[dict] = []
        start = 0

        while start + train_days + test_days <= len(dates):
            tr_dates = dates[start:start + train_days]
            te_dates = dates[start + train_days:start + train_days + test_days]

            df_tr = df[df["trade_date"].isin(tr_dates)]
            df_te = df[df["trade_date"].isin(te_dates)]

            s_tr = self.ic_engine.compute_ic_summary(
                self.ic_engine.compute_ic_series(df_tr, factor_name, "rank", return_col)
            )
            s_te = self.ic_engine.compute_ic_summary(
                self.ic_engine.compute_ic_series(df_te, factor_name, "rank", return_col)
            )

            results.append({
                "window": len(results) + 1,
                "train_start": tr_dates[0],
                "train_end": tr_dates[-1],
                "test_start": te_dates[0],
                "test_end": te_dates[-1],
                "train_ic": s_tr["ic_mean"],
                "train_icir": s_tr["icir"],
                "test_ic": s_te["ic_mean"],
                "test_icir": s_te["icir"],
                "test_ic_positive": s_te["ic_mean"] > 0,
                "direction_consistent": (
                    (s_tr["ic_mean"] > 0) == (s_te["ic_mean"] > 0)
                ) if abs(s_tr["ic_mean"]) > 1e-12 and abs(s_te["ic_mean"]) > 1e-12 else False,
            })

            start += test_days

        if not results:
            return {
                "results": pd.DataFrame(),
                "n_windows": 0,
                "ic_positive_ratio": 0.0,
                "direction_consistency_ratio": 0.0,
                "pass": False,
            }

        df_res = pd.DataFrame(results)
        pos_ratio = df_res["test_ic_positive"].mean()
        dir_ratio = df_res["direction_consistent"].mean()
        threshold = FactorTestConfig.ic_positive_ratio()

        return {
            "results": df_res,
            "n_windows": len(results),
            "ic_positive_ratio": pos_ratio,
            "direction_consistency_ratio": dir_ratio,
            "pass": pos_ratio >= threshold,
        }

    # ═══════════════════════════════════════════
    #  3. 置换检验
    # ═══════════════════════════════════════════

    def permutation_test(
        self,
        df: pd.DataFrame,
        factor_name: str,
        return_col: str = "fwd_ret_5d",
        n_perm: int = None,
        random_seed: int = 42,
    ) -> dict:
        """
        置换检验: 在每个截面内打乱因子值排名, 重复 N 次。
        p-value = P(|perm_IC_mean| >= |actual_IC_mean|)

        优化: 预计算收益侧排名 (不变), 仅重排因子侧。
        """
        n_perm = n_perm or FactorTestConfig.n_permutations()

        # 过滤有效数据
        df_valid = df.dropna(subset=[factor_name, return_col]).copy()
        date_counts = df_valid.groupby("trade_date").size()
        valid_dates = date_counts[date_counts >= self.min_cs].index
        df_valid = df_valid[df_valid["trade_date"].isin(valid_dates)].copy()

        if len(df_valid) == 0:
            return self._empty_permutation(n_perm)

        # ── 预计算收益侧 (固定不变) ──
        df_valid["_r_rank"] = df_valid.groupby("trade_date")[return_col].rank()
        df_valid["_r_c"] = (
            df_valid["_r_rank"]
            - df_valid.groupby("trade_date")["_r_rank"].transform("mean")
        )
        df_valid["_r_sq"] = df_valid["_r_c"] ** 2
        r_sq_agg = df_valid.groupby("trade_date")["_r_sq"].sum()  # Series, index=date

        # ── 实际 IC 均值 ──
        actual_ic = self.ic_engine.compute_ic_series(
            df_valid, factor_name, "rank", return_col
        )
        actual_mean = actual_ic.mean()

        # ── 置换分布 ──
        rng = np.random.RandomState(random_seed)
        perm_means = np.zeros(n_perm)
        grp_date = df_valid["trade_date"]

        for i in range(n_perm):
            # 截面内随机打乱因子值
            shuffled = df_valid.groupby("trade_date")[factor_name].transform(
                lambda x: x.iloc[rng.permutation(len(x))].values
            )
            # 排名
            f_rank = shuffled.groupby(grp_date).rank()
            # 去中心
            f_centered = f_rank - f_rank.groupby(grp_date).transform("mean")
            # 叉积和
            cross = (f_centered * df_valid["_r_c"]).groupby(grp_date).sum()
            f_sq_agg = (f_centered ** 2).groupby(grp_date).sum()
            # IC
            denom = np.sqrt(f_sq_agg * r_sq_agg)
            ic_vals = np.where(denom > 1e-12, cross / denom, 0.0)
            perm_means[i] = ic_vals.mean()

        # p-value: 双尾
        p_value = float((np.abs(perm_means) >= np.abs(actual_mean)).sum()) / n_perm

        return {
            "actual_ic_mean": float(actual_mean),
            "perm_ic_mean": float(perm_means.mean()),
            "perm_ic_std": float(perm_means.std()),
            "p_value": p_value,
            "significant": p_value < FactorTestConfig.significance_level(),
            "n_permutations": n_perm,
            "perm_2.5%": float(np.percentile(perm_means, 2.5)),
            "perm_97.5%": float(np.percentile(perm_means, 97.5)),
            "perm_distribution": perm_means,
        }

    # ═══════════════════════════════════════════
    #  4. 子周期稳定性
    # ═══════════════════════════════════════════

    def check_subperiod_stability(self, ic_series: pd.Series) -> dict:
        """
        分年度 IC 方向一致性:
          整体 IC > 0 的年份占比 / 整体 IC < 0 的年份占比。
          正比例 >= 70% 认为子周期稳定。
        """
        yearly = self.ic_engine.compute_yearly_stability(ic_series)
        if len(yearly) == 0:
            return {
                "n_years": 0,
                "consistent_ratio": 0.0,
                "pass": False,
                "yearly_stats": yearly,
            }

        overall_mean = ic_series.mean()
        if overall_mean > 0:
            consistent = (yearly["ic_mean"] > 0).sum()
        elif overall_mean < 0:
            consistent = (yearly["ic_mean"] < 0).sum()
        else:
            consistent = 0

        ratio = consistent / len(yearly)
        threshold = FactorTestConfig.yearly_consistency_ratio()

        return {
            "n_years": len(yearly),
            "overall_ic_mean": float(overall_mean),
            "consistent_ratio": float(ratio),
            "pass": ratio >= threshold,
            "yearly_stats": yearly,
        }

    # ═══════════════════════════════════════════
    #  5. IC 自相关
    # ═══════════════════════════════════════════

    def check_ic_autocorrelation(self, ic_series: pd.Series) -> dict:
        """
        IC 序列自相关:
          lag-1 自相关衡量 IC 的日际持续性。
          |AC(1)| > 0.1 说明 IC 有持续性, 因子信息不立即衰减。
        """
        ic = ic_series.dropna()
        if len(ic) < 3:
            return {
                "autocorr_lag1": 0.0,
                "autocorr_lag5": 0.0,
                "autocorr_lag10": 0.0,
                "has_persistence": False,
            }

        ac1 = self._safe_autocorr(ic, 1)
        ac5 = self._safe_autocorr(ic, 5)
        ac10 = self._safe_autocorr(ic, 10)

        return {
            "autocorr_lag1": ac1,
            "autocorr_lag5": ac5,
            "autocorr_lag10": ac10,
            "has_persistence": abs(ac1) > 0.1,
        }

    def _safe_autocorr(self, series: pd.Series, lag: int) -> float:
        if len(series) <= lag:
            return 0.0
        val = series.autocorr(lag=lag)
        return float(val) if not np.isnan(val) else 0.0

    # ═══════════════════════════════════════════
    #  全量校验
    # ═══════════════════════════════════════════

    def run_full_check(
        self,
        df: pd.DataFrame,
        factor_name: str,
        return_col: str = "fwd_ret_5d",
        n_perm: int = None,
    ) -> dict:
        """一次性运行全部 5 项校验。"""
        ic_series = self.ic_engine.compute_ic_series(
            df, factor_name, "rank", return_col
        )

        return {
            "factor_name": factor_name,
            "in_sample_oos": self.check_in_sample_oos(df, factor_name, return_col),
            "walk_forward": self.walk_forward(df, factor_name, return_col),
            "permutation_test": self.permutation_test(
                df, factor_name, return_col, n_perm=n_perm
            ),
            "subperiod_stability": self.check_subperiod_stability(ic_series),
            "ic_autocorrelation": self.check_ic_autocorrelation(ic_series),
        }

    # ═══════════════════════════════════════════

    def _empty_permutation(self, n_perm: int) -> dict:
        return {
            "actual_ic_mean": 0.0,
            "perm_ic_mean": 0.0,
            "perm_ic_std": 0.0,
            "p_value": 1.0,
            "significant": False,
            "n_permutations": n_perm,
            "perm_2.5%": 0.0,
            "perm_97.5%": 0.0,
            "perm_distribution": np.zeros(n_perm),
        }

    # ═══════════════════════════════════════════
    #  P4-A: Purged Walk-Forward CV
    # ═══════════════════════════════════════════

    def purged_walk_forward(
        self,
        df: pd.DataFrame,
        factor_name: str,
        return_col: str = "fwd_ret_5d",
        train_days: int = None,
        test_days: int = None,
        purge_days: int = 5,
        embargo_days: int = 2,
    ) -> dict:
        """Purged Walk-Forward 交叉验证

        在训练集与测试集之间插入 purge（h）和 embargo（p）区间，
        防止未来信息泄漏：
          - purge: 训练集尾部删除 h 天（因子用到的未来收益窗口）
          - embargo: 测试集头部跳过 p 天（避免价格冲击残留）

        Parameters
        ----------
        purge_days : int
            训练集尾部清除天数（默认 5 天，对应 fwd_ret_5d）
        embargo_days : int
            测试集头部跳过天数（默认 2 天）
        """
        train_days = train_days or FactorTestConfig.wf_train()
        test_days = test_days or FactorTestConfig.wf_test()

        dates = sorted(df["trade_date"].unique())
        results: List[dict] = []
        start = 0

        while start + train_days + purge_days + embargo_days + test_days <= len(dates):
            # 训练集：[start, start+train_days)
            tr_dates = dates[start:start + train_days]
            # purge 区间：[start+train_days, start+train_days+purge_days) —— 丢弃
            # embargo 区间：[start+train_days+purge_days, start+train_days+purge_days+embargo_days) —— 丢弃
            # 测试集：[start+train_days+purge_days+embargo_days, ...)
            te_start = start + train_days + purge_days + embargo_days
            te_dates = dates[te_start:te_start + test_days]

            df_tr = df[df["trade_date"].isin(tr_dates)]
            df_te = df[df["trade_date"].isin(te_dates)]

            s_tr = self.ic_engine.compute_ic_summary(
                self.ic_engine.compute_ic_series(df_tr, factor_name, "rank", return_col)
            )
            s_te = self.ic_engine.compute_ic_summary(
                self.ic_engine.compute_ic_series(df_te, factor_name, "rank", return_col)
            )

            results.append({
                "window": len(results) + 1,
                "train_start": tr_dates[0],
                "train_end": tr_dates[-1],
                "purge_days": purge_days,
                "embargo_days": embargo_days,
                "test_start": te_dates[0],
                "test_end": te_dates[-1],
                "train_ic": s_tr["ic_mean"],
                "train_icir": s_tr["icir"],
                "test_ic": s_te["ic_mean"],
                "test_icir": s_te["icir"],
                "test_ic_positive": s_te["ic_mean"] > 0,
                "direction_consistent": (
                    (s_tr["ic_mean"] > 0) == (s_te["ic_mean"] > 0)
                ) if abs(s_tr["ic_mean"]) > 1e-12 and abs(s_te["ic_mean"]) > 1e-12 else False,
                "degradation": 1.0 - (s_te["icir"] / s_tr["icir"]) if abs(s_tr["icir"]) > 1e-12 else 1.0,
            })

            start += test_days

        if not results:
            return {
                "results": pd.DataFrame(),
                "n_windows": 0,
                "purge_days": purge_days,
                "embargo_days": embargo_days,
                "ic_positive_ratio": 0.0,
                "direction_consistency_ratio": 0.0,
                "avg_degradation": 1.0,
                "pass": False,
            }

        df_res = pd.DataFrame(results)
        pos_ratio = df_res["test_ic_positive"].mean()
        dir_ratio = df_res["direction_consistent"].mean()
        avg_deg = df_res["degradation"].mean()
        threshold = FactorTestConfig.ic_positive_ratio()
        # 通过条件：IC 正占比 >= 阈值 且 平均衰减 < 60%
        passed = pos_ratio >= threshold and avg_deg < 0.60

        return {
            "results": df_res,
            "n_windows": len(results),
            "purge_days": purge_days,
            "embargo_days": embargo_days,
            "ic_positive_ratio": float(pos_ratio),
            "direction_consistency_ratio": float(dir_ratio),
            "avg_degradation": float(avg_deg),
            "pass": passed,
        }

    # ═══════════════════════════════════════════
    #  P4-B: IC 半衰期衰减
    # ═══════════════════════════════════════════

    def ic_half_life(self, ic_series: pd.Series) -> dict:
        """计算 IC 序列的半衰期

        用指数衰减模型拟合 IC 自相关函数，估计半衰期（天）。
        半衰期越长，因子 Alpha 越稳定，越不容易过拟合。

        Returns
        -------
        dict : {
            "half_life_days": float,
            "autocorr_lag1": float,
            "decay_rate": float,     # 日衰减率
            "stable": bool,          # 半衰期 >= 5 天视为稳定
        }
        """
        ic = ic_series.dropna()
        if len(ic) < 10:
            return {
                "half_life_days": 0.0,
                "autocorr_lag1": 0.0,
                "decay_rate": 1.0,
                "stable": False,
            }

        # 计算前 20 阶自相关
        max_lag = min(20, len(ic) // 3)
        acf_vals = []
        for lag in range(1, max_lag + 1):
            ac = self._safe_autocorr(ic, lag)
            acf_vals.append(ac)

        ac1 = acf_vals[0] if acf_vals else 0.0

        # 用 lag-1 自相关估计指数衰减率: acf(k) ≈ exp(-k / tau)
        # 半衰期 = ln(2) * tau = ln(2) / (-ln(ac1))
        if ac1 <= 0 or ac1 >= 1:
            half_life = 0.0
            decay_rate = 1.0
        else:
            import math
            decay_rate = ac1  # 日衰减率 ≈ lag-1 自相关
            tau = -1.0 / math.log(ac1) if ac1 > 0 and ac1 < 1 else 0
            half_life = math.log(2) * tau

        return {
            "half_life_days": float(half_life),
            "autocorr_lag1": float(ac1),
            "decay_rate": float(decay_rate),
            "stable": half_life >= 5.0,
            "acf_1to20": [float(x) for x in acf_vals],
        }

    # ═══════════════════════════════════════════
    #  P4-C: 三段审计
    # ═══════════════════════════════════════════

    def three_stage_audit(
        self,
        df: pd.DataFrame,
        factor_name: str,
        return_col: str = "fwd_ret_5d",
        n_perm: int = 100,
    ) -> dict:
        """三段审计：经济逻辑 → 统计验证 → 样本外稳健

        Stage 1 经济逻辑审查：
          - 因子方向是否符合经济学直觉
          - IC 均值是否显著不为零
          - 自相关是否正常（半衰期 > 2天）

        Stage 2 统计验证：
          - 置换检验 p < 0.05
          - 子周期稳定性 ≥ 70%

        Stage 3 样本外稳健：
          - Purged WF-CV IC正占比 ≥ 60%
          - ICIR 衰减 < 60%

        Returns
        -------
        dict : {
            "overall_score": float,       # 0~100 综合得分
            "overall_pass": bool,
            "stage_1": {...},
            "stage_2": {...},
            "stage_3": {...},
            "flags": [...],               # 风险提示列表
        }
        """
        ic_series = self.ic_engine.compute_ic_series(
            df, factor_name, "rank", return_col
        )
        ic_summary = self.ic_engine.compute_ic_summary(ic_series)

        flags = []
        stage_scores = {}

        # ── Stage 1: 经济逻辑 ──
        from factor_lib.registry import FACTOR_REGISTRY
        meta = FACTOR_REGISTRY.get(factor_name)
        direction_ok = True
        if meta:
            # 检查 IC 方向是否与因子定义一致
            expected_sign = meta.direction  # 1 or -1
            actual_sign = 1 if ic_summary["ic_mean"] > 0 else -1
            direction_ok = expected_sign == actual_sign
            if not direction_ok:
                flags.append(f"方向不符：预期{expected_sign}，实际{actual_sign}")
        else:
            flags.append("因子未注册，无法验证方向")

        ic_significant = abs(ic_summary["ic_mean"]) > 0.005  # IC > 0.5%
        if not ic_significant:
            flags.append(f"IC 均值过小：{ic_summary['ic_mean']:.4f}")

        half_life_info = self.ic_half_life(ic_series)
        persistence_ok = half_life_info["half_life_days"] >= 2.0
        if not persistence_ok:
            flags.append(f"IC 半衰期过短：{half_life_info['half_life_days']:.1f}天")

        s1_pass = direction_ok and ic_significant and persistence_ok
        s1_score = (
            (30 if direction_ok else 0) +
            (20 if ic_significant else 0) +
            (10 if persistence_ok else 0)
        )
        stage_scores["stage_1"] = {
            "pass": s1_pass,
            "score": s1_score,
            "max_score": 60,
            "direction_consistent": direction_ok,
            "ic_significant": ic_significant,
            "ic_mean": ic_summary["ic_mean"],
            "half_life_days": half_life_info["half_life_days"],
        }

        # ── Stage 2: 统计验证 ──
        perm = self.permutation_test(df, factor_name, return_col, n_perm=n_perm)
        subperiod = self.check_subperiod_stability(ic_series)

        s2_pass = perm["significant"] and subperiod["pass"]
        s2_score = (
            (15 if perm["significant"] else 0) +
            (15 if subperiod["pass"] else 0)
        )
        stage_scores["stage_2"] = {
            "pass": s2_pass,
            "score": s2_score,
            "max_score": 30,
            "permutation_pvalue": perm["p_value"],
            "permutation_significant": perm["significant"],
            "subperiod_consistency": subperiod["consistent_ratio"],
            "subperiod_pass": subperiod["pass"],
        }

        if not perm["significant"]:
            flags.append(f"置换检验不显著：p={perm['p_value']:.3f}")
        if not subperiod["pass"]:
            flags.append(f"子周期稳定性不足：{subperiod['consistent_ratio']:.1%}")

        # ── Stage 3: 样本外稳健 ──
        pwf = self.purged_walk_forward(df, factor_name, return_col)

        s3_pass = pwf["pass"]
        s3_score = 10 if s3_pass else 0
        stage_scores["stage_3"] = {
            "pass": s3_pass,
            "score": s3_score,
            "max_score": 10,
            "n_windows": pwf["n_windows"],
            "ic_positive_ratio": pwf["ic_positive_ratio"],
            "avg_degradation": pwf["avg_degradation"],
        }

        if not s3_pass:
            flags.append(f"Purged WF-CV 不通过：正占比={pwf['ic_positive_ratio']:.1%}, 衰减={pwf['avg_degradation']:.1%}")

        # ── 综合评分 ──
        total_score = sum(s["score"] for s in stage_scores.values())
        max_score = sum(s["max_score"] for s in stage_scores.values())
        overall_pct = total_score / max_score if max_score > 0 else 0
        overall_pass = overall_pct >= 0.70  # 70 分及格

        return {
            "factor_name": factor_name,
            "overall_score": round(total_score, 1),
            "overall_score_100": round(overall_pct * 100, 1),
            "overall_pass": overall_pass,
            "stage_1": stage_scores["stage_1"],
            "stage_2": stage_scores["stage_2"],
            "stage_3": stage_scores["stage_3"],
            "flags": flags,
            "ic_mean": ic_summary["ic_mean"],
            "icir": ic_summary["icir"],
            "n_days": ic_summary["n_days"],
        }
