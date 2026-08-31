#!/bin/bash

# 获取当前脚本所在目录
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=================================================="
echo " 🚀 正在启动【鞋底刺 向心刺】量化策略控制台..."
echo "=================================================="

# ── 穿网隧道（cloudflared）──────────────────────────────
TUNNEL_LOG="$DIR/.tunnel.log"
TUNNEL_URL_FILE="$DIR/.tunnel_url"

# 清空旧记录并清理可能残留的旧隧道进程
> "$TUNNEL_LOG"
> "$TUNNEL_URL_FILE"
pkill -9 cloudflared 2>/dev/null || true

if command -v cloudflared &> /dev/null; then
    echo "🌐 正在申请穿网链接（cloudflare tunnel - http2模式）..."
    # 后台启动隧道，指定 http2 规避部分运营商/代理拦截 QUIC UDP 7844 端口问题
    cloudflared tunnel --protocol http2 --url http://localhost:5173 --no-autoupdate > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!

    # 等待最多 30 秒，直到拿到链接
    for i in $(seq 1 30); do
        URL=$(grep -aEo 'https://[a-zA-Z0-9._-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -1)
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
    fi
else
    echo "⚠️  未检测到 cloudflared，跳过穿网隧道"
fi
# ─────────────────────────────────────────────────────────

# 检查是否安装了 npm (使用 npx concurrently 来同时运行前后端，日志更清晰)
if command -v npx &> /dev/null; then
    echo "✅ 侦测到 npm 环境，即将启动前后端融合进程..."
    # 使用 concurrently 同时启动前后端，并分别着色
    npx concurrently \
        --kill-others \
        --names "BACKEND,FRONTEND" \
        --prefix-colors "blue.bold,green.bold" \
        "cd web/backend && uvicorn app:app --host 0.0.0.0 --port 8000" \
        "cd web/frontend && npm run dev"
else
    # 降级方案：如果没有 npm/npx（通常不可能，因为用了 Vite），则使用 bash 后台运行
    echo "⚠️ 未侦测到 npx，使用基础 Bash 进程启动..."
    cd web/backend
    uvicorn app:app --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!
    
    cd ../frontend
    npm run dev &
    FRONTEND_PID=$!
    
    # 捕获 Ctrl+C 以便干净地关闭
    trap "kill $BACKEND_PID $FRONTEND_PID $TUNNEL_PID" SIGINT
    wait $BACKEND_PID $FRONTEND_PID
fi
