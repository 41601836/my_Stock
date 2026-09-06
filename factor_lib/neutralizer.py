# -*- coding: utf-8 -*-
"""
neutralizer.py — 因子中性化引擎
=================================================
截面中性化：剔除市值和行业暴露，得到纯净因子残差。
  - 单日截面 OLS 回归：factor = β0 + β1*ln_size + Σ β_ind*Industry_dummies + ε
  - 残差标准化后即为中性化因子值
  - 批量处理结果写入 factor_values_neutral 表

零侵入：不修改 registry / loader / ic_engine 核心逻辑。
"""

import sqlite3
import numpy as np
import pandas as pd
from typing import List, Optional, Dict

import statsmodels.api as sm

from factor_lib.config import FactorTestConfig
from factor_lib.loader import FactorDataLoader
from factor_lib.registry import FACTOR_REGISTRY


class FactorNeutralizer:
    """
    因子中性化引擎。

    用 OLS 做截面回归，将因子对 ln(流通市值) 和行业虚拟变量回归，
    取残差并标准化，得到剔除了规模和行业暴露的纯净因子值。
    """

    NEUTRAL_TABLE = "factor_values_neutral"

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or FactorTestConfig.db_path()
        self._loader = FactorDataLoader(self._db_path)

    # ═══════════════════════════════════════════
    #  核心: 单日截面中性化
    # ═══════════════════════════════════════════

    def neutralize_cross_section(
        self,
        factor_series: pd.Series,
        size_series: pd.Series,
        industry_series: pd.Series,
    ) -> pd.Series:
        """
        单日截面中性化。

        参数:
            factor_series: 因子值，index=ts_code
            size_series:   流通市值（原始值，内部取对数），index=ts_code
            industry_series: 行业名称，index=ts_code

        返回:
            标准化后的残差 ε，index=ts_code，name=factor_name_neutral
        """
        # 1. 构造 DataFrame，对齐索引
        df = pd.DataFrame({
            "factor": factor_series,
            "size": size_series,
            "industry": industry_series,
        }).dropna()

        if len(df) < 10:
            # 样本太少，无法可靠回归
            return pd.Series(dtype=float, name=f"{factor_series.name}_neutral")

        # 2. 取对数市值
        df["ln_size"] = np.log(df["size"].clip(lower=1e-6))

        # 3. 构造行业虚拟变量（drop_first 防共线）
        try:
            industry_dummies = pd.get_dummies(df["industry"], prefix="ind", drop_first=True)
        except Exception:
            # 如果行业全相同或其他异常，跳过行业中性化
            industry_dummies = pd.DataFrame(index=df.index)

        # 4. 构造自变量矩阵 X = [常数, ln_size, industry_dummies]
        X = pd.DataFrame({"ln_size": df["ln_size"]}, index=df.index)
        if len(industry_dummies.columns) > 0:
            X = pd.concat([X, industry_dummies.astype(float)], axis=1)
        X = sm.add_constant(X, has_constant="add")

        y = df["factor"].astype(float)

        # 5. OLS 回归
        try:
            model = sm.OLS(y, X).fit()
            residuals = model.resid
        except Exception as e:
            print(f"⚠️ [Neutralizer] OLS 回归失败: {e}，返回原始 z-score 作为兜底")
            # 兜底：只做标准化
            residuals = y - y.mean()

        # 6. 残差标准化（z-score）
        std = residuals.std(ddof=1)
        if std > 1e-12:
            residuals = (residuals - residuals.mean()) / std
        else:
            residuals = residuals - residuals.mean()

        residuals.name = f"{factor_series.name}_neutral"
        return residuals

    # ═══════════════════════════════════════════
    #  批量中性化 + 入库
    # ═══════════════════════════════════════════

    def batch_neutralize(
        self,
        factor_names: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        批量中性化：按交易日循环，对每个因子每日做截面中性化，结果入库。

        结果写入 factor_values_neutral 表，字段：ts_code, trade_date, <factor>_neutral, ...

        返回:
            全部中性化结果 DataFrame (long format)
        """
        start_date = start_date or FactorTestConfig.start_date()
        end_date = end_date or FactorTestConfig.end_date()

        # 1. 加载因子值
        print(f"ℹ️ [Neutralizer] 加载因子值: {factor_names} ({start_date} ~ {end_date})")
        factor_df = self._loader.load_factor_values(factor_names, start_date, end_date)

        # 2. 加载市值数据（从 daily_basic 取 circ_mv）
        size_df = self._load_size_data(start_date, end_date)

        # 3. 加载行业数据（从 stock_list 取 industry）
        industry_map = self._load_industry_map()

        # 4. 按交易日循环做中性化
        all_results = []
        trade_dates = sorted(factor_df["trade_date"].unique())
        total = len(trade_dates)
        print(f"ℹ️ [Neutralizer] 开始批量中性化，共 {total} 个交易日")

        for i, td in enumerate(trade_dates):
            if (i + 1) % 20 == 0 or i == 0 or i == total - 1:
                print(f"  进度: {i+1}/{total} ({td})")

            day_factor = factor_df[factor_df["trade_date"] == td].set_index("ts_code")
            day_size = size_df[size_df["trade_date"] == td].set_index("ts_code")["circ_mv"]

            # 对齐行业
            day_industry = pd.Series(
                {code: industry_map.get(code) for code in day_factor.index},
                index=day_factor.index,
                name="industry",
            )

            day_results = pd.DataFrame(index=day_factor.index)
            day_results["trade_date"] = td

            for fn in factor_names:
                if fn not in day_factor.columns:
                    continue
                neut = self.neutralize_cross_section(
                    day_factor[fn],
                    day_size,
                    day_industry,
                )
                day_results[f"{fn}_neutral"] = neut

            day_results = day_results.reset_index().rename(columns={"index": "ts_code"})
            all_results.append(day_results)

        result_df = pd.concat(all_results, ignore_index=True)

        # 5. 写入数据库
        self._write_neutral_table(result_df, factor_names)
        print(f"✅ [Neutralizer] 批量中性化完成，共 {len(result_df)} 行，已写入 {self.NEUTRAL_TABLE}")

        return result_df

    # ═══════════════════════════════════════════
    #  数据加载辅助
    # ═══════════════════════════════════════════

    def _load_size_data(
        self, start_date: str, end_date: Optional[str]
    ) -> pd.DataFrame:
        """
        从 daily_basic 表加载流通市值 circ_mv。
        返回: DataFrame[ts_code, trade_date, circ_mv]
        """
        conn = sqlite3.connect(self._db_path)
        try:
            sql = (
                "SELECT ts_code, trade_date, circ_mv "
                "FROM daily_basic WHERE trade_date >= ?"
            )
            params: list = [start_date]
            if end_date:
                sql += " AND trade_date <= ?"
                params.append(end_date)
            sql += " AND circ_mv IS NOT NULL AND circ_mv > 0"
            df = pd.read_sql(sql, conn, params=params)
        finally:
            conn.close()

        df["trade_date"] = df["trade_date"].astype(str)
        return df

    def _load_industry_map(self) -> Dict[str, str]:
        """
        从 stock_list 表加载股票-行业映射。
        返回: {ts_code: industry_name}
        """
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT ts_code, industry FROM stock_list WHERE industry IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()

        return {code: ind for code, ind in rows}

    # ═══════════════════════════════════════════
    #  数据库写入
    # ═══════════════════════════════════════════

    def _write_neutral_table(self, df: pd.DataFrame, factor_names: List[str]):
        """
        将中性化结果写入 factor_values_neutral 表。
        如果表已存在则先删除再重建（保证结构一致）。
        """
        neutral_cols = [f"{fn}_neutral" for fn in factor_names]
        conn = sqlite3.connect(self._db_path)
        try:
            # 检查表是否存在
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (self.NEUTRAL_TABLE,),
            ).fetchone()

            if exists:
                # 检查表结构是否匹配，不匹配则重建
                existing_cols = [
                    r[1] for r in conn.execute(
                        f"PRAGMA table_info({self.NEUTRAL_TABLE})"
                    ).fetchall()
                ]
                expected = {"ts_code", "trade_date"} | set(neutral_cols)
                if not expected.issubset(set(existing_cols)):
                    print(f"ℹ️ [Neutralizer] 表结构不匹配，重建 {self.NEUTRAL_TABLE}")
                    conn.execute(f"DROP TABLE {self.NEUTRAL_TABLE}")
                    exists = None

            if not exists:
                # 建表
                col_defs = ["ts_code TEXT", "trade_date TEXT"]
                col_defs += [f"{c} REAL" for c in neutral_cols]
                col_defs.append("PRIMARY KEY (ts_code, trade_date)")
                create_sql = f"CREATE TABLE {self.NEUTRAL_TABLE} ({', '.join(col_defs)})"
                conn.execute(create_sql)
                conn.execute(
                    f"CREATE INDEX idx_{self.NEUTRAL_TABLE}_date "
                    f"ON {self.NEUTRAL_TABLE}(trade_date)"
                )

            # 写入数据（INSERT OR REPLACE）
            write_cols = ["ts_code", "trade_date"] + neutral_cols
            placeholders = ", ".join(["?"] * len(write_cols))
            insert_sql = (
                f"INSERT OR REPLACE INTO {self.NEUTRAL_TABLE} "
                f"({', '.join(write_cols)}) VALUES ({placeholders})"
            )

            rows_to_insert = []
            for _, row in df.iterrows():
                vals = [row.get("ts_code"), row.get("trade_date")]
                for c in neutral_cols:
                    v = row.get(c)
                    vals.append(float(v) if pd.notna(v) else None)
                rows_to_insert.append(tuple(vals))

            conn.executemany(insert_sql, rows_to_insert)
            conn.commit()
        finally:
            conn.close()

    # ═══════════════════════════════════════════
    #  读取中性化因子值
    # ═══════════════════════════════════════════

    def load_neutral_factors(
        self,
        factor_names: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        从 factor_values_neutral 表读取中性化因子值 + 后复权收盘价。

        接口风格与 FactorDataLoader.load_factor_values 一致，
        方便 ICEngine 直接使用。
        """
        start_date = start_date or FactorTestConfig.start_date()
        end_date = end_date or FactorTestConfig.end_date()

        neutral_cols = [f"{fn}_neutral" for fn in factor_names]
        cols_sql = ", ".join(neutral_cols)

        conn = sqlite3.connect(self._db_path)
        try:
            sql = (
                f"SELECT f.ts_code, f.trade_date, {cols_sql}, "
                f"p.close AS _close, p.adj_factor AS _adj "
                f"FROM {self.NEUTRAL_TABLE} f "
                f"INNER JOIN daily_prices p "
                f"ON f.ts_code = p.ts_code AND f.trade_date = p.trade_date "
                f"WHERE f.trade_date >= ?"
            )
            params: list = [start_date]
            if end_date:
                sql += " AND f.trade_date <= ?"
                params.append(end_date)
            df = pd.read_sql(sql, conn, params=params)
        finally:
            conn.close()

        df["trade_date"] = df["trade_date"].astype(str)
        df["close_adj"] = df["_close"] * df["_adj"]
        df = df.drop(columns=["_close", "_adj"])

        # ST/次新股过滤（与 loader 保持一致）
        if FactorTestConfig.exclude_st():
            excluded = self._loader._load_excluded_codes()
            if excluded:
                df = df[~df["ts_code"].isin(excluded)]

        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        return df
