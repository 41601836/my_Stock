# -*- coding: utf-8 -*-
"""
backtester.py — 单因子回测器
=================================================
纯因子排名 Top-N 等权回测，完全独立于 agent/backtester.py。
不引用 agent/ 任何代码，不绑定策略上下文。

功能:
  - Top-N 选股（方向由 registry.direction 决定）
  - 等权组合净值曲线（扣交易成本）
  - 绩效统计: 年化收益/最大回撤/夏普/卡玛/Sortino/胜率
  - 分年度收益
  - 基准对比（全市场等权）
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Optional, List

from factor_lib.config import FactorTestConfig
from factor_lib.registry import FACTOR_REGISTRY
from factor_lib.loader import FactorDataLoader


@dataclass
class BacktestResult:
    factor_name: str
    top_n: int
    rebalance_freq: str
    cost_bps: float
    direction: int
    nav: pd.Series               # 组合净值 (起点=1.0)
    returns: pd.Series           # 每期收益 (扣成本)
    benchmark_nav: pd.Series     # 基准净值
    benchmark_returns: pd.Series  # 基准每期收益
    performance: dict             # 绩效统计
    benchmark_performance: dict   # 基准绩效
    yearly_returns: pd.DataFrame  # 分年度收益 (组合 + 基准)
    turnover: pd.Series           # 每期换手率
    holdings: pd.DataFrame        # 每期持仓明细


class FactorBacktester:

    def __init__(self, min_cross_section_size: int = None, loader: FactorDataLoader = None):
        self.min_cs = min_cross_section_size or FactorTestConfig.min_cross_section_size()
        self.loader = loader or FactorDataLoader()

    def run_backtest(
        self,
        df: pd.DataFrame,
        factor_name: str,
        top_n: int = None,
        return_col: str = "fwd_ret_5d",
        rebalance_freq: str = None,
        cost_bps: float = None,
        benchmark: str = None,
    ) -> BacktestResult:
        """
        纯因子排名 Top-N 等权回测。

        参数:
            df: 含 ts_code, trade_date, factor_name, return_col 的 DataFrame
            factor_name: 因子列名
            top_n: 选股数量 (默认从配置)
            return_col: 收益列名
            rebalance_freq: "weekly" 或 "daily"
            cost_bps: 单边交易成本 (bp)
            benchmark: "equal_weight" 或 "none"
        """
        top_n = top_n or FactorTestConfig.top_n()
        rebalance_freq = rebalance_freq or FactorTestConfig.bt_rebalance_freq()
        cost_bps = cost_bps if cost_bps is not None else FactorTestConfig.bt_cost_bps()
        benchmark = benchmark or FactorTestConfig.bt_benchmark()

        meta = FACTOR_REGISTRY.get(factor_name)
        direction = meta.direction if meta else 1

        # 1. 确定调仓日
        min_date = str(df["trade_date"].min())
        max_date = str(df["trade_date"].max())
        if rebalance_freq == "weekly":
            rebal_dates = self.loader.get_weekly_rebalance_dates(min_date, max_date)
        else:
            rebal_dates = sorted(df["trade_date"].unique())

        # 2. 过滤调仓日 + 去除 NaN
        df_r = df[df["trade_date"].isin(rebal_dates)].copy()
        df_r = df_r.dropna(subset=[factor_name, return_col]).copy()

        # 过滤截面太少的日期
        date_counts = df_r.groupby("trade_date").size()
        valid_dates = date_counts[date_counts >= self.min_cs].index
        df_r = df_r[df_r["trade_date"].isin(valid_dates)]

        if len(df_r) == 0:
            return self._empty_result(factor_name, top_n, rebalance_freq, cost_bps, direction)

        # 3. 截面排名: direction=+1 选最大值, direction=-1 选最小值
        if direction > 0:
            df_r["_rank"] = df_r.groupby("trade_date")[factor_name].rank(
                method="first", ascending=False
            )
        else:
            df_r["_rank"] = df_r.groupby("trade_date")[factor_name].rank(
                method="first", ascending=True
            )
        df_r["_selected"] = df_r["_rank"] <= top_n

        # 4. 组合收益 = Top-N 等权
        selected = df_r[df_r["_selected"]]
        portfolio_returns = selected.groupby("trade_date")[return_col].mean().sort_index()

        # 5. 基准收益 = 全市场等权
        if benchmark == "equal_weight":
            benchmark_returns = df_r.groupby("trade_date")[return_col].mean().sort_index()
        else:
            benchmark_returns = pd.Series(0.0, index=portfolio_returns.index)

        # 6. 换手率
        turnover = self._compute_turnover(selected, top_n)

        # 7. 扣成本
        avg_turnover = turnover.mean() if len(turnover) > 0 else 0.3
        cost_per_period = avg_turnover * cost_bps / 10000.0
        net_returns = portfolio_returns - cost_per_period
        net_benchmark = benchmark_returns  # 基准不扣成本 (被动持有)

        # 8. 净值
        annual_factor = 52 if rebalance_freq == "weekly" else 252
        nav = self._build_nav(net_returns)
        benchmark_nav = self._build_nav(net_benchmark)

        # 9. 绩效统计
        perf = self._compute_performance(net_returns, annual_factor)
        bench_perf = self._compute_performance(net_benchmark, annual_factor)

        # 10. 分年度收益
        yearly = self._compute_yearly_returns(net_returns, net_benchmark, annual_factor)

        # 11. 持仓明细
        holdings = selected[["trade_date", "ts_code", factor_name, return_col, "_rank"]].copy()
        holdings.columns = ["trade_date", "ts_code", "factor_value", "forward_return", "rank"]
        holdings = holdings.sort_values(["trade_date", "rank"])

        return BacktestResult(
            factor_name=factor_name,
            top_n=top_n,
            rebalance_freq=rebalance_freq,
            cost_bps=cost_bps,
            direction=direction,
            nav=nav,
            returns=net_returns,
            benchmark_nav=benchmark_nav,
            benchmark_returns=net_benchmark,
            performance=perf,
            benchmark_performance=bench_perf,
            yearly_returns=yearly,
            turnover=turnover,
            holdings=holdings,
        )

    # ═══════════════════════════════════════════
    #  净值
    # ═══════════════════════════════════════════

    def _build_nav(self, returns: pd.Series) -> pd.Series:
        """净值曲线，起点=1.0。"""
        if len(returns) == 0:
            return pd.Series([1.0], index=["init"])
        cumprod = (1 + returns).cumprod()
        return pd.concat([pd.Series([1.0], index=["init"]), cumprod])

    # ═══════════════════════════════════════════
    #  换手率
    # ═══════════════════════════════════════════

    def _compute_turnover(self, selected: pd.DataFrame, top_n: int) -> pd.Series:
        """
        每期换手率: 1 - 与上一期持仓的重叠比例。
        """
        dates = sorted(selected["trade_date"].unique())
        if len(dates) <= 1:
            return pd.Series(dtype=float)

        prev_set = set(selected[selected["trade_date"] == dates[0]]["ts_code"])
        turnovers = []
        for i in range(1, len(dates)):
            curr_set = set(selected[selected["trade_date"] == dates[i]]["ts_code"])
            overlap = len(prev_set & curr_set)
            t = 1.0 - overlap / max(len(curr_set), 1)
            turnovers.append(t)
            prev_set = curr_set

        return pd.Series(turnovers, index=dates[1:], name="turnover")

    # ═══════════════════════════════════════════
    #  绩效统计
    # ═══════════════════════════════════════════

    def _compute_performance(self, returns: pd.Series, annual_factor: int) -> dict:
        """计算绩效统计。"""
        r = returns.dropna()
        n = len(r)
        if n == 0:
            return self._empty_performance()

        # 年化收益
        total_return = (1 + r).prod() - 1
        n_years = n / annual_factor
        annual_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0

        # 波动率
        std = r.std(ddof=1) if n > 1 else 0.0
        annual_vol = std * np.sqrt(annual_factor)

        # 夏普
        sharpe = r.mean() / std * np.sqrt(annual_factor) if std > 1e-12 else 0.0

        # Sortino (下行风险)
        downside = r[r < 0]
        downside_std = downside.std(ddof=1) if len(downside) > 1 else 0.0
        sortino = r.mean() / downside_std * np.sqrt(annual_factor) if downside_std > 1e-12 else 0.0

        # 最大回撤
        nav = (1 + r).cumprod()
        running_max = nav.cummax()
        drawdown = (nav - running_max) / running_max
        max_drawdown = drawdown.min()

        # Calmar
        calmar = annual_return / abs(max_drawdown) if abs(max_drawdown) > 1e-12 else 0.0

        # 胜率
        win_rate = (r > 0).sum() / n if n > 0 else 0.0

        # 盈亏比
        gains = r[r > 0]
        losses = r[r < 0]
        avg_gain = gains.mean() if len(gains) > 0 else 0.0
        avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.0
        profit_loss_ratio = avg_gain / avg_loss if avg_loss > 1e-12 else 0.0

        return {
            "n_periods": n,
            "total_return": total_return,
            "annual_return": annual_return,
            "annual_volatility": annual_vol,
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown": max_drawdown,
            "calmar": calmar,
            "win_rate": win_rate,
            "profit_loss_ratio": profit_loss_ratio,
            "avg_return_per_period": r.mean(),
            "avg_gain": avg_gain,
            "avg_loss": -avg_loss,
        }

    def _empty_performance(self) -> dict:
        return {
            "n_periods": 0, "total_return": 0.0, "annual_return": 0.0,
            "annual_volatility": 0.0, "sharpe": 0.0, "sortino": 0.0,
            "max_drawdown": 0.0, "calmar": 0.0, "win_rate": 0.0,
            "profit_loss_ratio": 0.0, "avg_return_per_period": 0.0,
            "avg_gain": 0.0, "avg_loss": 0.0,
        }

    # ═══════════════════════════════════════════
    #  分年度收益
    # ═══════════════════════════════════════════

    def _compute_yearly_returns(
        self,
        returns: pd.Series,
        benchmark_returns: pd.Series,
        annual_factor: int,
    ) -> pd.DataFrame:
        """分年度收益统计。"""
        if len(returns) == 0:
            return pd.DataFrame()

        years = pd.Series(returns.index, index=returns.index).astype(str).str[:4]

        rows = []
        for yr, grp in returns.groupby(years):
            n = len(grp)
            total_ret = (1 + grp).prod() - 1
            bench_grp = benchmark_returns[benchmark_returns.index.astype(str).str[:4] == yr]
            bench_total = (1 + bench_grp).prod() - 1 if len(bench_grp) > 0 else 0.0
            excess = total_ret - bench_total

            std = grp.std(ddof=1) if n > 1 else 0.0
            sharpe = grp.mean() / std * np.sqrt(annual_factor) if std > 1e-12 else 0.0
            win = (grp > 0).sum() / n if n > 0 else 0.0

            rows.append({
                "year": yr,
                "n_periods": n,
                "portfolio_return": total_ret,
                "benchmark_return": bench_total,
                "excess_return": excess,
                "sharpe": sharpe,
                "win_rate": win,
            })

        return pd.DataFrame(rows)

    # ═══════════════════════════════════════════
    #  空结果
    # ═══════════════════════════════════════════

    def _empty_result(self, factor_name, top_n, rebalance_freq, cost_bps, direction):
        empty_nav = pd.Series([1.0], index=["init"])
        empty_ret = pd.Series(dtype=float)
        return BacktestResult(
            factor_name=factor_name, top_n=top_n, rebalance_freq=rebalance_freq,
            cost_bps=cost_bps, direction=direction,
            nav=empty_nav, returns=empty_ret,
            benchmark_nav=empty_nav.copy(), benchmark_returns=empty_ret.copy(),
            performance=self._empty_performance(),
            benchmark_performance=self._empty_performance(),
            yearly_returns=pd.DataFrame(),
            turnover=pd.Series(dtype=float),
            holdings=pd.DataFrame(),
        )
