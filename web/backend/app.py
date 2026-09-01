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

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
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
    record_visitor,
    get_visitor_stats,
    save_scan_history,   # 建仓扫描历史累计层
    get_scan_history,    # 建仓扫描历史查询层
    get_timing_alerts,   # 建仓时机预警评分
    get_portrait_analysis,  # T+1 画像分析路由层
    get_portrait_position_pick,  # T+1 画像三层漏斗建仓决策
    clean_nan_inf,
    PROJECT_ROOT
)

class SafeJSONResponse(JSONResponse):
    """
    全自动安全 JSON 响应器：
    拦截并递归清洗所有待返回数据中的 NaN, Infinity, -Infinity，
    避免 FastAPI / Starlette 抛出 JSON non-compliant 错误而导致 HTTP 500。
    """
    def render(self, content: any) -> bytes:
        return super().render(clean_nan_inf(content))

app = FastAPI(
    title="量化策略控制台 API",
    description="Antigravity 因子进化与市场自适应控制后台 API",
    version="1.0.0",
    default_response_class=SafeJSONResponse
)

# 配置 CORS 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import logging

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).error(f"Unhandled API error at {request.url}: {exc}")
    return SafeJSONResponse(
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


@app.get("/api/portrait/analysis")
def api_portrait_analysis(days: int = 10):
    """
    T+1 上涨画像分析路由层：统计最近 N 个推荐日中，
    上涨/下跌股票在各因子维度上的差异分布。
    参数 days: 分析的推荐日天数（默认 10 天）
    """
    return get_portrait_analysis(days=days)


@app.get("/api/portrait/position-pick")
def api_portrait_position_pick(top_n: int = 30, strategy: str = "left"):
    """
    T+1 画像三层过滤漏斗建仓决策路由层：
    层一：画像等级 ≥ B（portrait_score >= 60）
    层二：今日涨幅 <= 5%（避免追高）/ 右侧 <= 9.5%
    层三：同行业最多1支（仓位分散）
    最终返回 1-3 支精选建仓股票及漏斗统计。
    """
    return get_portrait_position_pick(top_n=max(10, min(top_n, 60)), strategy=strategy)

# 全局异步任务状态表
task_registry = {}

def is_task_running(task_type=None):
    """
    检测当前是否有正在运行的后台任务。
    - task_type=None：只要有任何任务在运行即返回 True（数据拉取/扫描场景）。
    - task_type 指定类型：只检测同类型任务是否在运行（回测/猎手可与数据任务并行）。
    由于数据拉取、因子工程与回测均高度依赖 SQLite 独占写入，
    因此全局同一时间仅允许一个重度后台任务运行，防止多进程 DB 死锁。
    """
    for tid, info in task_registry.items():
        if info.get("status") in ["PENDING", "RUNNING"]:
            # 若指定类型，只拦截同类型任务；否则拦截所有
            if task_type is None or info.get("type") == task_type:
                return True
    return False

def _run_bg_task(task_id: str, cmd: list, cwd: str, timeout: int = 600):
    """
    后台线程执行子进程并更新状态，支持保存 Process 实例以便人工干预终止
    """
    task_registry[task_id]["status"] = "RUNNING"
    task_registry[task_id]["started_at"] = time.strftime("%H:%M:%S")
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        task_registry[task_id]["process"] = proc
        stdout, stderr = proc.communicate(timeout=timeout)
        
        if proc.returncode == 0:
            task_registry[task_id]["status"] = "DONE"
        else:
            task_registry[task_id]["status"] = "ERROR" if task_registry[task_id]["status"] != "CANCELLED" else "CANCELLED"
            
        task_registry[task_id]["output"] = stdout[-2000:] if stdout else ""
        task_registry[task_id]["error"] = stderr[-800:] if stderr else ""
        task_registry[task_id]["returncode"] = proc.returncode
    except subprocess.TimeoutExpired:
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        task_registry[task_id]["status"] = "TIMEOUT"
        task_registry[task_id]["error"] = f"任务超时已强行终止 (超时阈值: {timeout}s)"
    except Exception as e:
        task_registry[task_id]["status"] = "ERROR"
        task_registry[task_id]["error"] = str(e)
    finally:
        task_registry[task_id]["finished_at"] = time.strftime("%H:%M:%S")
        task_registry[task_id].pop("process", None)

scheduler = BackgroundScheduler()

def _scheduled_fetch():
    if is_task_running():
        return
    task_id = f"fetch-cron-{uuid.uuid4().hex[:6]}"
    task_registry[task_id] = {"type": "fetch", "status": "PENDING", "started_at": None, "output": "", "error": ""}
    cmd = ["bash", "-c", f"{sys.executable} scripts/update_daily_data.py && PYTHONPATH=. {sys.executable} src/feature_engineering.py && {sys.executable} scripts/data_health_check.py"]
    t = threading.Thread(target=_run_bg_task, args=(task_id, cmd, PROJECT_ROOT, 900), daemon=True)
    t.start()

def _scheduled_health_check():
    import subprocess
    try:
        subprocess.run([sys.executable, "scripts/data_health_check.py"], cwd=PROJECT_ROOT)
    except Exception as e:
        import logging
        logging.error(f"Health check scheduled task failed: {e}")

@app.on_event("startup")
def startup_event():
    scheduler.add_job(_scheduled_fetch, CronTrigger(day_of_week='mon-fri', hour=18, minute=30))
    scheduler.add_job(_scheduled_fetch, CronTrigger(day_of_week='mon-fri', hour=20, minute=30))
    scheduler.add_job(_scheduled_health_check, CronTrigger(day_of_week='mon-fri', hour=8, minute=30))
    scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

@app.post("/api/run-fetch")
def api_run_fetch():
    """
    启动异步数据拉取任务 (scripts/update_daily_data.py)，超时 900s
    """
    if is_task_running():
        return {"status": "busy", "message": "⚠️ 系统已有后台数据任务正在执行中，请勿重复发起"}
        
    task_id = f"fetch-{uuid.uuid4().hex[:6]}"
    task_registry[task_id] = {"type": "fetch", "status": "PENDING", "started_at": None, "output": "", "error": ""}
    cmd = ["bash", "-c", f"{sys.executable} scripts/update_daily_data.py && PYTHONPATH=. {sys.executable} src/feature_engineering.py && {sys.executable} scripts/data_health_check.py"]
    t = threading.Thread(target=_run_bg_task, args=(task_id, cmd, PROJECT_ROOT, 900), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "PENDING", "message": "数据拉取任务已启动，预计耗时 1-3 分钟..."}

@app.post("/api/run-scan")
def api_run_scan():
    """
    启动异步因子有效性扫描 (quick 模式，~3 分钟)，超时 600s
    """
    if is_task_running():
        return {"status": "busy", "message": "⚠️ 系统已有后台数据任务正在执行中，请勿重复发起"}
        
    task_id = f"scan-{uuid.uuid4().hex[:6]}"
    task_registry[task_id] = {"type": "scan", "status": "PENDING", "started_at": None, "output": "", "error": ""}
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "agent", "run_agent.py"), "--mode", "quick"]
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
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "agent", "run_agent.py"), "--mode", "simulation"]
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
    info = dict(task_registry[task_id])
    info.pop("process", None)
    return {"task_id": task_id, **info}

