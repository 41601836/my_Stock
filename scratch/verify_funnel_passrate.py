# -*- coding: utf-8 -*-
"""验证生产链路三层漏斗通过率：仓位推荐 + 建仓扫描接口的 meta.portfolio / s3_* 字段"""
import json
import sys
import urllib.request

TARGETS = [
    ("仓位推荐", "http://127.0.0.1:8000/api/portrait/position-pick?max=10"),
    ("建仓扫描", "http://127.0.0.1:8000/api/scan-opportunities?max=5"),
]

ok = True
for name, url in TARGETS:
    print("==", name, "==")
    try:
        d = json.loads(urllib.request.urlopen(url, timeout=120).read())
    except Exception as e:
        print("  请求失败:", e)
        ok = False
        continue

    meta = d.get("meta", {}) or {}
    pf = meta.get("portfolio") or {}
    s3 = {k: v for k, v in meta.items() if k.startswith("s3_")}

    if pf:
        print("  meta.portfolio:", json.dumps(pf, ensure_ascii=False, default=str)[:500])
    if s3:
        print("  s3_* sidecar:", json.dumps(s3, ensure_ascii=False, default=str)[:400])
    if not pf and not s3:
        print("  !! meta.portfolio / s3_* 均缺失 | meta keys =", sorted(meta.keys()))
        ok = False

    rows = d.get("positions") or d.get("opportunities") or d.get("data") or []
    if isinstance(rows, list) and rows:
        grades = [r.get("portrait_grade") for r in rows[:10]]
        print("  rows=%d grades=%s" % (len(rows), grades))
        if "D" in grades:
            print("  ❌ 输出行中出现 D 级！")
            ok = False
    print()

print("🎉 生产链路通过率数据完整" if ok else "❌ 存在缺失或违规")
sys.exit(0 if ok else 1)
