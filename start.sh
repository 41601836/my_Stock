#!/bin/bash
# 不使用 set -e，因为 grep/curl 在探测时返回非零是正常行为，
# set -e 会误杀脚本（如穿网 URL 未就绪时 grep 返回 1 → 脚本退出）
set -uo pipefail

# ================================================================
# start.sh — 鞋底刺 向心刺 | 量化策略控制台 生产环境启动脚本
# ----------------------------------------------------------------
# 架构：前端预构建到 web/frontend/dist，后端 uvicorn 直接托管静态文件
#       单进程同时提供 API + 前端页面，无需 Vite dev server / 代理
# 端口：后端 8000（同时服务 API 和静态页面）
# ================================================================

# 获取当前脚本所在目录（项目根）
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# ── 子命令：stop / restart / status ──────────────────────────
PID_DIR="$DIR/.run"
PID_FILE="$PID_DIR/app.pid"

case "${1:-}" in
    stop)
        echo "🛑 正在停止服务..."
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE" 2>/dev/null || true)
            if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
                kill "$PID" 2>/dev/null || true
                sleep 2
                kill -9 "$PID" 2>/dev/null || true
                echo "✅ 后端进程 $PID 已停止"
            else
                echo "⚠️  PID $PID 不存在或已退出"
            fi
            rm -f "$PID_FILE"
        else
            echo "⚠️  未找到 PID 文件，服务可能未在运行"
        fi
        pkill -9 cloudflared 2>/dev/null || true
        exit 0
        ;;
    restart)
        echo "🔄 正在重启..."
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE" 2>/dev/null || true)
            [ -n "$PID" ] && kill "$PID" 2>/dev/null || true
            sleep 2
            [ -n "$PID" ] && kill -9 "$PID" 2>/dev/null || true
            rm -f "$PID_FILE"
        fi
        pkill -9 cloudflared 2>/dev/null || true
        # 重新执行自身（不带 stop/restart 参数）
        exec bash "$0"
        ;;
    status)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE" 2>/dev/null || true)
            if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
                echo "✅ 服务运行中 (PID $PID)"
                PORT="${PORT:-8000}"
                curl -sf "http://localhost:$PORT/api/status" > /dev/null 2>&1 \
                    && echo "✅ API 响应正常" \
                    || echo "⚠️  API 无响应"
                exit 0
            fi
        fi
        echo "❌ 服务未运行"
        exit 1
        ;;
esac

echo "=================================================="
echo " 🚀 正在启动【鞋底刺 向心刺】量化策略控制台 (生产模式)..."
echo "=================================================="

# ── 环境变量 ──────────────────────────────────────────────────
export PYTHONUNBUFFERED=1
export PYTHONPATH="$DIR:${PYTHONPATH:-}"

# ── 端口与日志路径（PID_DIR/PID_FILE 已在上方声明）────────────
PORT="${PORT:-8000}"
LOG_DIR="$DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"

mkdir -p "$PID_DIR" "$LOG_DIR"

# ── 清理可能残留的旧进程 ──────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  检测到旧进程 (PID $OLD_PID)，正在停止..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# ── 步骤 1：构建前端（若 dist 缺失或需要刷新）────────────────
FRONTEND_DIR="$DIR/web/frontend"
DIST_DIR="$FRONTEND_DIR/dist"

# 检查是否需要重新构建（dist 不存在 或 --build 参数）
NEED_BUILD=false
if [ ! -f "$DIST_DIR/index.html" ]; then
    NEED_BUILD=true
fi

if [ "${1:-}" = "--build" ] || [ "${1:-}" = "build" ]; then
    NEED_BUILD=true
fi

if [ "$NEED_BUILD" = true ]; then
    echo "📦 正在构建前端静态资源..."
    cd "$FRONTEND_DIR"
    npm install --silent 2>/dev/null || npm install
    npm run build
    cd "$DIR"
    echo "✅ 前端构建完成 → $DIST_DIR"
else
    echo "✅ 前端 dist 已存在，跳过构建（使用 --build 参数强制重建）"
fi

# ── 步骤 2：启动后端（生产模式，无 reload）────────────────────
echo ""
echo "⚙️  正在启动后端服务 (uvicorn 纯生产模式，无 reload)..."

cd "$DIR/web/backend"

