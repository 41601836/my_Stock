#!/bin/bash

# 获取当前脚本所在目录
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=================================================="
echo " 🚀 正在启动【鞋底刺刺向心底】量化策略控制台..."
echo "=================================================="

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
    trap "kill $BACKEND_PID $FRONTEND_PID" SIGINT
    wait $BACKEND_PID $FRONTEND_PID
fi
