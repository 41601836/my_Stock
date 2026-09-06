# -*- coding: utf-8 -*-
"""
factor_lib.resonance
======================
四重共振策略引擎

四个维度：
  - 筹码 (chip):      cyq_chip_concentration_60d
  - 资金 (capital):   amihud_illiq_20d + volume_skewness_20d
  - 板块 (sector):    sector_strength
  - 情绪 (sentiment): sentiment_composite

共振逻辑：
  1. 每个维度内因子方向对齐 → 截面排名归一化 → 加权求和 → 维度分 (0~1)
  2. 四维按 dimension_weights 加权 → 共振总分 (0~1)
  3. 根据总分 + 高维数量判定共振等级（strong / medium / weak / none）
  4. 按共振等级映射建议仓位区间

同时提供：
  - StockPool:         按流通市值/指数成分的股票池分层
  - SellSignalEngine:  3 条卖出铁律信号检测

零侵入原则：
  本模块只读 factor_values / factor_values_evo / daily_prices / stock_list，
  不修改任何现有表结构，不 import 任何 agent/web 层代码。
"""

import os
import yaml
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple, Any

from factor_lib.registry import FACTOR_REGISTRY
from factor_lib.loader import FactorDataLoader


# ═══════════════════════════════════════════
#  默认配置
# ═══════════════════════════════════════════

_DEFAULT_CONFIG = {
    "dimensions": {
        "chip": {
            "factors": ["cyq_chip_concentration_60d"],
            "weights": [1.0],
        },
        "capital": {
            "factors": ["amihud_illiq_20d", "volume_skewness_20d"],
            "weights": [0.6, 0.4],
        },
        "sector": {
            "factors": ["sector_strength"],
            "weights": [1.0],
        },
        "sentiment": {
            "factors": ["sentiment_composite"],
            "weights": [1.0],
        },
    },
    "dimension_weights": {
        "chip": 0.30,
        "capital": 0.25,
        "sector": 0.25,
        "sentiment": 0.20,
    },
    "resonance_thresholds": {
        "strong": 0.70,
        "medium": 0.50,
        "weak": 0.30,
    },
    "position_mapping": {
        "strong": [0.6, 0.8],
        "medium": [0.3, 0.5],
        "weak": [0.1, 0.2],
        "none": [0.0, 0.05],
    },
}


def _load_config_from_yaml(path: str) -> Dict[str, Any]:
    """从 YAML 文件加载配置，缺失字段用默认值补齐。"""
    if not os.path.exists(path):
        return dict(_DEFAULT_CONFIG)
    with open(path, "r", encoding="utf-8") as f:
        user_cfg = yaml.safe_load(f) or {}
    # 深度合并（简单实现：只合并顶层 key，子结构若用户提供则全量覆盖）
    cfg = {}
    for k, v in _DEFAULT_CONFIG.items():
        cfg[k] = user_cfg.get(k, v)
    return cfg


# ═══════════════════════════════════════════
#  ResonanceEngine — 四重共振评分引擎
# ═══════════════════════════════════════════

