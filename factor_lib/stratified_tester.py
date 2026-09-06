# -*- coding: utf-8 -*-
"""
stratified_tester.py — 分层测试引擎
=================================================
按因子值截面排名将股票分为 N 组，计算:
  - 各组等权收益与净值曲线
  - 多空收益（Top 组 - Bottom 组，方向由 registry.direction 决定）
  - 多空净值曲线（扣除交易成本）
  - 单调性检验（Spearman: 组序号 vs 平均收益）
  - 分组换手率（衡量策略可执行性）

支持日调 / 周调，可配置单边交易成本。
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from scipy import stats as sps

from factor_lib.config import FactorTestConfig
from factor_lib.registry import FACTOR_REGISTRY
from factor_lib.loader import FactorDataLoader


@dataclass
class StratifiedTestResult:
    factor_name: str
    n_groups: int
    rebalance_freq: str
    cost_bps: float
    direction: int
    group_returns: pd.DataFrame
    group_nav: pd.DataFrame
    long_short_returns: pd.Series
    long_short_nav: pd.Series
    monotonicity_score: float
    monotonicity_pvalue: float
    turnover: pd.DataFrame
    avg_turnover: float
    summary: dict


class StratifiedTester:

    def __init__(self, min_cross_section_size: int = None, loader: FactorDataLoader = None):
        self.min_cs = min_cross_section_size or FactorTestConfig.min_cross_section_size()
        self.loader = loader or FactorDataLoader()

    def run_stratified_test(
        self,
        df: pd.DataFrame,
        factor_name: str,
        n_groups: int = None,
        return_col: str = "fwd_ret_5d",
        rebalance_freq: str = None,
        cost_bps: float = None,
    ) -> StratifiedTestResult:
        """
        完整分层测试。

        参数:
            df: 含 ts_code, trade_date, factor_name, return_col 的 DataFrame
            factor_name: 因子列名
            n_groups: 分组数 (默认从配置读取)
            return_col: 收益列名 (如 fwd_ret_5d)
            rebalance_freq: "weekly" 或 "daily"
            cost_bps: 单边交易成本 (bp)

        返回: StratifiedTestResult
        """
        n_groups = n_groups or FactorTestConfig.n_groups()
        rebalance_freq = rebalance_freq or FactorTestConfig.strat_rebalance_freq()
        cost_bps = cost_bps if cost_bps is not None else FactorTestConfig.strat_cost_bps()

        # 因子方向
        meta = FACTOR_REGISTRY.get(factor_name)
        direction = meta.direction if meta else 1

        # 1. 确定调仓日
        min_date = str(df["trade_date"].min())
        max_date = str(df["trade_date"].max())
        if rebalance_freq == "weekly":
            rebal_dates = self.loader.get_weekly_rebalance_dates(min_date, max_date)
        else:
            rebal_dates = sorted(df["trade_date"].unique())

        # 2. 过滤到调仓日，丢弃 NaN
        df_r = df[df["trade_date"].isin(rebal_dates)].copy()
        df_r = df_r.dropna(subset=[factor_name, return_col]).copy()

        # 3. 过滤截面样本太少的日期
        date_counts = df_r.groupby("trade_date").size()
        valid_dates = date_counts[date_counts >= self.min_cs].index
        df_r = df_r[df_r["trade_date"].isin(valid_dates)]

        if len(df_r) == 0:
            return self._empty_result(factor_name, n_groups, rebalance_freq, cost_bps, direction)

        # 4. 向量化分组: 截面排名 → 均分 N 组
        df_r["_rank"] = df_r.groupby("trade_date")[factor_name].rank(method="first")
        df_r["_n"] = df_r.groupby("trade_date")["ts_code"].transform("count")
        df_r["group"] = ((df_r["_rank"] - 1) * n_groups // df_r["_n"] + 1).clip(1, n_groups).astype(int)
        df_r = df_r.drop(columns=["_rank", "_n"])

        # 5. 各组等权收益
        group_returns = (
            df_r.groupby(["trade_date", "group"])[return_col]
            .mean()
            .unstack("group")
            .sort_index()
        )
        group_returns.columns = [f"g{c}" for c in group_returns.columns]

        # 6. 各组净值 (扣成本)
        turnover = self._compute_turnover(df_r, n_groups)
        avg_turnover = turnover["turnover_rate"].mean() if len(turnover) > 0 else 0.0
        cost_per_period = avg_turnover * cost_bps / 10000.0

        net_group_returns = group_returns - cost_per_period
        group_nav = (1 + net_group_returns).cumprod()
        # Prepend initial 1.0
        group_nav = pd.concat([
            pd.DataFrame(1.0, index=["init"], columns=group_nav.columns),
            group_nav
        ])

        # 7. 多空收益
        if direction > 0:
            top_col = f"g{n_groups}"
            bottom_col = "g1"
        else:
            top_col = "g1"
            bottom_col = f"g{n_groups}"

        long_short_returns = group_returns[top_col] - group_returns[bottom_col]
        # 多空双边各扣一次成本
        long_short_net = long_short_returns - 2 * cost_per_period
        long_short_nav_raw = (1 + long_short_net).cumprod()
        # Prepend initial 1.0
        long_short_nav = pd.concat([
            pd.Series([1.0], index=["init"]),
            long_short_nav_raw
        ])

        # 8. 单调性检验
        avg_returns = group_returns.mean()
        mono_score, mono_p = self._compute_monotonicity(avg_returns, n_groups)

        # 9. 汇总
        summary = self._build_summary(
            group_returns, long_short_net, mono_score, mono_p,
            avg_turnover, cost_per_period, n_groups, direction
        )

        return StratifiedTestResult(
            factor_name=factor_name,
            n_groups=n_groups,
            rebalance_freq=rebalance_freq,
            cost_bps=cost_bps,
            direction=direction,
            group_returns=group_returns,
            group_nav=group_nav,
            long_short_returns=long_short_net,
            long_short_nav=long_short_nav,
            monotonicity_score=mono_score,
            monotonicity_pvalue=mono_p,
            turnover=turnover,
            avg_turnover=avg_turnover,
            summary=summary,
        )

    # ═══════════════════════════════════════════
    #  单调性检验
    # ═══════════════════════════════════════════

    def compute_monotonicity(self, group_returns: pd.DataFrame) -> dict:
        """独立单调性检验接口。"""
        avg = group_returns.mean()
        n_groups = len(avg)
        score, p = self._compute_monotonicity(avg, n_groups)
        return {"monotonicity_score": score, "monotonicity_pvalue": p}

    def _compute_monotonicity(self, avg_returns: pd.Series, n_groups: int) -> tuple:
        """
        Spearman 相关: 组序号 (1..N) vs 平均收益。
        |score| 越大越单调，p 值越低越显著。
        """
        group_idx = np.arange(1, n_groups + 1)
        if len(avg_returns) < 2 or avg_returns.std() < 1e-12:
            return 0.0, 1.0
        corr, p = sps.spearmanr(group_idx, avg_returns.values)
        if np.isnan(corr):
            return 0.0, 1.0
        return float(corr), float(p)

    # ═══════════════════════════════════════════
    #  多空净值
    # ═══════════════════════════════════════════

    def compute_long_short_nav(
        self,
        top_returns: pd.Series,
        bottom_returns: pd.Series,
        cost_bps: float = 15.0,
        turnover: float = 0.3,
    ) -> pd.Series:
        """独立多空净值接口。"""
        ls = top_returns - bottom_returns
        cost = 2 * turnover * cost_bps / 10000.0
        return (1 + ls - cost).cumprod()

    # ═══════════════════════════════════════════
    #  换手率
    # ═══════════════════════════════════════════

    def _compute_turnover(self, df: pd.DataFrame, n_groups: int) -> pd.DataFrame:
        """
        向量化换手率:
          对每只股票, 比较其在相邻调仓日是否在同组。
          turnover = 1 - stayed_count / total_count (每组每期)
        """
        cols = ["trade_date", "ts_code", "group"]
        m = df[cols].sort_values(["ts_code", "trade_date"]).copy()
        m["prev_group"] = m.groupby("ts_code")["group"].shift(1)
        m["same_group"] = (m["group"] == m["prev_group"]).astype(int)

        # 第一期无前值, same_group=0 但不算换手 (标记为 NaN)
        m.loc[m["prev_group"].isna(), "same_group"] = np.nan

        agg = m.groupby(["trade_date", "group"]).agg(
            total=("ts_code", "count"),
            stayed=("same_group", "sum"),
        ).reset_index()
        agg["stayed"] = agg["stayed"].fillna(0)
        agg["turnover_rate"] = 1.0 - agg["stayed"] / agg["total"].clip(lower=1)
        agg = agg[agg["turnover_rate"].notna()]

        return agg

    # ═══════════════════════════════════════════
    #  汇总
    # ═══════════════════════════════════════════

    def _build_summary(
        self, group_returns, ls_net_returns, mono_score, mono_p,
        avg_turnover, cost_per_period, n_groups, direction
    ) -> dict:
        ls_nav = (1 + ls_net_returns).cumprod()
        total_ret = ls_nav.iloc[-1] - 1 if len(ls_nav) > 0 else 0.0
        n_periods = len(ls_net_returns)
        annual_factor = 52 if n_periods > 0 else 1  # 周调年化 52
        annual_ret = (1 + total_ret) ** (annual_factor / max(n_periods, 1)) - 1 if total_ret > -1 else 0.0

        return {
            "n_periods": n_periods,
            "long_short_total_return": total_ret,
            "long_short_annual_return": annual_ret,
            "long_sharpe": ls_net_returns.mean() / ls_net_returns.std() * np.sqrt(annual_factor)
                           if ls_net_returns.std() > 1e-12 else 0.0,
            "long_short_win_rate": (ls_net_returns > 0).sum() / n_periods
                                   if n_periods > 0 else 0.0,
            "monotonicity_score": mono_score,
            "monotonicity_pvalue": mono_p,
            "avg_turnover": avg_turnover,
            "cost_per_period": cost_per_period,
            "n_groups": n_groups,
            "direction": direction,
            "top_group_avg_return": group_returns.iloc[:, -1].mean() if direction > 0
                                    else group_returns.iloc[:, 0].mean(),
            "bottom_group_avg_return": group_returns.iloc[:, 0].mean() if direction > 0
                                        else group_returns.iloc[:, -1].mean(),
        }

    def _empty_result(self, factor_name, n_groups, rebalance_freq, cost_bps, direction):
        return StratifiedTestResult(
            factor_name=factor_name,
            n_groups=n_groups,
            rebalance_freq=rebalance_freq,
            cost_bps=cost_bps,
            direction=direction,
            group_returns=pd.DataFrame(),
            group_nav=pd.DataFrame(),
            long_short_returns=pd.Series(dtype=float),
            long_short_nav=pd.Series(dtype=float),
            monotonicity_score=0.0,
            monotonicity_pvalue=1.0,
            turnover=pd.DataFrame(),
            avg_turnover=0.0,
            summary={"n_periods": 0},
        )
