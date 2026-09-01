# -*- coding: utf-8 -*-
"""画像5维分明细诊断"""
import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 直接调用 backend 函数获取详细数据
sys.path.insert(0, '/Users/lyu/Documents/my_Stock/web/backend')
from services import get_db_connection, DB_PATH
from portrait_router import compute_portrait_score

conn = get_db_connection(DB_PATH)

# 复用 position-pick 的前置逻辑，重跑以获取完整5维明细
from services import _get_factor_date, _get_restricted_stocks, _load_pkl_weights, WEIGHTS_PATH
import pandas as pd
import numpy as np

latest_fac = _get_factor_date(conn)
latest_cyq = pd.read_sql("SELECT MAX(trade_date) FROM stock_cyq_perf", conn).iloc[0, 0]
latest_mf  = pd.read_sql("SELECT MAX(trade_date) FROM moneyflow", conn).iloc[0, 0]
latest_pr  = pd.read_sql("SELECT MAX(trade_date) FROM daily_prices", conn).iloc[0, 0]

print(f"数据日期: 因子 {latest_fac}  筹码 {latest_cyq}  资金 {latest_mf}  价格 {latest_pr}")

# --- 因子打分 ---
df_fac = pd.read_sql(
    "SELECT stock_code, return_5d, return_20d, return_60d, excess_return_20d, "
    "       turnover_rate_20d, volatility_20d, volatility_60d, vol_ratio, north_net_inflow_ratio, "
    "       profit_ratio_estimate, chip_concentration, pe_ttm, hot_money_score "
    "FROM factor_values WHERE trade_date = ?",
    conn, params=(latest_fac,)
)
restricted = _get_restricted_stocks(conn)
if restricted:
    df_fac = df_fac[~df_fac["stock_code"].isin(restricted)]

_, rw = _load_pkl_weights(WEIGHTS_PATH)
if not rw:
    rw = {"north_net_inflow_ratio": -0.18, "return_5d": -0.54, "turnover_rate_20d": -0.28}

df_fac["factor_score"] = 0.0
for f, w in rw.items():
    if f in df_fac.columns:
        df_fac[f"_r_{f}"] = df_fac[f].rank(pct=True, na_option='bottom')
        df_fac["factor_score"] += w * df_fac[f"_r_{f}"]

fmin, fmax = df_fac["factor_score"].min(), df_fac["factor_score"].max()
frange = fmax - fmin if (fmax - fmin) > 1e-9 else 1.0
df_fac["factor_score_norm"] = (df_fac["factor_score"] - fmin) / frange

if "turnover_rate_20d" in df_fac.columns:
    df_fac = df_fac[(df_fac["turnover_rate_20d"] >= 0.5) & (df_fac["turnover_rate_20d"] <= 15.0)]

df_cyq = pd.read_sql("SELECT ts_code, winner_rate, chips_peak_pct FROM stock_cyq_perf WHERE trade_date = ?", conn, params=(latest_cyq,))
df_mf  = pd.read_sql("SELECT ts_code, net_mf_amount AS big_net_inflow FROM moneyflow WHERE trade_date = ?", conn, params=(latest_mf,))
df_pr  = pd.read_sql("SELECT ts_code, close, open, high, low, pct_chg FROM daily_prices WHERE trade_date = ?", conn, params=(latest_pr,))
df_info = pd.read_sql("SELECT ts_code, name, industry, market FROM stock_list", conn)

df = df_fac.rename(columns={"stock_code": "ts_code"})
df = df.merge(df_cyq,  on="ts_code", how="inner")
df = df.merge(df_mf,   on="ts_code", how="inner")
df = df.merge(df_pr,   on="ts_code", how="inner")
df = df.merge(df_info, on="ts_code", how="left")

df["name"] = df["name"].fillna("未知")
wr_dist = (df["winner_rate"] - 60.0).abs()
df["winner_rate_score"] = (1.0 - (wr_dist / 35.0).clip(0, 1.0))
df["inflow_norm"] = df["big_net_inflow"].rank(pct=True)
df["build_score"] = (
    df["factor_score_norm"] * 0.45 +
    df["winner_rate_score"] * 0.25 +
    df["inflow_norm"]       * 0.20 +
    (1.0 - df["pct_chg"].rank(pct=True)) * 0.10
)
df = df[(df["winner_rate"] >= 25.0) & (df["winner_rate"] <= 85.0)]
df = df[df["big_net_inflow"] > 0]
df_pool = df.nlargest(30, "build_score").copy()

