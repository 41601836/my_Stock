# -*- coding: utf-8 -*-
"""第二轮：用前端真实字段名检查 + 深挖空数据问题"""
import urllib.request
import json

BASE = "http://127.0.0.1:8000"

def get(path):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=120)
        return json.loads(r.read())
    except Exception as e:
        return {"__error__": str(e)}

issues = []

def check(name, cond, detail=""):
    status = "OK " if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" | {detail}" if detail else ""))
    if not cond:
        issues.append(f"{name}: {detail}")

print("=" * 70)
print("A. /api/portrait/analysis 前端真实字段")
print("=" * 70)
d = get("/api/portrait/analysis?days=60")
s = d.get("summary", {})
check("summary.total > 0", s.get("total", 0) > 0, f"total={s.get('total')} win_rate={s.get('win_rate')}")
check("summary.win_rate 有值", s.get("win_rate") is not None, f"{s.get('win_rate')}")
gs = d.get("grade_stats", [])
check("grade_stats 非空", len(gs) > 0, f"len={len(gs)}")
dw = d.get("daily_win_rate", [])
check("daily_win_rate 非空", len(dw) > 0, f"len={len(dw)}")
sb = d.get("score_buckets", [])
check("score_buckets 非空", len(sb) > 0, f"len={len(sb)}")
tu = d.get("top_up_stocks", [])
td = d.get("top_dn_stocks", [])
check("top_up/top_dn 非空", len(tu) > 0 and len(td) > 0, f"up={len(tu)} dn={len(td)}")

print()
print("=" * 70)
print("B. /api/portrait/position-pick picks 为空 → 深挖 funnel")
print("=" * 70)
d = get("/api/portrait/position-pick?limit=10")
print("  funnel:", json.dumps(d.get("funnel", {}), ensure_ascii=False))
print("  meta:", json.dumps(d.get("meta", {}), ensure_ascii=False)[:300])
check("picks 非空", len(d.get("picks", [])) > 0, f"len={len(d.get('picks', []))}")

print()
print("=" * 70)
print("C. /api/scan-history daily 为空 → 深挖")
print("=" * 70)
d = get("/api/scan-history?limit=10")
print("  summary:", json.dumps(d.get("summary", {}), ensure_ascii=False)[:300])
print("  meta:", json.dumps(d.get("meta", {}), ensure_ascii=False)[:300])
print("  timing:", json.dumps(d.get("timing", {}), ensure_ascii=False)[:200])
daily = d.get("daily", {})
check("daily 非空", len(daily) > 0, f"type={type(daily).__name__} len={len(daily)}")
if isinstance(daily, list) and daily:
    print("  daily[0]:", json.dumps(daily[0], ensure_ascii=False)[:300])
elif isinstance(daily, dict):
    k0 = list(daily.keys())[:3]
    print("  daily keys 样例:", k0)
    check("timing.alerts 非空", len(d.get("timing", {}).get("alerts", [])) > 0, f"len={len(d.get('timing', {}).get('alerts', []))}")

print()
print("=" * 70)
print("D. /api/scan-opportunities meta 与 big_net_inflow")
print("=" * 70)
d = get("/api/scan-opportunities?limit=9")
m = d.get("meta", {})
check("meta.factor_date 非空", bool(m.get("factor_date")), f"{m.get('factor_date')} scan={m.get('scan_date')}")
stocks = d.get("stocks", [])
check("stocks 非空", len(stocks) > 0, f"len={len(stocks)}")
bad_inflow = [s["ts_code"] for s in stocks if s.get("big_net_inflow") in (None, 0)]
check("big_net_inflow 全部非空非零", len(bad_inflow) == 0, f"零/空: {bad_inflow}")
bad_wr = [s["ts_code"] for s in stocks if not s.get("winner_rate")]
check("winner_rate 全部非零", len(bad_wr) == 0, f"零/空: {bad_wr}")
bad_fs = [s["ts_code"] for s in stocks if s.get("factor_score") in (None, 0)]
check("factor_score 全部非零", len(bad_fs) == 0, f"零/空: {bad_fs}")

print()
print("=" * 70)
print("E. theme-stocks / style-stocks 用正确参数重测")
print("=" * 70)
import urllib.parse
d = get("/api/market/theme-stocks?sector=" + urllib.parse.quote("半导体") + "&sort=desc")
check("theme-stocks 无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
ts = d.get("stocks") or d.get("items") or []
check("theme-stocks 非空", len(ts) > 0, f"len={len(ts)}")

# 取 overview 里的最新交易日
ov = get("/api/market/overview")
latest = ov.get("price_latest_date", "")
d = get("/api/market/style-stocks?date=" + latest + "&style=" + urllib.parse.quote("高换手风格 (Turnover)"))
check("style-stocks 无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
ss = d.get("stocks") or d.get("items") or []
check("style-stocks 非空", len(ss) > 0, f"len={len(ss)} date={latest}")

print()
print("=" * 70)
print("F. /api/market/sector-opportunities 板块机会")
print("=" * 70)
d = get("/api/market/sector-opportunities?sector=" + urllib.parse.quote("半导体"))
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
so = d.get("stocks") or []
check("板块机会非空", len(so) > 0, f"len={len(so)}")

print()
print("=" * 70)
print(f"汇总: {len(issues)} 个问题")
print("=" * 70)
for i in issues:
    print(f"  ❌ {i}")
if not issues:
    print("  ✅ 全部通过")
