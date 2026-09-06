# -*- coding: utf-8 -*-
"""
P1-3 跨 top_n 稳健性闸门 —— 离线验证（不触发真实回测）
数据：agent/auto_cruise_report_20260903.json（66 格点 / 22 组合真实巡航结果）
验证：
  1) load_resume_checkpoint 能解析出 traj_results（66 格点）
  2) 按 run_agent.py eval_robustness 同口径复算：combo10(top_n=10 +0.1977) 必须 FAIL
  3) 全样本中通过闸门（三档超额卡玛均 ≥0）的组合数
  4) 历史最优种子（combo10）闸门复核结果 = 弃用
  5) agent/config.yaml 闸门配置读取 + yaml 往返（巡航期物理重写）不丢 cruise 节
"""
import os
import sys
import yaml
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.run_agent import load_resume_checkpoint

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 1. 检查点解析 ----
ckpt = load_resume_checkpoint(PROJECT_ROOT)
assert ckpt is not None, "未找到巡航断点报告"
traj = ckpt["traj_results"]
print(f"[1] traj_results 格点数: {len(traj)}（真实报告 66 格点 / 22 组合，三档齐全）")
assert len(traj) == 66, f"格点数异常: {len(traj)}"

# ---- 2/3. 同口径复算闸门（与 run_agent.eval_robustness 逻辑一致） ----
PARAM_GRID = [{"top_n": 20}, {"top_n": 10}, {"top_n": 30}]
GATE_MIN = 0.0

combo_results = {}
for (ck, tn), cal in traj.items():
    combo_results.setdefault(ck, {})[tn] = cal

def eval_robustness(combo_key):
    per = {}
    for p in PARAM_GRID:
        tn = p["top_n"]
        if tn in combo_results.get(combo_key, {}):
            per[tn] = combo_results[combo_key][tn]
    if len(per) < len(PARAM_GRID):
        return False, "pending", per
    if min(per.values()) >= GATE_MIN:
        return True, "pass", per
    return False, "fail", per

pass_combos, fail_combos, pending_combos = [], [], []
for ck, per in combo_results.items():
    ok, status, p = eval_robustness(ck)
    view = {k: round(v, 4) for k, v in p.items()}
    if status == "pass":
        pass_combos.append((ck, view))
    elif status == "fail":
        fail_combos.append((ck, view))
    else:
        pending_combos.append((ck, view))

print(f"[2] 组合总数: {len(combo_results)}（期望 22）| 通过闸门: {len(pass_combos)} | 未通过: {len(fail_combos)} | 未齐: {len(pending_combos)}")
assert len(combo_results) == 22, f"组合数异常: {len(combo_results)}"

# 历史最优组合 = 报告 best_overall_combination
import json
reports = sorted(os.path.join(PROJECT_ROOT, "agent", f) for f in os.listdir(os.path.join(PROJECT_ROOT, "agent"))
                 if f.startswith("auto_cruise_report_") and f.endswith(".json"))
latest = max(reports, key=os.path.getmtime)
with open(latest, "r", encoding="utf-8") as f:
    rep = json.load(f)
best_combo = tuple(rep["best_overall_combination"])
best_cal = rep["best_overall_excess_calmar"]
print(f"[3] 报告历史最优: {best_combo} 超额卡玛={best_cal}")

ok, status, per = eval_robustness(best_combo)
view = {k: round(v, 4) for k, v in per.items()}
print(f"[4] 历史最优闸门复核: status={status} 三档={view} → {'保留种子' if ok else '弃用种子（符合预期）'}")
assert status == "fail" and not ok, "历史最优 combo10 理应被闸门拦截（top_n=30 为 -0.0495）"
assert min(per.values()) < 0, f"最小值应为负，实际 {min(per.values())}"
print(f"    三档最小值 = {min(per.values()):.4f} < 0 → 拦截正确")

# 全部通过的组合应为 0（22 组合三档齐全，仅 combo10 有 2 个正卡玛格点，第三档为负）
print(f"[5] 通过闸门组合数 = {len(pass_combos)}（期望 0：20260903 巡航无容量稳健组合）| fail={len(fail_combos)} pending={len(pending_combos)}")
assert len(pass_combos) == 0, f"预期 0 个通过，实际 {len(pass_combos)}"
assert len(fail_combos) == 22 and len(pending_combos) == 0, f"期望 22 fail / 0 pending，实际 {len(fail_combos)}/{len(pending_combos)}"

# ---- 6. 配置读取 + yaml 往返保留 ----
cfg_path = os.path.join(PROJECT_ROOT, "agent", "config.yaml")
with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
gate = cfg["cruise"]["robustness_gate"]
print(f"[6] config.yaml 闸门配置: {gate}")
assert gate["enabled"] is True and gate["min_excess_calmar"] == 0.0

# 模拟巡航期物理重写（cfg_data load → dump → reload）
dumped = yaml.safe_load(yaml.safe_dump(cfg, allow_unicode=True))
assert dumped.get("cruise", {}).get("robustness_gate", {}).get("enabled") is True, "yaml 往返后 cruise 节丢失！"
print("    yaml 往返（load→dump→reload）后 cruise.robustness_gate 完整保留 ✓")

print("\n✅ P1-3 闸门离线验证全部通过：旧巡航最优 combo10 被正确拦截，22 组合 0 个通过 → 新规则下巡航不部署权重。")
