# -*- coding: utf-8 -*-
"""
factor_lib.signal_pool
=======================
统一信号池

将多个独立信号源（多因子排名、共振评分、EVO ML等）的信号强度
加权合并为一个统一的综合信号向量，用于选股排序、仓位决策等。

合并方式：
  1. 各信号源独立计算信号分（0~1，值越高越好）
  2. 按权重加权求和
  3. 再次截面排名归一化到 0~1

零侵入原则：
  本模块只读因子库数据，不修改任何现有表结构。
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Any, Callable

from factor_lib.registry import FACTOR_REGISTRY


class SignalPool:
    """统一信号池

    用法：
        pool = SignalPool()
        pool.register_signal('mf202609_rank', weight=0.4)
        pool.register_signal('resonance_score', weight=0.4)
        pool.register_signal('evo_ml_score', weight=0.2)

        result = pool.get_signal_vector(date='20260101')
    """

    def __init__(self):
        self._signals: Dict[str, Dict[str, Any]] = {}

    def register_signal(
        self,
        name: str,
        source: str = "builtin",
        weight: float = 1.0,
        compute_fn: Optional[Callable] = None,
    ) -> None:
        """注册一个信号源

        Parameters
        ----------
        name : str
            信号源名称（唯一标识）。
        source : str
            信号源类型标签（用于调试/展示）。
        weight : float
            合并时的权重。
        compute_fn : callable, optional
            自定义计算函数，签名: fn(date: str) -> Series (index=ts_code, 值=信号分 0~1)
            如果为 None，则使用内置信号源（需 name 匹配内置实现）。
        """
        self._signals[name] = {
            "source": source,
            "weight": weight,
            "compute_fn": compute_fn,
        }

    def unregister_signal(self, name: str) -> None:
        """注销信号源"""
        self._signals.pop(name, None)

    def list_signals(self) -> List[Dict[str, Any]]:
        """列出所有已注册的信号源"""
        return [
            {"name": name, "source": info["source"], "weight": info["weight"]}
            for name, info in self._signals.items()
        ]

    def get_signal_vector(self, date: str) -> pd.Series:
        """获取指定日期的综合信号向量

        Parameters
        ----------
        date : str
            交易日期，格式 YYYYMMDD。

        Returns
        -------
        Series : index=ts_code, 值=综合信号分（0~1，排名百分位）
        """
        if not self._signals:
            raise ValueError("信号池为空，请先注册信号源")

        signal_vectors = {}
        total_weight = 0.0

        for name, info in self._signals.items():
            w = info["weight"]
            if w <= 0:
                continue

            compute_fn = info["compute_fn"]
            if compute_fn is not None:
                vec = compute_fn(date)
            else:
                vec = self._compute_builtin_signal(name, date)

            if vec is None or vec.empty:
                continue

            # 确保是 0~1 的排名分
            vec = vec.rank(pct=True)
            signal_vectors[name] = vec * w
            total_weight += w

        if not signal_vectors:
            return pd.Series(dtype=float)

        # 合并为 DataFrame，按 index 对齐
        df = pd.DataFrame(signal_vectors)
        # 加权求和（缺失的信号源按 0 处理，或者只在有数据的股票上计算）
        combined = df.sum(axis=1) / total_weight if total_weight > 0 else df.sum(axis=1)

        # 再次排名归一化
        result = combined.rank(pct=True)
        return result

    def get_signal_vectors_detail(self, date: str) -> pd.DataFrame:
        """获取各信号源的详细分数（含每路信号 + 综合分）

        Returns
        -------
        DataFrame : index=ts_code，列 = 各信号源名 + combined_score
        """
        if not self._signals:
            raise ValueError("信号池为空")

        cols = {}
        for name, info in self._signals.items():
            compute_fn = info["compute_fn"]
            if compute_fn is not None:
                vec = compute_fn(date)
            else:
                vec = self._compute_builtin_signal(name, date)
            if vec is not None and not vec.empty:
                cols[name] = vec.rank(pct=True)

        if not cols:
            return pd.DataFrame()

        df = pd.DataFrame(cols)

        # 加权综合
        total_w = sum(
            info["weight"] for name, info in self._signals.items()
            if name in cols and info["weight"] > 0
        )
        if total_w > 0:
            weighted = pd.Series(0.0, index=df.index)
            for name, s in cols.items():
                w = self._signals[name]["weight"]
                weighted += s.fillna(0) * w
            df["combined_score"] = (weighted / total_w).rank(pct=True)
        else:
            df["combined_score"] = df.mean(axis=1).rank(pct=True)

        return df

    # ── 内置信号源实现 ────────────────────────

    def _compute_builtin_signal(self, name: str, date: str) -> Optional[pd.Series]:
        """内置信号源计算

        支持的内置信号：
          - 'mf202609_rank'    : 202609 多因子排名分
          - 'resonance_score'  : 四重共振总分
          - 'evo_ml_score'     : EVO ML Rank 分数（暂未实现，返回 None）
        """
        if name == "mf202609_rank":
            return self._signal_mf202609_rank(date)
        elif name == "resonance_score":
            return self._signal_resonance_score(date)
        elif name == "evo_ml_score":
            return self._signal_evo_ml(date)
        else:
            # 尝试作为因子名处理
            return self._signal_from_factor(name, date)

    def _signal_mf202609_rank(self, date: str) -> Optional[pd.Series]:
        """202609 多因子排名分（用 MultiFactorCombiner 计算）"""
        try:
            from factor_lib.loader import FactorDataLoader
            from factor_lib.multi_factor import MultiFactorCombiner

            # 读取 mf202609 配置中的因子列表
            import os
            import yaml
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config", "multi_factor_202609.yaml"
            )
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            factors = [f["name"] for f in cfg.get("factors", [])]

            loader = FactorDataLoader()
            df = loader.load_factor_values(factors, start_date=date, end_date=date)
            if df.empty:
                return None

            factor_metas = {f: FACTOR_REGISTRY[f] for f in factors if f in FACTOR_REGISTRY}
            combiner = MultiFactorCombiner(factor_metas, method="rank_average")
            df["_dummy_ret"] = 0.0
            df = combiner.combine(df, factors, return_col="_dummy_ret",
                                  output_col="_score")

            return df.set_index("ts_code")["_score"]
        except Exception:
            return None

    def _signal_resonance_score(self, date: str) -> Optional[pd.Series]:
        """四重共振总分"""
        try:
            from factor_lib.resonance import ResonanceEngine
            engine = ResonanceEngine()
            df = engine.load_factors_for_resonance(date)
            if df.empty:
                return None
            res = engine.compute_resonance(df)
            return res["resonance_score"]
        except Exception:
            return None

    def _signal_evo_ml(self, date: str) -> Optional[pd.Series]:
        """EVO ML Rank 分数（预留接口，暂未实现）"""
        # TODO: 接入 EVO ML 模型的预测结果
        return None

    def _signal_from_factor(self, factor_name: str, date: str) -> Optional[pd.Series]:
        """将单个因子作为信号源（方向对齐 + 排名归一化）"""
        try:
            meta = FACTOR_REGISTRY.get(factor_name)
            if meta is None:
                return None

            from factor_lib.loader import FactorDataLoader
            loader = FactorDataLoader()
            df = loader.load_factor_values([factor_name], start_date=date, end_date=date)
            if df.empty:
                return None

            s = df.set_index("ts_code")[factor_name] * meta.direction
            return s.rank(pct=True)
        except Exception:
            return None
