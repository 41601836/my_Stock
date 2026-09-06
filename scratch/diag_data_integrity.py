# -*- coding: utf-8 -*-
"""
diag_data_integrity.py —— 全库数据失真体检（只读，不加锁不写库）
================================================================
背景：前端「今日策略推荐列表」5/10/20日涨幅出现 -80%~-98% 的不可能值。
链路：factor_values.return_5d ← close_adj.pct_change(5) ← close × adj_factor
     adj_factor = COALESCE(stk_factor.adj_factor, daily_prices.adj_factor, 1.0)
本脚本逐层取证：原始行情 → 复权因子 → close_adj → 因子截面。
"""
import sqlite3
import json

DB = "file:db/stock_data.db?mode=ro"
conn = sqlite3.connect(DB, uri=True, timeout=30.0)
conn.row_factory = sqlite3.Row

def q(sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]

print("=" * 72)
print("A. 基准面：各表最新日期")
for t in ["daily_prices", "stk_factor", "factor_values", "adj_factor"]:
    try:
        r = q(f"SELECT MAX(trade_date) AS d, COUNT(*) AS n FROM {t}")[0]
        print(f"  {t:<14} latest={r['d']}  rows={r['n']}")
    except Exception as e:
        print(f"  {t:<14} ⚠️ {e}")

latest = q("SELECT MAX(trade_date) AS d FROM daily_prices")[0]["d"]
print(f"\n>>> 以 daily_prices 最新交易日 {latest} 为基准截面")

print("=" * 72)
print("B. 失真样本取证：600884 杉杉股份 最近 12 个交易日")
rows = q("""
    SELECT p.trade_date, p.close, p.pct_chg,
           sf.adj_factor AS sf_af, p.adj_factor AS p_af,
           COALESCE(sf.adj_factor, p.adj_factor, 1.0) AS used_af
    FROM daily_prices p
    LEFT JOIN stk_factor sf ON p.ts_code = sf.ts_code AND p.trade_date = sf.trade_date
    WHERE p.ts_code='600884.SH'
    ORDER BY p.trade_date DESC LIMIT 12
""")
rows.reverse()
prev_af, prev_ca = None, None
for r in rows:
    ca = (r["close"] or 0) * (r["used_af"] or 1.0)
    af_chg = f"{(r['used_af']/prev_af-1)*100:+.2f}%" if prev_af else "  --  "
    ca_chg = f"{(ca/prev_ca-1)*100:+.2f}%" if prev_ca else "  --  "
    print(f"  {r['trade_date']}  close={r['close']:>8.2f}  pct_chg={r['pct_chg']:>7.2f}  "
          f"sf_af={r['sf_af']} p_af={r['p_af']} used_af={r['used_af']}  "
          f"af日环比={af_chg}  close_adj日环比={ca_chg}")
    prev_af, prev_ca = r["used_af"] or 1.0, ca

print("=" * 72)
print("C. 全市场复权因子连续性（最近 8 个交易日，日环比跳变 ±15% 以外即可疑）")
dates = [r["trade_date"] for r in q(
    "SELECT DISTINCT trade_date FROM stk_factor ORDER BY trade_date DESC LIMIT 8")]
dates.reverse()
ph = ",".join("?" * len(dates))
rows = q(f"""
    SELECT ts_code, trade_date, adj_factor FROM stk_factor
    WHERE trade_date IN ({ph}) ORDER BY ts_code, trade_date
""", dates)
from collections import defaultdict
by_stock = defaultdict(list)
for r in rows:
    by_stock[r["ts_code"]].append((r["trade_date"], r["adj_factor"]))
bad, bad_samples = {}, []
for code, seq in by_stock.items():
    seq = [(d, a) for d, a in seq if a]
    if len(seq) < 2:
        continue
    jumps = []
    for i in range(1, len(seq)):
        if seq[i-1][1] and abs(seq[i][1] / seq[i-1][1] - 1) > 0.15:
            jumps.append((seq[i][0], seq[i-1][1], seq[i][1], seq[i][1]/seq[i-1][1]))
    if jumps:
        bad[code] = jumps
        bad_samples.append((code, jumps[-1]))
