# -*- coding: utf-8 -*-
"""
ic_engine.py — IC 计算引擎
=================================================
全向量化截面 IC 计算，覆盖:
  - Rank IC (Spearman) / Normal IC (Pearson)
  - IC 均值 / ICIR / t 检验 / p 值 / 正负比例
  - IC 衰减曲线 (多周期)
  - IC 累积曲线
  - 分年度 IC 稳定性

口径与 scripts/factor_ic_analysis.py 一致:
  - 每日截面 Spearman 相关 = 因子排名 vs 收益排名的 Pearson 相关
  - 最小截面样本数过滤 (默认 30)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from scipy import stats as sps

from factor_lib.config import FactorTestConfig


class ICEngine:

    def __init__(self, min_cross_section_size: int = None):
        self.min_cs = min_cross_section_size or FactorTestConfig.min_cross_section_size()

    # ═══════════════════════════════════════════
    #  核心: 每日截面 IC 序列
    # ═══════════════════════════════════════════

    def compute_ic_series(
        self,
        df: pd.DataFrame,
        factor_name: str,
        ic_type: str = "rank",
        return_col: str = "fwd_ret_5d",
        use_neutral: bool = False,
    ) -> pd.Series:
        """
        计算每日截面 IC 序列（全向量化）。

        ic_type: "rank" = Spearman, "normal" = Pearson
        use_neutral: True 时使用 {factor_name}_neutral 列（中性化后的因子值）
        返回: pd.Series, index=trade_date, name="ic_{type}"
        """
        f_col = f"{factor_name}_neutral" if use_neutral else factor_name
        r_col = return_col

        # 1. 丢弃因子或收益为 NaN 的行
        mask = df[f_col].notna() & df[r_col].notna()
        df_valid = df[mask].copy()

        if len(df_valid) == 0:
            return pd.Series(dtype=float, name=f"ic_{ic_type}")

        # 2. 过滤截面样本数太少的日期
        date_counts = df_valid.groupby("trade_date").size()
        valid_dates = date_counts[date_counts >= self.min_cs].index
        df_valid = df_valid[df_valid["trade_date"].isin(valid_dates)]

        if len(df_valid) == 0:
            return pd.Series(dtype=float, name=f"ic_{ic_type}")

        # 3. 如果是 rank IC, 先排名 (等价于 Spearman)
        if ic_type == "rank":
            df_valid["_f"] = df_valid.groupby("trade_date")[f_col].rank()
            df_valid["_r"] = df_valid.groupby("trade_date")[r_col].rank()
        else:
            df_valid["_f"] = df_valid[f_col]
            df_valid["_r"] = df_valid[r_col]

        # 4. 截面去中心化 (减去当日均值)
        df_valid["_f_c"] = df_valid["_f"] - df_valid.groupby("trade_date")["_f"].transform("mean")
        df_valid["_r_c"] = df_valid["_r"] - df_valid.groupby("trade_date")["_r"].transform("mean")

        # 5. 叉积和平方和
        df_valid["_cross"] = df_valid["_f_c"] * df_valid["_r_c"]
        df_valid["_f_sq"] = df_valid["_f_c"] ** 2
        df_valid["_r_sq"] = df_valid["_r_c"] ** 2

        agg = df_valid.groupby("trade_date")[["_cross", "_f_sq", "_r_sq"]].sum()

        # 6. Pearson 相关 = cross / sqrt(f_sq * r_sq)
        denom = np.sqrt(agg["_f_sq"] * agg["_r_sq"])
        ic_series = np.where(denom > 1e-12, agg["_cross"] / denom, np.nan)
        ic_series = pd.Series(ic_series, index=agg.index, name=f"ic_{ic_type}")
        ic_series = ic_series.dropna()

        return ic_series

    # ═══════════════════════════════════════════
    #  IC 统计摘要
    # ═══════════════════════════════════════════

    def compute_ic_summary(self, ic_series: pd.Series) -> Dict:
        """
        IC 统计摘要: 均值、标准差、ICIR、t值、p值、正比例、胜率。

        胜率定义: IC > 0 的天数占比 (对正向因子)。
        """
        ic = ic_series.dropna()
        n = len(ic)
        if n == 0:
            return self._empty_summary()

        mean_ic = ic.mean()
        std_ic = ic.std(ddof=1) if n > 1 else 0.0
        icir = mean_ic / std_ic if std_ic > 1e-12 else 0.0

        # t 检验: H0: IC 均值 = 0
        if std_ic > 1e-12 and n > 1:
            t_stat = mean_ic / (std_ic / np.sqrt(n))
            p_value = 2 * sps.t.sf(np.abs(t_stat), df=n - 1)
        else:
            t_stat = 0.0
            p_value = 1.0

        positive_ratio = (ic > 0).sum() / n if n > 0 else 0.0
        win_rate = positive_ratio  # 对正向因子, IC>0 即"有效"

        return {
            "n_days": n,
            "ic_mean": mean_ic,
            "ic_std": std_ic,
            "icir": icir,
            "t_stat": t_stat,
            "p_value": p_value,
            "positive_ratio": positive_ratio,
            "win_rate": win_rate,
            "ic_max": ic.max(),
            "ic_min": ic.min(),
        }

    # ═══════════════════════════════════════════
    #  IC 衰减曲线
    # ═══════════════════════════════════════════

    def compute_ic_decay(
        self,
        df: pd.DataFrame,
        factor_name: str,
        periods: Optional[List[int]] = None,
        ic_type: str = "rank",
        use_neutral: bool = False,
    ) -> pd.DataFrame:
        """
        多周期 IC 衰减分析。
        需要 df 已含 fwd_ret_{N}d 列 (由 loader.compute_forward_returns 生成)。
        """
        if periods is None:
            periods = FactorTestConfig.return_periods()

        rows = []
        for n in periods:
            col = f"fwd_ret_{n}d"
            if col not in df.columns:
                continue
            ic = self.compute_ic_series(df, factor_name, ic_type, col, use_neutral)
            s = self.compute_ic_summary(ic)
            rows.append({"period": n, **s})

        return pd.DataFrame(rows)

    # ═══════════════════════════════════════════
    #  IC 累积曲线
    # ═══════════════════════════════════════════

    def compute_ic_cumulative(self, ic_series: pd.Series) -> pd.Series:
        """IC 累积求和曲线。"""
        return ic_series.dropna().cumsum()

    # ═══════════════════════════════════════════
    #  分年度 IC 稳定性
    # ═══════════════════════════════════════════

    def compute_yearly_stability(self, ic_series: pd.Series) -> pd.DataFrame:
        """
        分年度 IC 统计: 每年的均值/标准差/ICIR/正比例/t值。
        """
        ic = ic_series.dropna()
        if len(ic) == 0:
            return pd.DataFrame()

        # trade_date 格式 YYYYMMDD → 取前4位作为年份
        years = pd.Series(ic.index, index=ic.index).astype(str).str[:4]

        rows = []
        for yr, grp in ic.groupby(years):
            n = len(grp)
            m = grp.mean()
            s = grp.std(ddof=1) if n > 1 else 0.0
            ir = m / s if s > 1e-12 else 0.0
            t = m / (s / np.sqrt(n)) if s > 1e-12 and n > 1 else 0.0
            p = 2 * sps.t.sf(np.abs(t), df=n - 1) if s > 1e-12 and n > 1 else 1.0
            pos = (grp > 0).sum() / n if n > 0 else 0.0
            rows.append({
                "year": yr,
                "n_days": n,
                "ic_mean": m,
                "ic_std": s,
                "icir": ir,
                "t_stat": t,
                "p_value": p,
                "positive_ratio": pos,
            })

        return pd.DataFrame(rows)

    # ═══════════════════════════════════════════
    #  纯净 IC 对比分析（P1 新增）
    # ═══════════════════════════════════════════

    def compute_ic_comparison(
        self,
        factor_names: List[str],
        periods: Optional[List[int]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        ic_type: str = "rank",
        db_path: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        同时计算原始 IC 和纯净 IC（中性化后），返回对比分析表。

        参数:
            factor_names: 因子名列表
            periods: 未来收益周期列表（如 [5, 10, 20]）
            start_date / end_date: 日期范围
            ic_type: "rank" 或 "normal"
            db_path: 数据库路径，默认从 FactorTestConfig 读取

        返回:
            DataFrame，列包括:
              factor, period, raw_ic_mean, raw_icir,
              neutral_ic_mean, neutral_icir,
              ic_change_pct, direction_flip, verdict
            verdict:
              KEEP   - |neutral_icir| >= 0.15 且方向未变
              DROP   - |neutral_icir| < 0.10 或方向翻转
              REVIEW - 中间状态
        """
        # 延迟导入，避免循环引用
        from factor_lib.loader import FactorDataLoader
        from factor_lib.neutralizer import FactorNeutralizer
        from factor_lib.config import FactorTestConfig

        if periods is None:
            periods = [FactorTestConfig.default_period()]

        db_path = db_path or FactorTestConfig.db_path()
        loader = FactorDataLoader(db_path)
        neutralizer = FactorNeutralizer(db_path)

        # 加载原始因子 + 未来收益
        print(f"ℹ️ [IC-Compare] 加载原始因子数据: {factor_names}")
        raw_df = loader.load_factor_values(factor_names, start_date, end_date)
        raw_df = loader.compute_forward_returns(raw_df, periods)

        # 加载中性化因子 + 未来收益
        print(f"ℹ️ [IC-Compare] 加载中性化因子数据")
        try:
            neut_df = neutralizer.load_neutral_factors(factor_names, start_date, end_date)
            neut_df = loader.compute_forward_returns(neut_df, periods)
        except Exception as e:
            print(f"⚠️ [IC-Compare] 加载中性化数据失败: {e}")
            print("  请先运行 FactorNeutralizer.batch_neutralize() 生成中性化数据")
            return pd.DataFrame()

        rows = []
        for fn in factor_names:
            for period in periods:
                ret_col = f"fwd_ret_{period}d"

                # 原始 IC
                raw_ic = self.compute_ic_series(
                    raw_df, fn, ic_type, ret_col, use_neutral=False
                )
                raw_summary = self.compute_ic_summary(raw_ic)

                # 纯净 IC
                neut_ic = self.compute_ic_series(
                    neut_df, fn, ic_type, ret_col, use_neutral=True
                )
                neut_summary = self.compute_ic_summary(neut_ic)

                raw_ic_mean = raw_summary["ic_mean"]
                raw_icir = raw_summary["icir"]
                neut_ic_mean = neut_summary["ic_mean"]
                neut_icir = neut_summary["icir"]

                # IC 变化率（按 IC 均值的相对变化）
                if abs(raw_ic_mean) > 1e-8:
                    ic_change_pct = (neut_ic_mean - raw_ic_mean) / abs(raw_ic_mean) * 100
                else:
                    ic_change_pct = float("inf") if neut_ic_mean != 0 else 0.0

                # 方向翻转判定
                direction_flip = (raw_ic_mean * neut_ic_mean) < 0

                # 综合判定
                if direction_flip or abs(neut_icir) < 0.10:
                    verdict = "DROP"
                elif abs(neut_icir) >= 0.15 and not direction_flip:
                    verdict = "KEEP"
                else:
                    verdict = "REVIEW"

                rows.append({
                    "factor": fn,
                    "period": period,
                    "raw_ic_mean": raw_ic_mean,
                    "raw_icir": raw_icir,
                    "neutral_ic_mean": neut_ic_mean,
                    "neutral_icir": neut_icir,
                    "ic_change_pct": ic_change_pct,
                    "direction_flip": direction_flip,
                    "verdict": verdict,
                })

        return pd.DataFrame(rows)

    # ═══════════════════════════════════════════
    #  辅助
    # ═══════════════════════════════════════════

    def compute_both_ic(
        self,
        df: pd.DataFrame,
        factor_name: str,
        return_col: str = "fwd_ret_5d",
    ) -> Dict[str, pd.Series]:
        """同时计算 Rank IC 和 Normal IC。"""
        return {
            "rank": self.compute_ic_series(df, factor_name, "rank", return_col),
            "normal": self.compute_ic_series(df, factor_name, "normal", return_col),
        }

    def compute_full_report(
        self,
        df: pd.DataFrame,
        factor_name: str,
        return_col: str = "fwd_ret_5d",
        periods: Optional[List[int]] = None,
    ) -> Dict:
        """
        一次性计算全部 IC 指标，供报告模块调用。
        """
        ic_rank = self.compute_ic_series(df, factor_name, "rank", return_col)
        ic_normal = self.compute_ic_series(df, factor_name, "normal", return_col)

        return {
            "factor": factor_name,
            "rank_ic_series": ic_rank,
            "normal_ic_series": ic_normal,
            "rank_ic_summary": self.compute_ic_summary(ic_rank),
            "normal_ic_summary": self.compute_ic_summary(ic_normal),
            "ic_decay": self.compute_ic_decay(df, factor_name, periods),
            "ic_cumulative": self.compute_ic_cumulative(ic_rank),
            "yearly_stability": self.compute_yearly_stability(ic_rank),
        }

    def _empty_summary(self) -> Dict:
        return {
            "n_days": 0,
            "ic_mean": 0.0,
            "ic_std": 0.0,
            "icir": 0.0,
            "t_stat": 0.0,
            "p_value": 1.0,
            "positive_ratio": 0.0,
            "win_rate": 0.0,
            "ic_max": 0.0,
            "ic_min": 0.0,
        }


