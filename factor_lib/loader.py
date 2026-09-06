# -*- coding: utf-8 -*-
"""
loader.py — 统一数据加载器（唯一数据源出口）
=================================================
所有 IC/分层/回测/防过拟合模块通过本类读取数据。
口径与 scripts/factor_ic_analysis.py 和 agent/validator.py 一致：
  - adj_factor 直接取 daily_prices.adj_factor（与现有 IC 脚本一致）
  - close_adj = close * adj_factor
  - future_return_N = close_adj.shift(-N) / close_adj - 1，clip(-0.5, 0.8)
  - ST/次新股过滤与 validator.py 一致
"""

import os
import sys
import sqlite3
import datetime
import pandas as pd
import numpy as np
from typing import List, Optional, Set

from factor_lib.config import FactorTestConfig
from factor_lib.registry import get_factors_by_table, FACTOR_REGISTRY

from config.paths import PATHS, startup_check

startup_check()


class FactorDataLoader:
    """统一数据加载器，所有上层模块的唯一数据出口。"""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or FactorTestConfig.db_path()

    # ═══════════════════════════════════════════
    #  公开接口
    # ═══════════════════════════════════════════

    def load_factor_values(
        self,
        factor_names: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        加载因子值 + 后复权收盘价（用于计算未来收益率）。

        返回: DataFrame[ts_code, trade_date, <factor1>, ..., <factorN>, close_adj]
        自动处理 factor_values.stock_code 和 factor_values_evo.ts_code 的列名差异。
        """
        start_date = start_date or FactorTestConfig.start_date()
        end_date = end_date or FactorTestConfig.end_date()

        classic = []
        evo = []
        for fn in factor_names:
            meta = FACTOR_REGISTRY.get(fn)
            if meta is None:
                raise ValueError(f"未知因子: {fn}，请在 registry 中注册")
            if meta.table == "factor_values":
                classic.append(fn)
            elif meta.table == "factor_values_evo":
                evo.append(fn)

        parts = []
        if classic:
            parts.append(
                self._load_from_table("factor_values", classic, "stock_code", start_date, end_date)
            )
        if evo:
            parts.append(
                self._load_from_table("factor_values_evo", evo, "ts_code", start_date, end_date)
            )

        if len(parts) == 0:
            raise ValueError("无有效因子可加载")
        if len(parts) == 1:
            df = parts[0]
        else:
            df = pd.merge(parts[0], parts[1], on=["ts_code", "trade_date"], how="inner")

        # ST/次新股过滤
        if FactorTestConfig.exclude_st():
            excluded = self._load_excluded_codes()
            if excluded:
                before = len(df)
                df = df[~df["ts_code"].isin(excluded)]
                after = len(df)
                if before > 0:
                    print(f"ℹ️ [Loader] ST/次新股过滤: {before} → {after} 行 (剔除 {before - after})")

        # 按日期排序
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        return df

    def compute_forward_returns(
        self,
        df: pd.DataFrame,
        periods: Optional[List[int]] = None,
    ) -> pd.DataFrame:
        """
        在含 close_adj 的 DataFrame 上计算多周期未来收益率。
        口径与 factor_ic_analysis.py 完全一致:
          future_return_N = close_adj.shift(-N) / close_adj - 1
          clip(-0.5, 0.8)
        """
        if periods is None:
            periods = FactorTestConfig.return_periods()

        clip_lo, clip_hi = FactorTestConfig.clip_return()
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        for n in periods:
            col = f"fwd_ret_{n}d"
            df[col] = (
                df.groupby("ts_code")["close_adj"].shift(-n)
                / df["close_adj"]
                - 1.0
            )
            df[col] = df[col].clip(clip_lo, clip_hi)

        return df

    def load_daily_prices(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """加载日K线数据（ts_code, trade_date, close, adj_factor, vol, pct_chg）。"""
        start_date = start_date or FactorTestConfig.start_date()
        end_date = end_date or FactorTestConfig.end_date()

        conn = sqlite3.connect(self._db_path)
        try:
            sql = (
                "SELECT ts_code, trade_date, open, high, low, close, "
                "pct_chg, vol, adj_factor "
                "FROM daily_prices WHERE trade_date >= ?"
            )
            params: list = [start_date]
            if end_date:
                sql += " AND trade_date <= ?"
                params.append(end_date)
            sql += " ORDER BY ts_code, trade_date"
            df = pd.read_sql(sql, conn, params=params)
        finally:
            conn.close()

        df["trade_date"] = df["trade_date"].astype(str)
        df["close_adj"] = df["close"] * df["adj_factor"]
        return df

    def load_trade_calendar(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[str]:
        """加载交易日历列表（按日期升序）。trade_cal 用 cal_date 列。"""
        start_date = start_date or FactorTestConfig.start_date()
        end_date = end_date or FactorTestConfig.end_date()

        conn = sqlite3.connect(self._db_path)
        try:
            sql = "SELECT DISTINCT cal_date FROM trade_cal WHERE is_open = 1 AND cal_date >= ?"
            params: list = [start_date]
            if end_date:
                sql += " AND cal_date <= ?"
                params.append(end_date)
            sql += " ORDER BY cal_date"
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            # 兜底: 从 daily_prices 构造交易日历
            sql2 = "SELECT DISTINCT trade_date FROM daily_prices WHERE trade_date >= ?"
            params2: list = [start_date]
            if end_date:
                sql2 += " AND trade_date <= ?"
                params2.append(end_date)
            sql2 += " ORDER BY trade_date"
            rows = conn.execute(sql2, params2).fetchall()
        finally:
            conn.close()

        return [r[0] for r in rows]

    def get_weekly_rebalance_dates(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[str]:
        """从交易日历中取每周最后一个交易日（周五或该周最后交易日）。"""
        all_dates = self.load_trade_calendar(start_date, end_date)
        if not all_dates:
            return []

        df = pd.DataFrame({"trade_date": all_dates})
        df["dt"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        df["year"] = df["dt"].dt.year
        df["week"] = df["dt"].dt.isocalendar().week

        weekly = (
            df.sort_values("trade_date")
            .groupby(["year", "week"])
            .last()["trade_date"]
            .tolist()
        )
        return weekly

    # ═══════════════════════════════════════════
    #  内部方法
    # ═══════════════════════════════════════════

    def _load_from_table(
        self,
        table: str,
        factor_cols: List[str],
        code_col: str,
        start_date: str,
        end_date: Optional[str],
    ) -> pd.DataFrame:
        """
        从指定因子表加载因子值 + 后复权收盘价。
        code_col: 该表中股票代码列名（factor_values='stock_code', evo='ts_code'）
        统一输出列名为 ts_code。
        """
        cols_sql = ", ".join(factor_cols)
        sql = (
            f"SELECT f.{code_col} AS ts_code, f.trade_date, {cols_sql}, "
            f"p.close AS _close, p.adj_factor AS _adj "
            f"FROM {table} f "
            f"INNER JOIN daily_prices p "
            f"ON f.{code_col} = p.ts_code AND f.trade_date = p.trade_date "
            f"WHERE f.trade_date >= ?"
        )
        params: list = [start_date]
        if end_date:
            sql += " AND f.trade_date <= ?"
            params.append(end_date)

        conn = sqlite3.connect(self._db_path)
        try:
            df = pd.read_sql(sql, conn, params=params)
        finally:
            conn.close()

        df["trade_date"] = df["trade_date"].astype(str)
        df["close_adj"] = df["_close"] * df["_adj"]
        df = df.drop(columns=["_close", "_adj"])

        # 极端值过滤：因子值 inf → NaN
        for col in factor_cols:
            if col in df.columns:
                df[col] = df[col].replace([np.inf, -np.inf], np.nan)

        return df

    def _load_excluded_codes(self) -> Set[str]:
        """
        加载 ST/退市/次新股过滤名单。
        口径与 agent/validator.py 一致:
          - name LIKE '%ST%'
          - list_date >= (today - exclude_new_stock_days)
        """
        days = FactorTestConfig.exclude_new_stock_days()
        cutoff = (
            datetime.datetime.now() - datetime.timedelta(days=days)
        ).strftime("%Y%m%d")

        conn = sqlite3.connect(self._db_path)
        try:
            sql = (
                "SELECT ts_code FROM stock_list "
                "WHERE name LIKE '%ST%' OR list_date >= ?"
            )
            rows = conn.execute(sql, [cutoff]).fetchall()
        except Exception as e:
            print(f"⚠️ [Loader] 读取过滤名单失败: {e}")
            return set()
        finally:
            conn.close()

        return {r[0] for r in rows}
