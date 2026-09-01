# -*- coding: utf-8 -*-
"""画像分 5 维边界 fuzz 扫描：随机输入下断言 [0,100]、各维 [0,20]、明细合计==总分"""
import sys

sys.path.insert(0, "web/backend")

import numpy as np
from portrait_router import compute_portrait_score, PORTRAIT_CONFIG

cfg = PORTRAIT_CONFIG
rng = np.random.default_rng(42)

N = 5000
viol = {"total_range": 0, "dim_range": 0, "sum_mismatch": 0, "grade_invalid": 0}
grade_seen = set()
label_seen = set()

for _ in range(N):
    r = compute_portrait_score(
        factor_score=rng.uniform(-0.1, 1.1),          # 含越界值
        profit_ratio_estimate=rng.uniform(-0.1, 1.1),
        pe_ttm=rng.uniform(-20, 300),                 # 含负 PE / 极端高 PE
        hot_money_score=rng.uniform(0, 1),
        return_5d=rng.uniform(-0.3, 0.5),             # 含大跌 / 暴涨
        chips_concentration=rng.uniform(30, 100),
        volatility_60d=rng.uniform(0.2, 3.0),
        cfg=cfg,
    )
    total, d, g = r["portrait_score"], r["portrait_details"], r["portrait_grade"]
    grade_seen.add(g)
    label_seen.add(r["portrait_label"])
    if not (0.0 <= total <= 100.0):
        viol["total_range"] += 1
        print("❌ total 越界:", total, d)
    if any(v < 0 or v > 20.0 for v in d.values()):
        viol["dim_range"] += 1
        print("❌ 单维越界:", d)
    if abs(sum(d.values()) - total) > 0.251:          # 明细各自 round(,1)，5 维累计最大 ±0.25
        viol["sum_mismatch"] += 1
        print("❌ 明细≠总分:", d, total)
    if g not in ("A", "B", "C", "D"):
        viol["grade_invalid"] += 1
        print("❌ 非法等级:", g, total)

# 分段边界精确取样（跳变敏感点）
edge_inputs = [
    dict(factor_score=0.78, profit_ratio_estimate=0.25, pe_ttm=55.0, hot_money_score=0.28, return_5d=0.045, chips_concentration=76.0),   # 全下界
    dict(factor_score=0.90, profit_ratio_estimate=0.55, pe_ttm=95.0, hot_money_score=0.60, return_5d=0.075, chips_concentration=86.0),   # 全上界
    dict(factor_score=0.94, profit_ratio_estimate=0.85, pe_ttm=160.0, hot_money_score=0.0, return_5d=0.076, chips_concentration=92.0),   # 零分区
    dict(factor_score=0.68, profit_ratio_estimate=0.0, pe_ttm=0.0, hot_money_score=1.0, return_5d=-0.2, chips_concentration=70.0),       # 负PE/涣散界
]
edge_scores = []
for e in edge_inputs:
    r = compute_portrait_score(volatility_60d=1.6, cfg=cfg, **e)
    edge_scores.append(r["portrait_score"])
    assert 0 <= r["portrait_score"] <= 100, "边界样本越界: %s %s" % (e, r)

print("fuzz N=%d | 违规: %s" % (N, viol))
print("等级覆盖: %s | 标签覆盖: %s" % (sorted(grade_seen), sorted(label_seen)))
print("边界样本得分: 下界=%.1f 上界=%.1f 零分区=%.1f 负PE/涣散=%.1f" % tuple(edge_scores))
ok = all(v == 0 for v in viol.values()) and grade_seen == {"A", "B", "C", "D"}
print("🎉 fuzz + 边界扫描全部通过" if ok else "❌ 存在违规")
sys.exit(0 if ok else 1)
