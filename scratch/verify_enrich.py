# -*- coding: utf-8 -*-
"""验证 3 个升级端点（用后可删）"""
import json, urllib.request

B = "http://localhost:8000/api/evo"
for url in ["/compare/scan", "/scan-opportunities?top_n=10",
            "/portrait/position-pick?top_n=10&strategy=left"]:
    try:
        with urllib.request.urlopen(B + url, timeout=90) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        print(url, "FAIL", e)
        continue
    if "compare" in url:
        evo = d.get("evo") or {}
        st = evo.get("stocks") or []
        has = sum(1 for s in st if (s.get("evo") or {}).get("cross_mean") is not None)
        cl = (d.get("classic") or {}).get("stocks") or []
        print(f"[compare/scan] classic={len(cl)} evo={len(st)} 有cross_mean={has} date={evo.get('factor_date')}")
        if st:
            print("   evo 第一只:", st[0].get("ts_code"), st[0].get("evo"))
    elif "scan" in url:
        co = d.get("classic_overlay") or {}
        st = co.get("stocks") or []
        has = sum(1 for s in st if isinstance(s.get("evo"), dict) and s["evo"].get("cross_mean") is not None)
        print(f"[scan-opp] stocks={len(st)} 有evo增强={has} factor_date={d.get('factor_date')}")
    else:
        co = d.get("classic_overlay") or {}
        pk = co.get("picks") or []
        adjs = [(p.get("ts_code"), p["evo"].get("evo_adjusted_score"))
                for p in pk if isinstance(p.get("evo"), dict) and p["evo"].get("evo_adjusted_score") is not None]
        print(f"[portrait-pick] picks={len(pk)} 有adjusted={len(adjs)} 前3: {adjs[:3]}")
