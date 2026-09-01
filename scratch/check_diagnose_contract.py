# -*- coding: utf-8 -*-
"""验证 diagnose 接口契约字段完整性"""
import urllib.request
import json

r = urllib.request.urlopen("http://127.0.0.1:8000/api/market/diagnose?ts_code=300159.SZ&strategy=scanner", timeout=90)
d = json.loads(r.read())

need = ["ts_code", "name", "close", "pct_chg", "final_score", "strategy",
        "radar_data", "strengths", "weaknesses", "raw_metrics",
        "valuation", "technical", "chips", "factor", "portrait"]
ok = True
for k in need:
    v = d.get(k)
    has = k in d and v is not None
    ok = ok and has
    preview = str(v)[:60] if not isinstance(v, (list, dict)) else f"len={len(v)}"
    print(f"  [{'OK' if has else 'MISS'}] {k}: {preview}")

print()
print("radar_data[0]:", json.dumps(d["radar_data"][0], ensure_ascii=False) if d.get("radar_data") else "N/A")
print("strengths:", d.get("strengths"))
print("weaknesses:", d.get("weaknesses"))
print("close:", d.get("close"), "pct_chg:", d.get("pct_chg"), "final_score:", d.get("final_score"))
print()
print("===", "ALL FIELDS OK" if ok else "MISSING FIELDS", "===")