def check_direction_consistency(meta, ic_summary: Dict, icir_min: float = None) -> Dict:
    """
    方向元数据 vs 实测 IC 符号一致性审计（P0-1 自动告警）。

    effective_ic = ic_mean * direction —— 按 registry 注册方向做多时的实际 IC 符号。
      severity:
        "mismatch": effective_ic < 0 且 |ICIR| ≥ icir_min（统计显著的反向，方向疑似做反）
        "suspect" : effective_ic < 0 但证据偏弱（|ICIR| 不足）
        "ok"      : 方向与实测一致，或样本不足
    """
    if icir_min is None:
        icir_min = FactorTestConfig.icir_min()

    n = ic_summary.get("n_days", 0) or 0
    ic_mean = ic_summary.get("ic_mean", 0.0) or 0.0
    icir = ic_summary.get("icir", 0.0) or 0.0
    direction = meta.direction if meta is not None else 1
    eff = ic_mean * direction

    if n < 50:
        return {"severity": "ok", "effective_ic": eff,
                "message": f"IC 样本不足（{n} 天），跳过方向校验"}
    if eff >= 0:
        return {"severity": "ok", "effective_ic": eff, "icir": icir,
                "message": f"方向与实测一致（effective IC={eff:+.4f}, ICIR={icir:+.2f}）"}
    if abs(icir) >= icir_min:
        return {"severity": "mismatch", "effective_ic": eff, "icir": icir,
                "message": (
                    f"⚠️ 方向疑似做反：实测 RankIC={ic_mean:+.4f} 与注册方向"
                    f"（{'正向/值大越好' if direction > 0 else '反向/值小越好'}）符号相反，"
                    f"且 |ICIR|={abs(icir):.2f} ≥ 阈值 {icir_min}。"
                    f"请核查 registry.direction——若全样本与近期窗口同向为负，应翻转方向元数据。")}
    return {"severity": "suspect", "effective_ic": eff, "icir": icir,
            "message": (f"实测 IC 符号与注册方向相反但证据偏弱"
                        f"（RankIC={ic_mean:+.4f}, |ICIR|={abs(icir):.2f} < {icir_min}），持续观察")}