@app.post("/api/task-clear")
def api_task_clear():
    """
    强制重置与终止所有正在运行或卡顿的后台任务
    """
    cleared = []
    for tid, info in list(task_registry.items()):
        if info.get("status") in ["PENDING", "RUNNING"]:
            proc = info.get("process")
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            info["status"] = "CANCELLED"
            info["error"] = "任务已被手动强行重置"
            cleared.append(tid)
    return {"status": "success", "message": f"成功解锁并清理 {len(cleared)} 个卡顿任务", "cleared": cleared}

@app.post("/api/task-cancel/{task_id}")
def api_task_cancel(task_id: str):
    """
    取消并强行终止特定的异步任务
    """
    if task_id not in task_registry:
        return {"status": "error", "message": f"任务 {task_id} 不存在"}
    
    info = task_registry[task_id]
    proc = info.get("process")
    if proc:
        try:
            proc.kill()
        except Exception:
            pass
    info["status"] = "CANCELLED"
    info["error"] = "任务已被手动取消"
    return {"status": "success", "message": f"任务 {task_id} 已强行终止"}

@app.get("/api/scan-opportunities")
def api_scan_opportunities():
    """
    实时建仓机会扫描：基于最新截面因子+筹码+大资金流入，筛选可建仓股票。
    每次调用结果自动写入 scan_history 表（同日同股去重）。
    """
    result = get_build_position_opportunities()
    # 自动累计写历史（异常不影响主流程）
    try:
        written = save_scan_history(result)
        if result.get("meta") is not None:
            result["meta"]["history_written"] = written
    except Exception as _e:
        pass
    return result

