# -*- coding: utf-8 -*-
"""
alpha_hunter.py — Alpha 搜索引擎

将 IC 筛选 + 中性化预计算 + 遗传搜索 + 统一回测串联成一条流水线。

执行流程：
1. 从 registry 获取候选因子
2. IC 预筛选（半衰期≥1.5周）
3. 预计算中性化残差缓存
4. 遗传搜索（复合适应度，查表回测，毫秒级）
5. 输出最优组合 + 适应度历史
"""
import os
import sys
import json
import time
import numpy as np
from typing import Dict, List, Tuple, Optional

from factor_lib.registry import get_candidate_factors, FACTOR_REGISTRY
from factor_lib.data_loader import FactorDataLoader
from factor_lib.unified_backtester import UnifiedBacktester, compute_fitness
from factor_lib.ic_screener import ICScreener


class AlphaHunter:
    """Alpha 搜索引擎 — 一键运行全流水线"""

    def __init__(self, db_path: str = "db/stock_data.db"):
        self.db_path = db_path
        self.loader = FactorDataLoader(db_path)
        self.backtester = UnifiedBacktester(db_path)
        self.ic_screener = ICScreener(db_path)

        self.dates: List[str] = []
        self.passed_factors: List[str] = []
        self.ic_report: List[Dict] = []
        self.neutral_cache_ready = False

    def run_full_pipeline(
        self,
        weeks: int = 104,
        population_size: int = 50,
        max_generations: int = 10,
        top_n: int = 20,
        buffer_n: int = 35,
    ) -> Dict:
        """
        执行完整 Alpha 搜索流水线

        Returns
        -------
        dict: best_combo, best_fitness, history, ic_report
        """
        t0 = time.time()
        print("=" * 70)
        print("🎯 Alpha 搜索引擎启动")
        print("=" * 70)

        # ── 1. 获取回测日期 ──
        self.dates = self.loader.get_backtest_dates(weeks)
        print(f"\n📅 回测周期: {len(self.dates)} 周 ({self.dates[0]} → {self.dates[-1]})")

        # ── 2. IC 预筛选 ──
        candidates = get_candidate_factors()
        print(f"\n📊 IC 预筛选: {len(candidates)} 个候选因子")
        self.ic_report, self.passed_factors, failed = self.ic_screener.screen_factors(
            candidates, self.dates
        )

        if not self.passed_factors:
            print("⚠️ 无因子通过 IC 筛选！放宽标准重试...")
            self.ic_report, self.passed_factors, failed = self.ic_screener.screen_factors(
                candidates, self.dates, min_ic=0.008, min_t=1.5, min_halflife_weeks=1.0
            )

        if not self.passed_factors:
            print("❌ 仍无因子通过，终止搜索")
            return {"best_combo": None, "best_fitness": -999, "error": "no factors passed IC screening"}

        print(f"\n✅ {len(self.passed_factors)} 因子通过筛选: {self.passed_factors}")

        # ── 3. 预计算中性化残差缓存 ──
        print(f"\n📋 预计算中性化缓存...")
        self.loader.precompute_neutral_cache(self.dates, self.passed_factors)
        self.neutral_cache_ready = True

        # ── 4. 遗传搜索 ──
        print(f"\n🧬 遗传搜索: {population_size} 个体 × {max_generations} 代")
        from agent.genetic_search import GeneticFactorSearcher

        ga = GeneticFactorSearcher(
            candidate_factors=self.passed_factors,
            population_size=population_size,
            max_generations=max_generations,
        )

        # 评估函数（查表回测，毫秒级）
        def evaluate(combo):
            weights = {f: 1.0 / len(combo) for f in combo}  # 等权初始
            result = self.backtester.run(
                factor_weights=weights,
                dates=self.dates,
                top_n=top_n,
                buffer_n=buffer_n,
                data_loader=self.loader,
            )
            fitness = compute_fitness(result)
            return fitness

        result = ga.evolve(evaluate_fn=evaluate)

        elapsed = time.time() - t0
        print(f"\n{'='*70}")
        print(f"🎯 搜索完成! 耗时 {elapsed:.0f}s")
        print(f"   最优组合: {result['best_combo']}")
        print(f"   最优适应度: {result['best_fitness']:.4f}")
        print(f"   评估组合数: {len(result['all_evaluated'])}")
        print(f"{'='*70}")

        # ── 5. 输出 ──
        # 保存搜索结果
        os.makedirs("reports", exist_ok=True)
        output = {
            "best_combo": result["best_combo"],
            "best_fitness": round(result["best_fitness"], 4),
            "history": result["history"],
            "ic_report": self.ic_report,
            "passed_factors": self.passed_factors,
            "elapsed_seconds": round(elapsed),
            "n_weeks": len(self.dates),
            "n_evaluated": len(result["all_evaluated"]),
        }
        with open("reports/alpha_hunt_result.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        print(f"📁 结果已保存: reports/alpha_hunt_result.json")

        return output

    def quick_test_single(self, factor_weights: Dict[str, float]) -> Dict:
        """快速测试单个因子组合"""
        if not self.dates:
            self.dates = self.loader.get_backtest_dates(104)

        result = self.backtester.run(
            factor_weights=factor_weights,
            dates=self.dates,
            data_loader=self.loader if self.neutral_cache_ready else None,
        )
        result["fitness"] = compute_fitness(result)
        return result


if __name__ == "__main__":
    hunter = AlphaHunter()
    result = hunter.run_full_pipeline(weeks=104, population_size=30, max_generations=5)
    print(f"\n最终结果: Fitness={result.get('best_fitness', 'N/A')}")
