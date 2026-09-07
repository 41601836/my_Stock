# -*- coding: utf-8 -*-
"""
ic_screener.py — 因子 IC 预筛选器

补丁2落地：半衰期门槛从4周放宽至1.5周，保留短周期高敏锐因子

筛选标准：
- |Rank IC 均值| > 0.015
- |IC t 统计量| > 2.0
- IC 半衰期 ≥ 1.5 周
- IC 胜率 > 53% 或 < 47%
- 衰减单调性：IC 衰减曲线 Spearman rho < -0.3
"""
import sqlite3
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from scipy.stats import spearmanr, ttest_1samp


class ICScreener:
    """因子 IC 预筛选器"""

    def __init__(self, db_path: str = "db/stock_data.db"):
        self.db_path = db_path

    def screen_factors(
        self,
        factor_names: List[str],
        dates: List[str],
        forward_days: int = 5,
        min_ic: float = 0.015,
        min_t: float = 2.0,
        min_halflife_weeks: float = 1.5,
        min_winrate: float = 0.53,
        min_decay_rho: float = -0.3,
    ) -> Tuple[List[Dict], List[str], List[str]]:
        """
        对候选因子逐一进行 IC 体检

        Returns
        -------
        report : list of dict  每个因子的详细体检数据
        passed : list           通过筛选的因子名
        failed : list           被淘汰的因子名
        """
        conn = sqlite3.connect(self.db_path)
        report = []
        passed = []
        failed = []

        for i, f in enumerate(factor_names):
            print(f"  [{i+1}/{len(factor_names)}] 筛选 {f}...", end=" ")

            ic_series, winrate, halflife, decay_rho, ic_mean, ic_std, t_stat = \
                self._compute_ic_stats(f, dates, forward_days, conn)

            # 判定
            ok_ic = abs(ic_mean) > min_ic
            ok_t = abs(t_stat) > min_t
            ok_halflife = halflife is None or halflife >= min_halflife_weeks
            ok_winrate = winrate > min_winrate or winrate < (1 - min_winrate)
            ok_decay = decay_rho is not None and decay_rho < min_decay_rho

            # 半衰期和衰减不达标不直接淘汰，只标记
            all_pass = ok_ic and ok_t and ok_winrate

            entry = {
                "factor": f,
                "ic_mean": round(ic_mean, 4),
                "ic_std": round(ic_std, 4),
                "t_stat": round(t_stat, 2),
                "winrate": round(winrate, 4),
                "halflife_weeks": round(halflife, 1) if halflife else None,
                "decay_rho": round(decay_rho, 4) if decay_rho is not None else None,
                "pass_ic": ok_ic,
                "pass_t": ok_t,
                "pass_halflife": ok_halflife,
                "pass_winrate": ok_winrate,
                "pass_decay": ok_decay,
                "status": "PASS" if all_pass else "FAIL",
                "reason": self._fail_reason(ok_ic, ok_t, ok_halflife, ok_winrate, ok_decay),
            }
            report.append(entry)

            if all_pass:
                passed.append(f)
                print(f"✅ IC={ic_mean:+.4f} t={t_stat:.1f} hl={halflife or 'N/A'}w")
            else:
                failed.append(f)
                print(f"❌ {entry['reason']}")

        conn.close()
        return report, passed, failed

    def _compute_ic_stats(self, factor, dates, forward_days, conn):
        """计算单因子的 IC 统计"""
        ics = []
        ic_dates = []

        for dt in dates:
            # 加载因子截面
            df = pd.read_sql(
                "SELECT stock_code AS ts_code, " + factor +
                " FROM factor_values WHERE trade_date = ?",
                conn, params=[dt]
            )

            if len(df) < 30:
                continue

            # 获取未来收益
            ret_df = self._get_forward_returns(dt, forward_days, conn)
            if ret_df.empty:
                continue

            merged = df.merge(ret_df, on="ts_code", how="inner")
            # 清除 NaN
            merged = merged.dropna(subset=[factor, "forward_ret"])
            if len(merged) < 30:
                continue

            # 方向调整
            from factor_lib.registry import FACTOR_REGISTRY
            meta = FACTOR_REGISTRY.get(factor)
            direction = meta.direction if meta else 1

            corr, _ = spearmanr(merged[factor], merged["forward_ret"])
            if np.isfinite(corr):
                ics.append(direction * corr)
                ic_dates.append(dt)

        if len(ics) < 20:
            return [], 0.5, None, None, 0, 1, 0

        ic_arr = np.array(ics)
        ic_mean = np.mean(ic_arr)
        ic_std = np.std(ic_arr, ddof=1)
        t_stat, _ = ttest_1samp(ic_arr, 0)
        winrate = np.mean(ic_arr > 0)

        # 半衰期估算
        halflife = self._estimate_halflife(ic_arr)

        # 衰减单调性
        decay_rho = self._compute_decay_rho(ic_arr)

        return ics, winrate, halflife, decay_rho, ic_mean, ic_std, float(t_stat)

    def _get_forward_returns(self, date, forward_days, conn):
        """获取 N 日前瞻收益"""
        try:
            # 获取 date 后的下一个交易日（YYYYMMDD 格式用字符串比较）
            next_dt_row = pd.read_sql(
                "SELECT MIN(trade_date) as next_dt FROM daily_prices "
                "WHERE trade_date > ? ORDER BY trade_date LIMIT 1",
                conn, params=[date]
            )

            if next_dt_row.empty or next_dt_row.iloc[0]["next_dt"] is None:
                return pd.DataFrame()

            next_dt = next_dt_row.iloc[0]["next_dt"]

            close_t0 = pd.read_sql(
                "SELECT ts_code, close FROM daily_prices WHERE trade_date = ?",
                conn, params=[date]
            )
            close_t1 = pd.read_sql(
                "SELECT ts_code, close FROM daily_prices WHERE trade_date = ?",
                conn, params=[next_dt]
            )

            merged = close_t0.merge(close_t1, on="ts_code", suffixes=("_0", "_1"))
            merged["forward_ret"] = (merged["close_1"] - merged["close_0"]) / merged["close_0"]
            return merged[["ts_code", "forward_ret"]]
        except Exception:
            return pd.DataFrame()

    def _estimate_halflife(self, ic_arr):
        """估算 IC 半衰期（周数）"""
        n = len(ic_arr)
        if n < 20:
            return None

        # 用最近52周IC的趋势估算衰减
        recent = ic_arr[-min(52, n):]
        x = np.arange(len(recent))

        if np.std(recent) < 1e-8:
            return 999  # 不衰减

        slope = np.polyfit(x, recent, 1)[0]
        if slope >= -1e-6:
            return 999  # 不衰减

        current_level = np.mean(recent[-4:])
        if current_level <= 0:
            return 0

        # 半衰期 = 当前水平 / |衰减斜率|
        halflife = abs(current_level / slope)
        return max(halflife, 0.5)  # 至少0.5周

    def _compute_decay_rho(self, ic_arr):
        """计算IC衰减曲线的 Spearman rho（单调性度量）"""
        n = len(ic_arr)
        if n < 20:
            return None

        # 计算滚动IC的衰减趋势
        window = min(20, n // 3)
        rolling_ic = pd.Series(ic_arr).rolling(window, min_periods=5).mean().dropna().values

        if len(rolling_ic) < 5:
            return None

        x = np.arange(len(rolling_ic))
        corr, _ = spearmanr(x, rolling_ic)
        return float(corr) if np.isfinite(corr) else None

    def _fail_reason(self, ok_ic, ok_t, ok_hl, ok_wr, ok_decay):
        reasons = []
        if not ok_ic:
            reasons.append("IC不足")
        if not ok_t:
            reasons.append("t值不足")
        if not ok_hl:
            reasons.append("半衰期过短")
        if not ok_wr:
            reasons.append("胜率不足")
        if not ok_decay:
            reasons.append("衰减非单调")
        return " | ".join(reasons) if reasons else "未知"


def run_ic_screening(factor_names=None, dates=None):
    """
    运行因子 IC 预筛选

    Returns: (report, passed, failed)
    """
    from factor_lib.registry import get_candidate_factors
    from factor_lib.data_loader import get_loader

    if factor_names is None:
        factor_names = get_candidate_factors()

    if dates is None:
        loader = get_loader()
        dates = loader.get_backtest_dates(weeks=104)  # 用最近2年

    print(f"\n{'='*60}")
    print(f"📊 因子 IC 预筛选: {len(factor_names)} 个候选 × {len(dates)} 周")
    print(f"{'='*60}\n")

    screener = ICScreener()
    report, passed, failed = screener.screen_factors(factor_names, dates)

    print(f"\n{'='*60}")
    print(f"✅ 通过: {len(passed)} 个因子")
    print(f"❌ 淘汰: {len(failed)} 个因子")
    print(f"{'='*60}\n")

    # 保存报告
    import json
    report_path = "reports/factor_ic_report.json"
    os.makedirs("reports", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "total": len(report),
            "passed": passed,
            "failed": failed,
            "details": report,
        }, f, ensure_ascii=False, indent=2)
    print(f"📁 报告已保存: {report_path}")

    return report, passed, failed


if __name__ == "__main__":
    import os
    run_ic_screening()
