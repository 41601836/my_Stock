# -*- coding: utf-8 -*-
"""外部交叉验证：东财搜索/行情接口实测这些代码是否真实存在（用后可删）"""
import json, urllib.request, urllib.parse

CODES = ["920427", "920227", "600610", "600622", "600604", "600594", "600641", "600479", "600881", "600691"]

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

print("=== 1) 东财搜索建议接口（type=14 股票） ===")
for c in CODES:
    try:
        url = ("https://searchadapter.eastmoney.com/api/suggest/get?input=" + c +
               "&type=14&token=D43BF722C8E33BDC906FB84D85E326E8&count=4")
        d = json.loads(http_get(url))
        items = (d.get("QuotationCodeTable") or {}).get("Data") or []
        if items:
            info = " | ".join(f"{x.get('Code')}({x.get('Name')}) MktNum={x.get('MktNum')} SecuScale={x.get('SecurityType')}" for x in items[:2])
            print(f"{c}: ✅ {info}")
        else:
            print(f"{c}: ❌ 东财无结果")
    except Exception as e:
        print(f"{c}: ⚠️ {type(e).__name__}: {str(e)[:60]}")

print("\n=== 2) 东财行情 API（secid 探测：SH=1.x / SZ=0.x / BJ=0.x? 实测） ===")
def quote(secid):
    url = (f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}"
           f"&fields=f43,f57,f58,f107&invt=2&fltt=1")
    return json.loads(http_get(url))

for c in CODES:
    found = None
    for mkt in ("0", "1"):
        try:
            d = quote(f"{mkt}.{c}")
            data = d.get("data")
            if data and data.get("f57"):
                found = f"secid={mkt}.{c} code={data.get('f57')} name={data.get('f58')}"
                break
        except Exception:
            pass
    print(f"{c}: {'✅ ' + found if found else '❌ 行情接口无数据'}")
