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

# 单飞锁 + 运行状态（供 /api/evo/scheduler/status 查询）
_lock = threading.Lock()
_state: Dict[str, Any] = {
    "status": "idle",          # idle / running / ok / error / skipped
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
    "duration_sec": None,
    "output_tail": "",
}

EVO_JOBS: List[Dict[str, Any]] = []   # 注册的 job 描述（status 接口用）
_scheduler: Optional[BackgroundScheduler] = None

# 子进程链：因子计算 → 动态权重 → 拥挤度/衰减监控（&& 串联，前者成功才跑后者）
# 第四步 ML 推理 / 第五步 文本采集+打分：enabled 时追加，"; ||" 隔离 —— 失败不拖垮前面步骤
EVO_TIMEOUT_SEC = 1800                # 因子 ~4min + 权重/监控/推理 ~2min + 文本 ~4min，余量充足


def _pipeline_cmd() -> str:
    py = sys.executable  # 与后端进程同一解释器（miniconda 3.13，apscheduler/fastapi 已验证）
    cmd = (
        f"PYTHONPATH=. {py} src/feature_engineering_evo.py && "
        f"PYTHONPATH=. {py} src/evo_dynamic_weights.py && "
        f"PYTHONPATH=. {py} src/evo_monitors.py"
    )
    if EvoConfig.get("lambdarank.enabled", False):
        cmd += (
            f" ; (PYTHONPATH=. {py} src/evo_ml_rank.py --predict "
            f"|| echo '[ML] predict failed (non-blocking)')"
        )
    if EvoConfig.get("text_factors.enabled", False):
        cmd += (
            f" ; (PYTHONPATH=. {py} src/evo_text_pipeline.py --daily "
            f"|| echo '[Text] daily failed (non-blocking)')"
        )
    return cmd


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
        _state.update(
            status="running",
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=None, exit_code=None,
        )
        logger.info(f"[EvoScheduler] 开始每日 EVO 管线: {_pipeline_cmd()}")
        try:
            proc = subprocess.run(
                ["bash", "-c", _pipeline_cmd()],
                cwd=PROJECT_ROOT, capture_output=True, text=True,
                timeout=EVO_TIMEOUT_SEC,
            )
            tail = ((proc.stdout or "") + (proc.stderr or ""))[-1500:]
            _state.update(
                status="ok" if proc.returncode == 0 else "error",
                exit_code=proc.returncode,
                output_tail=tail,
                duration_sec=round(time.time() - t0, 1),
                finished_at=time.strftime("%H:%M:%S"),
            )
            logger.info(f"[EvoScheduler] 管线结束 exit={proc.returncode} "
                        f"耗时 {time.time() - t0:.0f}s")
        except subprocess.TimeoutExpired:
            _state.update(
                status="error", exit_code=-9,
                output_tail=f"任务超时（>{EVO_TIMEOUT_SEC}s）已终止",
                duration_sec=round(time.time() - t0, 1),
                finished_at=time.strftime("%H:%M:%S"),
            )
            logger.error("[EvoScheduler] 管线超时终止")
        except Exception as e:
            _state.update(
                status="error", exit_code=-1, output_tail=str(e)[:1500],
                duration_sec=round(time.time() - t0, 1),
                finished_at=time.strftime("%H:%M:%S"),
            )
            logger.error(f"[EvoScheduler] 管线异常: {e}")
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