class ResonanceEngine:
    """四重共振评分引擎

    Parameters
    ----------
    config : dict or str, optional
        配置字典或 YAML 文件路径。None 时使用内置默认配置。
    """

    DIMENSION_NAMES = ["chip", "capital", "sector", "sentiment"]
    DIMENSION_LABELS = {
        "chip": "筹码",
        "capital": "资金",
        "sector": "板块",
        "sentiment": "情绪",
    }

    def __init__(self, config: Optional[Any] = None):
        if config is None:
            self.config = dict(_DEFAULT_CONFIG)
        elif isinstance(config, str):
            self.config = _load_config_from_yaml(config)
        elif isinstance(config, dict):
            # 用默认配置补齐缺失键
            self.config = dict(_DEFAULT_CONFIG)
            for k, v in config.items():
                self.config[k] = v
        else:
            raise TypeError("config 必须是 dict、str（文件路径）或 None")

        self.dimensions = self.config["dimensions"]
        self.dimension_weights = self.config["dimension_weights"]
        self.thresholds = self.config["resonance_thresholds"]
        self.position_mapping = self.config["position_mapping"]

        # 收集所有需要的因子名（去重、保序）
        self.all_factors: List[str] = []
        for dim in self.DIMENSION_NAMES:
            for f in self.dimensions[dim]["factors"]:
                if f not in self.all_factors:
                    self.all_factors.append(f)

    # ── 方向对齐 ──────────────────────────────

    def _align_direction(self, df: pd.DataFrame) -> pd.DataFrame:
        """对所有因子做方向对齐：乘以 direction，统一为"值越高越好"。"""
        df = df.copy()
        for f in self.all_factors:
            meta = FACTOR_REGISTRY.get(f)
            direction = meta.direction if meta else 1
            if f in df.columns:
                df[f] = df[f] * direction
        return df

    # ── 维度分数计算 ──────────────────────────

    def compute_dimension_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算四维维度分数

        Parameters
        ----------
        df : DataFrame
            单日截面数据，index=ts_code，列为各因子原始值。
            （或含多日 trade_date 列，按 trade_date 分组计算）

        Returns
        -------
        DataFrame : index=ts_code（或 MultiIndex trade_date+ts_code），
                    列 = chip_score, capital_score, sector_score, sentiment_score
        """
        # 方向对齐
        df_aligned = self._align_direction(df)

        # 判断是否是多日面板（有 trade_date 列）
        has_date = "trade_date" in df_aligned.columns
        group_key = ["trade_date"] if has_date else None

        result = pd.DataFrame(index=df_aligned.index)
        if has_date:
            result["trade_date"] = df_aligned["trade_date"]

        for dim in self.DIMENSION_NAMES:
            factors = self.dimensions[dim]["factors"]
            weights = self.dimensions[dim]["weights"]

            # 检查因子列是否存在
            avail_factors = [f for f in factors if f in df_aligned.columns]
            if not avail_factors:
                result[f"{dim}_score"] = np.nan
                continue

            # 调整权重：只保留有数据的因子，重新归一化
            avail_weights = []
            for f, w in zip(factors, weights):
                if f in avail_factors:
                    avail_weights.append(w)
            w_sum = sum(avail_weights)
            if w_sum == 0:
                result[f"{dim}_score"] = np.nan
                continue
            norm_weights = [w / w_sum for w in avail_weights]

            # 截面排名归一化到 [0, 1]
            if has_date:
                ranked = df_aligned.groupby("trade_date")[avail_factors].rank(pct=True)
            else:
                ranked = df_aligned[avail_factors].rank(pct=True)

            # 加权求和
            score = pd.Series(0.0, index=df_aligned.index)
            for f, w in zip(avail_factors, norm_weights):
                score += ranked[f].fillna(0) * w

            result[f"{dim}_score"] = score

        return result

    # ── 共振等级判定 ──────────────────────────

    def _determine_level(self, total_score: float, high_dim_count: int) -> str:
        """根据总分和高维数量判定共振等级"""
        t_strong = self.thresholds.get("strong", 0.7)
        t_medium = self.thresholds.get("medium", 0.5)
        t_weak = self.thresholds.get("weak", 0.3)

        if total_score >= t_strong and high_dim_count >= 3:
            return "strong"
        if total_score >= t_medium and high_dim_count >= 2:
            return "medium"
        if total_score >= t_weak and high_dim_count >= 1:
            return "weak"
        return "none"

    def compute_resonance(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算共振评分 + 等级 + 建议仓位

        Parameters
        ----------
        df : DataFrame
            单日截面（index=ts_code，列=各因子）或多日面板（含 trade_date）。

        Returns
        -------
        DataFrame : 包含四维分数 + resonance_score + resonance_level + position_low/position_high
        """
        dim_scores = self.compute_dimension_scores(df)

        # 总共振分 = Σ dimension_weight × dimension_score
        dim_score_cols = [f"{d}_score" for d in self.DIMENSION_NAMES]
        total_score = pd.Series(0.0, index=dim_scores.index)
        for dim in self.DIMENSION_NAMES:
            w = self.dimension_weights.get(dim, 0)
            total_score += dim_scores[f"{dim}_score"].fillna(0) * w

        result = dim_scores.copy()
        result["resonance_score"] = total_score

        # 高维计数：维度分 >= 0.6 的数量
        high_dim_count = pd.Series(0, index=result.index, dtype=int)
        for dim in self.DIMENSION_NAMES:
            high_dim_count += (result[f"{dim}_score"] >= 0.6).astype(int)

        # 共振等级
        result["resonance_level"] = [
            self._determine_level(float(ts), int(hc))
            for ts, hc in zip(total_score, high_dim_count)
        ]

        # 建议仓位区间
        pos_low = []
        pos_high = []
        for level in result["resonance_level"]:
            rng = self.position_mapping.get(level, [0.0, 0.05])
            pos_low.append(rng[0])
            pos_high.append(rng[1])
        result["position_low"] = pos_low
        result["position_high"] = pos_high

        return result

    # ── 便捷方法 ──────────────────────────────

    def _get_available_factors(self, table: str = "factor_values") -> List[str]:
        """检查因子表中实际存在的列，避免加载不存在的因子报错"""
        import sqlite3
        loader = FactorDataLoader()
        db_path = loader._db_path
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in cursor.fetchall()]
            conn.close()
            return cols
        except Exception:
            return []

    def _compute_sector_strength_online(self, date: str, df: pd.DataFrame) -> pd.Series:
        """实时计算板块强度（当 sector_strength 因子不在表中时用）

        基于当日涨跌幅 + 成交额排名，按行业分组后合成。
        返回 Series: index=ts_code, 值=sector_strength (0~1)
        """
        import sqlite3
        loader = FactorDataLoader()
        db_path = loader._db_path

        try:
            conn = sqlite3.connect(db_path)
            # 读取行业信息
            stock_info = pd.read_sql(
                "SELECT ts_code, industry FROM stock_list WHERE industry IS NOT NULL",
                conn
            )
            conn.close()
        except Exception:
            return pd.Series(np.nan, index=df.index)

        if stock_info.empty or "industry" not in stock_info.columns:
            return pd.Series(np.nan, index=df.index)

        # 合并行业到 df
        df2 = df.join(stock_info.set_index("ts_code")["industry"], how="left")

        # 计算板块指标
        # 1. 板块收益率中位数
        sector_ret = df2.groupby("industry")["close_adj"].pct_change() if "close_adj" in df2.columns else pd.Series(0, index=df2.index)
        # 用 close_adj 的日涨跌幅近似
        if "close_adj" in df2.columns:
            # 单日截面没有 pct_change，用 stock_list 没有价格
            # 直接用成交额排名代替
            pass

        # 简化版：按行业分组，计算组内上涨家数占比（用成交额分位近似）
        # 更精确的做法需要前日收盘价，这里用成交额排名 + 行业数量做近似
        # 实际生产中 sector_strength 应该在 feature_engineering 中预计算

        # 临时方案：每个行业取平均成交额排名作为强度代理
        # 这不是真正的板块强度，但能让维度不为空
        if "vol_ratio" in df2.columns:
            sector_avg_vol = df2.groupby("industry")["vol_ratio"].transform("mean")
            # 排名归一化
            sector_strength = sector_avg_vol.rank(pct=True)
            return sector_strength

        return pd.Series(0.5, index=df.index)  # 默认中性值

    def load_factors_for_resonance(self, date: str) -> pd.DataFrame:
        """用 FactorDataLoader 加载四维所需因子的单日截面

        智能回退：只加载表中实际存在的因子，缺失的因子跳过。
        板块强度如果不在表中，则实时计算（简化版代理）。
        """
        # 1. 检查哪些因子在表中实际存在
        avail_cols = self._get_available_factors("factor_values")
        avail_cols_evo = self._get_available_factors("factor_values_evo")

        # 筛选出有数据的因子
        factors_to_load = [f for f in self.all_factors if f in avail_cols or f in avail_cols_evo]

        if not factors_to_load:
            # 一个因子都没有，返回空
            return pd.DataFrame()

        # 2. 加载可用因子
        loader = FactorDataLoader()
        df = loader.load_factor_values(
            factors_to_load, start_date=date, end_date=date
        )
        if df.empty:
            return df

        # 设索引
        df = df.set_index("ts_code")
        df = df.drop(columns=["trade_date"], errors="ignore")

        # 3. 如果 sector_strength 不在表中，实时计算（简化版）
        if "sector_strength" not in df.columns and "sector_strength" in self.all_factors:
            df["sector_strength"] = self._compute_sector_strength_online(date, df)

        return df

    def run_scan(
        self,
        date: Optional[str] = None,
        top_n: int = 50,
        use_neutral: bool = False,
    ) -> Dict[str, Any]:
        """完整共振扫描流程

        Parameters
        ----------
        date : str, optional
            扫描日期，默认取最新有数据的日期。
        top_n : int
            返回前 N 名。
        use_neutral : bool
            是否先做行业中性化（暂未实现，预留参数）。

        Returns
        -------
        dict : {
            "success": bool,
            "scan_date": str,
            "total_scanned": int,
            "stocks": [...],   # 按 resonance_score 降序的 Top-N
            "level_distribution": {strong: n, medium: n, weak: n, none: n},
        }
        """
        try:
            # 1. 确定扫描日期
            if date is None:
                date = self._resolve_latest_date()
            if not date:
                return {"success": False, "error": "无法确定最新交易日期"}

            # 2. 加载因子数据
            df = self.load_factors_for_resonance(date)
            if df.empty:
                return {"success": False, "error": f"{date} 无因子数据"}

            total_scanned = len(df)

            # 3. 行业中性化（预留，暂未实现）
            if use_neutral:
                # TODO: 调用 FactorNeutralizer 做行业+市值中性化
                pass

            # 4. 计算共振评分
            res = self.compute_resonance(df)

            # 5. 等级分布统计
            level_counts = res["resonance_level"].value_counts().to_dict()
            level_dist = {
                "strong": int(level_counts.get("strong", 0)),
                "medium": int(level_counts.get("medium", 0)),
                "weak": int(level_counts.get("weak", 0)),
                "none": int(level_counts.get("none", 0)),
            }

            # 6. 排序取 Top-N
            res_sorted = res.sort_values("resonance_score", ascending=False).head(top_n)

            # 7. 组装结果
            stocks = []
            for rank, (ts_code, row) in enumerate(res_sorted.iterrows(), start=1):
                stock_item = {
                    "ts_code": ts_code,
                    "rank": rank,
                    "resonance_score": round(float(row["resonance_score"]), 6),
                    "resonance_level": row["resonance_level"],
                    "position_low": round(float(row["position_low"]), 4),
                    "position_high": round(float(row["position_high"]), 4),
                    "dimension_scores": {
                        dim: round(float(row[f"{dim}_score"]), 6)
                        if pd.notna(row[f"{dim}_score"]) else None
                        for dim in self.DIMENSION_NAMES
                    },
                    "dimension_labels": {
                        dim: self.DIMENSION_LABELS[dim]
                        for dim in self.DIMENSION_NAMES
                    },
                }
                stocks.append(stock_item)

            return {
                "success": True,
                "scan_date": date,
                "total_scanned": total_scanned,
                "top_n": top_n,
                "stocks": stocks,
                "level_distribution": level_dist,
                "dimension_weights": self.dimension_weights,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _resolve_latest_date(self) -> str:
        """轻量定位最新全量截面日期"""
        import sqlite3
        from factor_lib.config import FactorTestConfig
        db_path = FactorTestConfig.db_path()

        tables = set()
        for f in self.all_factors:
            meta = FACTOR_REGISTRY.get(f)
            if meta:
                tables.add(meta.table)

        conn = sqlite3.connect(db_path)
        try:
            series = []
            for t in tables:
                df_c = pd.read_sql(
                    f"SELECT trade_date, COUNT(*) AS cnt FROM {t} "
                    f"WHERE trade_date >= strftime('%Y%m%d', date('now', '-120 days')) "
                    f"GROUP BY trade_date",
                    conn,
                )
                if not df_c.empty:
                    series.append(df_c.set_index("trade_date")["cnt"])
            if not series:
                return ""
        finally:
            conn.close()

        if len(series) == 1:
            counts = series[0]
        else:
            counts = pd.concat(series, axis=1).dropna().min(axis=1)
        counts = counts.sort_index()
        max_cnt = counts.max()
        good = counts[counts >= max_cnt * 0.8]
        return str(good.index[-1]) if len(good) else str(counts.index[-1])


# ═══════════════════════════════════════════
#  StockPool — 股票池分层
# ═══════════════════════════════════════════

class StockPool:
    """股票池分层工具

    分层规则（优先用指数成分，没有则用市值分位数近似）：
      - large:  沪深300成分  或 市值前 6%
      - mid:    中证500成分  或 市值 6%~16%
      - small:  中证1000/国证2000 或 市值 16%~36%
      - micro:  其余
    """

    POOL_NAMES = ["large", "mid", "small", "micro", "all"]

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from factor_lib.config import FactorTestConfig
            db_path = FactorTestConfig.db_path()
        self._db_path = db_path

    def get_pool_stocks(self, pool_name: str, date: Optional[str] = None) -> List[str]:
        """返回指定池子的股票代码列表

        Parameters
        ----------
        pool_name : str
            large / mid / small / micro / all
        date : str, optional
            参考日期（用于取最新流通市值），默认最新交易日

        Returns
        -------
        list of str : ts_code 列表
        """
        if pool_name == "all":
            return self._get_all_stocks(date)

        if pool_name not in self.POOL_NAMES:
            raise ValueError(f"未知池子: {pool_name}，可选: {self.POOL_NAMES}")

        # 优先尝试从指数成分表读取（如果有 index_components 表）
        index_stocks = self._try_index_components(pool_name, date)
        if index_stocks:
            return index_stocks

        # 兜底：用流通市值分位数近似
        return self._pool_by_market_cap(pool_name, date)

    def _get_all_stocks(self, date: Optional[str]) -> List[str]:
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        try:
            if date:
                row = conn.execute(
                    "SELECT DISTINCT ts_code FROM daily_prices WHERE trade_date = ?",
                    [date]
                ).fetchall()
            else:
                row = conn.execute(
                    "SELECT DISTINCT ts_code FROM stock_list"
                ).fetchall()
            return [r[0] for r in row]
        finally:
            conn.close()

    def _try_index_components(self, pool_name: str, date: Optional[str]) -> List[str]:
        """尝试从指数成分表获取，失败返回空列表"""
        import sqlite3
        index_map = {
            "large": ["000300.SH", "000300"],   # 沪深300
            "mid":   ["000905.SH", "000905"],   # 中证500
            "small": ["000852.SH", "000852", "399303.SZ", "399303"],  # 中证1000 / 国证2000
        }
        codes = index_map.get(pool_name, [])
        if not codes:
            return []

        conn = sqlite3.connect(self._db_path)
        try:
            # 检查表是否存在
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='index_components'"
            ).fetchone()
            if not tbl:
                return []

            placeholders = ",".join(["?"] * len(codes))
            if date:
                rows = conn.execute(
                    f"SELECT DISTINST ts_code FROM index_components "
                    f"WHERE index_code IN ({placeholders}) AND trade_date = ?",
                    codes + [date]
                ).fetchall()
            else:
                # 取最新一个调整日
                latest = conn.execute(
                    f"SELECT MAX(trade_date) FROM index_components WHERE index_code IN ({placeholders})",
                    codes
                ).fetchone()
                if not latest or not latest[0]:
                    return []
                rows = conn.execute(
                    f"SELECT DISTINCT ts_code FROM index_components "
                    f"WHERE index_code IN ({placeholders}) AND trade_date = ?",
                    codes + [latest[0]]
                ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []
        finally:
            conn.close()

    def _pool_by_market_cap(self, pool_name: str, date: Optional[str]) -> List[str]:
        """用流通市值分位数近似分层

        分位数规则：
          large: top 6%
          mid:   6% ~ 16%
          small: 16% ~ 36%
          micro: 其余
        """
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        try:
            # 获取最新交易日的流通市值
            if not date:
                row = conn.execute(
                    "SELECT MAX(trade_date) FROM daily_basic WHERE circ_mv IS NOT NULL"
                ).fetchone()
                date = row[0] if row and row[0] else ""

            if not date:
                return []

            df = pd.read_sql(
                "SELECT ts_code, circ_mv AS free_mv FROM daily_basic "
                "WHERE trade_date = ? AND circ_mv IS NOT NULL "
                "ORDER BY circ_mv DESC",
                conn, params=[date]
            )
        except Exception:
            # 兜底：用 total_mv 或直接返回空
            try:
                df = pd.read_sql(
                    "SELECT ts_code, total_mv AS free_mv FROM daily_basic "
                    "WHERE trade_date = ? AND total_mv IS NOT NULL "
                    "ORDER BY total_mv DESC",
                    conn, params=[date] if date else ""
                )
            except Exception:
                return []
        finally:
            conn.close()

        if df.empty:
            return []

        n = len(df)
        quantiles = {
            "large": (0, int(n * 0.06)),
            "mid":   (int(n * 0.06), int(n * 0.16)),
            "small": (int(n * 0.16), int(n * 0.36)),
            "micro": (int(n * 0.36), n),
        }
        start, end = quantiles[pool_name]
        return df.iloc[start:end]["ts_code"].tolist()


# ═══════════════════════════════════════════
#  SellSignalEngine — 3 条卖出铁律
# ═══════════════════════════════════════════

class SellSignalEngine:
    """3 条卖出铁律信号引擎

    铁律①：预期兑现 + 情绪高潮 → 分批止盈 (take_profit)
    铁律②：板块弱化 + 资金流出 → 降仓 (reduce_position)
    铁律③：个股破位 + 共振消失 → 清仓 (exit)

    优先级：exit > reduce_position > take_profit
    """

    # 优先级排序（数字越大优先级越高）
    SIGNAL_PRIORITY = {
        "exit": 3,
        "reduce_position": 2,
        "take_profit": 1,
    }

    def __init__(self, resonance_engine: Optional[ResonanceEngine] = None):
        self.resonance = resonance_engine or ResonanceEngine()

    # ── 铁律①：预期兑现 + 情绪高潮 → 分批止盈 ──

    def check_signal_1_expectation_peak(
        self,
        stock_data: pd.DataFrame,
        date: str,
    ) -> Dict[str, Any]:
        """铁律①：预期兑现 + 情绪高潮 → 分批止盈

        触发条件：
          a. sentiment_composite > 0.8（情绪高潮，已做方向对齐后的值越高越好，
             这里用原始值的高分位数来判断，即情绪过热）
          b. surprise_earnings_gap 在过去10天下降（预期兑现/收敛）
          c. 累计涨幅 > 20%（已经涨了不少）

        注意：sentiment_composite 是反向因子（值越高越差），
        所以高分位数 = 情绪高潮。
        """
        try:
            if stock_data.empty or "sentiment_composite" not in stock_data.columns:
                return {"signal": None, "level": None, "reason": "缺少情绪因子数据",
                        "triggered": False}

            df = stock_data.copy()
            if "trade_date" in df.columns:
                df = df.set_index("trade_date")
            df = df.sort_index()

            if date not in df.index:
                return {"signal": None, "level": None, "reason": f"日期 {date} 不在数据中",
                        "triggered": False}

            # a. 情绪高潮：sentiment_composite 在截面高分位（反向因子，值高=情绪热=不好）
            # 用该股票历史分位数近似：高于 80% 分位视为高潮
            sent_vals = df["sentiment_composite"].dropna()
            if len(sent_vals) < 10:
                sent_high = False
            else:
                sent_today = df.loc[date, "sentiment_composite"]
                sent_threshold = sent_vals.quantile(0.8)
                sent_high = bool(pd.notna(sent_today) and sent_today > sent_threshold)

            # b. 预期兑现：surprise_earnings_gap 过去10天下降
            expect_converging = False
            try:
                if "surprise_earnings_gap" in df.columns:
                    # 取过去10个交易日
                    idx_pos = df.index.get_loc(date)
                    start_pos = max(0, idx_pos - 9)
                    recent = df.iloc[start_pos:idx_pos + 1]["surprise_earnings_gap"].dropna()
                    if len(recent) >= 5:
                        # 趋势判断：前半段均值 vs 后半段均值
                        mid = len(recent) // 2
                        early_mean = recent.iloc[:mid].mean()
                        late_mean = recent.iloc[mid:].mean()
                        # surprise_earnings_gap 是反向因子（值高=不好）
                        # 下降 = 缺口收敛 = 预期兑现
                        if early_mean > 0 and late_mean < early_mean * 0.7:
                            expect_converging = True
            except Exception:
                pass

            # c. 累计涨幅 > 20%（过去20日）
            big_gain = False
            try:
                if "close_adj" in df.columns:
                    idx_pos = df.index.get_loc(date)
                    start_pos = max(0, idx_pos - 19)
                    prices = df.iloc[start_pos:idx_pos + 1]["close_adj"].dropna()
                    if len(prices) >= 10:
                        ret = prices.iloc[-1] / prices.iloc[0] - 1
                        big_gain = bool(ret > 0.20)
            except Exception:
                pass

            # 综合判定
            conditions_met = sum([sent_high, expect_converging, big_gain])
            if conditions_met >= 3:
                level = "strong"
                triggered = True
            elif conditions_met == 2:
                level = "medium"
                triggered = True
            elif conditions_met == 1:
                level = "weak"
                triggered = True
            else:
                level = None
                triggered = False

            reason_parts = []
            if sent_high:
                reason_parts.append("情绪高潮")
            if expect_converging:
                reason_parts.append("预期兑现")
            if big_gain:
                reason_parts.append("累计涨幅>20%")

            return {
                "signal": "take_profit" if triggered else None,
                "level": level,
                "triggered": triggered,
                "reason": " + ".join(reason_parts) if reason_parts else "未触发",
                "conditions": {
                    "sentiment_peak": sent_high,
                    "expectation_converging": expect_converging,
                    "big_gain": big_gain,
                },
            }
        except Exception as e:
            return {
                "signal": None, "level": None, "triggered": False,
                "reason": f"检查异常: {e}", "conditions": {},
            }

    # ── 铁律②：板块弱化 + 资金流出 → 降仓 ──

    def check_signal_2_sector_weakening(
        self,
        stock_data: pd.DataFrame,
        date: str,
    ) -> Dict[str, Any]:
        """铁律②：板块弱化 + 资金流出 → 降仓

        触发条件：
          a. sector_strength 连续 3 日下降
          b. amihud_illiq_20d 连续上升（流动性恶化）
          c. volume_skewness_20d < 0（放量下跌为主）
        """
        try:
            if stock_data.empty:
                return {"signal": None, "level": None, "reason": "无数据",
                        "triggered": False}

            df = stock_data.copy()
            if "trade_date" in df.columns:
                df = df.set_index("trade_date")
            df = df.sort_index()

            if date not in df.index:
                return {"signal": None, "level": None, "reason": f"日期 {date} 不在数据中",
                        "triggered": False}

            idx_pos = df.index.get_loc(date)
            if idx_pos < 3:
                return {"signal": None, "level": None,
                        "reason": "历史数据不足3天", "triggered": False,
                        "conditions": {}}

            # a. sector_strength 连续 3 日下降（4个点连续下降3次）
            sector_decreasing = False
            try:
                if "sector_strength" in df.columns:
                    vals = df.iloc[idx_pos - 3:idx_pos + 1]["sector_strength"].dropna()
                    if len(vals) >= 4:
                        sector_decreasing = bool(
                            vals.iloc[0] > vals.iloc[1] > vals.iloc[2] > vals.iloc[3]
                        )
            except Exception:
                pass

            # b. amihud_illiq_20d 连续上升（流动性恶化）
            # 注意：amihud 是反向因子，值上升 = 非流动性上升 = 不好
            illiq_increasing = False
            try:
                if "amihud_illiq_20d" in df.columns:
                    vals = df.iloc[idx_pos - 3:idx_pos + 1]["amihud_illiq_20d"].dropna()
                    if len(vals) >= 4:
                        illiq_increasing = bool(
                            vals.iloc[0] < vals.iloc[1] < vals.iloc[2] < vals.iloc[3]
                        )
            except Exception:
                pass

            # c. volume_skewness_20d < 0（放量下跌为主，左偏 = 跌时放量）
            vol_skew_negative = False
            try:
                if "volume_skewness_20d" in df.columns:
                    skew_val = df.loc[date, "volume_skewness_20d"]
                    vol_skew_negative = bool(pd.notna(skew_val) and skew_val < 0)
            except Exception:
                pass

            # 综合判定
            conditions_met = sum([sector_decreasing, illiq_increasing, vol_skew_negative])
            if conditions_met >= 3:
                level = "strong"
                triggered = True
            elif conditions_met == 2:
                level = "medium"
                triggered = True
            elif conditions_met == 1:
                level = "weak"
                triggered = True
            else:
                level = None
                triggered = False

            reason_parts = []
            if sector_decreasing:
                reason_parts.append("板块强度连续下降")
            if illiq_increasing:
                reason_parts.append("流动性恶化")
            if vol_skew_negative:
                reason_parts.append("放量下跌")

            return {
                "signal": "reduce_position" if triggered else None,
                "level": level,
                "triggered": triggered,
                "reason": " + ".join(reason_parts) if reason_parts else "未触发",
                "conditions": {
                    "sector_decreasing": sector_decreasing,
                    "illiquidity_increasing": illiq_increasing,
                    "volume_skew_negative": vol_skew_negative,
                },
            }
        except Exception as e:
            return {
                "signal": None, "level": None, "triggered": False,
                "reason": f"检查异常: {e}", "conditions": {},
            }

    # ── 铁律③：个股破位 + 共振消失 → 清仓 ──

    def check_signal_3_breakdown(
        self,
        stock_data: pd.DataFrame,
        date: str,
    ) -> Dict[str, Any]:
        """铁律③：个股破位 + 共振消失 → 清仓

        触发条件：
          a. close < MA20（跌破20日均线）
          b. resonance_level == 'none' 或 'weak'
          c. 近5日跌幅 > 8%
        """
        try:
            if stock_data.empty:
                return {"signal": None, "level": None, "reason": "无数据",
                        "triggered": False}

            df = stock_data.copy()
            has_trade_date = "trade_date" in df.columns
            if has_trade_date:
                df = df.set_index("trade_date")
            df = df.sort_index()

            if date not in df.index:
                return {"signal": None, "level": None, "reason": f"日期 {date} 不在数据中",
                        "triggered": False}

            idx_pos = df.index.get_loc(date)

            # a. close < MA20
            below_ma20 = False
            try:
                if "close_adj" in df.columns:
                    start_pos = max(0, idx_pos - 19)
                    ma_series = df.iloc[start_pos:idx_pos + 1]["close_adj"].dropna()
                    if len(ma_series) >= 15:
                        ma20 = ma_series.mean()
                        close_today = df.loc[date, "close_adj"]
                        below_ma20 = bool(pd.notna(close_today) and close_today < ma20)
            except Exception:
                pass

            # b. 共振等级 weak 或 none
            resonance_gone = False
            try:
                # 如果 stock_data 里已经有 resonance_level 直接用
                if "resonance_level" in df.columns:
                    lv = df.loc[date, "resonance_level"]
                    resonance_gone = bool(lv in ("weak", "none"))
                else:
                    # 否则用共振引擎计算（需要截面数据，这里只能粗略判断）
                    # 取该日所有维度分，检查是否都低
                    dim_cols = [f"{d}_score" for d in self.resonance.DIMENSION_NAMES]
                    avail_dims = [c for c in dim_cols if c in df.columns]
                    if len(avail_dims) >= 2:
                        dim_vals = [df.loc[date, c] for c in avail_dims
                                    if pd.notna(df.loc[date, c])]
                        if dim_vals:
                            avg_score = sum(dim_vals) / len(dim_vals)
                            high_count = sum(1 for v in dim_vals if v >= 0.6)
                            resonance_gone = bool(avg_score < 0.5 and high_count < 2)
            except Exception:
                pass

            # c. 近5日跌幅 > 8%
            big_drop = False
            try:
                if "close_adj" in df.columns:
                    start_pos = max(0, idx_pos - 4)
                    prices = df.iloc[start_pos:idx_pos + 1]["close_adj"].dropna()
                    if len(prices) >= 4:
                        ret = prices.iloc[-1] / prices.iloc[0] - 1
                        big_drop = bool(ret < -0.08)
            except Exception:
                pass

            # 综合判定
            conditions_met = sum([below_ma20, resonance_gone, big_drop])
            if conditions_met >= 3:
                level = "strong"
                triggered = True
            elif conditions_met == 2:
                level = "medium"
                triggered = True
            elif conditions_met == 1:
                level = "weak"
                triggered = True
            else:
                level = None
                triggered = False

            reason_parts = []
            if below_ma20:
                reason_parts.append("跌破MA20")
            if resonance_gone:
                reason_parts.append("共振消失")
            if big_drop:
                reason_parts.append("5日跌幅>8%")

            return {
                "signal": "exit" if triggered else None,
                "level": level,
                "triggered": triggered,
                "reason": " + ".join(reason_parts) if reason_parts else "未触发",
                "conditions": {
                    "below_ma20": below_ma20,
                    "resonance_gone": resonance_gone,
                    "big_drop_5d": big_drop,
                },
            }
        except Exception as e:
            return {
                "signal": None, "level": None, "triggered": False,
                "reason": f"检查异常: {e}", "conditions": {},
            }

    # ── 全部信号检查 ──────────────────────────

    def get_all_signals(
        self,
        stock_data: pd.DataFrame,
        date: str,
    ) -> Dict[str, Any]:
        """同时检查 3 个信号，返回所有触发的信号列表（按优先级排序）

        Parameters
        ----------
        stock_data : DataFrame
            单只股票的历史面板数据（含 trade_date 列，或 index=trade_date）。
        date : str
            检查日期。

        Returns
        -------
        dict : {
            "signals": [...],           # 按优先级降序的触发信号
            "top_signal": str or None,  # 最高优先级信号
            "top_level": str or None,   # 最高优先级信号的等级
            "date": str,
            "details": {
                "take_profit": {...},
                "reduce_position": {...},
                "exit": {...},
            }
        }
        """
        s1 = self.check_signal_1_expectation_peak(stock_data, date)
        s2 = self.check_signal_2_sector_weakening(stock_data, date)
        s3 = self.check_signal_3_breakdown(stock_data, date)

        details = {
            "take_profit": s1,
            "reduce_position": s2,
            "exit": s3,
        }

        # 收集触发的信号，按优先级降序
        triggered = []
        for sig_name in ["exit", "reduce_position", "take_profit"]:
            info = details[sig_name]
            if info.get("triggered"):
                triggered.append({
                    "signal": sig_name,
                    "level": info.get("level"),
                    "reason": info.get("reason"),
                    "priority": self.SIGNAL_PRIORITY.get(sig_name, 0),
                })

        top_signal = triggered[0] if triggered else None

        return {
            "date": date,
            "signals": triggered,
            "top_signal": top_signal["signal"] if top_signal else None,
            "top_level": top_signal["level"] if top_signal else None,
            "triggered_count": len(triggered),
            "details": details,
        }
