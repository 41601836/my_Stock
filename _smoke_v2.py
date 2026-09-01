#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2 全链路烟雾测试：7 页面 + 12 API"""
import urllib.request, json

VITE = "http://127.0.0.1:5173"
pages = [
    ("/overview",        "市场宏观全览"),
    ("/scanner",         "建仓机会扫描"),
    ("/scan-history",    "扫描历史追踪"),
    ("/portrait",        "T+1画像分析"),
    ("/hunter",          "胜率猎手优化器"),
    ("/pick",            "核心策略仪表盘"),
    ("/diagnosis/600519.SH", "茅台诊断页"),
]
apis = [
    ("/api/status",                      "系统状态"),
    ("/api/market/overview",             "市场概览"),
    ("/api/market/regime-dashboard",     "路由仪表盘"),
    ("/api/market/theme-stocks?sector=%E4%BA%92%E8%81%94%E7%BD%91", "题材下钻(互联网)"),
    ("/api/portrait/analysis?days=60",   "画像分析(60天)"),
    ("/api/scan-opportunities?max=5",    "建仓扫描(5条)"),
    ("/api/scan-history?limit=10",       "扫描历史(10条)"),
    ("/api/market/search-stock?keyword=%E8%8C%85%E5%8F%B0", "股票搜索(茅台)"),
    ("/api/market/diagnose?ts_code=600519.SH", "个股诊断(茅台)"),
    ("/api/portrait/position-pick?max=10", "仓位推荐(10条)"),
    ("/api/hunter/result?days=60",       "胜率猎手结果"),
    ("/api/stats/summary",               "系统统计摘要"),
]

def hit(u, want_json=True):
    try:
        req = urllib.request.Request(u, headers={"User-Agent":"smoke-v2"})
        with urllib.request.urlopen(req, timeout=120) as r:
            b = r.read()
            if r.status != 200:
                return False, f"HTTP {r.status}"
            if want_json:
                try:
                    d = json.loads(b.decode("utf-8", errors="replace"))
                    if isinstance(d, dict) and d.get("error"):
                        return False, f"err={d['error'][:80]}"
                    return True, "OK"
                except Exception as e:
                    return False, f"JSON_ERR: {e}"
            else:
                low = b.lower()[:4096]
                if b"html" in low or b"vite" in low or b"title" in low or b"doctype" in low:
                    return True, "OK"
                return False, f"非HTML? {len(b)} bytes"
    except Exception as e:
        return False, f"EXC: {e}"

ok = 0
tot = len(pages) + len(apis)

print("="*68)
print("① 7 个前端页面 (Vite 渲染 HTML)")
print("="*68)
for p, name in pages:
    good, m = hit(f"{VITE}{p}", want_json=False)
    s = "✅" if good else "❌"
    if good: ok += 1
    print(f"  {s} {name.ljust(14)} [{p.split('?')[0].ljust(22)}] → {m}")

print()
print("="*68)
print("② 12 个后端接口 (经 Vite 代理转发)")
print("="*68)
for a, name in apis:
    good, m = hit(f"{VITE}{a}", want_json=True)
    s = "✅" if good else "❌"
    if good: ok += 1
    print(f"  {s} {name.ljust(20)} → {m}")

print()
print("="*68)
print(f"③ 汇总: {ok}/{tot} 通过  |  {'🔥 全绿' if ok == tot else '⚠️ 有失败项请排查'}")
print("="*68)