# 使用 nohup + 后台运行，日志写入文件
# 通过 app.py 的 __main__ dual-stack 启动器：同时监听 IPv4+IPv6，
# 解决 macOS localhost 双记录 Happy Eyeballs 竞态造成的
# 浏览器间歇性 ERR_CONNECTION_REFUSED / OFFLINE / Failed to fetch。
PORT="$PORT" WORKERS=1 RELOAD=false nohup "$(which python3)" app.py \
    > "$BACKEND_LOG" 2>&1 &

BACKEND_PID=$!
echo "$BACKEND_PID" > "$PID_FILE"

cd "$DIR"

# ── 步骤 3：等待后端就绪 ──────────────────────────────────────
echo "⏳ 等待后端就绪..."
READY=false
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$PORT/api/status" > /dev/null 2>&1; then
        READY=true
        break
    fi
    # 检查进程是否还活着
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "❌ 后端进程意外退出！最近日志："
        tail -30 "$BACKEND_LOG"
        exit 1
    fi
    sleep 1
done

if [ "$READY" = false ]; then
    echo "⚠️  后端启动超时（30s），请检查 $BACKEND_LOG"
    tail -20 "$BACKEND_LOG"
    exit 1
fi

# ── 步骤 4：穿网隧道（可选，cloudflared）──────────────────────
TUNNEL_LOG="$DIR/.tunnel.log"
TUNNEL_URL_FILE="$DIR/.tunnel_url"
> "$TUNNEL_LOG"
> "$TUNNEL_URL_FILE"
pkill -9 cloudflared 2>/dev/null || true

if command -v cloudflared &> /dev/null; then
    echo "🌐 正在申请穿网链接（cloudflare tunnel - http2模式）..."
    cloudflared tunnel --protocol http2 --url "http://localhost:$PORT" --no-autoupdate > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!

    for i in $(seq 1 30); do
        URL=$(grep -aEo 'https://[a-zA-Z0-9._-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1 || true)
        if [ -n "$URL" ]; then
            echo "$URL" > "$TUNNEL_URL_FILE"
            echo ""
            echo "  ╔══════════════════════════════════════════════╗"
            echo "  ║  🔗 穿网链接已就绪（每次重启会变）           ║"
            echo "  ║  $URL"
            echo "  ╚══════════════════════════════════════════════╝"
            echo ""
            break
        fi
        sleep 1
    done

    if [ ! -s "$TUNNEL_URL_FILE" ]; then
        echo "⚠️  穿网链接获取超时，请查看 .tunnel.log"
        # 超时后终止 cloudflared 进程，避免遗留
        [ -n "${TUNNEL_PID:-}" ] && kill "$TUNNEL_PID" 2>/dev/null || true
        TUNNEL_PID=""
    fi
else
    echo "⚠️  未检测到 cloudflared，跳过穿网隧道"
fi

# ── 步骤 5：输出启动信息 ──────────────────────────────────────
LOCAL_URL="http://localhost:$PORT"
TUNNEL_URL=$(cat "$TUNNEL_URL_FILE" 2>/dev/null || true)

echo ""
echo "=================================================="
echo " ✅ 【鞋底刺 向心刺】已成功启动！"
echo "=================================================="
echo "  📡 本地访问:  $LOCAL_URL"
if [ -n "$TUNNEL_URL" ]; then
    echo "  🌐 穿网访问:  $TUNNEL_URL"
fi
echo "  📋 后端 PID:  $BACKEND_PID  (pid 文件: $PID_FILE)"
echo "  📝 日志文件:  $BACKEND_LOG"
echo ""
echo "  停止服务:  kill \$(cat $PID_FILE)  或  bash start.sh stop"
echo "  重新构建前端:  bash start.sh --build"
echo "=================================================="
echo ""

# ── 前台保持运行：始终等待后端进程（核心服务）──────────────────
# 穿网隧道进程是附属的，不应决定脚本生命周期；
# 后端进程退出时脚本自然结束，Ctrl+C 时 cleanup 统一清理。
cleanup() {
    echo ""
    echo "🛑 正在停止服务..."
    if [ -n "${TUNNEL_PID:-}" ]; then
        kill "$TUNNEL_PID" 2>/dev/null || true
    fi
    if [ -f "$PID_FILE" ]; then
        kill "$(cat "$PID_FILE")" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi
    pkill -9 cloudflared 2>/dev/null || true
    echo "✅ 已停止"
}

trap cleanup SIGINT SIGTERM

wait "$BACKEND_PID"
