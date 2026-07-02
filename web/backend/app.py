# -*- coding: utf-8 -*-
"""
app.py —— FastAPI 后端服务器主入口
========================================================================
1. 初始化 FastAPI 实例并开放 CORS 跨域。
2. 定义系统状态、今日推荐股票、回测绩效、因子权重以及 Agent 状态监控 API 接口。
3. 绑定 services.py 数据提取层。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import subprocess
import threading
import uuid
import time
import os

from services import (
    get_market_status,
    get_deployed_factors,
    get_today_portfolio,
    get_performance_data,
    get_agent_logs,
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

def _run_bg_task(task_id: str, cmd: list, cwd: str):
    """
    后台线程执行子进程并更新状态
    """
    task_registry[task_id]["status"] = "RUNNING"
    task_registry[task_id]["started_at"] = time.strftime("%H:%M:%S")
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=300
        )
        task_registry[task_id]["status"] = "DONE"
        task_registry[task_id]["output"] = result.stdout[-2000:] if result.stdout else ""
        task_registry[task_id]["error"] = result.stderr[-800:] if result.stderr else ""
        task_registry[task_id]["returncode"] = result.returncode
    except subprocess.TimeoutExpired:
        task_registry[task_id]["status"] = "TIMEOUT"
        task_registry[task_id]["error"] = "Task timed out after 300s"
    except Exception as e:
        task_registry[task_id]["status"] = "ERROR"
        task_registry[task_id]["error"] = str(e)
    task_registry[task_id]["finished_at"] = time.strftime("%H:%M:%S")

@app.post("/api/run-fetch")
def api_run_fetch():
    """
    启动异步数据拉取任务 (scripts/test_tushare_fetch.py)
    """
    task_id = f"fetch-{uuid.uuid4().hex[:6]}"
    task_registry[task_id] = {"type": "fetch", "status": "PENDING", "started_at": None, "output": "", "error": ""}
    cmd = ["python3", os.path.join(PROJECT_ROOT, "scripts", "test_tushare_fetch.py")]
    t = threading.Thread(target=_run_bg_task, args=(task_id, cmd, PROJECT_ROOT), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "PENDING", "message": "数据拉取任务已启动，预计耗时 1-3 分钟..."}

@app.post("/api/run-scan")
def api_run_scan():
    """
    启动异步因子扫描任务 (agent/run_agent.py --mode quick)
    """
    task_id = f"scan-{uuid.uuid4().hex[:6]}"
    task_registry[task_id] = {"type": "scan", "status": "PENDING", "started_at": None, "output": "", "error": ""}
    cmd = ["python3", os.path.join(PROJECT_ROOT, "agent", "run_agent.py"), "--mode", "quick"]
    t = threading.Thread(target=_run_bg_task, args=(task_id, cmd, PROJECT_ROOT), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "PENDING", "message": "因子快速扫描已启动，预计耗时 20-40 秒..."}

@app.get("/api/task-status/{task_id}")
def api_task_status(task_id: str):
    """
    查询异步任务运行状态
    """
    if task_id not in task_registry:
        return {"task_id": task_id, "status": "NOT_FOUND"}
    return {"task_id": task_id, **task_registry[task_id]}

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
