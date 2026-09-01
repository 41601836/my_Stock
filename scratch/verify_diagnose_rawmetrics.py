# -*- coding: utf-8 -*-
"""验证 /api/market/diagnose 返回 raw_metrics 4 字段"""
import json
import urllib.request

url = "http://127.0.0.1:8000/api/market/diagnose?ts_code=600519.SH"
d = json.loads(urllib.request.urlopen(url, timeout=120).read())

if d.get("error"):
    print("❌ error:", d.get("error"))
    print(d.get("trace", "")[:500])
    raise SystemExit(1)

rm = d.get("raw_metrics")
print("keys:", sorted(d.keys()))
print("raw_metrics =", rm)
assert rm is not None, "raw_metrics 缺失!"

wr, cc, mf, tr = rm["winner_rate"], rm["chip_concentration"], rm["net_mf_amount"], rm["turnover_rate_20d"]
print(f"  筹码胜率    winner_rate        = {wr}%  {'✅' if wr > 0 else '⚠️ 0'}")
print(f"  筹码集中度  chip_concentration = {cc}%  {'✅' if cc > 0 else '⚠️ 0'}")
print(f"  主力净流入  net_mf_amount      = {mf} 万元 → 前端显示 {mf/10000:.2f} 亿  {'✅' if mf != 0 else '⚠️ 0'}")
print(f"  20日换手率  turnover_rate_20d  = {tr}%  {'✅' if tr > 0 else '⚠️ 0'}")
print("✅ diagnose raw_metrics 4/4 字段齐备")

# 抽查另外两只股票（一只科创板一只创业板）
for code in ("688691.SH", "301560.SZ"):
    d2 = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:8000/api/market/diagnose?ts_code={code}", timeout=120).read())
    rm2 = d2.get("raw_metrics") or {}
    ok = all(k in rm2 for k in ("winner_rate", "chip_concentration", "net_mf_amount", "turnover_rate_20d"))
    print(f"  {code}: raw_metrics={'✅' if ok else '❌'} {rm2}")
