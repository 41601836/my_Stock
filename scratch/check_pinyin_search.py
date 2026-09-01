# -*- coding: utf-8 -*-
"""拼音搜索全场景验证"""
import urllib.request
import json
import urllib.parse

def search(kw):
    r = urllib.request.urlopen(
        "http://127.0.0.1:8000/api/market/search-stock?query=" + urllib.parse.quote(kw), timeout=30)
    d = json.loads(r.read())
    res = d.get("results") or d.get("stocks") or []
    return [(x["ts_code"], x["name"]) for x in res[:3]]

cases = [
    # 全拼
    ("maotai", "贵州茅台 600519"),
    ("guizhoumaotai", "贵州茅台 600519"),
    ("dongfangcaifu", "东方财富 300059"),
    ("jinshanbangong", "金山办公 688111"),
    # 简拼
    ("gzmt", "贵州茅台 600519"),
    ("dfcf", "东方财富 300059"),
    ("xygf", "新研股份 300159"),
    ("gldq", "格力电器 000651"),
    ("hkws", "海康威视 002415"),
    # 多音字（简拼）
    ("cqpj", "重庆啤酒 600132"),
    ("caqc", "长安汽车 000625"),
    ("xmwy", "厦门钨业 600549"),
    # 混合字母
    ("tcl", None),  # TCL科技
    # 原有场景回归
    ("300159", "代码"),
    ("新研股份", "中文名"),
    ("茅台", "中文名"),
]
fails = 0
for kw, expect in cases:
    try:
        got = search(kw)
        hit = bool(got)
        status = "OK " if hit else "EMPTY"
        if not hit:
            fails += 1
        print(f"[{status}] {kw!r:18} -> {got}" + (f"   (期望: {expect})" if expect else ""))
    except Exception as e:
        fails += 1
        print(f"[ERR ] {kw!r:18} -> {e}")

print()
print(f"=== {len(cases) - fails}/{len(cases)} 通过, {fails} 个空/错误 ===")
