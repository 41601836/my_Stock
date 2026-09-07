# -*- coding: utf-8 -*-
"""
data_loader.py — 统一因子数据入口

唯一职责：
1. 从 DB 读取原始因子值
2. 应用 Universe 过滤（ST/次新/低流动性/涨跌停）
3. 提供中性化残差预计算缓存（回测启动时一次性算好，搜索时查表）

所有策略、Agent、回测引擎都通过 load_factors() 获取数据。
"""
import os
import sqlite3
import numpy as np
import pandas as pd
from typing import Dict, List, Optional

DB_PATH = "db/stock_data.db"


class FactorDataLoader:
    """统一因子数据加载器"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._neutral_cache: Dict[str, Dict[str, pd.Series]] = {}
        self._cache_loaded = False
        self._cache_factors: List[str] = []
        self._cache_dates: List[str] = []
        self._universe_cache: Optional[set] = None

    # ──────────── Universe 过滤 ────────────

    def get_universe(self, date: str) -> set:
        """
        获取指定日期的有效股票池

        过滤规则：
        - 剔除 ST / *ST / 退市警示
        - 剔除上市未满 60 交易日
        - 剔除 20 日日均成交额后 10%
        - 剔除当日涨停/跌停（high == low）
        """
        if self._universe_cache is not None:
            return self._universe_cache

        conn = sqlite3.connect(self.db_path)

        # 1. 基础股票列表
        stocks = pd.read_sql(
            "SELECT DISTINCT ts_code FROM daily_prices WHERE trade_date = ?",
            conn, params=[date]
        )["ts_code"].tolist()

        if not stocks:
            conn.close()
            return set()

        placeholders = ",".join(["?"] * len(stocks))

        # 2. 剔除 ST
        st_stocks = pd.read_sql(f"""
            SELECT DISTINCT ts_code FROM stock_info
            WHERE ts_code IN ({placeholders})
              AND (name LIKE '%ST%' OR name LIKE '%*ST%' OR name LIKE '%退%')
        """, conn, params=stocks)["ts_code"].tolist() if os.path.exists(
            "db/stock_data.db"
        ) else []
        st_set = set(st_stocks)

        # 3. 剔除次新股（上市 < 60 交易日）
        # 计算每只股票到目标日期的交易日数
        ipo_counts = pd.read_sql(f"""
            SELECT ts_code, COUNT(*) as cnt
            FROM daily_prices
            WHERE ts_code IN ({placeholders})
              AND trade_date <= ?
            GROUP BY ts_code
        """, conn, params=stocks + [date])

        if not ipo_counts.empty:
            new_stocks = set(ipo_counts[ipo_counts["cnt"] < 60]["ts_code"].tolist())
        else:
            new_stocks = set()

        # 4. 剔除 20 日日均成交额后 10%
        # 取目标日期前 20 天的日均成交额
        amount_df = pd.read_sql(f"""
            SELECT ts_code, AVG(amount) as avg_amount
            FROM daily_prices
            WHERE ts_code IN ({placeholders})
              AND trade_date <= ?
              AND trade_date > date(?, '-30 days')
            GROUP BY ts_code
        """, conn, params=stocks + [date, date])

        if not amount_df.empty and len(amount_df) > 50:
            threshold = amount_df["avg_amount"].quantile(0.10)
            low_liq = set(amount_df[amount_df["avg_amount"] < threshold]["ts_code"].tolist())
        else:
            low_liq = set()

        # 5. 剔除当日涨跌停 (high == low 表示一字板)
        limit_df = pd.read_sql(f"""
            SELECT ts_code
            FROM daily_prices
            WHERE ts_code IN ({placeholders})
              AND trade_date = ?
              AND high = low
        """, conn, params=stocks + [date])
        limit_set = set(limit_df["ts_code"].tolist()) if not limit_df.empty else set()

        conn.close()

        universe = set(stocks) - st_set - new_stocks - low_liq - limit_set
        self._universe_cache = universe
        return universe

    # ──────────── 原始数据加载 ────────────

    def load_raw_factors(
        self,
        date: str,
        factor_names: List[str],
        table: str = "factor_values"
    ) -> pd.DataFrame:
        """加载指定日期的原始因子值"""
        conn = sqlite3.connect(self.db_path)
        cols = ", ".join(factor_names)
        df = pd.read_sql(
            f"SELECT stock_code AS ts_code, {cols} "
            f"FROM {table} WHERE trade_date = ?",
            conn, params=[date]
        )
        conn.close()
        return df

    def load_raw_factors_batch(
        self,
        dates: List[str],
        factor_names: List[str],
        table: str = "factor_values"
    ) -> pd.DataFrame:
        """批量加载多个日期的原始因子值（宽表）"""
        conn = sqlite3.connect(self.db_path)
        placeholders = ",".join(["?"] * len(dates))
        cols = ", ".join(factor_names)
        df = pd.read_sql(
            f"SELECT trade_date, stock_code AS ts_code, {cols} "
            f"FROM {table} WHERE trade_date IN ({placeholders})",
            conn, params=dates
        )
        conn.close()
        return df

    # ──────────── 中性化预计算缓存 ────────────

    def precompute_neutral_cache(
        self,
        dates: List[str],
        factor_names: List[str],
        table: str = "factor_values"
    ) -> None:
        """
        回测启动前一次性计算所有因子在所有截面的中性化残差

        结果存入内存字典: _neutral_cache[factor][date] = pd.Series(ts_code → residual)
        遗传搜索时查表加权，零次 OLS 回归
        """
        print(f"📋 预计算中性化缓存: {len(factor_names)} 因子 × {len(dates)} 截面...")

        from factor_lib.neutralizer import FactorNeutralizer
        neutralizer = FactorNeutralizer()

        # 分批加载（每批 20 个日期，避免内存爆炸）
        batch_size = 20
        total_loaded = 0

        for i in range(0, len(dates), batch_size):
            batch_dates = dates[i:i + batch_size]
            raw_df = self.load_raw_factors_batch(batch_dates, factor_names, table)

            if raw_df.empty:
                continue

            # 逐截面中性化
            for dt in batch_dates:
                day_df = raw_df[raw_df["trade_date"] == dt].copy()
                if len(day_df) < 30:
                    continue

                # 加载 size 和 industry 信息
                day_df = self._add_size_industry(day_df, dt)
                if day_df is None or day_df.empty:
                    continue

                # 逐因子中性化
                try:
                    neutralized = neutralizer.neutralize_cross_section(
                        day_df, factor_names,
                        size_col="ln_free_mv",
                        industry_col="industry"
                    )
                    for f in factor_names:
                        if f in neutralized.columns:
                            if f not in self._neutral_cache:
                                self._neutral_cache[f] = {}
                            self._neutral_cache[f][dt] = neutralized[f].copy()
                except Exception:
                    # 中性化失败，回退原始值
                    for f in factor_names:
                        if f in day_df.columns:
                            if f not in self._neutral_cache:
                                self._neutral_cache[f] = {}
                            self._neutral_cache[f][dt] = day_df[f].copy()

            total_loaded += len(batch_dates)
            if total_loaded % 100 == 0 or total_loaded >= len(dates):
                print(f"   进度: {total_loaded}/{len(dates)} 截面")

        self._cache_loaded = True
        self._cache_factors = factor_names
        self._cache_dates = dates

        mem_mb = sum(
            len(d) * s.memory_usage(deep=True) / 1e6
            for f, dates_d in self._neutral_cache.items()
            for _, s in dates_d.items()
        )
        print(f"✅ 中性化缓存完成: {len(self._neutral_cache)} 因子, ~{mem_mb:.0f}MB")

    def _add_size_industry(self, df: pd.DataFrame, date: str) -> pd.DataFrame:
        """给 DataFrame 添加 ln_free_mv 和 industry 列"""
        conn = sqlite3.connect(self.db_path)
        ts_codes = df["ts_code"].tolist()
        placeholders = ",".join(["?"] * len(ts_codes))

        try:
            info = pd.read_sql(f"""
                SELECT ts_code, circ_mv, industry
                FROM daily_basic
                WHERE ts_code IN ({placeholders}) AND trade_date = ?
            """, conn, params=ts_codes + [date])

            if info.empty:
                # 回退到 stock_info
                info = pd.read_sql(f"""
                    SELECT ts_code, circ_mv, industry
                    FROM stock_info
                    WHERE ts_code IN ({placeholders})
                """, conn, params=ts_codes)

            conn.close()

            if info.empty:
                return df

            merged = df.merge(info[["ts_code", "circ_mv", "industry"]], on="ts_code", how="left")
            merged["ln_free_mv"] = np.log(merged["circ_mv"].clip(lower=1))
            merged["industry"] = merged["industry"].fillna("未知")
            return merged
        except Exception:
            conn.close()
            return df

    # ──────────── 统一查询入口 ────────────

    def get_cross_section(
        self,
        date: str,
        factor_names: List[str],
        level: str = "neutral",
        apply_universe: bool = True
    ) -> pd.DataFrame:
        """
        统一数据入口：获取指定日期的因子截面

        Parameters
        ----------
        date : str          交易日期 YYYYMMDD
        factor_names : list 因子名列表
        level : str         "raw" 原始值 / "neutral" 中性化残差
        apply_universe : bool 是否应用 Universe 过滤
        """
        if level == "neutral" and self._cache_loaded:
            # 从缓存查表
            result = {}
            for f in factor_names:
                if f in self._neutral_cache and date in self._neutral_cache[f]:
                    result[f] = self._neutral_cache[f][date]
                else:
                    # 缓存未命中，实时计算
                    result[f] = self._compute_single_neutral(date, f)
            df = pd.DataFrame(result)
            if not df.empty:
                df.index.name = "ts_code"
                df = df.reset_index()
        else:
            # 实时加载
            meta = {f: "factor_values" for f in factor_names}
            table = list(set(meta.values()))[0] if meta else "factor_values"
            df = self.load_raw_factors(date, factor_names, table)
            if level == "neutral" and not df.empty:
                df = self._add_size_industry(df, date)
                if "ln_free_mv" in df.columns:
                    from factor_lib.neutralizer import FactorNeutralizer
                    neutralizer = FactorNeutralizer()
                    df = neutralizer.neutralize_cross_section(
                        df, factor_names,
                        size_col="ln_free_mv",
                        industry_col="industry"
                    )

        if apply_universe and not df.empty:
            universe = self.get_universe(date)
            if universe:
                df = df[df["ts_code"].isin(universe)]

        return df

    def _compute_single_neutral(self, date: str, factor: str) -> pd.Series:
        """实时计算单个因子的中性化残差（缓存未命中时的回退）"""
        df = self.load_raw_factors(date, [factor])
        if df.empty:
            return pd.Series(dtype=float)
        df = self._add_size_industry(df, date)
        if "ln_free_mv" not in df.columns:
            return df.set_index("ts_code")[factor]
        from factor_lib.neutralizer import FactorNeutralizer
        neutralizer = FactorNeutralizer()
        result = neutralizer.neutralize_cross_section(
            df, [factor], size_col="ln_free_mv", industry_col="industry"
        )
        return result[factor] if factor in result.columns else pd.Series(dtype=float)

    # ──────────── 回测日期列表 ────────────

    def get_backtest_dates(self, weeks: int = 208) -> List[str]:
        """获取回测所需的周频日期列表（每周最后一个交易日）"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql(
            "SELECT DISTINCT trade_date FROM factor_values ORDER BY trade_date",
            conn
        )
        conn.close()

        if df.empty:
            return []

        dates = df["trade_date"].tolist()

        # 按年-周分组，取每组最后一个日期
        weekly_map = {}
        for d in dates:
            dt = pd.Timestamp(d)
            key = f"{dt.year}-{dt.isocalendar()[1]}"
            if key not in weekly_map or d > weekly_map[key]:
                weekly_map[key] = d

        weekly = sorted(weekly_map.values())
        if len(weekly) > weeks:
            weekly = weekly[-weeks:]

        return weekly


# 全局实例
_loader_instance = None


def get_loader() -> FactorDataLoader:
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = FactorDataLoader()
    return _loader_instance


def load_factors(date, factor_names, level="neutral", apply_universe=True):
    """便捷函数"""
    return get_loader().get_cross_section(date, factor_names, level, apply_universe)