@app.get("/api/market/sector-opportunities")
def api_sector_opportunities(sector: str = ""):
    """
    根据主板块或行业名称过滤，返回 5 维评分最高的 Top 10 股票
    """
    if not sector:
        return {"error": "Sector parameter is required", "stocks": []}
    return get_build_position_opportunities(sector_filter=sector, top_n=10)


@app.get("/api/scan-history")
def api_scan_history(
    days: int = 30,
    top_n_per_day: int = 0,
    min_appear: int = 1
):
    """
    查询建仓扫描历史累计数据。

    参数：
    - days:          查询最近 N 个自然日（默认 30）
    - top_n_per_day: 只看每日 Top-N 席位（0 = 不限）
    - min_appear:    频率排行最小上榜次数门槛（默认 1）

    返回：
    - summary: 上榜频率排行（出现次数+平均排名+平均因子分）
    - daily:   按日期分组的每日原始记录
    - streak:  当前连续上榜天数 >= 2 的股票排行
    - meta:    统计元信息（总记录数、唯一股票数等）
    """
    return get_scan_history(
        days=max(1, min(days, 365)),
        top_n_per_day=top_n_per_day,
        min_appear=min_appear
    )


@app.get("/api/scan-history/stock/{ts_code}")
def api_scan_history_stock(ts_code: str, days: int = 90):
    """
    查询某只股票近 N 天内的历史上榜记录（用于个股历史追踪）。
    返回：该股每次上榜的日期、排名、评分等完整信息。
    """
    return get_scan_history(
        days=max(1, min(days, 365)),
        ts_code=ts_code
    )


@app.get("/api/scan-history/timing")
def api_timing_alerts(lookback_days: int = 20):
    """
    建仓时机预警：基于今日在榜股票，计算多维信号综合评分。

    评分维度：初次入榜、排名跃升、连续第3天、二次入榜、
              因子极强、市场状态匹配（Bear/Dark加分）、
              信号过热/追涨风险（扣分）。

    返回三级预警：
      golden（≥60分）= 最佳建仓窗口
      watch （35-59）= 跟踪观察期
      normal（<35）  = 普通信号
    """
    return get_timing_alerts(lookback_days=max(5, min(lookback_days, 60)))

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
def api_market_theme_stocks(sector: str = "", sort: str = "desc", limit: int | None = None, sort_by: str | None = None):
    """
    获取游资热点题材下的具体股票列表
    S2：limit/sort_by 默认值从 config/thresholds.yaml.hot_money_tracker 读取
    """
    if not sector:
        return {"error": "Sector parameter is required"}
    return get_theme_stocks(sector, limit=limit, sort_order=sort, sort_by=sort_by)

@app.get("/api/market/search-stock")
def api_market_search_stock(query: str = ""):
    """
    模糊查询股票代码或名称
    """
    if not query:
        return {"results": []}
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

class TrackRequest(BaseModel):
    path: str
    device_id: str

@app.post("/api/stats/track")
def track_visitor(req: TrackRequest, request: Request):
    ip = request.headers.get("CF-Connecting-IP")
    if not ip:
        x_forwarded = request.headers.get("X-Forwarded-For")
        if x_forwarded:
            ip = x_forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
            
    user_agent = request.headers.get("User-Agent", "unknown")
    try:
        record_visitor(ip, req.device_id, req.path, user_agent)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/summary")
def get_stats():
    try:
        return get_visitor_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# EVO 进化层路由（平行挂载，绝不影响任何现有 /api/* 接口）
