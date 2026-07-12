# -*- coding: utf-8 -*-
"""
win_rate_hunter.py —— 基于遗传算法的胜率最大化寻优器
"""
import os
import sys
import argparse
import random
import yaml
from datetime import datetime

# 确保能找到项目根目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.paths import PATHS, startup_check
startup_check()

from agent.backtester import run_portfolio_backtest
from agent.validator import compute_historical_ic_series
import tempfile
import copy

def load_default_config():
    with open(PATHS.config.agent, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def generate_individual():
    """基因编码：生成随机个体"""
    return {
        "top_n_stocks": random.randint(5, 50),
        "multiplier": round(random.uniform(0.5, 3.0), 2)
    }

def calculate_fitness(ind, start_date, end_date, df_aligned, factors, weights, base_cfg):
    """回测并计算适应度（胜率）"""
    try:
        # Create temp config
        temp_cfg = copy.deepcopy(base_cfg)
        temp_cfg["backtest"]["top_n_stocks"] = ind["top_n_stocks"]
        temp_cfg["special_boost"]["multiplier"] = ind["multiplier"]
        
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml") as f:
            yaml.dump(temp_cfg, f)
            temp_cfg_path = f.name
            
        metrics, portfolio_equity = run_portfolio_backtest(
            df_aligned=df_aligned,
            selected_factors=factors,
            weights=weights,
            weeks_to_backtest=104, # Simplified
            config_path=temp_cfg_path
        )
        
        os.remove(temp_cfg_path)
        
        if not metrics or metrics.get("weeks", 0) == 0:
            return 0.0, 0.0, 0.0
            
        win_rate = metrics.get("excess_win_rate", 0.0)
        calmar = metrics.get("excess_calmar_ratio", 0.0)
        fitness = win_rate + max(0, calmar) * 0.01 
        
        return fitness, win_rate, calmar
    except Exception as e:
        return 0.0, 0.0, 0.0

def crossover(p1, p2):
    """单点交叉"""
    if random.random() < 0.5:
        return {"top_n_stocks": p1["top_n_stocks"], "multiplier": p2["multiplier"]}
    else:
        return {"top_n_stocks": p2["top_n_stocks"], "multiplier": p1["multiplier"]}

def mutate(ind):
    """突变"""
    if random.random() < 0.2:
        ind["top_n_stocks"] = random.randint(5, 50)
    if random.random() < 0.2:
        ind["multiplier"] = round(random.uniform(0.5, 3.0), 2)
    return ind

def run_evolution(args):
    print(f"🚀 开始胜率猎手 (Win Rate Hunter) 进化寻优...")
    print(f"📅 测试区间: {args.start} -> {args.end}")
    print(f"🧬 种群数量: {args.population} | 进化代数: {args.generations}")
    
    cfg = load_default_config()
    db_path = PATHS.database.stock_data
    factors = cfg["factors"]["custom_new_factors"]
    weights = {f: 1.0 for f in factors}
    
    print(f"📊 正在预加载数据横截面...")
    _, df_aligned = compute_historical_ic_series(db_path, PATHS.data.market_regime_labels_v2, factors)
    print(f"📊 数据预加载完成，样本量: {len(df_aligned)}")
    
    # 1. 初始化种群
    population = [generate_individual() for _ in range(args.population)]
    
    best_overall = None
    best_fitness = -1
    
    for gen in range(1, args.generations + 1):
        print(f"\n" + "="*50)
        print(f"🔄 Generation {gen} / {args.generations}")
        
        # 2. 评估适应度
        scored_population = []
        for i, ind in enumerate(population):
            fit, wr, calmar = calculate_fitness(ind, args.start, args.end, df_aligned, factors, weights, cfg)
            scored_population.append((ind, fit, wr, calmar))
            print(f"  [{i+1}/{args.population}] Eval: top_n={ind['top_n_stocks']}, mult={ind['multiplier']} -> WinRate={wr*100:.1f}%, Calmar={calmar:.2f}")
            
        # 按适应度降序排序
        scored_population.sort(key=lambda x: x[1], reverse=True)
        
        # 记录本代最佳
        gen_best = scored_population[0]
        if gen_best[1] > best_fitness:
            best_fitness = gen_best[1]
            best_overall = gen_best
            
        print(f"🏆 本代最佳: top_n={gen_best[0]['top_n_stocks']}, mult={gen_best[0]['multiplier']} | 胜率: {gen_best[2]*100:.2f}% | 卡玛: {gen_best[3]:.4f}")
        
        if gen == args.generations:
            break
            
        # 3. 锦标赛选择与繁衍
        next_gen = []
        # 精英保留 (Elitism): 保留表现最好的 20%
        elite_count = max(1, int(args.population * 0.2))
        next_gen.extend([x[0] for x in scored_population[:elite_count]])
        
        while len(next_gen) < args.population:
            # 在前 50% 的优质个体中随机选择父母
            pool = scored_population[:max(2, int(args.population/2))]
            p1 = random.choice(pool)[0]
            p2 = random.choice(pool)[0]
            
            child = crossover(p1, p2)
            child = mutate(child)
            next_gen.append(child)
            
        population = next_gen
        
    print(f"\n🎉 进化完成！史上最强超额胜率组合：")
    print(f"✅ top_n_stocks = {best_overall[0]['top_n_stocks']}")
    print(f"✅ special_boost_multiplier = {best_overall[0]['multiplier']}")
    print(f"🏆 最高胜率: {best_overall[2]*100:.2f}% | 超额卡玛: {best_overall[3]:.4f}")
    
    # 自动应用最优策略到 config.yaml
    cfg_path = PATHS.config.agent
    with open(cfg_path, "r", encoding="utf-8") as f:
        final_cfg = yaml.safe_load(f)
    
    final_cfg["backtest"]["top_n_stocks"] = best_overall[0]['top_n_stocks']
    final_cfg["special_boost"]["multiplier"] = best_overall[0]['multiplier']
    
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(final_cfg, f, allow_unicode=True)
        
    print(f"\n💾 [系统通知] 已自动将最优参数应用至系统配置文件: {cfg_path}")

    # 将结果保存为 JSON 供前端直观展示
    import json
    result_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "best_params": best_overall[0],
        "best_win_rate": round(best_overall[2] * 100, 2),
        "best_calmar": round(best_overall[3], 4),
        "start": args.start,
        "end": args.end,
        "generations": args.generations,
        "population": args.population
    }
    
    # 将文件存放在项目根目录 logs 文件夹下
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    out_file = os.path.join(log_dir, "hunter_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=4, ensure_ascii=False)
    print(f"💾 [系统通知] 寻优结论已写入: {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Win Rate Hunter GA Optimizer")
    parser.add_argument("--start", type=str, required=True, help="起始日期 (YYYYMMDD)")
    parser.add_argument("--end", type=str, required=True, help="结束日期 (YYYYMMDD)")
    parser.add_argument("--generations", type=int, default=5, help="进化代数")
    parser.add_argument("--population", type=int, default=20, help="种群大小")
    args = parser.parse_args()
    
    run_evolution(args)
