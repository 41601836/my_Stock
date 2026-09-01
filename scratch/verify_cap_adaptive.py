# -*- coding: utf-8 -*-
"""验证 evo_dynamic_weights.cap 自适应逻辑：cap = max(max_w, 1/n_eff)"""
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "web/backend")

import numpy as np
import pandas as pd
from evo_dynamic_weights import calc_weights_snapshot


def make_ic(n_days=25, n_pos=3, n_neg=2, seed=1, skew=False):
    rng = np.random.default_rng(seed)
    cols = {}
    for i in range(n_pos):
        cols[f"pos_{i}"] = rng.normal(0.10, 0.05, n_days)
    for j in range(n_neg):
        cols[f"neg_{j}"] = rng.normal(-0.10, 0.05, n_days)
    if skew and n_pos >= 2:
        # 人为让第一个因子 IC 极强 → raw 份额极不均匀，触发 water-filling
        cols["pos_0"] = cols["pos_0"] * 8.0
    idx = [f"202608{d:02d}" for d in range(1, n_days + 1)]
    return pd.DataFrame(cols, index=idx)


ok = True
TOL = 2e-6  # calc_weights_snapshot 返回 round(w, 6)，n 个因子累加最大舍入误差约 n×5e-7

# 场景1: n_eff=3 → cap=max(0.30, 1/3)=0.3333，权重不应超过 0.3333+tol
snap = calc_weights_snapshot(make_ic(n_pos=3, n_neg=2), "20260825")
w = snap["weights"]
nz = [v for v in w.values() if v > 0]
print("场景1 n_eff=3 | mode=%s | non-zero=%d" % (snap["mode"], len(nz)))
for c, v in sorted(w.items(), key=lambda x: -x[1]):
    print("   %-8s %.4f" % (c, v))
print("   sum=%.4f max=%.4f" % (sum(w.values()), max(nz) if nz else 0))
if abs(sum(w.values()) - 1.0) > TOL:
    ok = False
    print("   ❌ 权重和不为 1")
if max(nz) > 1 / 3 + TOL:
    ok = False
    print("   ❌ 存在因子超过自适应 cap 1/3")
print("   ✅ 场景1 通过" if ok else "   ❌ 场景1 失败")

# 场景2: n_eff=5 → 5×0.30=1.5>1，cap=0.30 正常生效
snap2 = calc_weights_snapshot(make_ic(n_pos=5, n_neg=2, seed=2), "20260825")
w2 = {c: v for c, v in snap2["weights"].items() if v > 0}
print("\n场景2 n_eff=5 | mode=%s | non-zero=%d | max=%.4f sum=%.4f"
      % (snap2["mode"], len(w2), max(w2.values()), sum(snap2["weights"].values())))
if max(w2.values()) > 0.30 + TOL or abs(sum(snap2["weights"].values()) - 1.0) > TOL:
    ok = False
    print("   ❌ cap=0.30 被突破或权重和异常")
else:
    print("   ✅ cap=0.30 严格生效")

# 场景3: 极不均匀 + n_eff=3 → water-filling 应压平至 ≤ 1/3
snap3 = calc_weights_snapshot(make_ic(n_pos=3, n_neg=2, seed=3, skew=True), "20260825")
w3 = {c: v for c, v in snap3["weights"].items() if v > 0}
print("\n场景3 skew n_eff=3 | mode=%s | weights:" % snap3["mode"])
for c, v in sorted(w3.items(), key=lambda x: -x[1]):
    print("   %-8s %.4f" % (c, v))
if max(w3.values()) > 1 / 3 + TOL or abs(sum(snap3["weights"].values()) - 1.0) > TOL:
    ok = False
    print("   ❌ skew 场景突破自适应 cap")
else:
    print("   ✅ water-filling 收敛，全部 ≤ 1/3")

# 场景4: 全负 IC → uniform_fallback 兜底
snap4 = calc_weights_snapshot(make_ic(n_pos=0, n_neg=4), "20260825")
print("\n场景4 全负IC | mode=%s | each=%.4f" % (snap4["mode"], 1 / 4))
if snap4["mode"] != "uniform_fallback":
    ok = False
    print("   ❌ 应落入 uniform_fallback")
else:
    print("   ✅ 兜底模式正确")

print("\n" + ("🎉 全部 4 场景验证通过" if ok else "❌ 存在失败场景"))
sys.exit(0 if ok else 1)