print(f"  覆盖股票数: {len(by_stock)}，复权因子异常跳变股票数: {len(bad)}")
if bad_samples:
    print("  跳变最猛的 10 个样本（末次跳变）:")
    for code, j in sorted(bad_samples, key=lambda x: x[1][3])[:10]:
        print(f"    {code}: {j[0]}  {j[1]} -> {j[2]}  (×{j[3]:.4f})")
    jump_date_count = defaultdict(int)
    for code, js in bad.items():
        for j in js:
            jump_date_count[j[0]] += 1
    print("  按跳变日分布:", dict(sorted(jump_date_count.items())))

print("=" * 72)
print("D. 因子截面合理性：factor_values 最新日 return_5d 分布")
fv_date = q("SELECT MAX(trade_date) AS d FROM factor_values")[0]["d"]
dist = q(f"""
    SELECT COUNT(*) AS total,
           SUM(CASE WHEN return_5d < -0.40 THEN 1 ELSE 0 END) AS lt_m40,
           SUM(CASE WHEN return_5d < -0.27 THEN 1 ELSE 0 END) AS lt_m27,
           SUM(CASE WHEN return_5d > 0.80 THEN 1 ELSE 0 END) AS gt_80,
           SUM(CASE WHEN return_5d IS NULL THEN 1 ELSE 0 END) AS nulls
    FROM factor_values WHERE trade_date = '{fv_date}'
""")[0]
print(f"  factor_values 截面 {fv_date}: 总数={dist['total']}  "
      f"return_5d<-40%: {dist['lt_m40']}  <-27%(跌停极限): {dist['lt_m27']}  "
      f">80%: {dist['gt_80']}  NULL: {dist['nulls']}")

print("=" * 72)
print("D2. stk_factor 每日覆盖面（近 6 个交易日） vs daily_prices 股票数")
for d in q("""
    SELECT trade_date, COUNT(*) AS n FROM stk_factor
    WHERE trade_date >= (SELECT MAX(trade_date) FROM stk_factor WHERE trade_date < '20260902') - 0
    GROUP BY trade_date ORDER BY trade_date DESC LIMIT 6
"""):
    dp = q("SELECT COUNT(*) AS n FROM daily_prices WHERE trade_date = ?", (d["trade_date"],))[0]["n"]
    print(f"  {d['trade_date']}: stk_factor 覆盖 {d['n']:>5} 只 / daily_prices {dp:>5} 只"
          f"  缺口 {dp - d['n']}")
# 0902 当天 daily_prices.adj_factor 非空率
r = q("""
    SELECT COUNT(*) AS total,
           SUM(CASE WHEN adj_factor IS NOT NULL THEN 1 ELSE 0 END) AS has_af
    FROM daily_prices WHERE trade_date = '20260902'
""")[0]
print(f"  daily_prices@20260902: 总 {r['total']} 行，adj_factor 非空仅 {r['has_af']} 行")

print("=" * 72)
print("E. 交叉验证：同一批股票「官方 pct_chg 累计」vs「factor_values.return_5d」")
# 官方口径：最近5个交易日 pct_chg 连乘（基于真实未复权价的官方涨跌幅，除权日已修正）
pd5 = q(f"""
    SELECT ts_code, COUNT(*) AS n, SUM(CASE WHEN pct_chg IS NOT NULL THEN 1 ELSE 0 END) AS has
    FROM daily_prices WHERE trade_date IN (
        SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 5)
    GROUP BY ts_code
""")
official = {}
for r in q(f"""
    SELECT ts_code, pct_chg FROM daily_prices
    WHERE trade_date IN (SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date DESC LIMIT 5)
      AND pct_chg IS NOT NULL
"""):
    official.setdefault(r["ts_code"], []).append(r["pct_chg"])
fv = {r["stock_code"]: r["return_5d"] for r in q(
    f"SELECT stock_code, return_5d FROM factor_values WHERE trade_date='{fv_date}' AND return_5d IS NOT NULL")}
mismatch, agree = 0, 0
samples = []
for code, f5 in fv.items():
    chgs = official.get(code)
    if not chgs or len(chgs) < 5:
        continue
    cum = 1.0
    for v in chgs:
        cum *= (1 + v / 100)
    off5 = cum - 1
    if abs(f5 - off5) > 0.10:
        mismatch += 1
        if len(samples) < 8:
            samples.append((code, round(f5 * 100, 2), round(off5 * 100, 2)))
    else:
        agree += 1
print(f"  两口径一致(|diff|<=10pct): {agree}   严重不一致: {mismatch}")
print("  不一致样本 (code, factor口径5d%, 官方口径5d%):")
for s in samples:
    print(f"    {s}")

conn.close()
print("\n✅ 体检完成（只读，未写库）")
