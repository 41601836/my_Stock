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
