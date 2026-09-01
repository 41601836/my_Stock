# -*- coding: utf-8 -*-
"""验证修复后 Regime 是否从 Bear 变 Bull"""
import sys, os, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from services import get_market_status, compute_live_regime, get_regime_dashboard

print("=" * 70)
print("修复后验证测试 (services.py get_market_status 直连)")
print("=" * 70)

live = compute_live_regime()
print(f"\n[compute_live_regime] 实时计算结果:")
print(f"    Regime:       {live['regime']}")
print(f"    Model:        {live['model_used']}")
print(f"    DB 最新日期:  {live['db_latest_date']}")
print(f"    20日收益:     {live['return_20d']*100:+.2f}%")
print(f"    5日收益:      {live['return_5d']*100:+.2f}%")
print(f"    波动率 中位:  {live['vol_50pct']:.4f}")
print(f"    触发项:       {[t['name'] for t in live['triggers']]}")

ms = get_market_status()
print(f"\n[get_market_status] API 返回值（现在应该是 Bull 而不是 Bear）:")
print(f"    trade_date:       {ms['trade_date']}")
print(f"    db_latest_date:   {ms['db_latest_date']}")
print(f"    regime:           {ms['regime']}  ← 期望 Bull (Bear就是BUG!)")
print(f"    model_used:       {ms['model_used']}")
dbg = ms.get("_debug", {})
print(f"    [_debug] regime来源:   {dbg.get('regime_source')}")
print(f"    [_debug] CSV 日期:     {dbg.get('csv_last_date_int')}")
print(f"    [_debug] DB  日期:     {dbg.get('db_latest_int')}")
print(f"    [_debug] CSV  regime:  {dbg.get('csv_regime')}")
print(f"    [_debug] LIVE regime:  {dbg.get('live_regime')}")
print(f"    [_debug] LIVE triggers:{[t['name'] for t in dbg.get('live_triggers',[])]}")

dash = get_regime_dashboard()
print(f"\n[get_regime_dashboard] 路由仪表盘:")
print(f"    Regime:         {dash.get('regime')}")
print(f"    20日收益:       {dash.get('indicators',{}).get('return_20d'):+.2f}%")
print(f"    5日收益:        {dash.get('indicators',{}).get('return_5d'):+.2f}%")
print(f"    上涨家数占比:   {dash.get('indicators',{}).get('up_ratio'):.1f}%")
print(f"    5日MDD:         {dash.get('indicators',{}).get('mdd_5d'):+.2f}%")
print(f"    仓位建议:       {dash.get('position_advice',{})}")
hist = dash.get('regime_history', [])
print(f"    Regime 历史 ({len(hist)} 条):")
for h in hist:
    flag = "  ← LIVE 实时追加" if h.get('_live') else ""
    print(f"      {h['date']} | {h['regime']:<6} | port={h['portfolio_return']:>+.2f}%  bench={h['benchmark_return']:>+.2f}%{flag}")

# Final assert
assert ms['regime'] == 'Bull', f"❌ 修复失败: API 返回 {ms['regime']}，期望 Bull！请检查代码修改是否生效"
assert ms['model_used'] == 'Bull_Model', f"❌ 修复失败: model={ms['model_used']}，期望 Bull_Model"
print("\n✅ 所有断言通过！Regime 已成功从静态 Bear 切换到 动态 Bull")
print("   接下来重启后端服务 uvicorn，前端 Dashboard 就会正确显示牛市状态。")
