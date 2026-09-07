# -*- coding: utf-8 -*-
"""
alpha_hunt 路由 — Alpha 搜索流水线 API

Endpoints:
  POST /api/alpha-hunt/run          启动 Alpha 搜索
  GET  /api/alpha-hunt/status       查询搜索状态
  GET  /api/alpha-hunt/ic-report    因子 IC 体检报告
  GET  /api/alpha-hunt/result       搜索结果
  POST /api/alpha-hunt/validate     对指定组合运行四关验证
  GET  /api/alpha-hunt/validate-result  获取验证结果
"""
import os
import json
import threading
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/alpha-hunt", tags=["alpha-hunt"])

# 全局状态
_hunt_state = {
    "running": False,
    "stage": "idle",
    "progress": "",
    "start_time": None,
    "elapsed": 0,
    "result": None,
    "ic_report": None,
    "validate_result": None,
}
_hunt_thread: Optional[threading.Thread] = None


class HuntRequest(BaseModel):
    weeks: int = 104
    population_size: int = 50
    max_generations: int = 10
    top_n: int = 20
    buffer_n: int = 35


class ValidateRequest(BaseModel):
    factor_weights: dict
    weeks: int = 104


def _run_hunt_background(req: HuntRequest):
    """后台执行 Alpha 搜索"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    _hunt_state["running"] = True
    _hunt_state["stage"] = "IC 预筛选"
    _hunt_state["progress"] = "正在筛选因子..."
    _hunt_state["start_time"] = time.time()

    try:
        from factor_lib.alpha_hunter import AlphaHunter

        hunter = AlphaHunter()

        # 1. 获取日期
        _hunt_state["stage"] = "获取回测日期"
        hunter.dates = hunter.loader.get_backtest_dates(req.weeks)
        _hunt_state["progress"] = f"{len(hunter.dates)} 周回测日期已加载"

        # 2. IC 预筛选
        _hunt_state["stage"] = "IC 预筛选"
        from factor_lib.registry import get_candidate_factors
        candidates = get_candidate_factors()
        _hunt_state["progress"] = f"筛选 {len(candidates)} 个候选因子..."
        hunter.ic_report, hunter.passed_factors, failed = hunter.ic_screener.screen_factors(
            candidates, hunter.dates
        )

        if not hunter.passed_factors:
            # 放宽标准重试
            _hunt_state["progress"] = "无因子通过，放宽标准重试..."
            hunter.ic_report, hunter.passed_factors, failed = hunter.ic_screener.screen_factors(
                candidates, hunter.dates, min_ic=0.008, min_t=1.5, min_halflife_weeks=1.0
            )

        _hunt_state["ic_report"] = hunter.ic_report

        if not hunter.passed_factors:
            _hunt_state["stage"] = "完成（无因子通过）"
            _hunt_state["result"] = {
                "best_combo": None,
                "best_fitness": -999,
                "error": "no factors passed IC screening",
                "passed_factors": [],
            }
            _hunt_state["running"] = False
            return

        # 3. 预计算中性化缓存
        _hunt_state["stage"] = "中性化预计算"
        _hunt_state["progress"] = f"预计算 {len(hunter.passed_factors)} 因子..."
        hunter.loader.precompute_neutral_cache(hunter.dates, hunter.passed_factors)
        hunter.neutral_cache_ready = True

        # 4. 遗传搜索
        _hunt_state["stage"] = "遗传搜索"
        _hunt_state["progress"] = f"启动 GA: 50 个体 × 10 代..."
        from agent.genetic_search import GeneticFactorSearcher
        from factor_lib.unified_backtester import compute_fitness

        ga = GeneticFactorSearcher(
            candidate_factors=hunter.passed_factors,
            population_size=req.population_size,
            max_generations=req.max_generations,
        )

        def evaluate(combo):
            weights = {f: 1.0 / len(combo) for f in combo}
            result = hunter.backtester.run(
                factor_weights=weights,
                dates=hunter.dates,
                top_n=req.top_n,
                buffer_n=req.buffer_n,
                data_loader=hunter.loader,
            )
            return compute_fitness(result)

        ga_result = ga.evolve(evaluate_fn=evaluate)

        _hunt_state["result"] = {
            "best_combo": ga_result.get("best_combo"),
            "best_fitness": round(ga_result.get("best_fitness", 0), 4),
            "history": ga_result.get("history", []),
            "passed_factors": hunter.passed_factors,
            "n_weeks": len(hunter.dates),
            "n_evaluated": len(ga_result.get("all_evaluated", [])),
        }
        _hunt_state["stage"] = "完成"

        # 保存结果
        os.makedirs("reports", exist_ok=True)
        with open("reports/alpha_hunt_result.json", "w", encoding="utf-8") as f:
            json.dump(_hunt_state["result"], f, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        _hunt_state["stage"] = f"错误: {str(e)}"
        _hunt_state["result"] = {"error": str(e)}
    finally:
        _hunt_state["running"] = False
        _hunt_state["elapsed"] = time.time() - _hunt_state["start_time"]


def _run_validate_background(req: ValidateRequest):
    """后台执行四关验证"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    _hunt_state["validate_result"] = {"running": True, "stage": "初始化..."}

    try:
        from factor_lib.data_loader import FactorDataLoader
        from factor_lib.validation_gate import ValidationGate

        loader = FactorDataLoader()
        dates = loader.get_backtest_dates(req.weeks)

        gate = ValidationGate()
        result = gate.run_all_gates(req.factor_weights, dates)

        _hunt_state["validate_result"] = {
            "running": False,
            "overall_pass": result["overall_pass"],
            "gates": {
                "gate1": result["gates"]["gate1"],
                "gate2": result["gates"]["gate2"],
                "gate3": result["gates"]["gate3"],
                "gate4": result["gates"]["gate4"],
            },
            "summary": result["summary"],
        }

        with open("reports/validation_result.json", "w", encoding="utf-8") as f:
            json.dump(_hunt_state["validate_result"], f, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        _hunt_state["validate_result"] = {"running": False, "error": str(e)}


@router.post("/run")
async def run_hunt(req: HuntRequest):
    """启动 Alpha 搜索"""
    global _hunt_thread

    if _hunt_state["running"]:
        raise HTTPException(status_code=409, detail="搜索正在进行中")

    _hunt_thread = threading.Thread(target=_run_hunt_background, args=(req,), daemon=True)
    _hunt_thread.start()

    return {"status": "started", "message": "Alpha 搜索已启动"}


@router.get("/status")
async def get_status():
    """查询搜索状态"""
    elapsed = 0
    if _hunt_state["start_time"]:
        elapsed = time.time() - _hunt_state["start_time"]

    return {
        "running": _hunt_state["running"],
        "stage": _hunt_state["stage"],
        "progress": _hunt_state["progress"],
        "elapsed_seconds": round(elapsed),
    }


@router.get("/ic-report")
async def get_ic_report():
    """获取因子 IC 体检报告"""
    if _hunt_state["ic_report"]:
        return {"factors": _hunt_state["ic_report"]}

    # 尝试从文件加载
    report_path = "reports/factor_ic_report.json"
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return {"factors": []}


@router.get("/result")
async def get_result():
    """获取搜索结果"""
    if _hunt_state["result"]:
        return _hunt_state["result"]

    result_path = "reports/alpha_hunt_result.json"
    if os.path.exists(result_path):
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return {"best_combo": None, "best_fitness": 0}


@router.post("/validate")
async def run_validation(req: ValidateRequest):
    """对指定因子组合运行四关验证"""
    thread = threading.Thread(target=_run_validate_background, args=(req,), daemon=True)
    thread.start()
    return {"status": "started", "message": "四关验证已启动"}


@router.get("/validate-result")
async def get_validate_result():
    """获取验证结果"""
    if _hunt_state["validate_result"]:
        return _hunt_state["validate_result"]

    result_path = "reports/validation_result.json"
    if os.path.exists(result_path):
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return {"running": False, "error": "无验证结果"}
