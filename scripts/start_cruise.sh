#!/bin/bash
# ============================================================================
# start_cruise.sh —— Agent 自主进化巡航守护启动器 (P1)
# 用法: bash scripts/start_cruise.sh [--sleep-seconds 10]
# 特性:
#   1. nohup + disown 双保险，终端关闭 (SIGHUP) 不再杀死巡航进程
#   2. 时间戳日志文件 logs/cruise_<时间>.log，不覆盖历史日志
#   3. logs/cruise.pid 防重复启动，与后端 /api/agent/cruise/start 共用
#   4. run_agent 内部已注册 SIGHUP/SIGTERM/SIGINT 处理器，kill <pid> 可安全退出
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

PID_FILE=logs/cruise.pid
mkdir -p logs

# 防重复启动：PID 文件存在且进程存活则拒绝
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️ 巡航已在运行中 (PID $OLD_PID)，如需重启请先: kill $OLD_PID"
        exit 1
    fi
fi

LOG_FILE="logs/cruise_$(date +%Y%m%d_%H%M%S).log"
nohup python3 -u agent/run_agent.py --auto "$@" >> "$LOG_FILE" 2>&1 &
CRUISE_PID=$!
disown || true
echo "$CRUISE_PID" > "$PID_FILE"

echo "🚀 巡航已启动: PID $CRUISE_PID | 日志: $LOG_FILE"
echo "   查看日志: tail -f $LOG_FILE"
echo "   停止: kill $CRUISE_PID  (SIGTERM 会恢复 config.yaml 并导出报告)"
