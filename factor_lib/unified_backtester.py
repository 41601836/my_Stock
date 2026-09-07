# -*- coding: utf-8 -*-
"""
unified_backtester.py — 统一回测引擎

三大核心改进：
1. Buffer Zone 换仓（Top20 买入 / Top35 卖出阈值）
2. 交易成本（佣金 2.5bp + 印花 5bp + 滑点 5bp = 12.5bp/单边）
3. 分层输出（Q1-Q5 五组收益）

所有策略、Agent、回测都调用此引擎，结果完全可比。
"""
import sqlite3
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


class UnifiedBacktester:
    """统一回测引擎"""

    def __init__(
        self,
        db_path: str = "db/stock_data.db",
        cost_bps: float = 12.5,
        benchmark: str = "000300.SH",
    ):
        self.db_path = db_path
        self.cost_bps = cost_bps  # 单边交易成本（基点）
        self.benchmark = benchmark
        self._next_date_cache: Dict[str, str] = {}

    def run(
        self,
        factor_weights: Dict[str, float],
        dates: List[str],
        top_n: int = 20,
        buffer_n: int = 35,
        quantile_groups: int = 5,
        data_loader=None,
    ) -> Dict:
        """
        执行回测

        Parameters
        ----------
        factor_weights : dict   {因子名: 权重}
        dates : list           回测日期列表（周频）
        top_n : int            买入排名阈值
        buffer_n : int         卖出排名阈值（Buffer Zone）
        quantile_groups : int  分层数（默认5组）
        data_loader : FactorDataLoader 或 None（不传则实时加载）

        Returns
        -------
        dict: excess_calmar, excess_return, max_drawdown, ic_mean, ic_ir,
              weekly_returns, turnover_series, quantile_returns, portfolio_holdings
        """
        factor_names = list(factor_weights.keys())
        weights = np.array([factor_weights[f] for f in factor_names])

        holdings: List[str] = []  # 当前持仓股票
        weekly_returns: List[float] = []
        benchmark_returns: List[float] = []
        turnover_series: List[float] = []
        ic_list: List[float] = []
        quantile_returns: List[List[float]] = [[] for _ in range(quantile_groups)]
        all_scores: List[pd.DataFrame] = []

        conn = sqlite3.connect(self.db_path)

        for i, dt in enumerate(dates):
            # 1. 获取因子截面
            if data_loader is not None:
                df = data_loader.get_cross_section(dt, factor_names, level="neutral")
            else:
                df = self._load_raw(dt, factor_names, conn)

            if df.empty or len(df) < 50:
                continue

            # 2. 应用方向 + 加权打分
            from factor_lib.registry import FACTOR_REGISTRY
            score = np.zeros(len(df))
            for j, f in enumerate(factor_names):
                meta = FACTOR_REGISTRY.get(f)
                direction = meta.direction if meta else 1
                rank_vals = df[f].rank(method="average", pct=True) if f in df.columns else 0
                score += direction * weights[j] * rank_vals

            df["composite_score"] = score
            df = df.sort_values("composite_score", ascending=False)
            all_scores.append(df[["ts_code", "composite_score"]].copy())

            # 3. IC 计算
            ic = self._compute_ic(df, factor_names, weights, dt, conn)
            if np.isfinite(ic):
                ic_list.append(ic)

            # 4. 分层收益（Q1-Q5）
            q_returns = self._compute_quantile_returns(df, quantile_groups, dt, conn)
            for q in range(quantile_groups):
                if q < len(q_returns):
                    quantile_returns[q].append(q_returns[q])

            # 5. Buffer Zone 换仓
            new_top = df.head(top_n)["ts_code"].tolist()
            new_buffer = set(df.head(buffer_n)["ts_code"].tolist())

            old_holdings = holdings[:]
            # 卖出：不在 buffer 内的
            sell_list = [s for s in holdings if s not in new_buffer]
            # 买入：在 new_top 但不在持仓中的
            buy_list = [s for s in new_top if s not in holdings]
            # 替换：卖出和买入配对
            n_replace = min(len(sell_list), len(buy_list))
            for k in range(n_replace):
                holdings.remove(sell_list[k])
                holdings.append(buy_list[k])
            # 补充到 top_n
            for s in new_top:
                if s not in holdings and len(holdings) < top_n:
                    holdings.append(s)
            holdings = holdings[:top_n]

            # 6. 计算换手率
            turnover = len(buy_list) / max(top_n, 1)
            turnover_series.append(turnover)

            # 7. 计算下周收益
            if i < len(dates) - 1:
                next_dt = dates[i + 1]
                port_ret = self._compute_portfolio_return(holdings, dt, next_dt, conn)
                bench_ret = self._compute_benchmark_return(dt, next_dt, conn)
                weekly_returns.append(port_ret)
                benchmark_returns.append(bench_ret)

        conn.close()

        # 8. 计算统计指标
        weekly_returns = np.array(weekly_returns)
        benchmark_returns = np.array(benchmark_returns)
        excess_returns = weekly_returns - benchmark_returns

        # 扣除交易成本
        turnover_arr = np.array(turnover_series[:len(weekly_returns)])
        cost_arr = turnover_arr * self.cost_bps / 10000.0
        excess_returns_net = excess_returns - cost_arr

        # 年化
        ann_excess = np.mean(excess_returns_net) * 52 if len(excess_returns_net) > 0 else 0
        cum_excess = np.cumprod(1 + excess_returns_net)
        max_dd = self._max_drawdown(cum_excess)
        excess_calmar = ann_excess / abs(max_dd) if abs(max_dd) > 1e-6 else (ann_excess if ann_excess > 0 else 0)

        # IC 统计
        ic_arr = np.array(ic_list)
        ic_mean = np.mean(ic_arr) if len(ic_arr) > 0 else 0
        ic_std = np.std(ic_arr) if len(ic_arr) > 1 else 1e-6
        ic_ir = ic_mean / ic_std if ic_std > 1e-8 else 0

        # 分层平均
        q_avg = [np.mean(qr) * 52 if qr else 0 for qr in quantile_returns]

        # 单调性（Spearman）
        q_spearman = self._spearman_rho(q_avg) if len(q_avg) >= 3 else 0

        return {
            "excess_calmar": round(excess_calmar, 4),
            "excess_return_annual": round(ann_excess, 4),
            "max_drawdown": round(float(max_dd), 4),
            "ic_mean": round(float(ic_mean), 4),
            "ic_ir": round(float(ic_ir), 4),
            "weekly_returns": weekly_returns.tolist(),
            "excess_returns_net": excess_returns_net.tolist(),
            "turnover_avg": round(float(np.mean(turnover_arr)) if len(turnover_arr) > 0 else 0, 4),
            "quantile_returns_annual": [round(q, 4) for q in q_avg],
            "quantile_monotonicity": round(float(q_spearman), 4),
            "n_weeks": len(weekly_returns),
            "holdings_final": holdings,
        }

    def _load_raw(self, date, factor_names, conn):
        cols = ", ".join(factor_names)
        df = pd.read_sql(
            f"SELECT stock_code AS ts_code, {cols} "
            f"FROM factor_values WHERE trade_date = ?",
            conn, params=[date]
        )
        return df

    def _get_next_date(self, date, conn, days_ahead=7):
        """获取 date 后 days_ahead 天内的下一个交易日"""
        if date in self._next_date_cache:
            return self._next_date_cache[date]
        all_dates = pd.read_sql(
            "SELECT DISTINCT trade_date FROM daily_prices WHERE trade_date > ? ORDER BY trade_date LIMIT 10",
            conn, params=[date]
        )
        if all_dates.empty:
            return None
        next_dt = all_dates.iloc[0]["trade_date"]
        self._next_date_cache[date] = next_dt
        return next_dt

    def _compute_ic(self, df, factor_names, weights, date, conn) -> float:
        """计算加权因子 IC"""
        try:
            future = pd.read_sql(
                "SELECT ts_code, close FROM daily_prices WHERE trade_date = ?",
                conn, params=[date]
            )
            if future.empty:
                return 0.0

            next_dt = self._get_next_date(date, conn)
            if next_dt is None:
                return 0.0

            next_close = pd.read_sql(
                "SELECT ts_code, close FROM daily_prices WHERE trade_date = ?",
                conn, params=[next_dt]
            )
            if next_close.empty:
                return 0.0

            merged = future.merge(next_close, on="ts_code", suffixes=("_t0", "_t1"))
            merged["ret"] = (merged["close_t1"] - merged["close_t0"]) / merged["close_t0"]
            merged = merged.merge(df[["ts_code", "composite_score"]], on="ts_code", how="inner")

            if len(merged) < 30:
                return 0.0

            from scipy.stats import spearmanr
            corr, _ = spearmanr(merged["composite_score"], merged["ret"])
            return float(corr) if np.isfinite(corr) else 0.0
        except Exception as e:
            return 0.0

    def _compute_quantile_returns(self, df, n_groups, date, conn):
        """计算 Q1-Qn 分组收益"""
        try:
            df_sorted = df.sort_values("composite_score", ascending=False).copy()
            n = len(df_sorted)
            if n < n_groups * 10:
                return [0.0] * n_groups

            group_size = n // n_groups
            returns = []

            next_dt = self._get_next_date(date, conn)
            if next_dt is None:
                return [0.0] * n_groups

            close_t0 = pd.read_sql(
                "SELECT ts_code, close FROM daily_prices WHERE trade_date = ?",
                conn, params=[date]
            )
            close_t1 = pd.read_sql(
                "SELECT ts_code, close FROM daily_prices WHERE trade_date = ?",
                conn, params=[next_dt]
            )

            merged = close_t0.merge(close_t1, on="ts_code", suffixes=("_0", "_1"))
            merged["ret"] = (merged["close_1"] - merged["close_0"]) / merged["close_0"]
            merged = merged.merge(df_sorted[["ts_code"]], on="ts_code")

            for g in range(n_groups):
                start = g * group_size
                end = (g + 1) * group_size if g < n_groups - 1 else n
                group_ret = merged.iloc[start:end]["ret"].mean()
                returns.append(float(group_ret) if np.isfinite(group_ret) else 0.0)

            return returns
        except Exception:
            return [0.0] * n_groups

    def _compute_portfolio_return(self, holdings, dt, next_dt, conn) -> float:
        """计算等权组合收益"""
        if not holdings:
            return 0.0
        try:
            close_t0 = pd.read_sql(
                f"SELECT ts_code, close FROM daily_prices "
                f"WHERE trade_date = ? AND ts_code IN ({','.join(['?']*len(holdings))})",
                conn, params=[dt] + holdings
            )
            close_t1 = pd.read_sql(
                f"SELECT ts_code, close FROM daily_prices "
                f"WHERE trade_date = ? AND ts_code IN ({','.join(['?']*len(holdings))})",
                conn, params=[next_dt] + holdings
            )

            merged = close_t0.merge(close_t1, on="ts_code", suffixes=("_0", "_1"))
            merged["ret"] = (merged["close_1"] - merged["close_0"]) / merged["close_0"]
            return float(merged["ret"].mean()) if not merged.empty else 0.0
        except Exception:
            return 0.0

    def _compute_benchmark_return(self, dt, next_dt, conn) -> float:
        """计算基准收益（全市场等权均值作为基准）"""
        try:
            r = pd.read_sql(
                "SELECT ts_code, close FROM daily_prices WHERE trade_date = ?",
                conn, params=[dt]
            )
            r2 = pd.read_sql(
                "SELECT ts_code, close FROM daily_prices WHERE trade_date = ?",
                conn, params=[next_dt]
            )
            if r.empty or r2.empty:
                return 0.0
            merged = r.merge(r2, on="ts_code", suffixes=("_0", "_1"))
            merged["ret"] = (merged["close_1"] - merged["close_0"]) / merged["close_0"]
            return float(merged["ret"].mean())
        except Exception:
            return 0.0

    def _max_drawdown(self, cum_returns: np.ndarray) -> float:
        """计算最大回撤"""
        if len(cum_returns) == 0:
            return 0.0
        peak = np.maximum.accumulate(cum_returns)
        dd = (cum_returns - peak) / peak
        return float(np.min(dd)) if len(dd) > 0 else 0.0

    def _spearman_rho(self, values: List[float]) -> float:
        """计算列表的 Spearman rho（单调性度量）"""
        if len(values) < 3:
            return 0.0
        ranks = pd.Series(values).rank().values
        ideal = np.arange(1, len(values) + 1)
        from scipy.stats import spearmanr
        corr, _ = spearmanr(ranks, ideal)
        return float(corr) if np.isfinite(corr) else 0.0


def compute_fitness(backtest_result: Dict) -> float:
    """
    复合适应度函数（补丁4）

    Fitness = Excess Return / max(MDD, 4%) × min(1.0, ICIR / 0.4)
    """
    er = backtest_result["excess_return_annual"]
    mdd = abs(backtest_result["max_drawdown"])
    icir = backtest_result["ic_ir"]

    mdd_protected = max(mdd, 0.04)
    base = er / mdd_protected if mdd_protected > 0 else 0
    icir_penalty = min(1.0, abs(icir) / 0.4) if icir != 0 else 0

    return base * icir_penalty
