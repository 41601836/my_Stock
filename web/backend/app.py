# -*- coding: utf-8 -*-
"""
app.py —— FastAPI 后端服务器主入口
========================================================================
1. 初始化 FastAPI 实例并开放 CORS 跨域。
2. 定义系统状态、今日推荐股票、回测绩效、因子权重以及 Agent 状态监控 API 接口。
3. 绑定 services.py 数据提取层。
"""

import sys
import os

# 将项目根目录（web/backend 向上两级）注入 sys.path，
# 确保 config、agent 等包无论从哪个工作目录启动 uvicorn 都能正确导入。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import subprocess
import threading
import uuid
import time
import glob
import yaml
import shutil

from services import (
    get_market_status,
    get_deployed_factors,
    get_today_portfolio,
    get_performance_data,
    get_agent_logs,
    get_jack_performance_data,
    get_build_position_opportunities,
    get_tracker_attribution_data,
    determine_adaptive_hold_period,
    get_market_overview_data,
    get_regime_dashboard,
    get_theme_stocks,
    search_stock,
    diagnose_stock,
    get_style_stocks,
    PROJECT_ROOT
)

app = FastAPI(title="量化策略控制台 API", description="Antigravity 因子进化与市场自适应控制后台 API", version="1.0.0")

# 配置 CORS 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Request
from fastapi.responses import JSONResponse
import logging

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).error(f"Unhandled API error at {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"message": "服务器内部发生未捕获的异常。请检查后台日志。", "detail": str(exc)},
    )


@app.get("/api/status")
def api_status():
    """
    返回当前市场状态及当前运行模型
    """
    return get_market_status()

@app.get("/api/portfolio")
def api_portfolio():
    """
    今日股票推荐 Top 10 + 昨日持仓盈亏
    """
    return get_today_portfolio()

@app.get("/api/performance")
def api_performance():
    """
    三曲线累计收益净值走势 + 卡玛绩效统计
    """
    return get_performance_data()

@app.get("/api/jack-performance")
def api_jack_performance():
    """
    游资/散户模拟三曲线累计收益净值走势 + 卡玛绩效统计
    """
    return get_jack_performance_data()

@app.get("/api/factors")
def api_factors():
    """
    当前部署的因子权重 (包含 Range 与 Bull 模型配置)
    """
    return get_deployed_factors()

@app.get("/api/agent")
def api_agent():
    """
    Agent 寻优轨迹记录与系统最新日志
    """
    return get_agent_logs()

# 全局异步任务状态表
task_registry = {}

def is_task_running(task_type=None):
    """检测当前是否有正在运行的同类型任务或任何后台任务"""
    for tid, info in task_registry.items():
        if info.get("status") in ["PENDING", "RUNNING"]:
            if task_type is None or info.get("type") == task_type:
                return True
    return False

def _run_bg_task(task_id: str, cmd: list, cwd: str, timeout: int = 600):
    """
    后台线程执行子进程并更新状态
    """
    task_registry[task_id]["status"] = "RUNNING"
    task_registry[task_id]["started_at"] = time.strftime("%H:%M:%S")
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        task_registry[task_id]["status"] = "DONE"
        task_registry[task_id]["output"] = result.stdout[-2000:] if result.stdout else ""
        task_registry[task_id]["error"] = result.stderr[-800:] if result.stderr else ""
        task_registry[task_id]["returncode"] = result.returncode
    except subprocess.TimeoutExpired:
        task_registry[task_id]["status"] = "TIMEOUT"
        task_registry[task_id]["error"] = f"Task timed out after {timeout}s"
    except Exception as e:
        task_registry[task_id]["status"] = "ERROR"
        task_registry[task_id]["error"] = str(e)
    task_registry[task_id]["finished_at"] = time.strftime("%H:%M:%S")

