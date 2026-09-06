# -*- coding: utf-8 -*-
"""
sector_factor.py —— 板块强度因子
====================================
基于行业分组的板块强度合成，包含：
- 板块收益（中位数涨跌幅）
- 板块宽度（上涨家数/总家数）
- 板块成交额排名分位

合成方式：加权求和后截面 rank 归一化到 [0, 1]

注意：板块强度因子需要全市场截面数据，不能按单只股票 groupby 计算。
"""

import numpy as np
import pandas as pd


class SectorFactor:
    """板块强度因子计算类"""

    def compute_sector_strength(self, daily_data: pd.DataFrame,
                                stock_info_df: pd.DataFrame) -> pd.Series:
        """
        计算某一交易日的板块强度，并映射回个股层面

        Parameters
        ----------
        daily_data : pd.DataFrame
            某交易日全市场日线 DataFrame，需含 ts_code, close, pct_chg, amount 列
            （如果有 net_inflow 列也会被使用，否则用成交额排名代替）
        stock_info_df : pd.DataFrame
            stock_list 表的 DataFrame，需含 ts_code, industry 列

        Returns
        -------
        pd.Series
            index=ts_code, value=sector_strength（值在 [0, 1] 区间）
        """
        # 合并行业信息
        df = daily_data.merge(
            stock_info_df[["ts_code", "industry"]],
            on="ts_code",
            how="left"
        )

        # 过滤掉无行业分类的股票
        df = df[df["industry"].notna() & (df["industry"] != "")].copy()

        if len(df) == 0:
            return pd.Series(dtype=float)

        # 计算各板块指标
        def _sector_stats(group):
            pct_chg = group["pct_chg"].dropna()
            amount = group["amount"].dropna()
            n_total = len(pct_chg)
            n_up = (pct_chg > 0).sum()
            return pd.Series({
                "sector_return": pct_chg.median() if n_total > 0 else np.nan,
                "sector_breadth": n_up / n_total if n_total > 0 else np.nan,
                "sector_amount": amount.sum() if len(amount) > 0 else np.nan,
                "stock_count": n_total,
            })

        sector_stats = df.groupby("industry", dropna=True).apply(_sector_stats, include_groups=False)
        sector_stats = sector_stats[sector_stats["stock_count"] >= 3].copy()  # 至少3只成分股

        if len(sector_stats) == 0:
            return pd.Series(dtype=float)

        # 板块成交额排名分位（排名/总数，值越大成交额越高）
        sector_stats["sector_amount_rank"] = sector_stats["sector_amount"].rank(pct=True)

        # 三个成分分别做截面 rank 归一化到 [0, 1]
        sector_stats["_r_return"] = sector_stats["sector_return"].rank(pct=True)
        sector_stats["_r_breadth"] = sector_stats["sector_breadth"].rank(pct=True)
        sector_stats["_r_amount_rank"] = sector_stats["sector_amount_rank"]  # 已经是分位数

        # 加权合成板块强度
        sector_stats["sector_strength"] = (
            sector_stats["_r_return"].fillna(0.5) * 0.4
            + sector_stats["_r_breadth"].fillna(0.5) * 0.3
            + sector_stats["_r_amount_rank"].fillna(0.5) * 0.3
        )

        # 将板块强度映射回个股
        strength_map = sector_stats["sector_strength"].to_dict()
        result = df["industry"].map(strength_map)
        result.index = df["ts_code"]
        result.name = "sector_strength"

        return result


def calc_sector_strength_factor(all_stocks_df: pd.DataFrame,
                                stock_info: pd.DataFrame) -> pd.Series:
    """
    对多交易日的全市场数据计算板块强度因子

    Parameters
    ----------
    all_stocks_df : pd.DataFrame
        多交易日全市场日线 DataFrame，需含 ts_code, trade_date, close, pct_chg, amount 列
    stock_info : pd.DataFrame
        stock_list 表的 DataFrame，需含 ts_code, industry 列

    Returns
    -------
    pd.Series
        MultiIndex (trade_date, ts_code) 的板块强度 Series
    """
    sf = SectorFactor()
    all_results = []

    for trade_date, day_df in all_stocks_df.groupby("trade_date", sort=False):
        day_strength = sf.compute_sector_strength(day_df, stock_info)
        if len(day_strength) > 0:
            day_strength = day_strength.to_frame("sector_strength")
            day_strength["trade_date"] = trade_date
            day_strength = day_strength.reset_index().set_index(["trade_date", "ts_code"])
            all_results.append(day_strength)

    if not all_results:
        return pd.Series(dtype=float, name="sector_strength")

    result = pd.concat(all_results)["sector_strength"]
    return result