print(f"\n✅ 经过前置过滤后的候选池（按 build_score 排序前{len(df_pool)}名）：")
print(f"   过滤条件：winner_rate 25-85%（放宽） · big_net_inflow > 0 · turnover_rate_20d 0.5-15%")

# 计算每支 Top 候选股的 5 维画像分
def safe_f(val, default=0.0):
    try:
        v = float(val)
        return default if pd.isna(v) else v
    except:
        return default

print(f"\n{'排名':>3} {'代码':<12} {'名称':<10} {'综合分':>6} {'画像分':>6} {'等级':<3} | 位置 估值 温度 筹码 因子 |  原始参数概览")
print("-" * 120)

for rank, (_, row) in enumerate(df_pool.iterrows(), 1):
    res = compute_portrait_score(
        factor_score          = safe_f(row.get("factor_score_norm"), 0.0),
        profit_ratio_estimate = safe_f(row.get("profit_ratio_estimate"), 0.5),
        pe_ttm                = safe_f(row.get("pe_ttm"), 9999.0),
        hot_money_score       = safe_f(row.get("hot_money_score"), 0.5),
        return_5d             = safe_f(row.get("return_5d"), 0.0),
        chips_concentration   = safe_f(row.get("chips_peak_pct"), 0.0),
        volatility_60d        = safe_f(row.get("volatility_60d"), 1.4),
    )
    d = res["portrait_details"]
    # 原始参数概览（用于看哪一项过低）
    raw = (f"盈{safe_f(row.get('profit_ratio_estimate'))*100:>5.0f}% "
           f"PE{safe_f(row.get('pe_ttm'),999):>5.0f} "
           f"热{safe_f(row.get('hot_money_score'))*100:>3.0f} "
           f"R5{safe_f(row.get('return_5d'))*100:>5.1f}% "
           f"筹{safe_f(row.get('chips_peak_pct')):>4.0f} "
           f"因{safe_f(row.get('factor_score_norm'))*100:>3.0f}")
    mark = " ←被过滤" if rank <= 2 else ""
    print(f"{rank:>3} {str(row.get('ts_code','')):<12} {str(row.get('name','')):<10} "
          f"{safe_f(row.get('build_score'))*100:>5.1f} "
          f"{res['portrait_score']:>6.1f} {res['portrait_grade']:<3} |"
          f"{d.get('位置分',0):>4.0f} {d.get('估值分',0):>4.0f} {d.get('温度分',0):>4.0f} {d.get('筹码分',0):>4.0f} {d.get('因子分',0):>4.0f} |"
          f" {raw}{mark}")

conn.close()
print("\n💡 层一准入：左侧画像分≥50 / 右侧画像分≥45（C+ 级以上放宽）。 满分为100=位置(20)+估值(20)+温度(20)+筹码(20)+因子(20)")
# 统计得分分布
scores = []
grades = {"A":0,"B":0,"C":0,"D":0}
pass_left = 0
pass_right = 0
for _, r in df_pool.iterrows():
    res = compute_portrait_score(
        factor_score          = safe_f(r.get("factor_score_norm"), 0.0),
        profit_ratio_estimate = safe_f(r.get("profit_ratio_estimate"), 0.5),
        pe_ttm                = safe_f(r.get("pe_ttm"), 9999.0),
        hot_money_score       = safe_f(r.get("hot_money_score"), 0.5),
        return_5d             = safe_f(r.get("return_5d"), 0.0),
        chips_concentration   = safe_f(r.get("chips_peak_pct"), 0.0),
        volatility_60d        = safe_f(r.get("volatility_60d"), 1.4),
    )
    s = res["portrait_score"]
    scores.append(s)
    grades[res["portrait_grade"]] = grades.get(res["portrait_grade"], 0) + 1
    if s >= 50: pass_left += 1
    if s >= 45: pass_right += 1
import numpy as np
print(f"\n📊 Top{len(df_pool)} 画像分分布：min={min(scores):.1f}  max={max(scores):.1f}  avg={np.mean(scores):.1f}  median={np.median(scores):.1f}")
print(f"   等级分布：A={grades['A']}  B={grades['B']}  C={grades['C']}  D={grades['D']}")
print(f"   左侧(≥50) 通过层一: {pass_left}/{len(df_pool)}   右侧(≥45) 通过层一: {pass_right}/{len(df_pool)}")
