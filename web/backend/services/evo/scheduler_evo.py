# -*- coding: utf-8 -*-
"""
services.evo.scheduler_evo —— EVO 进化层独立每日调度器
=================================================================
与经典层 app.py 的 scheduler 完全隔离（独立 BackgroundScheduler 实例），
随 routers.evo 模块 import 自动启动（app.py 零改动）。

时序设计（对齐经典层数据链）：
  经典层：周一~五 18:30 / 20:30  update_daily_data → feature_engineering → health_check
  EVO 层：周一~五 19:30 / 21:30  feature_engineering_evo → evo_dynamic_weights
  （在经典层数据+因子就绪之后；UPSERT 幂等，重复运行安全）

防重入：非阻塞线程锁；上一轮未跑完则跳过本次并记录日志。
"""

import os
import sys
import time
import threading
import subprocess
import logging
from typing import Dict, Any, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from services.evo._common import PROJECT_ROOT, EvoConfig

logger = logging.getLogger("services.evo.scheduler_evo")
logger.setLevel(logging.INFO)   # 独立脚本运行时 root logger 默认 WARNING，不显式 setLevel 则 info 全被过滤

# EVO 独立文件日志（硬约束：logs/evo/ 目录，与经典层 logs 隔离）
_EVO_LOG_DIR = os.path.join(PROJECT_ROOT, "logs", "evo")
try:
    os.makedirs(_EVO_LOG_DIR, exist_ok=True)
    _fh = logging.FileHandler(os.path.join(_EVO_LOG_DIR, "scheduler.log"), encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_fh)
except Exception:
    pass

# 单飞锁 + 运行状态（供 /api/evo/scheduler/status 查询）
_lock = threading.Lock()
_state: Dict[str, Any] = {
    "status": "idle",          # idle / running / ok / partial / error / skipped / skipped_running
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
    "duration_sec": None,
    "output_tail": "",
    "steps": [],               # 分步结果：[{key,name,required,exit_code,status,duration_sec,tail}]
}

EVO_JOBS: List[Dict[str, Any]] = []   # 注册的 job 描述（status 接口用）
_scheduler: Optional[BackgroundScheduler] = None

# 分步子进程：因子计算 → 动态权重 → 拥挤度/衰减监控（核心，失败即终止）
# ML 推理 / 文本采集+打分（可选，enabled 时追加；失败隔离但状态显式上报为 partial）
EVO_TIMEOUT_SEC = 1800                # 单步超时；因子 ~4min，余量充足


def _pipeline_steps() -> List[Dict[str, Any]]:
    """返回当日应执行的步骤清单（每次调用实时读 evo.yaml，热加载生效）。"""
    py = sys.executable  # 与后端进程同一解释器（miniconda 3.13，apscheduler/fastapi 已验证）
    steps: List[Dict[str, Any]] = [
        {"key": "feature_evo", "name": "EVO因子计算", "required": True,
         "cmd": f"PYTHONPATH=. {py} src/feature_engineering_evo.py"},
        {"key": "dynamic_weights", "name": "动态权重", "required": True,
         "cmd": f"PYTHONPATH=. {py} src/evo_dynamic_weights.py"},
        {"key": "monitors", "name": "拥挤度/衰减监控", "required": True,
         "cmd": f"PYTHONPATH=. {py} src/evo_monitors.py"},
    ]
    if EvoConfig.get("lambdarank.enabled", False):
        steps.append({"key": "ml_predict", "name": "ML推理(LambdaRank)", "required": False,
                      "cmd": f"PYTHONPATH=. {py} src/evo_ml_rank.py --predict"})
    if EvoConfig.get("text_factors.enabled", False):
        steps.append({"key": "text_daily", "name": "文本采集打分", "required": False,
                      "cmd": f"PYTHONPATH=. {py} src/evo_text_pipeline.py --daily"})
    return steps


def _pipeline_cmd() -> str:
    """展示用命令串（核心 && 串联，可选步骤 ; 隔离），与实际分步执行语义一致。"""
    steps = _pipeline_steps()
    core = " && ".join(s["cmd"] for s in steps if s["required"])
    opt = "".join(
        f" ; ({s['cmd']} || echo '[{s['key']}] failed (non-blocking)')"
        for s in steps if not s["required"]
    )
    return core + opt


