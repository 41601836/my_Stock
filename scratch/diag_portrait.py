# -*- coding: utf-8 -*-
"""画像建仓决策 - 无法推选股票诊断脚本"""
import requests, json, sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    resp = requests.get('http://localhost:8000/api/portrait/position-pick?top_n=30&strategy=left', timeout=60)
    resp.encoding = 'utf-8'
    d = resp.json()
except Exception as e:
    print(f"[API ERROR] {e}")
    sys.exit(1)

meta = d.get('meta', {})
funnel = d.get('funnel', {})
picks = d.get('picks', [])
l1_rej = funnel.get('layer1_reject', [])
l2_rej = funnel.get('layer2_reject', [])
l3_rej = funnel.get('layer3_reject', [])

print("=" * 70)
print("画像建仓决策 - 诊断报告")
print("=" * 70)
print(f"扫描日期: {meta.get('scan_date')}   因子日期: {meta.get('factor_date')}")
print(f"筹码日期: {meta.get('cyq_date')}   策略: {meta.get('strategy')}")
print(f"扫描候选池数 top_n: {meta.get('top_n_scanned')}")

print("\n【漏斗各层统计】")
print(f"  L0 候选池总数:         {funnel.get('layer0_total')}  (综合build_score Top N)")
print(f"  L1 层一 画像≥60分:     {funnel.get('layer1_pass')} 通过 / {len(l1_rej)} 淘汰")
print(f"  L2 层二 热度/涨幅过滤: {funnel.get('layer2_pass')} 通过 / {len(l2_rej)} 淘汰")
print(f"  L3 层三 行业去重:      {funnel.get('layer3_pass')} 最终入选")

if l1_rej:
    print("\n" + "="*70)
    print("【🚫 L1层一 淘汰明细 - 画像分 < 60（核心问题！）】")
    print("="*70)
    print(f"{'代码':<12} {'名称':<10} {'分':>5} {'等级':<4} 各维分数明细")
    print("-" * 70)
    # 遍历每只淘汰股，需要获取其5维分
    # 注意：layer1_reject 返回的是简化结构，我们单独获取被拒绝的股票画像5维
    # 这里先以简化的方式输出
    for r in l1_rej:
        sc = r['portrait_score']
        grd = r.get('portrait_grade', 'D')
        gap = 60 - sc
        print(f"{r['ts_code']:<12} {r['name']:<10} {sc:>5.1f} {grd:<4}  ↓差 {gap:>4.1f}分达线")

if l2_rej:
    print("\n【🚫 L2层二 淘汰明细 - 热度/涨幅过滤】")
    for r in l2_rej:
        print(f"  {r['ts_code']:<12} {r['name']:<10} 画像={r['portrait_score']:>5.1f} 今日+{r['pct_chg']:>5.2f}% | {r['reject_reason']}")

if l3_rej:
    print("\n【🚫 L3层三 淘汰明细 - 同行业去重】")
    for r in l3_rej:
        print(f"  {r['ts_code']:<12} {r['name']:<10} 画像={r['portrait_score']:>5.1f} | {r['reject_reason']}")

if picks:
    print("\n" + "="*70)
    print("【✅ 最终入选建议建仓】")
    print("="*70)
    for r in picks:
        print(f"#{r['pick_rank']} {r['ts_code']} {r['name']}")
        print(f"   画像分={r['portrait_score']} [{r['portrait_grade']}] {r['portrait_label']}")
        print(f"   选股理由: {r['pick_reason']}")
        print(f"   建议仓位: {r['suggested_weight']}%  今日收盘: {r['close']}  今日涨跌: +{r['pct_chg']}%")
        print(f"   5维明细: {json.dumps(r.get('portrait_details', {}), ensure_ascii=False)}")
        print()
else:
    print("\n" + "="*70)
    print("【❌ 根本原因分析 - 无股票入选】")
    print("="*70)
    l0 = funnel.get('layer0_total', 0)
    l1 = funnel.get('layer1_pass', 0)
    print(f"\n📌 候选池初始数量: {l0} 只")
    print(f"📌 层一画像≥60分通过率: {l1}/{l0} = {l1/l0*100 if l0 else 0:.1f}%")

    if l1 == 0:
        print("\n🎯 核心故障点: 层一（画像分≥60）全军覆没！")
        print("  ⚠️  当前门槛: portrait_score ≥ 60 分（B级以上）")
        if l1_rej:
            max_sc = max(r['portrait_score'] for r in l1_rej)
            avg_sc = sum(r['portrait_score'] for r in l1_rej) / len(l1_rej)
            print(f"  📊 候选池最高画像分: {max_sc:.1f}  平均画像分: {avg_sc:.1f}")
            print(f"  📏 最高分距60分门槛还差: {60 - max_sc:.1f} 分")
        print("\n  🔍 可能原因：")
        print("  1) 当前熊市(Bear)市场状态下，多数股票筹码/估值/热度不符合 左侧低吸画像")
        print("  2) 筹码集中度(黄金76-82) 或 获利盘比例(≤25%) 要求过于严格")
        print("  3) 因子分黄金甜区(0.80-0.89) 要求过于严格，多数股要么<0.7要么>0.92")
        print("  4) 建议：放宽画像阈值(60→50) 或 切换到右侧策略 (strategy=right)")
    elif len(picks) == 0:
        if funnel.get('layer2_pass', 0) == 0:
            print("\n🎯 故障点: 层二（热度过滤）全军覆没")
            print("  今日涨幅 ≤ 4.5% / 上影线 ≤ 3.5% / 20日涨幅 ≤ 25% 要求过严")
        else:
            print("\n🎯 故障点: 层三（行业去重）后无余留")
    print("\n建议：点击页面顶部【扫描因子】→【刷新决策】或切换到「右侧突破」策略")
