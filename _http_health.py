import urllib.request, json

U = "http://127.0.0.1:8000"

def jget(p, timeout=180):
    with urllib.request.urlopen(U + p, timeout=timeout) as r:
        return json.loads(r.read())

d = jget("/api/status")
print("系统状态 date=%s regime=%s/%s db=%s ret=%.2f%%" % (
    d.get("trade_date"), d.get("regime"), d.get("model_used"),
    d.get("db_health"), d.get("portfolio_return", 0) * 100
))

o = jget("/api/market/overview")
sf = o.get("sector_money_flow", [])
top_n = len(sf[0].get("sectors", [])) if sf else 0
bot_n = len(sf[1].get("sectors", [])) if len(sf) > 1 else 0
themes = o.get("theme_popularity", [])
print(f"市场概览 板块资金流Top={top_n} Bot={bot_n} 题材热度={len(themes)}")
print(f"  Top吸金板块示例: {[(s['sector'], s['net_inflow_yi']) for s in (sf[0]['sectors'][:3] if sf else [])]}")
print(f"  题材热度示例: {themes[:3]}")

t = jget("/api/market/theme-stocks?sector=%E7%94%B5%E5%8A%9B&limit=3")
ss = t.get("stocks", [])
print(f"游资题材下钻(电力 limit=3) → 返回 {len(ss)} 股")
for s in ss:
    print(f"  {s['name']}({s['ts_code']}) {s['industry']} 当日={s['pct_chg']}% 5日={s['pct_chg_5d']}% 换手={s['turnover_rate']}%")