def _evo_pipeline() -> None:
    """每日 EVO 管线：因子计算 + 动态权重（防重入，幂等 UPSERT）"""
    # 全关则不跑（安全闸 2）
    evo_any_on = (
        EvoConfig.get("cross_factors.enabled", False)
        or EvoConfig.get("surprise_factors.enabled", False)
        or EvoConfig.get("dynamic_weights.enabled", False)
        or EvoConfig.get("graham_filter.enabled", False)
    )
    if not evo_any_on:
        logger.info("[EvoScheduler] evo.yaml 全模块关闭，跳过")
        _state.update(status="skipped", finished_at=time.strftime("%H:%M:%S"))
        return

    if not _lock.acquire(blocking=False):
        logger.warning("[EvoScheduler] 上一轮 EVO 任务仍在运行，跳过本次触发")
        _state.update(status="skipped_running", finished_at=time.strftime("%H:%M:%S"))
        return
    try:
        t0 = time.time()
        steps = _pipeline_steps()
        _state.update(
            status="running",
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=None, exit_code=None, steps=[],
        )
        logger.info(f"[EvoScheduler] 开始每日 EVO 管线（{len(steps)} 步）: {_pipeline_cmd()}")

        # 每步完整输出落 logs/evo/scheduler_YYYYMMDD.log（独立日志硬约束）
        log_path = os.path.join(_EVO_LOG_DIR, f"scheduler_{time.strftime('%Y%m%d')}.log")
        step_results: List[Dict[str, Any]] = []
        overall = "ok"

        for i, step in enumerate(steps, 1):
            t_s = time.time()
            logger.info(f"[EvoScheduler] 步骤 {i}/{len(steps)} 「{step['name']}」开始")
            out = ""
            rc = 0
            try:
                proc = subprocess.run(
                    ["bash", "-c", step["cmd"]],
                    cwd=PROJECT_ROOT, capture_output=True, text=True,
                    timeout=EVO_TIMEOUT_SEC,
                )
                out = (proc.stdout or "") + (proc.stderr or "")
                rc = proc.returncode
            except subprocess.TimeoutExpired as e:
                out = f"步骤超时（>{EVO_TIMEOUT_SEC}s）已终止\n"
                out += (e.stdout or "") + (e.stderr or "") if e.stdout or e.stderr else ""
                rc = -9
            except Exception as e:
                out = f"步骤异常: {e}"
                rc = -1

            dur = round(time.time() - t_s, 1)
            ok = rc == 0
            try:
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                             f"step={step['key']} rc={rc} dur={dur}s =====\n")
                    lf.write(out[-20000:])
            except Exception:
                pass

            step_results.append({
                "key": step["key"], "name": step["name"],
                "required": step["required"], "exit_code": rc,
                "status": "ok" if ok else "failed",
                "duration_sec": dur,
                "tail": out[-800:],
            })
            _state.update(steps=list(step_results))  # 实时刷新，status 接口可观察在跑的步骤

            if ok:
                logger.info(f"[EvoScheduler] 步骤 「{step['name']}」 完成 ({dur}s)")
            else:
                logger.error(f"[EvoScheduler] 步骤 「{step['name']}」 失败 rc={rc} ({dur}s)，"
                             f"尾部输出: {out[-300:]}")
                if step["required"]:
                    overall = "error"
                    break          # 核心步骤失败：终止后续（等价旧 && 语义）
                overall = "partial"  # 可选步骤失败：隔离继续，但状态显式上报

        _state.update(
            status=overall,
            exit_code=0 if overall == "ok" else (1 if overall == "error" else 2),
            output_tail=(step_results[-1]["tail"] if step_results else ""),
            duration_sec=round(time.time() - t0, 1),
            finished_at=time.strftime("%H:%M:%S"),
        )
        logger.info(f"[EvoScheduler] 管线结束 status={overall} "
                    f"耗时 {time.time() - t0:.0f}s，分步: "
                    + ", ".join(f"{s['key']}={s['status']}" for s in step_results))
    finally:
        _lock.release()


def trigger_manual() -> Dict[str, Any]:
    """手动触发一次（带防重入）；供 POST /api/evo/scheduler/run"""
    if _state.get("status") == "running":
        return {"ok": False, "message": "EVO 管线正在运行中，请勿重复触发"}
    t = threading.Thread(target=_evo_pipeline, daemon=True)
    t.start()
    return {"ok": True, "message": "EVO 管线已后台启动（因子计算约 4 分钟 + 动态权重约 20 秒）"}


def get_state() -> Dict[str, Any]:
    """调度器状态（供 GET /api/evo/scheduler/status）"""
    return {
        "enabled": _scheduler is not None,
        "cron": "mon-fri 19:30 / 21:30（经典层 18:30/20:30 数据链完成之后）",
        "pipeline": _pipeline_cmd(),
        "jobs": EVO_JOBS,
        "last_run": dict(_state),
    }


def start_evo_scheduler() -> Optional[BackgroundScheduler]:
    """启动 EVO 独立调度器；失败返回 None（绝不影响后端启动）"""
    global _scheduler
    try:
        sched = BackgroundScheduler(daemon=True, name="evo-scheduler")
        for job_id, hh, mm in [("evo_pipeline_evening", 19, 30),
                               ("evo_pipeline_night", 21, 30)]:
            sched.add_job(
                _evo_pipeline,
                CronTrigger(day_of_week="mon-fri", hour=hh, minute=mm),
                id=job_id, replace_existing=True,
                misfire_grace_time=3600,      # 错过 1h 内仍补跑
                coalesce=True,                # 多次错过合并为一次
            )
        sched.start()
        _scheduler = sched
        # start 之后再收集 next_run_time（add_job 返回的 Job 此时才就绪）
        for job_id, hh, mm in [("evo_pipeline_evening", 19, 30),
                               ("evo_pipeline_night", 21, 30)]:
            nxt = None
            try:
                j = sched.get_job(job_id)
                if j is not None and getattr(j, "next_run_time", None):
                    nxt = str(j.next_run_time)
            except Exception:
                pass
            EVO_JOBS.append({
                "id": job_id,
                "cron": f"mon-fri {hh:02d}:{mm:02d}",
                "next_run": nxt,
            })
        logger.info(f"[EvoScheduler] 已启动：{len(EVO_JOBS)} 个每日任务 "
                    f"(mon-fri 19:30 / 21:30)，管线 = {_pipeline_cmd()}")
        return sched
    except Exception as e:
        logger.error(f"[EvoScheduler] 启动失败（接口不受影响，可手动触发）: {e}")
        return None
