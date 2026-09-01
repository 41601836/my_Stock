# -*- coding: utf-8 -*-
"""策略感知诊断验证：同一股票在不同策略下得分应有差异"""
import urllib.request
import json

def diag(ts_code, strategy):
    url = f"http://127.0.0.1:8000/api/market/diagnose?ts_code={ts_code}&strategy={strategy}"
    r = urllib.request.urlopen(url, timeout=120)
    return json.loads(r.read())

ts = "300159.SZ"
strategies = ["current", "base_bull", "base_range", "scanner", "strategy_0703.yaml"]

results = {}
for s in strategies:
    d = diag(ts, s)
    if d.get("error"):
        print(f"❌ {s}: error={d['error']}")
        continue
    radar = [x["subject"] for x in d.get("radar_data", [])]
    results[s] = {
        "final": d["final_score"],
        "n_factors": len(d.get("active_factors", [])),
        "radar": radar,
        "strengths": len(d.get("strengths", [])),
        "weaknesses": len(d.get("weaknesses", [])),
    }
    print(f"\n== {s} ==")
    print(f"  final_score={d['final_score']} | 因子数={results[s]['n_factors']}")
    print(f"  雷达: {radar}")
    print(f"  加分 {results[s]['strengths']} 项 / 扣分 {results[s]['weaknesses']} 项")
    if d.get("strengths"):
        print(f"  + {d['strengths'][0]}")
    if d.get("weaknesses"):
        print(f"  - {d['weaknesses'][0]}")

print()
if len(results) >= 2:
    scores = {s: v["final"] for s, v in results.items()}
    distinct = len(set(scores.values()))
    print(f"各策略 final_score: {scores}")
    print(f"=== {'✅ 策略间得分有差异' if distinct >= 2 else '⚠️ 得分全部相同，策略未生效'}（{distinct} 个不同值 / {len(scores)} 策略） ===")
