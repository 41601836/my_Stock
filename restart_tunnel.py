# -*- coding: utf-8 -*-
"""重启 cloudflared trycloudflare 穿透到 :5173（前端反代 /api 到 :8000）"""
import os, subprocess, time, re, sys, signal

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TUNNEL_LOG = os.path.join(PROJECT_ROOT, ".tunnel.log")
TUNNEL_URL_FILE = os.path.join(PROJECT_ROOT, ".tunnel_url")

# 1) 干掉所有 cloudflared 残留（不管是否已经挂）
killed = 0
try:
    out = subprocess.run(["pgrep", "-f", "cloudflared tunnel"], capture_output=True, text=True)
    for pid in out.stdout.strip().splitlines():
        if pid:
            try:
                os.kill(int(pid), signal.SIGKILL)
                killed += 1
            except ProcessLookupError:
                pass
except Exception:
    pass
time.sleep(1.2)
print(f"✅ 清理旧隧道进程：干掉 {killed} 个 cloudflared")

# 2) 清空日志 & URL 文件
open(TUNNEL_LOG, "w").close()
open(TUNNEL_URL_FILE, "w").close()

# 3) 启动新 tunnel（http2 协议，避免 UDP 被墙）
cmd = [
    "cloudflared", "tunnel",
    "--protocol", "http2",
    "--url", "http://localhost:5173",
    "--no-autoupdate",
]
logfp = open(TUNNEL_LOG, "w", buffering=1)
proc = subprocess.Popen(cmd, stdout=logfp, stderr=subprocess.STDOUT, cwd=PROJECT_ROOT)
print(f"🚀 新 cloudflared 启动 PID={proc.pid}，申请链接中（最多 45 秒）...")

# 4) 轮询等待 URL 出现
URL = None
pattern = re.compile(r'https://[a-zA-Z0-9._-]+\.trycloudflare\.com')
for i in range(1, 46):
    time.sleep(1)
    if proc.poll() is not None:
        print(f"❌ cloudflared 意外退出 exitcode={proc.returncode}，日志最后 20 行：")
        sys.stdout.flush()
        with open(TUNNEL_LOG, "r", errors="replace") as f:
            lines = f.readlines()
            print("".join(lines[-20:]))
        sys.exit(1)
    try:
        with open(TUNNEL_LOG, "r", errors="replace") as f:
            m = pattern.search(f.read())
            if m:
                URL = m.group(0)
                break
    except Exception:
        pass

if not URL:
    print("❌ 45 秒仍未拿到 URL，可能 Cloudflare 边缘节点拥堵，请稍后重试或手动 `cat .tunnel.log` 看原因。")
    sys.exit(2)

# 5) 写入文件并输出
with open(TUNNEL_URL_FILE, "w") as f:
    f.write(URL + "\n")

print()
print("=" * 65)
print(" 🎉  外网穿透已重新上线（每次重启 URL 都会变）")
print("=" * 65)
print(f"   🔗 前端控制台首页:       {URL}")
print(f"   📎 直达画像建仓决策页:   {URL}/position-pick")
print(f"   📎 直达因子权重配置:     {URL}/factors")
print(f"   📎 直达市场概览:         {URL}/overview")
print(f"   📎 直达扫描历史:         {URL}/scan-history")
print("-" * 65)
print(f"   ℹ️  tunnel 进程 PID:     {proc.pid}")
print(f"   ℹ️  日志/URL 落盘:       {TUNNEL_LOG} / {TUNNEL_URL_FILE}")
print("=" * 65)
print("  ⚠️  再次挂机时直接运行：")
print(f"     cd {PROJECT_ROOT} && python3 restart_tunnel.py")
