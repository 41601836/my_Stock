# -*- coding: utf-8 -*-
"""搜索多场景验证"""
import urllib.request
import json
import urllib.parse

def search(kw):
    r = urllib.request.urlopen("http://127.0.0.1:8000/api/market/search-stock?query=" + urllib.parse.quote(kw), timeout=30)
    d = json.loads(r.read())
    res = d.get("results") or d.get("stocks") or []
    return [(x["ts_code"], x["name"]) for x in res[:3]]

for kw in ["300159", "新研股份", "茅台", "600519", "MAOTAI", "00700"]:
    try:
        print(f"{kw!r:12} -> {search(kw)}")
    except Exception as e:
        print(f"{kw!r:12} -> ERR {e}")
