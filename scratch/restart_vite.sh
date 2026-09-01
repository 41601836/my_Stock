#!/bin/bash
cd /Users/lyu/Documents/my_Stock/web/frontend
nohup npm run dev > /tmp/vite_dev.log 2>&1 &
echo "vite pid=$!"