# - 前缀：/api/evo/*
# - 代码：routers/evo.py  +  services/evo/  （全新目录，0 侵入经典层）
# - 配置：config/evo.yaml  （8 大模块独立开关，支持热加载）
# ═══════════════════════════════════════════════════════════
try:
    from routers import evo_router
    app.include_router(evo_router)
    # 启动时打印一行标记，方便日志里确认进化层已挂载
    import logging as _evo_logging
    _evo_logging.getLogger(__name__).info(
        "✅ [Evo] 进化层路由已挂载：/api/evo/*（平行层，经典路由不受影响）"
    )
except Exception as _evo_exc:
    import logging as _evo_logging2
    _evo_logging2.getLogger(__name__).warning(
        f"⚠️ [Evo] 进化层路由挂载失败（经典系统照常运行）：{_evo_exc}"
    )


# ══════════════════════════════════════════════════════════════════
# 生产环境：托管前端静态文件（dist）—— 必须放在所有 API 路由之后
# 当 web/frontend/dist 存在时，将其作为 SPA 静态资源挂载，
# 使后端单进程即可提供完整前后端服务（无需 Vite dev server / 代理）。
# 注意：此 catch-all 路由必须在所有 /api/* 路由注册之后，否则会拦截 API 请求
# ══════════════════════════════════════════════════════════════════
_FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.isdir(_FRONTEND_DIST) and os.path.exists(os.path.join(_FRONTEND_DIST, "index.html")):
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    # 挂载 /assets 静态资源目录（JS/CSS/图片等）
    _assets_path = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(_assets_path):
        app.mount("/assets", StaticFiles(directory=_assets_path), name="assets")

    # SPA fallback：所有非 /api 路径返回 index.html，交给 React Router 处理
    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str):
        # 排除 API 路径（已被具体路由匹配）
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not Found")
        # 请求的文件若存在于 dist 中，直接返回该文件
        candidate = os.path.join(_FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        # 否则返回 index.html（客户端路由）
        return FileResponse(os.path.join(_FRONTEND_DIST, "index.html"))

    logging.getLogger(__name__).info(f"✅ 生产模式：已挂载前端静态文件 { _FRONTEND_DIST }")


if __name__ == "__main__":
    import socket as _socket
    import uvicorn as _uvicorn

    # Dual-stack launcher：同时监听 IPv4 + IPv6，解决 macOS "localhost"
    # 在 A/AAAA 双记录下的 Happy Eyeballs 竞态导致间歇性
    # ERR_CONNECTION_REFUSED（相对路径 fetch 先冲 IPv6 失败、用户看到 OFFLINE）。
    # 可通过环境变量覆盖：PORT=8000 RELOAD=true WORKERS=1 python3 app.py
    _port = int(os.environ.get("PORT", "8000"))
    _reload = os.environ.get("RELOAD", "false").lower() in ("1", "true", "yes", "on")
    _workers = int(os.environ.get("WORKERS", "1"))

    _sockets = []
    # ── 1) IPv6 socket（尝试 dual-stack：V6ONLY=0）────────────
    _s6 = _socket.socket(_socket.AF_INET6, _socket.SOCK_STREAM)
    _s6.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    try:
        _s6.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, 0)
        _s6.bind(("::", _port))
        _dual_stack_ok = True
    except OSError:
        # 系统不允许 dual-stack（部分 Linux sysctl 禁用）：退化为纯 IPv6 socket
        try:
            _s6.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, 1)
            _s6.bind(("::", _port))
            _dual_stack_ok = False
        except OSError:
            _s6.close()
            _s6 = None
            _dual_stack_ok = False
    if _s6 is not None:
        _s6.listen(128)
        _sockets.append(_s6)

    # ── 2) IPv4 socket（仅当 dual-stack 失败时再开，避免双绑冲突）──
    if not _dual_stack_ok:
        _s4 = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        _s4.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            _s4.bind(("0.0.0.0", _port))
            _s4.listen(128)
            _sockets.append(_s4)
        except OSError:
            _s4.close()

    if not _sockets:
        raise RuntimeError(f"无法在端口 {_port} 上绑定 IPv4/IPv6 任一 socket，请检查端口占用")

    _cfg = _uvicorn.Config("app:app", reload=_reload, workers=_workers, access_log=False)
    _srv = _uvicorn.Server(_cfg)
    _srv.run(sockets=_sockets)
