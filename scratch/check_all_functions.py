# -*- coding: utf-8 -*-
"""逐项检查所有 API 的实际数据质量（非零、字段完整、数值合理）"""
import urllib.request
import json

BASE = "http://127.0.0.1:8000"

def get(path):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=60)
        return json.loads(r.read())
    except Exception as e:
        return {"__error__": str(e)}

issues = []

def check(name, cond, detail=""):
    status = "OK " if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" | {detail}" if detail else ""))
    if not cond:
        issues.append(f"{name}: {detail}")

def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

print("=" * 70)
print("① /api/market/overview 市场概览")
print("=" * 70)
d = get("/api/market/overview")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
t = d.get("today", {})
check("today.total_amount_yi > 0", is_num(t.get("total_amount_yi")) and t.get("total_amount_yi", 0) > 0, f"{t.get('total_amount_yi')}")
check("today.up_count > 0", t.get("up_count", 0) > 0, f"{t.get('up_count')}")
ad = d.get("adv_dec", {})
check("adv_dec.up > 0", ad.get("up", 0) > 0, f"up={ad.get('up')} down={ad.get('down')}")
tp = d.get("temperature", {})
check("temperature.median_winner > 0", is_num(tp.get("median_winner")) and tp.get("median_winner", 0) > 0, f"{tp}")
check("temperature.overbought_ratio > 0", tp.get("overbought_ratio", 0) > 0, f"{tp.get('overbought_ratio')}")
check("regime in BULL/RANGE/BEAR", d.get("regime") in ("BULL", "RANGE", "BEAR"), f"{d.get('regime')}")
sr = d.get("style_rotation", [])
check("style_rotation 长度>=5", len(sr) >= 5, f"len={len(sr)}")
if sr:
    last = sr[-1]
    vals = [last.get(k) for k in ["高换手风格 (Turnover)", "筹码锁仓风格 (Chips)", "大单大市风格 (Inflow)"]]
    check("style_rotation 最新日三值非None", all(v is not None for v in vals), f"{vals}")
sf = d.get("sector_money_flow", [])
top = next((s for s in sf if s.get("type") == "top"), {}).get("sectors", [])
bot = next((s for s in sf if s.get("type") == "bottom"), {}).get("sectors", [])
check("sector top 非空", len(top) > 0, f"len={len(top)}")
check("sector top net_inflow_yi 非全零", any(s.get("net_inflow_yi", 0) != 0 for s in top), f"first={top[0] if top else None}")
check("sector bottom 非空", len(bot) > 0, f"len={len(bot)}")
th = d.get("theme_popularity", [])
check("theme_popularity 非空", len(th) > 0, f"len={len(th)}")
ee = d.get("earning_effect_history", [])
check("earning_effect_6 非空且金额非零", len(ee) >= 6 and any(e.get("amount_yi", 0) > 0 for e in ee), f"len={len(ee)} amounts={[e.get('amount_yi') for e in ee[:3]]}")
bpo = d.get("build_position_opportunities")
bpo_list = []
if isinstance(bpo, dict):
    bpo_list = bpo.get("stocks") or bpo.get("opportunities") or []
elif isinstance(bpo, list):
    bpo_list = bpo
check("build_position_opportunities 非空", len(bpo_list) > 0, f"type={type(bpo).__name__} len={len(bpo_list)}")
if bpo_list:
    b0 = bpo_list[0]
    check("扫描项 net_mf_yi 非零", b0.get("net_mf_yi", 0) != 0, f"{b0.get('ts_code')} net_mf_yi={b0.get('net_mf_yi')} big_net_inflow={b0.get('big_net_inflow')}")

print()
print("=" * 70)
print("② /api/market/regime-dashboard 路由仪表盘")
print("=" * 70)
d = get("/api/market/regime-dashboard")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
ind = d.get("indicators", {})
for k in ["return_20d", "mdd_5d", "vol_20d", "up_ratio", "return_5d"]:
    check(f"indicators.{k} 存在", k in ind and is_num(ind[k]), f"{ind.get(k)}")
check("position_advice.advice 非空", bool(d.get("position_advice", {}).get("advice")), f"{d.get('position_advice', {}).get('advice', '')[:30]}")

print()
print("=" * 70)
print("③ /api/portrait/analysis?days=60 画像分析")
print("=" * 70)
d = get("/api/portrait/analysis?days=60")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
check("daily_stats 非空", len(d.get("daily_stats", [])) > 0, f"len={len(d.get('daily_stats', []))}")
tiers = d.get("tier_stats") or d.get("tier_summary") or []
check("tier_stats 非空", len(tiers) > 0, f"len={len(tiers)} keys={list(d.keys())[:15]}")

