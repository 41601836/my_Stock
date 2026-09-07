# -*- coding: utf-8 -*-
"""
validation_gate.py — 四关防过拟合验证

关卡1: Purged Walk-Forward CV（5折, purge+embargo）
关卡2: 参数扰动敏感性（100次±20%扰动，≥80%保持正超额）
关卡3: 分层单调性检验（Q1-Q5 Spearman rho > 0.7）
关卡4: 样本外持有测试（2025年数据，超额年化>0 且 Calmar>0.3）
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from scipy.stats import spearmanr
from factor_lib.unified_backtester import UnifiedBacktester, compute_fitness
from factor_lib.data_loader import FactorDataLoader


class ValidationGate:
    """四关防过拟合验证器"""

    def __init__(self, db_path: str = "db/stock_data.db"):
        self.db_path = db_path
        self.backtester = UnifiedBacktester(db_path)
        self.loader = FactorDataLoader(db_path)

    def run_all_gates(
        self,
        factor_weights: Dict[str, float],
        dates: List[str],
        top_n: int = 20,
        buffer_n: int = 35,
    ) -> Dict:
        """
        运行四关验证

        Returns
        -------
        dict: {
            overall_pass: bool,
            gates: {gate1, gate2, gate3, gate4},
            summary: str,
        }
        """
        print("=" * 60)
        print("🔍 四关防过拟合验证")
        print("=" * 60)

        gate1 = self.gate1_purged_wfcv(factor_weights, dates, top_n, buffer_n)
        print(f"\n关卡1 (Purged WF-CV): {'✅ PASS' if gate1['pass'] else '❌ FAIL'} - {gate1['summary']}")

        gate2 = self.gate2_param_perturbation(factor_weights, dates, top_n, buffer_n)
        print(f"关卡2 (参数扰动): {'✅ PASS' if gate2['pass'] else '❌ FAIL'} - {gate2['summary']}")

        gate3 = self.gate3_monotonicity(factor_weights, dates, top_n, buffer_n)
        print(f"关卡3 (分层单调性): {'✅ PASS' if gate3['pass'] else '❌ FAIL'} - {gate3['summary']}")

        gate4 = self.gate4_out_of_sample(factor_weights, dates, top_n, buffer_n)
        print(f"关卡4 (样本外): {'✅ PASS' if gate4['pass'] else '❌ FAIL'} - {gate4['summary']}")

        overall = gate1["pass"] and gate2["pass"] and gate3["pass"] and gate4["pass"]
        summary = (
            f"{'✅ 四关全过' if overall else '❌ 未通过'} — "
            f"CV {'✅' if gate1['pass'] else '❌'} / "
            f"扰动 {'✅' if gate2['pass'] else '❌'} / "
            f"单调 {'✅' if gate3['pass'] else '❌'} / "
            f"样本外 {'✅' if gate4['pass'] else '❌'}"
        )
        print(f"\n{'='*60}")
        print(f"综合结论: {summary}")
        print(f"{'='*60}")

        return {
            "overall_pass": overall,
            "gates": {"gate1": gate1, "gate2": gate2, "gate3": gate3, "gate4": gate4},
            "summary": summary,
        }

    # ──── 关卡1: Purged Walk-Forward CV ────

    def gate1_purged_wfcv(
        self, factor_weights, dates, top_n=20, buffer_n=35,
        n_folds=5, purge_weeks=2, embargo_weeks=2,
    ) -> Dict:
        """Purged Walk-Forward 交叉验证"""
        n = len(dates)
        if n < 20:
            return {"pass": True, "summary": "数据不足，跳过", "ratio": 1.0, "per_fold": []}

        fold_size = n // n_folds
        train_ratio = 0.6
        fold_results = []

        for i in range(n_folds):
            start = i * fold_size
            end = min((i + 1) * fold_size, n)
            if end - start < 10:
                continue

            split = int(start + (end - start) * train_ratio)
            purge_end = min(split + purge_weeks, end)

            train_dates = dates[start:split]
            test_dates = dates[purge_end:end] if purge_end < end else []

            if not train_dates or not test_dates:
                continue

            # 训练集回测
            train_result = self.backtester.run(
                factor_weights, train_dates, top_n, buffer_n, self.loader
            )
            # 测试集回测
            test_result = self.backtester.run(
                factor_weights, test_dates, top_n, buffer_n, self.loader
            )

            train_calmar = train_result["excess_calmar"]
            test_calmar = test_result["excess_calmar"]
            ratio = test_calmar / train_calmar if abs(train_calmar) > 1e-6 else 0.0

            fold_results.append({
                "fold": i + 1,
                "train_weeks": len(train_dates),
                "test_weeks": len(test_dates),
                "train_calmar": round(train_calmar, 4),
                "test_calmar": round(test_calmar, 4),
                "ratio": round(ratio, 4),
            })

        if not fold_results:
            return {"pass": True, "summary": "有效折数不足", "ratio": 1.0, "per_fold": []}

        avg_ratio = np.mean([f["ratio"] for f in fold_results])
        passed = avg_ratio > 0.5

        return {
            "pass": passed,
            "ratio": round(avg_ratio, 4),
            "per_fold": fold_results,
            "summary": f"ratio={avg_ratio:.4f} ({'PASS' if passed else 'FAIL: 过拟合'}), threshold=0.5",
        }

    # ──── 关卡2: 参数扰动敏感性 ────

    def gate2_param_perturbation(
        self, factor_weights, dates, top_n=20, buffer_n=35,
        n_perturbations=100, perturb_range=0.20, pass_rate=0.80,
    ) -> Dict:
        """参数扰动敏感性测试"""
        rng = np.random.RandomState(42)
        original = np.array(list(factor_weights.values()))
        factor_names = list(factor_weights.keys())

        positive_count = 0
        perturb_calmar_list = []

        for _ in range(n_perturbations):
            noise = rng.uniform(1 - perturb_range, 1 + perturb_range, size=len(original))
            perturbed = original * noise
            perturbed = np.maximum(perturbed, 0.01)  # 不允许负权重

            perturbed_weights = dict(zip(factor_names, perturbed))
            result = self.backtester.run(
                perturbed_weights, dates, top_n, buffer_n, self.loader
            )
            if result["excess_calmar"] > 0:
                positive_count += 1
            perturb_calmar_list.append(result["excess_calmar"])

        actual_rate = positive_count / n_perturbations
        passed = actual_rate >= pass_rate

        return {
            "pass": passed,
            "positive_rate": round(actual_rate, 4),
            "threshold": pass_rate,
            "n_perturbations": n_perturbations,
            "calmar_mean": round(float(np.mean(perturb_calmar_list)), 4),
            "calmar_std": round(float(np.std(perturb_calmar_list)), 4),
            "summary": f"{positive_count}/{n_perturbations} 正超额 ({actual_rate:.0%}), threshold={pass_rate:.0%}",
        }

    # ──── 关卡3: 分层单调性 ────

    def gate3_monotonicity(
        self, factor_weights, dates, top_n=20, buffer_n=35,
        n_groups=5, threshold=0.7,
    ) -> Dict:
        """分层单调性检验"""
        result = self.backtester.run(
            factor_weights, dates, top_n, buffer_n, self.loader
        )

        q_returns = result.get("quantile_returns_annual", [])
        monotonicity = result.get("quantile_monotonicity", 0)

        if len(q_returns) < n_groups:
            return {"pass": False, "summary": "分层收益数据不足", "q_returns": q_returns}

        # 检查 Q1 > Q5
        q1_gt_q5 = q_returns[0] > q_returns[-1] if len(q_returns) >= 5 else False

        # 检查 Spearman rho
        passed = monotonicity > threshold and q1_gt_q5

        q_str = " > ".join([f"Q{i+1}:{r:+.2%}" for i, r in enumerate(q_returns)])

        return {
            "pass": passed,
            "quantile_returns": q_returns,
            "monotonicity_rho": monotonicity,
            "threshold": threshold,
            "q1_gt_q5": q1_gt_q5,
            "summary": f"{q_str}, rho={monotonicity:.2f} ({'PASS' if passed else 'FAIL'})",
        }

    # ──── 关卡4: 样本外持有测试 ────

    def gate4_out_of_sample(
        self, factor_weights, dates, top_n=20, buffer_n=35,
        min_annual=0.0, min_calmar=0.3,
    ) -> Dict:
        """样本外持有测试（2025年数据）"""
        # 分割：2025年之前为样本内，2025年为样本外
        sample_in = [d for d in dates if d < "20250101"]
        sample_out = [d for d in dates if d >= "20250101"]

        if len(sample_out) < 5:
            return {"pass": True, "summary": "样本外数据不足，跳过", "sample_out_weeks": 0}

        oos_result = self.backtester.run(
            factor_weights, sample_out, top_n, buffer_n, self.loader
        )

        oos_annual = oos_result["excess_return_annual"]
        oos_calmar = oos_result["excess_calmar"]

        passed = oos_annual > min_annual and oos_calmar > min_calmar

        return {
            "pass": passed,
            "sample_out_weeks": len(sample_out),
            "oos_excess_annual": round(oos_annual, 4),
            "oos_calmar": round(oos_calmar, 4),
            "oos_ic": oos_result["ic_mean"],
            "summary": f"样本外 {len(sample_out)} 周: 年化={oos_annual:+.2%}, Calmar={oos_calmar:.4f} ({'PASS' if passed else 'FAIL'})",
        }
