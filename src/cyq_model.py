# -*- coding: utf-8 -*-
"""
cyq_model.py —— CYQ 筹码分布模型
====================================
基于换手率衰减的筹码分布直方图估算，输出：
- 浮盈比例 (profit_ratio)
- 上方抛压 (upper_pressure)
- 筹码峰价格 (chip_peak_price)
- 筹码集中度 (chip_concentration_cyq)
- 平均持仓成本 (avg_cost)

性能优化说明：
- 使用 numpy 向量化计算每日筹码扩散
- 支持对单只股票一次性计算窗口内所有交易日的分布（滚动方式）
- 价格格复用：window 内 min/max 固定，避免重复计算
"""

import numpy as np
import pandas as pd


class CYQModel:
    """CYQ 筹码分布模型"""

    def __init__(self, window: int = 60, decay_lambda: float = 0.05, n_bins: int = 50):
        """
        初始化 CYQ 模型

        Parameters
        ----------
        window : int
            计算分布的历史窗口天数，默认 60
        decay_lambda : float
            指数衰减系数，默认 0.05（越远的日子权重越低）
        n_bins : int
            价格格数量，默认 50
        """
        self.window = window
        self.decay_lambda = decay_lambda
        self.n_bins = n_bins

    def compute_distribution(self, df: pd.DataFrame) -> dict:
        """
        计算单只股票最新交易日的筹码分布

        Parameters
        ----------
        df : pd.DataFrame
            日线 DataFrame，需包含 high, low, close, turnover_rate, vol, amount 列
            按时间升序排列，取最后 window 行计算

        Returns
        -------
        dict
            包含 profit_ratio, upper_pressure, chip_peak_price,
            chip_concentration_cyq, avg_cost 的字典
        """
        # 取最近 window 天数据
        win_df = df.tail(self.window).copy()
        n_days = len(win_df)
        if n_days < 5:
            return {
                "profit_ratio": np.nan,
                "upper_pressure": np.nan,
                "chip_peak_price": np.nan,
                "chip_concentration_cyq": np.nan,
                "avg_cost": np.nan,
            }

        # 典型价
        typical_price = (win_df["high"].values + win_df["low"].values + win_df["close"].values) / 3.0

        # 当前价（最后一天收盘价）
        current_price = win_df["close"].iloc[-1]

        # 价格区间
        price_min = win_df["low"].min()
        price_max = win_df["high"].max()
        price_range = price_max - price_min
        if price_range < 1e-8:
            price_range = price_max * 0.01  # 防止除零

        # 价格格
        bin_edges = np.linspace(price_min, price_max, self.n_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
        bin_width = bin_edges[1] - bin_edges[0]

        # 扩散 sigma = 价格区间 / 100
        sigma = price_range / 100.0

        # 指数衰减权重：days_ago 从 0（当日）到 n_days-1（最老）
        days_ago = np.arange(n_days - 1, -1, -1)  # [n_days-1, n_days-2, ..., 0]
        turnover = win_df["turnover_rate"].values
        # 换手率为 0 或 NaN 的保护
        turnover = np.where(np.isfinite(turnover) & (turnover > 0), turnover, 0.0)
        decay_weights = turnover * np.exp(-self.decay_lambda * days_ago)
        total_weight = decay_weights.sum()

        if total_weight < 1e-12:
            return {
                "profit_ratio": np.nan,
                "upper_pressure": np.nan,
                "chip_peak_price": np.nan,
                "chip_concentration_cyq": np.nan,
                "avg_cost": np.nan,
            }

        # 向量化计算所有天的正态分布扩散到价格格
        # typical_price: (n_days,), bin_centers: (n_bins,)
        # 计算每个 (day, bin) 的正态分布概率密度
        diff = typical_price[:, np.newaxis] - bin_centers[np.newaxis, :]  # (n_days, n_bins)
        # 正态分布概率密度（乘以 bin_width 近似概率质量）
        pdf_vals = np.exp(-0.5 * (diff / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi)) * bin_width
        # 按衰减权重加权
        weighted_hist = (pdf_vals * decay_weights[:, np.newaxis]).sum(axis=0)  # (n_bins,)

        # 归一化
        hist_sum = weighted_hist.sum()
        if hist_sum < 1e-12:
            return {
                "profit_ratio": np.nan,
                "upper_pressure": np.nan,
                "chip_peak_price": np.nan,
                "chip_concentration_cyq": np.nan,
                "avg_cost": np.nan,
            }
        distribution = weighted_hist / hist_sum

        # === 计算指标 ===

        # 1. 浮盈比例：当前价以下筹码权重 / 总权重
        below_mask = bin_centers <= current_price
        profit_ratio = distribution[below_mask].sum()

        # 2. 上方抛压：当前价以上筹码权重 / 总权重
        above_mask = bin_centers >= current_price
        upper_pressure = distribution[above_mask].sum()

        # 3. 筹码峰价格：分布众数
        peak_idx = np.argmax(distribution)
        chip_peak_price = bin_centers[peak_idx]

        # 4. 筹码集中度：±10% 价格区间内的筹码占比
        lower_bound = current_price * 0.9
        upper_bound = current_price * 1.1
        conc_mask = (bin_centers >= lower_bound) & (bin_centers <= upper_bound)
        chip_concentration_cyq = distribution[conc_mask].sum()

        # 5. 平均持仓成本
        avg_cost = (distribution * bin_centers).sum()

        return {
            "profit_ratio": float(profit_ratio),
            "upper_pressure": float(upper_pressure),
            "chip_peak_price": float(chip_peak_price),
            "chip_concentration_cyq": float(chip_concentration_cyq),
            "avg_cost": float(avg_cost),
        }

    def compute_rolling(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        滚动计算 DataFrame 中每个交易日的筹码分布指标
        （对单只股票，输出等长 DataFrame）

        Parameters
        ----------
        df : pd.DataFrame
            日线 DataFrame，按时间升序排列

        Returns
        -------
        pd.DataFrame
            包含 cyq_profit_ratio, cyq_upper_pressure, cyq_chip_concentration,
            cyq_avg_cost 列的 DataFrame，索引与输入一致
        """
        n = len(df)
        results = {
            "cyq_profit_ratio": np.full(n, np.nan),
            "cyq_upper_pressure": np.full(n, np.nan),
            "cyq_chip_concentration": np.full(n, np.nan),
            "cyq_avg_cost": np.full(n, np.nan),
        }

        # 从第 window 天开始计算（前面天数不足窗口）
        for i in range(self.window - 1, n):
            start = i - self.window + 1
            win_df = df.iloc[start:i + 1]
            dist = self.compute_distribution(win_df)
            results["cyq_profit_ratio"][i] = dist["profit_ratio"]
            results["cyq_upper_pressure"][i] = dist["upper_pressure"]
            results["cyq_chip_concentration"][i] = dist["chip_concentration_cyq"]
            results["cyq_avg_cost"][i] = dist["avg_cost"]

        return pd.DataFrame(results, index=df.index)


# ═══════════════════════════════════════════════════════════════
#  便捷函数：批量计算多只股票的 CYQ 因子
# ═══════════════════════════════════════════════════════════════

def calc_cyq_factors(df: pd.DataFrame, window: int = 60, decay_lambda: float = 0.05) -> pd.DataFrame:
    """
    对多只股票的日线 DataFrame 计算 CYQ 筹码因子

    Parameters
    ----------
    df : pd.DataFrame
        包含 ts_code（或 stock_code）列的多股票日线 DataFrame
        需含 high, low, close, turnover_rate 列，按 ts_code + trade_date 排序
    window : int
        窗口天数，默认 60
    decay_lambda : float
        衰减系数，默认 0.05

    Returns
    -------
    pd.DataFrame
        新增 4 列：cyq_profit_ratio_60d, cyq_upper_pressure_60d,
        cyq_chip_concentration_60d, cyq_avg_cost_dev_60d
    """
    code_col = "ts_code" if "ts_code" in df.columns else "stock_code"
    model = CYQModel(window=window, decay_lambda=decay_lambda)

    all_results = []
    for code, group in df.groupby(code_col, sort=False):
        group = group.sort_values("trade_date") if "trade_date" in group.columns else group
        res = model.compute_rolling(group)
        res.index = group.index
        all_results.append(res)

    result_df = pd.concat(all_results).sort_index()

    # 计算当前价相对平均成本的偏离
    close_col = "close"
    result_df["cyq_avg_cost_dev_60d"] = (
        (df[close_col] - result_df["cyq_avg_cost"]) / result_df["cyq_avg_cost"]
    )

    # 重命名列，加窗口后缀
    result_df = result_df.rename(columns={
        "cyq_profit_ratio": "cyq_profit_ratio_60d",
        "cyq_upper_pressure": "cyq_upper_pressure_60d",
        "cyq_chip_concentration": "cyq_chip_concentration_60d",
    })

    # 丢弃 avg_cost 中间列（用户只要偏离率）
    result_df = result_df.drop(columns=["cyq_avg_cost"], errors="ignore")

    return result_df