print()
print("=" * 70)
print("④ /api/portrait/position-pick 仓位推荐")
print("=" * 70)
d = get("/api/portrait/position-pick?limit=10")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
items = d.get("items") or d.get("positions") or d.get("data") or []
check("推荐列表非空", len(items) > 0, f"len={len(items)} keys={list(d.keys())[:15]}")
if items:
    i0 = items[0] if isinstance(items, list) else items
    if isinstance(i0, dict):
        check("推荐项含 ts_code/name", bool(i0.get("ts_code")) , f"{i0.get('ts_code')} {i0.get('name')}")

print()
print("=" * 70)
print("⑤ /api/scan-opportunities 建仓扫描")
print("=" * 70)
d = get("/api/scan-opportunities?limit=5")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
opp = d.get("opportunities") or d.get("items") or []
check("扫描机会非空", len(opp) > 0, f"len={len(opp)} keys={list(d.keys())[:15]}")
if opp:
    o0 = opp[0]
    check("扫描项 net_mf_yi 非零", o0.get("net_mf_yi", 0) != 0, f"{o0.get('ts_code')} net_mf_yi={o0.get('net_mf_yi')}")
    check("扫描项 factor_date 非空", bool(o0.get("factor_date") or o0.get("trade_date")), f"{o0.get('factor_date')} {o0.get('trade_date')}")

print()
print("=" * 70)
print("⑥ /api/scan-history 扫描历史")
print("=" * 70)
d = get("/api/scan-history?limit=10")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
hist = d.get("history") or d.get("items") or []
check("历史非空", len(hist) > 0, f"len={len(hist)} keys={list(d.keys())[:15]}")

print()
print("=" * 70)
print("⑦ /api/market/diagnose 个股诊断(600519.SH)")
print("=" * 70)
d = get("/api/market/diagnose?ts_code=600519.SH")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
check("name=贵州茅台", d.get("name") == "贵州茅台", f"{d.get('name')}")
val = d.get("valuation", {})
check("valuation.pe_ttm > 0", val.get("pe_ttm", 0) > 0, f"{val}")
tech = d.get("technical", {})
check("technical.price_now > 0", tech.get("price_now", 0) > 0, f"{tech.get('price_now')}")
ch = d.get("chips", {})
check("chips.winner_rate > 0", ch.get("winner_rate", 0) > 0, f"{ch}")
fac = d.get("factor", {})
check("factor.factor_score > 0", fac.get("factor_score", 0) > 0, f"{fac}")
p = d.get("portrait", {})
check("portrait.total_score > 0", p.get("total_score", 0) > 0, f"{p}")

print()
print("=" * 70)
print("⑧ /api/hunter/result 胜率猎手")
print("=" * 70)
d = get("/api/hunter/result")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
check("有结果数据", bool(d), f"keys={list(d.keys())[:10] if isinstance(d, dict) else type(d)}")

print()
print("=" * 70)
print("⑨ /api/stats/summary 系统统计")
print("=" * 70)
d = get("/api/stats/summary")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
check("非空", bool(d), f"keys={list(d.keys())[:10] if isinstance(d, dict) else type(d)}")

print()
print("=" * 70)
print("⑩ /api/market/theme-stocks 题材下钻")
print("=" * 70)
d = get("/api/market/theme-stocks?sector=半导体&sort=desc")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
ts = d.get("stocks") or d.get("items") or []
check("题材股列表非空", len(ts) > 0, f"len={len(ts)} keys={list(d.keys())[:10]}")

print()
print("=" * 70)
print("⑪ /api/market/style-stocks 风格个股")
print("=" * 70)
d = get("/api/market/style-stocks?date=20260829&style=%E9%AB%98%E6%8D%A2%E6%89%8B%E9%A3%8E%E6%A0%BC%20(Turnover)")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
ss = d.get("stocks") or d.get("items") or []
check("风格股列表非空", len(ss) > 0, f"len={len(ss)} keys={list(d.keys())[:10]}")

print()
print("=" * 70)
print("⑫ /api/performance 绩效")
print("=" * 70)
d = get("/api/performance")
check("无 error", d.get("__error__") is None and d.get("error") is None, str(d.get("error") or d.get("__error__") or ""))
check("非空", bool(d), f"keys={list(d.keys())[:10] if isinstance(d, dict) else type(d)}")

print()
print("=" * 70)
print(f"汇总: {len(issues)} 个问题")
print("=" * 70)
for i in issues:
    print(f"  ❌ {i}")
if not issues:
    print("  ✅ 全部通过")
