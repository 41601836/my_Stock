# -*- coding: utf-8 -*-
"""临时冒烟脚本：阶段 3 拥挤度 + 衰减 5 接口验证（用后可删）"""
import sys, os, json

sys.path.insert(0, "/Users/lyu/Documents/my_Stock/web/backend")
os.chdir("/Users/lyu/Documents/my_Stock/web/backend")

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)
print("=" * 70)
print("SMOKE 阶段3：拥挤度 + 衰减 5 接口")
print("=" * 70)

# 1. /api/evo/crowding/status
print("\n[1/5] GET /api/evo/crowding/status:")
r = client.get("/api/evo/crowding/status")
assert r.status_code == 200, r.status_code
d = r.json()
print(f"    date={d.get('date')}, count={d.get('count')}, summary={d.get('summary')}")
for f in (d.get("factors") or [])[:6]:
    bar = "#" * int((f.get("crowding_score") or 0) * 30)
    print(f"      {f['factor_name']:34s} {f['crowding_score']:.3f} |{bar:<30}| {f['action']}")
print("    PASS" if d.get("count") else "    EMPTY")

# 2. /api/evo/crowding/history
print("\n[2/5] GET /api/evo/crowding/history?factor_name=inter_overshoot_reversal:")
r = client.get("/api/evo/crowding/history", params={"factor_name": "inter_overshoot_reversal"})
assert r.status_code == 200, r.status_code
d = r.json()
print(f"    count={d.get('count')} (最新1日快照)")
print("    PASS" if d.get("count") else "    EMPTY")

# 3. /api/evo/decay/alerts
print("\n[3/5] GET /api/evo/decay/alerts:")
r = client.get("/api/evo/decay/alerts")
assert r.status_code == 200, r.status_code
d = r.json()
print(f"    red={d.get('n_red')}, yellow={d.get('n_yellow')}, total={d.get('count')}")
for a in (d.get("alerts") or [])[:6]:
    print(f"      [{a['level']:6s}] {a['factor_name']:34s} {a['description']}")
print("    PASS" if d.get("count") is not None else "    FAIL")

# 4. /api/evo/decay/history
print("\n[4/5] GET /api/evo/decay/history?days=60:")
r = client.get("/api/evo/decay/history", params={"days": 60})
assert r.status_code == 200, r.status_code
d = r.json()
print(f"    count={d.get('count')} (期望 ~60日 x 13因子 = 780 行)")
print("    PASS" if d.get("count", 0) > 500 else "    EMPTY/TOO FEW")

# 5. /api/evo/compare/portfolio（验证拥挤度 action 与组合联动）
print("\n[5/5] GET /api/evo/compare/portfolio?top_n=5 (crowding 联动检查):")
r = client.get("/api/evo/compare/portfolio", params={"top_n": 5})
assert r.status_code == 200, r.status_code
d = r.json()
evo = d.get("evo", {})
print(f"    engine_flags: {evo.get('engine_flags')}")
print(f"    weight_mode={evo.get('weight_mode')}, weight_as_of={evo.get('weight_as_of')}")
print(f"    overlap_ratio={evo.get('classic_overlap_ratio')}, fused_by_fallback={evo.get('fused_by_fallback')}")
for s in (evo.get("stocks") or [])[:5]:
    print(f"      {s['ts_code']}: evo_score={s['evo_score']:+.4f} graham={s.get('graham_score')}")
print("    PASS" if evo.get("stocks") else "    EMPTY")

print("\nSMOKE END")
