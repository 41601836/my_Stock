# -*- coding: utf-8 -*-
"""诊股看盘页 3 个依赖接口检查"""
import urllib.request
import json
import urllib.parse

BASE = "http://127.0.0.1:8000"

def get(path):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=90)
        return ("OK", json.loads(r.read()))
    except Exception as e:
        return ("ERR", str(e))

s, d = get("/api/strategies")
print("1) /api/strategies:", s)
if s == "OK":
    print("   type:", type(d).__name__, "keys/len:", list(d.keys()) if isinstance(d, dict) else len(d))
    print("   sample:", json.dumps(d, ensure_ascii=False)[:200])
else:
    print("   err:", d)

s, d = get("/api/market/search-stock?query=" + urllib.parse.quote("300159"))
print("2) /api/market/search-stock:", s)
if s == "OK":
    print("   results:", len(d.get("results", [])), json.dumps(d.get("results", [])[:1], ensure_ascii=False)[:150])
else:
    print("   err:", d)

s, d = get("/api/market/diagnose?ts_code=300159.SZ&strategy=current")
print("3) /api/market/diagnose(300159.SZ):", s)
if s == "OK":
    print("   name:", d.get("name"), "| error:", d.get("error"))
    p = d.get("portrait", {})
    print("   portrait:", p.get("total_score"), p.get("total_grade"))
else:
    print("   err:", d)
