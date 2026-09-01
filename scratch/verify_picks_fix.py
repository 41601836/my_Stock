# -*- coding: utf-8 -*-
"""直接调用后端内部 API 函数验证（不依赖 shell 引号）"""
import sys, os, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from services import get_portrait_position_pick

for strat in ["left", "right"]:
    print("=" * 65)
    print(f"画像建仓 API 验证 (策略={strat.upper()} 模式, Bull 市场环境 20260831)")
    print("=" * 65)
    d = get_portrait_position_pick(top_n=30, strategy=strat)
    f = d.get('funnel', {})
    p = d.get('picks', [])
    print(f"  数据日期:       {d.get('meta',{}).get('scan_date')}")
    print(f"  候选池层0:      {f.get('layer0_total')} 只")
    print(f"  层1阈值:        {f.get('layer1_threshold')} | {f.get('layer1_remark')}")
    print(f"  层一通过率:     {f.get('layer1_pass')} / {f.get('layer0_total')}")
    print(f"  层二通过率:     {f.get('layer2_pass')} / {f.get('layer1_pass') or 0}")
    print(f"  层三通过:       {f.get('layer3_pass')} 只 (最终行业去重)")
    print(f"  ★最终精选建仓:  {len(p)} 只")
    print()
    if p:
        print(f'🎯 今日推选股票 ({len(p)} 只):')
        for x in p:
            print(f"  #{x['pick_rank']} {x['ts_code']:<10} {x['name']:<8} 画像分={x['portrait_score']:>5.1f}({x['portrait_grade']}) 涨幅={x['pct_chg']:>+.2f}% 建议权重={x['suggested_weight']:>4.1f}% | {x['pick_reason']}")
    else:
        print(f'⚠️  仍然 0 只通过。被淘汰明细:')
        r = f.get('layer1_reject', [])
        if r:
            print(f'  层一被淘汰 {len(r)} 只:')
            for x in r:
                print(f"    {x['ts_code']:<10} {x['name']:<8} 画像分={x['portrait_score']:>5.1f}({x['portrait_grade']}) | {x['reject_reason']}")
        r2 = f.get('layer2_reject', [])
        if r2:
            print(f'  层二被淘汰 {len(r2)} 只:')
            for x in r2:
                print(f"    {x['ts_code']:<10} {x['name']:<8} 画像分={x['portrait_score']:>5.1f}({x['portrait_grade']}) | {x['reject_reason']}")
    print()
