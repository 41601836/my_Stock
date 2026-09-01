# -*- coding: utf-8 -*-
"""临时冒烟脚本：EVO 每日调度器验证（status + 手动 run 全管线，用后可删）"""
import sys, os, time

sys.path.insert(0, "/Users/lyu/Documents/my_Stock/web/backend")
os.chdir("/Users/lyu/Documents/my_Stock/web/backend")

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)
print("=" * 70)
print("SMOKE 调度器：status + 手动 run 全管线")
print("=" * 70)

# 1. status（应显示 enabled=True + 2 jobs）
print("\n[1/2] GET /api/evo/scheduler/status:")
r = client.get("/api/evo/scheduler/status")
assert r.status_code == 200, r.status_code
d = r.json()
print(f"    enabled={d.get('enabled')}")
print(f"    cron  ={d.get('cron')}")
for j in d.get("jobs", []):
    print(f"    job: {j['id']} @ {j['cron']} → next_run={j['next_run']}")
assert d.get("enabled") is True and len(d.get("jobs", [])) == 2, "调度器未正确启动"
print("    PASS(调度器已启动, 2 jobs 注册)")

# 2. 手动触发 + 轮询到完成
print("\n[2/2] POST /api/evo/scheduler/run (真实跑一次全管线):")
r = client.post("/api/evo/scheduler/run")
assert r.status_code == 200, r.status_code
print(f"    触发: {r.json()}")

deadline = time.time() + 600  # 最长等 10 分钟
last = {}
while time.time() < deadline:
    time.sleep(15)
    s = client.get("/api/evo/scheduler/status").json().get("last_run", {})
    last = s
    st = s.get("status")
    print(f"    [{time.strftime('%H:%M:%S')}] status={st} elapsed={s.get('duration_sec')}")
    if st not in ("running",):
        break

print(f"\n    最终状态: {last.get('status')}, exit={last.get('exit_code')}, 耗时={last.get('duration_sec')}s")
tail = (last.get("output_tail") or "")
for line in tail.strip().splitlines()[-8:]:
    print(f"      | {line}")
mark = "PASS(全管线成功)" if last.get("status") == "ok" and last.get("exit_code") == 0 else "FAIL"
print(f"\n    {mark}")
print("SMOKE END")
