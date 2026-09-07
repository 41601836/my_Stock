# -*- coding: utf-8 -*-
"""
genetic_search.py — 遗传算法因子组合搜索

替代原始随机网格搜索，实现智能进化：
1. 初始种群：从候选池随机生成 N 个因子组合
2. 适应度评估：用回测超额卡玛作为适应度
3. 选择：锦标赛选择（保留精英）
4. 交叉：均匀交叉，混合两个父代的因子
5. 变异：以一定概率替换一个因子
6. 进化：多代迭代，适应度逐代提升
"""
import random
import numpy as np
from typing import List, Tuple, Dict, Optional


class GeneticFactorSearcher:
    """遗传算法因子组合搜索器"""

    def __init__(
        self,
        candidate_factors: List[str],
        population_size: int = 50,
        combo_size_range: Tuple[int, int] = (2, 5),
        crossover_rate: float = 0.7,
        mutation_rate: float = 0.10,
        elite_ratio: float = 0.2,
        max_generations: int = 10,
        seed: int = 42,
    ):
        self.candidate_factors = candidate_factors
        self.pop_size = population_size
        self.combo_min, self.combo_max = combo_size_range
        self.cx_rate = crossover_rate
        self.mut_rate = mutation_rate
        self.elite_n = max(1, int(population_size * elite_ratio))
        self.max_gen = max_generations
        self.rng = random.Random(seed)

        # 类别分类（用于智能初始化）
        self.momentum = [f for f in candidate_factors if "return" in f or "momentum" in f]
        self.risk = [f for f in candidate_factors if "volatility" in f or "drawdown" in f or "atr" in f]
        self.liquidity = [f for f in candidate_factors if "turnover" in f or "amihud" in f or "vol_ratio" in f or "amount" in f]
        self.chip = [f for f in candidate_factors if "chip" in f or "cyq" in f or "profit_ratio" in f]
        self.valuation = [f for f in candidate_factors if f in ["pe_ttm", "pb", "roe"]]
        self.sector = [f for f in candidate_factors if "sector" in f or "industry" in f]
        self.sentiment = [f for f in candidate_factors if "sentiment" in f or "overnight" in f or "intraday" in f]
        self.categories = [c for c in [self.momentum, self.risk, self.liquidity, self.chip,
                                       self.valuation, self.sector, self.sentiment] if c]

    def _random_individual(self) -> List[str]:
        """生成一个因子组合（智能类别拼装）"""
        size = self.rng.randint(self.combo_min, self.combo_max)
        combo = set()
        # 从每个类别中按概率选取
        for cat in self.categories:
            if self.rng.random() > 0.3 and len(combo) < size:
                combo.add(self.rng.choice(cat))
        # 补齐
        while len(combo) < size:
            combo.add(self.rng.choice(self.candidate_factors))
        return sorted(combo)

    def init_population(self) -> List[List[str]]:
        """初始化种群"""
        pop = []
        for _ in range(self.pop_size):
            ind = self._random_individual()
            while ind in pop:
                ind = self._random_individual()
            pop.append(ind)
        return pop

    def _tournament_select(self, population, fitnesses, k=3) -> List[str]:
        """锦标赛选择"""
        indices = self.rng.sample(range(len(population)), min(k, len(population)))
        best_idx = max(indices, key=lambda i: fitnesses[i])
        return population[best_idx][:]

    def _crossover(self, parent1, parent2) -> Tuple[List[str], List[str]]:
        """均匀交叉"""
        if self.rng.random() > self.cx_rate:
            return parent1[:], parent2[:]

        all_factors = sorted(set(parent1) | set(parent2))
        child1, child2 = set(), set()
        for f in all_factors:
            if self.rng.random() < 0.5:
                child1.add(f)
            else:
                child2.add(f)

        # 确保大小在范围内
        for child in [child1, child2]:
            while len(child) < self.combo_min:
                child.add(self.rng.choice(self.candidate_factors))
            while len(child) > self.combo_max:
                child.remove(self.rng.choice(list(child)))

        return sorted(child1), sorted(child2)

    def _mutate(self, individual) -> List[str]:
        """变异：随机替换一个因子"""
        if self.rng.random() > self.mut_rate or len(individual) == 0:
            return individual[:]

        mutated = individual[:]
        idx = self.rng.randint(0, len(mutated) - 1)
        # 选一个不在当前组合中的因子
        candidates = [f for f in self.candidate_factors if f not in mutated]
        if candidates:
            mutated[idx] = self.rng.choice(candidates)
        return sorted(mutated)

    def evolve(
        self,
        evaluate_fn,
        initial_population: Optional[List[List[str]]] = None,
        tested_cache: Optional[Dict] = None,
    ) -> Dict:
        """
        执行遗传进化

        Parameters
        ----------
        evaluate_fn : callable
            输入因子组合，返回适应度（超额卡玛）
        initial_population : list, optional
            初始种群（如传入则使用，否则随机生成）
        tested_cache : dict, optional
            已测试组合的缓存 {tuple(combo): fitness}，避免重复评估

        Returns
        -------
        dict
            包含 best_combo, best_fitness, history, all_evaluated
        """
        if tested_cache is None:
            tested_cache = {}

        population = initial_population or self.init_population()
        history = []
        all_evaluated = dict(tested_cache)
        global_best = None
        global_best_fitness = -999.0

        for gen in range(self.max_gen):
            # 评估适应度
            fitnesses = []
            for ind in population:
                key = tuple(ind)
                if key in all_evaluated:
                    fit = all_evaluated[key]
                else:
                    fit = evaluate_fn(ind)
                    all_evaluated[key] = fit
                fitnesses.append(fit)

            # 记录
            gen_best_idx = np.argmax(fitnesses)
            gen_best = population[gen_best_idx]
            gen_best_fit = fitnesses[gen_best_idx]
            gen_avg = np.mean(fitnesses)

            if gen_best_fit > global_best_fitness:
                global_best_fitness = gen_best_fit
                global_best = gen_best[:]

            history.append({
                "generation": gen + 1,
                "best_fitness": gen_best_fit,
                "avg_fitness": gen_avg,
                "best_combo": gen_best,
                "population_diversity": len(set(tuple(i) for i in population)),
            })

            print(f"   🧬 Gen {gen+1}/{self.max_gen}: best={gen_best_fit:.4f} avg={gen_avg:.4f} diversity={len(set(tuple(i) for i in population))}")

            # 最后一代不需要产生后代
            if gen == self.max_gen - 1:
                break

            # 精英保留
            elite_indices = sorted(range(len(population)), key=lambda i: fitnesses[i], reverse=True)[:self.elite_n]
            new_pop = [population[i][:] for i in elite_indices]

            # 产生后代
            while len(new_pop) < self.pop_size:
                p1 = self._tournament_select(population, fitnesses)
                p2 = self._tournament_select(population, fitnesses)
                c1, c2 = self._crossover(p1, p2)
                c1 = self._mutate(c1)
                c2 = self._mutate(c2)
                new_pop.append(c1)
                if len(new_pop) < self.pop_size:
                    new_pop.append(c2)

            population = new_pop[:self.pop_size]

        return {
            "best_combo": global_best,
            "best_fitness": global_best_fitness,
            "history": history,
            "all_evaluated": all_evaluated,
        }