@app.post("/api/run-fetch")
def api_run_fetch():
    """
    启动异步数据拉取任务 (scripts/test_tushare_fetch.py)，超时 900s
    """
    if is_task_running("fetch"):
        return {"status": "busy", "message": "⚠️ 数据同步拉取任务已在后台执行中，请勿重复点击"}
        
    task_id = f"fetch-{uuid.uuid4().hex[:6]}"
    task_registry[task_id] = {"type": "fetch", "status": "PENDING", "started_at": None, "output": "", "error": ""}
    cmd = ["bash", "-c", "python3 scripts/update_daily_data.py && PYTHONPATH=. python3 src/feature_engineering.py"]
    t = threading.Thread(target=_run_bg_task, args=(task_id, cmd, PROJECT_ROOT, 900), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "PENDING", "message": "数据拉取任务已启动，预计耗时 1-3 分钟..."}

@app.post("/api/run-scan")
def api_run_scan():
    """
    启动异步因子有效性扫描 (quick 模式，~3 分钟)，超时 600s
    """
    if is_task_running("scan"):
        return {"status": "busy", "message": "⚠️ 因子效能扫描任务已在后台执行中，请勿重复点击"}
        
    task_id = f"scan-{uuid.uuid4().hex[:6]}"
    task_registry[task_id] = {"type": "scan", "status": "PENDING", "started_at": None, "output": "", "error": ""}
    cmd = ["python3", os.path.join(PROJECT_ROOT, "agent", "run_agent.py"), "--mode", "quick"]
    t = threading.Thread(target=_run_bg_task, args=(task_id, cmd, PROJECT_ROOT, 600), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "PENDING", "message": "因子效能扫描已启动，预计耗时 2-4 分钟..."}

@app.post("/api/run-backtest")
def api_run_backtest():
    """
    触发 simulation 回测，更新 backtest_results_v2.csv 和数据截止日期，超时 600s
    """
    if is_task_running("backtest"):
        return {"status": "busy", "message": "⚠️ 回测评估任务已在后台执行中，请勿重复点击"}
        
    task_id = f"bt-{uuid.uuid4().hex[:6]}"
    task_registry[task_id] = {"type": "backtest", "status": "PENDING", "started_at": None, "output": "", "error": ""}
    cmd = ["python3", os.path.join(PROJECT_ROOT, "agent", "run_agent.py"), "--mode", "simulation"]
    t = threading.Thread(target=_run_bg_task, args=(task_id, cmd, PROJECT_ROOT, 600), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "PENDING", "message": "回测仿真已启动，更新数据截止日期，预计耗时 1-2 分钟..."}

@app.post("/api/hunter/run")
async def api_hunter_run(request: Request):
    """
    触发胜率猎手遗传算法引擎
    """
    if is_task_running("hunter"):
        return {"status": "busy", "message": "⚠️ 胜率猎手进化寻优任务已在后台执行中，请勿重复点击"}
        
    data = await request.json()
    start_date = data.get("start", "20260101")
    end_date = data.get("end", "20260703")
    generations = str(data.get("generations", 5))
    population = str(data.get("population", 20))
    
    task_id = f"hunter-{uuid.uuid4().hex[:6]}"
    task_registry[task_id] = {"type": "hunter", "status": "PENDING", "started_at": None, "output": "", "error": ""}
    
    cmd = [
        "python", os.path.join(PROJECT_ROOT, "win_rate_hunter.py"),
        "--start", start_date,
        "--end", end_date,
        "--generations", generations,
        "--population", population
    ]
    # 超时时间设为 1 个小时，因为进化引擎计算量极大
    t = threading.Thread(target=_run_bg_task, args=(task_id, cmd, PROJECT_ROOT, 3600), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "PENDING", "message": "胜率猎手遗传进化已点火，将在后台持续寻优..."}

@app.get("/api/hunter/result")
def api_hunter_result():
    """
    获取最近一次胜率猎手的寻优结论
    """
    import os, json
    res_file = os.path.join(PROJECT_ROOT, "logs", "hunter_results.json")
    if os.path.exists(res_file):
        with open(res_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"error": "尚未生成寻优结论，请先运行猎手"}

