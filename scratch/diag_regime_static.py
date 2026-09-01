# -*- coding: utf-8 -*-
"""实时计算当前 Regime 诊断报告"""
import sys, os, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web', 'backend'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from services import get_db_connection, DB_PATH, RESULTS_PATH, get_market_status, get_regime_dashboard
import pandas as pd
import numpy as np

print("=" * 70)
print("市场状态 (Regime) 根因诊断报告")
print("=" * 70)

# 1. 当前 get_market_status 返回值
print("\n【1】API get_market_status 当前返回值（从 CSV 最后一行读取，静态）：")
ms = get_market_status()
print(f"    trade_date:       {ms['trade_date']}")
print(f"    db_latest_date:   {ms['db_latest_date']}")
print(f"    regime (静态):    {ms['regime']} (来自 {RESULTS_PATH} 最后一行)")
print(f"    model_used:       {ms['model_used']}")

# 2. backtest_results_v2.csv 最后一行
print(f"\n【2】backtest_results_v2.csv 最后 5 行：")
if os.path.exists(RESULTS_PATH):
    df = pd.read_csv(RESULTS_PATH).tail(5)
    for _, row in df.iterrows():
        rd = str(int(row['trade_date']))
        rd = f"{rd[:4]}-{rd[4:6]}-{rd[6:]}"
        print(f"    {rd} | regime={row['regime']:<6} | model={row['model_used']:<24} | port_ret={float(row['portfolio_return'])*100:>6.2f}%")

# 3. 实时计算指标
print("\n【3】基于数据库最新数据的实时指标计算：")
conn = get_db_connection(DB_PATH)
df_bench = pd.read_sql(
    "SELECT trade_date, "
    "  AVG(pct_chg) as pct_chg, "
    "  SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as up_ratio "
    "FROM daily_prices "
    "GROUP BY trade_date "
    "ORDER BY trade_date DESC LIMIT 60",
    conn
)
conn.close()

df_bench = df_bench.sort_values("trade_date").reset_index(drop=True)
df_bench["nav"] = (1.0 + df_bench["pct_chg"] / 100.0).cumprod()
df_bench["return_20d"] = df_bench["nav"] / df_bench["nav"].shift(20) - 1.0
df_bench["return_10d"] = df_bench["nav"] / df_bench["nav"].shift(10) - 1.0
df_bench["return_5d"]  = df_bench["nav"] / df_bench["nav"].shift(5)  - 1.0
df_bench["vol_20d"]    = df_bench["pct_chg"].rolling(20).std()
roll_max_5d = df_bench["nav"].rolling(5).max()
df_bench["mdd_5d"] = (df_bench["nav"] - roll_max_5d) / roll_max_5d

last = df_bench.iloc[-1]
ret20 = float(last["return_20d"]) if not pd.isna(last["return_20d"]) else 0.0
ret10 = float(last["return_10d"]) if not pd.isna(last["return_10d"]) else 0.0
ret5  = float(last["return_5d"])  if not pd.isna(last["return_5d"])  else 0.0
vol20 = float(last["vol_20d"])    if not pd.isna(last["vol_20d"])    else 0.0
mdd5  = float(last["mdd_5d"])     if not pd.isna(last["mdd_5d"])     else 0.0
up_r  = float(last["up_ratio"])   if not pd.isna(last["up_ratio"])   else 0.5

valid_vol = df_bench["vol_20d"].dropna()
vol_50pct = float(valid_vol.quantile(0.50)) if len(valid_vol) > 0 else 1.5
vol_75pct = float(valid_vol.quantile(0.75)) if len(valid_vol) > 0 else 2.0

print(f"    最新交易日:       {last['trade_date']}")
print(f"    20日全市场收益:   {ret20*100:>7.2f}%   (Bull 阈值 > +5%, Bear 阈值 < -3%)")
print(f"    10日全市场收益:   {ret10*100:>7.2f}%")
print(f"    近 5日全市场收益: {ret5*100:>7.2f}%   (Dark 阈值 < -4.5%)")
print(f"    5日最大回撤(MDD): {mdd5*100:>7.2f}%   (Dark 阈值 < -5%)")
print(f"    20日波动率(σ):    {vol20:>8.4f}    (中位={vol_50pct:.4f}, 75分位={vol_75pct:.4f})")
print(f"    今日上涨家数占比: {up_r*100:>6.1f}%   (Dark 阈值 < 30%)")

# 4. 按 get_regime_dashboard 的判定逻辑实时判定 Real Regime
print("\n【4】按标准路由判定规则实时判定 真实 Regime：")
print(f"    触发条件检查：")
triggers = []
if ret5 < -0.045:
    triggers.append(f"周收益率触发 Dark条件: ret5w={ret5*100:.2f}% < -4.5% ❌")
    print(f"    ✅ {triggers[-1]}")
else:
    print(f"    ⏭️  周收益率: ret5w={ret5*100:.2f}% >= -4.5% (Dark不触发)")

if mdd5 < -0.05:
    triggers.append(f"5日最大回撤 Dark条件: mdd5={mdd5*100:.2f}% < -5% ❌")
    print(f"    ✅ {triggers[-1]}")
else:
    print(f"    ⏭️  5日MDD: {mdd5*100:.2f}% >= -5% (Dark不触发)")

if vol20 > vol_75pct:
    triggers.append(f"波动率过热: vol20={vol20:.4f} > {vol_75pct:.4f} (75分位) ⚠️")
    print(f"    ✅ {triggers[-1]}")
else:
    print(f"    ⏭️  波动率: vol20={vol20:.4f} <= {vol_75pct:.4f} (不触发过热)")

if up_r < 0.30:
    triggers.append(f"上涨占比 Dark条件: up_r={up_r*100:.1f}% < 30% ❌")
    print(f"    ✅ {triggers[-1]}")
else:
    print(f"    ⏭️  上涨家数: up_r={up_r*100:.1f}% >= 30% (Dark不触发)")

# 判断最终状态
if ret5 < -0.045 or mdd5 < -0.05 or up_r < 0.30:
    real_regime = "Dark"
    real_model = "Dark_Model"
    reason = "触发 Dark 避险条件 (Weekly暴跌 / MDD过大 / 上涨家数不足)"
elif ret20 > 0.05 and vol20 < vol_50pct and not triggers:
    real_regime = "Bull"
    real_model = "Bull_Model"
    reason = "触发 Bull 进攻条件 (20日+5% 低波动稳步上涨)"
elif ret20 < -0.03 and vol20 > vol_50pct and not [t for t in triggers if 'Dark' in t]:
    real_regime = "Bear"
    real_model = "Bear_Model"
    reason = "触发 Bear 防御条件 (20日-3% + 高波动下跌)"
else:
    real_regime = "Range"
    real_model = "Range_Model"
    reason = "未触发任何避险/进攻极端条件 → 震荡市箱体操作"

print(f"\n{'='*70}")
print(f"  📌 静态 Regime (CSV 最后一行 20260626): {ms['regime']} (已滞后 66+ 天!)")
print(f"  🎯 实时 Regime (真实 20260831):          {real_regime}")
print(f"  🧠 判定理由: {reason}")
print(f"  📦 推荐使用模型: {real_model}")
print(f"{'='*70}")
