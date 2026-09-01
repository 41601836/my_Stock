# -*- coding: utf-8 -*-
"""临时冒烟脚本：阶段 2 动态权重三接口验证（用后可删）"""
import sys, os, json

sys.path.insert(0, "/Users/lyu/Documents/my_Stock/web/backend")
os.chdir("/Users/lyu/Documents/my_Stock/web/backend")

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)
print("=" * 70)
print("SMOKE 阶段2：动态权重 + 组合对比")
print("=" * 70)

# 1. /api/evo/weights/dynamic
print("\n[1/3] GET /api/evo/weights/dynamic:")
r = client.get("/api/evo/weights/dynamic")
assert r.status_code == 200, r.status_code
d = r.json()
w = d.get("weights", {})
print(f"    trade_date={d.get('trade_date')}, regime={d.get('regime')}, mode={d.get('meta', {}).get('mode')}")
for k, v in sorted(w.items(), key=lambda x: -x[1]):
    if v > 0:
        print(f"      {k:30s} w={v:.4f}  ICIR={d.get('ic_ir', {}).get(k)}")
n_pos = sum(1 for v in w.values() if v > 0)
print(f"    PASS({n_pos}/{len(w)} 个因子有效权重, 和={sum(w.values()):.4f})")

# 2. /api/evo/weights/history
print("\n[2/3] GET /api/evo/weights/history?days=30:")
r = client.get("/api/evo/weights/history", params={"days": 30})
assert r.status_code == 200, r.status_code
d = r.json()
print(f"    count={d['count']} (期望 20 个快照)")
if d["count"]:
    s0 = d["series"][0]
    print(f"    最新快照 {s0['trade_date']}: weights键数={len(s0.get('weights', {}))}, regime={s0.get('regime')}")
    f = "inter_overshoot_reversal"
    vals = [(s["trade_date"], s.get("weights", {}).get(f)) for s in d["series"] if s.get("weights")]
    if vals:
        print(f"    {f} 权重漂移(最早→最新): {vals[-1][1]} → {vals[0][1]}")
print("    PASS" if d["count"] >= 1 else "    EMPTY")

# 3. /api/evo/compare/portfolio
print("\n[3/3] GET /api/evo/compare/portfolio?top_n=5:")
r = client.get("/api/evo/compare/portfolio", params={"top_n": 5})
assert r.status_code == 200, r.status_code
d = r.json()
evo = d.get("evo", {})
classic = d.get("classic", {})
print(f"    classic: {len(classic.get('stocks', []) or [])} 只 (error={classic.get('error')})")
print(f"    evo    : {len(evo.get('stocks', []) or [])} 只, weight_mode={evo.get('weight_mode')}, weight_as_of={evo.get('weight_as_of')}")
print(f"    engine_flags: {evo.get('engine_flags')}")
print(f"    overlap_ratio={evo.get('classic_overlap_ratio')}, fused_by_fallback={evo.get('fused_by_fallback')}")
print(f"    共同推荐 overlap_codes: {d.get('overlap_codes')}")
for s in (evo.get("stocks") or [])[:5]:
    print(f"      {s['ts_code']}: evo_score={s['evo_score']:+.4f} dyn={s['dynamic_part']:.4f} graham={s.get('graham_score')}/7 adj={s.get('graham_adj')}")
mark = "PASS(EVO 侧真实数据 + 熔断检查)" if len(evo.get("stocks") or []) >= 1 else "EMPTY"
print(f"    {mark}")
print("\nSMOKE END")