@app.get("/api/strategies")
def api_get_strategies():
    """
    获取所有的策略预设并判断当前激活状态
    """
    strategies = []
    strat_dir = os.path.join(PROJECT_ROOT, "agent", "strategies")
    if not os.path.exists(strat_dir):
        return {"strategies": [], "current": "custom"}
        
    for file in glob.glob(os.path.join(strat_dir, "*.yaml")):
        name = os.path.basename(file)
        try:
            with open(file, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
                strategies.append({
                    "name": name,
                    "top_n_stocks": cfg.get("backtest", {}).get("top_n_stocks", "N/A"),
                    "multiplier": cfg.get("special_boost", {}).get("multiplier", "N/A")
                })
        except Exception:
            continue
            
    # Read current config to determine which strategy is active
    current_name = "custom"
    try:
        with open(os.path.join(PROJECT_ROOT, "agent", "config.yaml"), 'r', encoding='utf-8') as f:
            current_cfg = yaml.safe_load(f)
            c_top = current_cfg.get("backtest", {}).get("top_n_stocks")
            c_mult = current_cfg.get("special_boost", {}).get("multiplier")
            for s in strategies:
                if s["top_n_stocks"] == c_top and s["multiplier"] == c_mult:
                    current_name = s["name"]
                    break
    except Exception:
        pass
        
    # Sort strategies by name descending so newer ones are at top
    strategies.sort(key=lambda x: x["name"], reverse=True)
    return {"strategies": strategies, "current": current_name}

@app.post("/api/strategies/switch")
async def api_switch_strategy(request: Request):
    """
    一键切换并加载目标策略
    """
    data = await request.json()
    name = data.get("name")
    if not name:
        return {"status": "error", "message": "No strategy name provided."}
        
    src = os.path.join(PROJECT_ROOT, "agent", "strategies", name)
    dst = os.path.join(PROJECT_ROOT, "agent", "config.yaml")
    
    if not os.path.exists(src):
        return {"status": "error", "message": f"Strategy {name} not found."}
        
    try:
        shutil.copy(src, dst)
        return {"status": "success", "message": f"成功切换至 {name} 金牌策略"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/task-status/{task_id}")
def api_task_status(task_id: str):
    """
    查询异步任务运行状态
    """
    if task_id not in task_registry:
        return {"task_id": task_id, "status": "NOT_FOUND"}
    return {"task_id": task_id, **task_registry[task_id]}

@app.get("/api/scan-opportunities")
def api_scan_opportunities():
    """
    实时建仓机会扫描：基于最新截面因子+笹码+大资金流入，筛选可建仓股票
    """
    return get_build_position_opportunities()

@app.get("/api/tracker/attribution")
def api_tracker_attribution():
    """
    获取样本外建仓逻辑的归因跟踪数据 (包含衰减图、Regime 诊断、历史明细)
    """
    return get_tracker_attribution_data()

@app.get("/api/tracker/adaptive-period")
def api_tracker_adaptive_period():
    """
    自适应换仓周期反馈接口：返回策略大势评估出的最优换仓天数
    """
    return {"adaptive_period": determine_adaptive_hold_period()}

@app.get("/api/market/overview")
def api_market_overview():
    """
    获取宏观量化市场全览数据 (赚钱效应、筹码温度、资金流向排行及因子风格轮动)
    """
    return get_market_overview_data()

@app.get("/api/market/regime-dashboard")
def api_market_regime_dashboard():
    """
    获取实时市场状态路由层的判定细节及历史
    """
    return get_regime_dashboard()

@app.get("/api/market/theme-stocks")
def api_market_theme_stocks(sector: str = ""):
    """
    获取游资热点题材下的具体股票列表
    """
    if not sector:
        return {"error": "Sector parameter is required"}
    return get_theme_stocks(sector)

@app.get("/api/market/search-stock")
def api_market_search_stock(query: str = ""):
    """
    模糊查询股票代码或名称
    """
    if not query:
        return {"stocks": []}
    return search_stock(query)

@app.get("/api/market/diagnose")
def api_market_diagnose(ts_code: str = "", strategy: str = "current"):
    """
    对指定股票进行策略诊断
    """
    if not ts_code:
        return {"error": "Missing ts_code"}
    return diagnose_stock(ts_code, strategy)

@app.get("/api/market/style-stocks")
def api_market_style_stocks(date: str = "", style: str = ""):
    """
    获取某日特定风格的前20名支撑个股
    """
    if not date or not style:
        return {"error": "Missing parameters"}
    return get_style_stocks(date, style)

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
