# -*- coding: utf-8 -*-
"""验证修复后的 overview 真实数据字段"""
import sys
sys.path.insert(0, '.')
from web.backend.services import get_market_overview_data

d = get_market_overview_data()
lines = []
lines.append(f"error: {d.get('error')}")
for k in ('hot_money_themes', 'inst_themes', 'main_cap_themes', 'inflow_rank', 'outflow_rank'):
    v = d.get(k)
    lines.append(f"{k}: {'MISSING' if v is None else 'len=%d' % len(v)}")

lines.append("")
h = d.get('hot_money_themes') or []
if h:
    lines.append(f"== hot_money_themes[0] == {h[0]}")
lines.append("")
lines.append("== inst_themes Top3（按真实筹码集中排序）==")
for t in (d.get('inst_themes') or [])[:3]:
    lines.append(str({k2: t[k2] for k2 in ('sector', 'chips_peak', 'net_inflow', 'streak_days')}))
lines.append("")
lines.append("== main_cap_themes Top3（真实流入占比）==")
for t in (d.get('main_cap_themes') or [])[:3]:
    lines.append(str({k2: t[k2] for k2 in ('sector', 'net_inflow', 'inflow_ratio', 'streak_days')}))
lines.append("")
lines.append(f"inflow_rank[:2] = {(d.get('inflow_rank') or [])[:2]}")
lines.append(f"outflow_rank[:2] = {(d.get('outflow_rank') or [])[:2]}")

with open('scratch/verify_overview_out.txt', 'w', encoding='utf-8') as f:
    f.write("\n".join(lines))
print("done")
