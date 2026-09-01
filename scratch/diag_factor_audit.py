# -*- coding: utf-8 -*-
"""
5维因子真实性·有效性·时效性 诊断脚本（配合 localhost:5173/scanner 选出股票核查）
输出：结构化 JSON 报告 + 控制台摘要
"""
import sys, os, json, sqlite3, collections, datetime
import numpy as np
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "web", "backend"))
sys.path.insert(0, _PROJECT_ROOT)

from services._common import DB_PATH, get_db_connection
from services.scanner import get_build_position_opportunities


def section(title):
    print("\n" + "=" * 72)
    print(f"▍ {title}")
    print("=" * 72)


# ──────────────────────────── 1. 时效性诊断 ────────────────────────────
section("1 · 时效性：4 张核心表数据血统 & 日期对齐")

conn = get_db_connection(DB_PATH, timeout=30.0)
try:
    # 1.1 各表最新日期 + 行数密度
    density_row = pd.read_sql(
        "SELECT COUNT(*) AS c FROM daily_prices WHERE trade_date=(SELECT MAX(trade_date) FROM daily_prices)",
        conn,
    )
    dp_density = int(density_row.iloc[0, 0])
    print(f"  daily_prices 最新日期行数（≈全市场覆盖基准）: {dp_density}")

    tables = [
        ("daily_prices",   "trade_date", 0.90, "每日收盘行情"),
        ("factor_values",  "trade_date", 0.80, "因子截面快照"),
        ("stock_cyq_perf", "trade_date", 0.90, "筹码分布 CYQ"),
        ("moneyflow",      "trade_date", 0.90, "大单资金流"),
    ]
    min_rows_abs = 1000
    today_yyyymmdd = datetime.date.today().strftime("%Y%m%d")

    date_report = {}
    for tname, dcol, cov_factor, zh in tables:
        threshold = max(int(dp_density * cov_factor), min_rows_abs)
        df = pd.read_sql(
            f"SELECT {dcol} AS d, COUNT(*) AS c FROM {tname} GROUP BY {dcol} ORDER BY {dcol} DESC LIMIT 10",
            conn,
        )
        if df.empty:
            print(f"  [⚠️] {tname:20s} 表完全空!!! 中文名: {zh}")
            date_report[tname] = {"latest": "", "rows": 0, "ok": False, "reason": "empty table"}
            continue
        latest = df.iloc[0]
        ok_rows = int(latest["c"]) >= threshold
        latest_d = str(latest["d"])
        # 距今天数（自然日）
        try:
            dt_latest = datetime.datetime.strptime(latest_d, "%Y%m%d").date()
            days_ago = (datetime.date.today() - dt_latest).days
        except Exception:
            days_ago = None
        status = "✅" if ok_rows and (days_ago is None or days_ago <= 5) else ("⚠️" if days_ago is None or days_ago <= 10 else "❌")
        print(f"  {status} {tname:20s} | latest={latest_d} rows={int(latest['c']):5d} | thresh≥{threshold} "
              f"{'OK' if ok_rows else 'LOW COVERAGE'} | staleness={days_ago if days_ago is not None else '?'}自然日 | {zh}")

        # 找"满足覆盖率"的真实 LATEST（scanner 实际使用日期）
        good = df[df["c"] >= threshold]
        effective_latest = str(good.iloc[0]["d"]) if not good.empty else str(df.sort_values("c", ascending=False).iloc[0]["d"])
        print(f"         └─ scanner 实际采用的有效 LATEST = {effective_latest}")
        date_report[tname] = {
            "raw_latest": latest_d,
            "effective_latest": effective_latest,
            "rows_at_raw_latest": int(latest["c"]),
            "rows_at_effective": int(df[df["d"].astype(str) == str(effective_latest)]["c"].iloc[0]) if effective_latest in df["d"].astype(str).tolist() else int(latest["c"]),
            "threshold": threshold,
            "coverage_ok": ok_rows,
            "days_ago": days_ago,
            "description": zh,
        }

    # 1.2 跨表日期一致性
    effective_dates = [v["effective_latest"] for v in date_report.values()]
    all_aligned = len(set(effective_dates)) == 1 and all(effective_dates[0] == d for d in effective_dates)
    align_dates = collections.Counter(effective_dates)
    print(f"\n  跨表日期一致性: {'✅ 完全对齐 -> ' + str(align_dates) if all_aligned else '⚠️ 存在分裂 -> ' + str(align_dates)}")

    # 1.3 最新 trade_cal：对照今日是否交易日
    try:
        cal = pd.read_sql("SELECT cal_date, is_open FROM trade_cal ORDER BY cal_date DESC LIMIT 20", conn)
        if not cal.empty:
            latest_cal = str(cal.iloc[0]["cal_date"])
            today_open = bool(int(cal[cal["cal_date"].astype(str) == today_yyyymmdd]["is_open"].iloc[0])) if today_yyyymmdd in cal["cal_date"].astype(str).tolist() else None
            print(f"  交易所日历最新记录: {latest_cal} | 今日({today_yyyymmdd}) 是否交易日: {'未知' if today_open is None else ('是' if today_open else '否（休市）')}")
        else:
            print("  [⚠️] trade_cal 表无数据，无法对照交易日历")
    except Exception as _e:
        print(f"  [—] trade_cal 查询跳过: {_e}")

finally:
    pass

# ──────────────────────────── 2. 取扫描结果并真实性核查 ────────────────────────────
section("2 · 真实性：选出股票 vs 底层表 逐字段核对")

scan_res = get_build_position_opportunities()
scan_meta = scan_res.get("meta", {})
stocks = scan_res.get("stocks", [])
print(f"  scanner 返回 Top {len(stocks)} 股票")
print(f"  meta: scan_date={scan_meta.get('scan_date')}  factor={scan_meta.get('factor_date')}  "
      f"cyq={scan_meta.get('cyq_date')}  mf={scan_meta.get('mf_date')}")
print(f"        total_scanned={scan_meta.get('total_scanned')} after_filter={scan_meta.get('after_filter')} final_count={scan_meta.get('final_count')}")

if not stocks:
    print("  [❌] 空结果集，后续核查跳过")
    conn.close()
    sys.exit(0)

codes = [s["ts_code"] for s in stocks]
ph = ",".join(["?"] * len(codes))

# 2.1 从 4 张原表按 scanner 实际用的日期拉原始值
f_date = scan_meta.get("factor_date") or scan_meta.get("scan_date")
c_date = scan_meta.get("cyq_date")   or scan_meta.get("scan_date")
m_date = scan_meta.get("mf_date")    or scan_meta.get("scan_date")
d_date = scan_meta.get("scan_date")

print(f"\n  查询日期窗口：FV={f_date}  CYQ={c_date}  MF={m_date}  DP={d_date}")

try:
    fv_df = pd.read_sql(
        f"SELECT stock_code AS ts_code, return_5d, return_10d, return_20d, return_60d, excess_return_20d, "
        f"turnover_rate_20d, volatility_20d, volatility_60d, vol_ratio, north_net_inflow_ratio, "
        f"profit_ratio_estimate, chip_concentration, hot_money_score, pe_ttm "
        f"FROM factor_values WHERE trade_date=? AND stock_code IN ({ph})",
        conn, params=[f_date] + codes,
    )
    print(f"  factor_values 命中 {len(fv_df)}/{len(codes)} 行")

    cyq_df = pd.read_sql(
        f"SELECT ts_code, winner_rate, chips_peak_pct FROM stock_cyq_perf WHERE trade_date=? AND ts_code IN ({ph})",
        conn, params=[c_date] + codes,
    )
    print(f"  stock_cyq_perf 命中 {len(cyq_df)}/{len(codes)} 行")

    mf_df = pd.read_sql(
        f"SELECT ts_code, (net_mf_amount/10000.0) AS net_mf_wan FROM moneyflow WHERE trade_date=? AND ts_code IN ({ph})",
        conn, params=[m_date] + codes,
    )
    print(f"  moneyflow       命中 {len(mf_df)}/{len(codes)} 行 (万元单位)")

    dp_df = pd.read_sql(
        f"SELECT ts_code, close, pct_chg FROM daily_prices WHERE trade_date=? AND ts_code IN ({ph})",
        conn, params=[d_date] + codes,
    )
    print(f"  daily_prices    命中 {len(dp_df)}/{len(codes)} 行")

    # 合并成核查基线
    check_df = pd.DataFrame({"ts_code": codes})
    check_df = check_df.merge(fv_df.add_suffix("_fv").rename(columns={"ts_code_fv": "ts_code"}), on="ts_code", how="left")
    check_df = check_df.merge(cyq_df.add_suffix("_cyq").rename(columns={"ts_code_cyq": "ts_code"}), on="ts_code", how="left")
    check_df = check_df.merge(mf_df.add_suffix("_mf").rename(columns={"ts_code_mf": "ts_code"}), on="ts_code", how="left")
    check_df = check_df.merge(dp_df.add_suffix("_dp").rename(columns={"ts_code_dp": "ts_code"}), on="ts_code", how="left")

    # 构建 map
    m = {row["ts_code"]: row for _, row in check_df.iterrows()}

    print(f"\n  {'排名':<4} {'代码':<14} {'字段':<18} {'API返回':>14} {'DB原始值':>14} {'偏差':>10}  {'状态'}")
    print("  " + "-" * 90)

    field_mismatches = []
    for s in stocks:
        code = s["ts_code"]
        rk = s["rank"]
        base = m.get(code, {})
        checks = [
            # (field_in_api, column_in_DB, tolerance)
            ("winner_rate",    "winner_rate_cyq",    0.5),
            ("chips_peak_pct", "chips_peak_pct_cyq", 0.5),
            ("big_net_inflow", "net_mf_wan_mf",      0.02),  # 亿 vs 万元差1e4!! scanner 里写的是 net_mf_wan
            ("close",          "close_dp",           0.01),
            ("pct_chg",        "pct_chg_dp",         0.1),
            ("turnover_rate",  "turnover_rate_20d_fv", 0.5),
        ]
        for field, dbcol, tol in checks:
            api_v = s.get(field)
            raw_v = base.get(dbcol) if isinstance(base, dict) else None
            # big_net_inflow 单位核查：
            # scanner.py line 348: "big_net_inflow": round(float(r.get("net_mf_wan", 0.0)), 2)
            #   net_mf_wan = net_mf_amount / 10000 → 万元，前端显示 "亿" → 实际数值 100 会显示 "100 亿"
            #   这意味着：单位可能错位！
            if field == "big_net_inflow":
                # 期望真实语义如果是"亿"：需要 net_mf_wan_mf 再 / 10000 才是亿
                db_in_yi = (float(raw_v) / 10000.0) if raw_v is not None and pd.notna(raw_v) else None
                # 而 API 返回的是 net_mf_wan（万元），但前端 suffix 是 "亿"
                # 所以如果 API=0.05，实际是 0.05 万元 = 500 元 —— 这显然不合理！
                mismatch_unit = None
                if api_v is not None and db_in_yi is not None:
                    diff = abs(float(api_v) - db_in_yi)
                    expected = f"万元→API:{api_v:.2f}(但前端写亿，语义错位)"
                    # 看两种可能：
                    # A) API存万元→标"亿"字：错 10^4 倍
                    # B) 正确语义是亿: API 应 = db_in_yi
                    mismatch_unit = "UNIT?" if abs(float(api_v) - db_in_yi) > tol else "OK"
                display_raw = raw_v if isinstance(raw_v, (int, float, type(None))) or not hasattr(raw_v, "item") else (None if pd.isna(raw_v) else float(raw_v))
            else:
                mismatch_unit = None
                display_raw = raw_v

            # 偏差计算
            a = float(api_v) if api_v is not None else None
            b = None
            if field == "big_net_inflow":
                b = db_in_yi
            elif display_raw is None or (isinstance(display_raw, float) and np.isnan(display_raw)):
                b = None
            else:
                try:
                    b = float(display_raw)
                except Exception:
                    b = None

            if a is None and b is None:
                state, dev = "⚠️ 双空", "N/A"
            elif a is None:
                state, dev = "❌ API缺", "N/A"
            elif b is None:
                state, dev = "❌ DB缺", "N/A"
            else:
                diff = a - b
                pct = (diff / b * 100) if abs(b) > 1e-9 else 0
                dev = f"{diff:+.4g} ({pct:+.2f}%)"
                state = "✅" if abs(diff) <= tol else ("⚠️差大" if abs(diff) <= tol * 10 else "❌错配")
                if state != "✅":
                    field_mismatches.append({
                        "rank": rk, "code": code, "field": field, "api": a, "db": b, "diff": diff
                    })

            a_s = f"{a:.4g}" if a is not None else "None"
            b_s = f"{b:.4g}" if b is not None else "None"
            unit_tag = " (万元→亿口径)" if field == "big_net_inflow" else ""
            print(f"  {str(rk)+' ':.<4} {code:<14} {field:<18} {a_s:>14} {b_s:>14} {dev:>10}  {state}{unit_tag}")

    # 2.2 big_net_inflow 单位专门核查（关键！）
    section("2.1 · 重点核查：主力净流入单位（big_net_inflow 万元 vs 亿 错位？）")
    print("  scanner.py 逻辑:")
    print("    moneyflow.net_mf_amount (元) → /10000 → net_mf_wan (万元)")
    print("    row['big_net_inflow'] = round(net_mf_wan, 2)  # ← 存的是万")
    print("    前端显示 suffix=' 亿'  →  若 DB 真实净流入=500万元 → API=500 → 前端显示 '500 亿' ❌失真×10000")
    print()
    any_unit_issue = False
    for s in stocks:
        code = s["ts_code"]
        rk = s["rank"]
        api_v = s.get("big_net_inflow")
        # 到 moneyflow 取真实 net_mf_amount
        row = conn.execute(
            "SELECT net_mf_amount FROM moneyflow WHERE trade_date=? AND ts_code=?",
            (m_date, code),
        ).fetchone()
        real_yuan = float(row[0]) if row and row[0] is not None else 0.0
        real_wan  = real_yuan / 10000.0
        real_yi   = real_yuan / 1e8
        api_matches_wan = api_v is not None and abs(api_v - real_wan) < 0.01
        api_matches_yi  = api_v is not None and abs(api_v - real_yi)  < 0.01
        status = "❌ 万/亿错位: API是万元但前端标亿" if (api_matches_wan and abs(real_wan) > 1e-4) else (
                 "✅ 单位正确(亿)" if api_matches_yi else "⚠️ 需人工核对")
        if "❌" in status: any_unit_issue = True
        print(f"  {rk:>2}.{code:<14}  net_mf_amount={real_yuan:>12.0f}元 = {real_wan:>8.2f}万 = {real_yi:>8.4f}亿  "
              f"| API.big_net_inflow={api_v} | {status}")

    print(f"\n  ➜ 单位错位问题: {'❌ 存在 — 建议立即修复：big_net_inflow 改存 亿元 (net_mf_amount/1e8)' if any_unit_issue else '✅ 无'}")

finally:
    pass

# ──────────────────────────── 3. 因子有效性诊断 ────────────────────────────
section("3 · 有效性：因子截面分布 / 空值率 / factor_score 归一化核查")

# 3.1 factor_score：原 score vs 归一化后的得分范围
# 读取 scanner 选出日的全量因子 (全市场)
try:
    col_sql = ",".join([
        "stock_code", "return_5d", "return_10d", "return_20d", "return_60d", "excess_return_20d",
        "turnover_rate_20d", "volatility_20d", "volatility_60d", "vol_ratio",
        "north_net_inflow_ratio", "profit_ratio_estimate", "chip_concentration", "hot_money_score",
    ])
    fv_all = pd.read_sql(
        f"SELECT {col_sql} FROM factor_values WHERE trade_date=?", conn, params=(f_date,)
    )
    print(f"  全市场因子快照 ({f_date}): {len(fv_all)} 只股票")

    # 统计每个因子的空值率
    print(f"\n  因子列空值率（全市场 N={len(fv_all)}）:")
    for col in fv_all.columns:
        if col == "stock_code":
            continue
        null_cnt = int(fv_all[col].isna().sum())
        rate = null_cnt / max(len(fv_all), 1) * 100
        bar = "█" * int(rate / 2) + "░" * (50 - int(rate / 2))
        tag = " ❌严重缺失" if rate > 50 else (" ⚠️ 偏高" if rate > 10 else " ✅")
        print(f"    {col:<26s} {rate:>6.2f}% ({null_cnt:>5d}/{len(fv_all)}) {bar}{tag}")

    # 3.2 factor_score 分布：基于 Range 权重重算一遍并看分布
    try:
        from services._common import WEIGHTS_PATH, _load_pkl_weights
        _, rw = _load_pkl_weights(WEIGHTS_PATH)
        if not rw:
            rw = {"return_20d": 0.2, "excess_return_20d": 0.15, "profit_ratio_estimate": 0.2,
                  "chip_concentration": 0.15, "hot_money_score": 0.1, "turnover_rate_20d": 0.1, "vol_ratio": 0.1}
    except Exception:
        rw = {"return_20d": 0.2, "excess_return_20d": 0.15, "profit_ratio_estimate": 0.2,
              "chip_concentration": 0.15, "hot_money_score": 0.1, "turnover_rate_20d": 0.1, "vol_ratio": 0.1}
    print(f"\n  权重表 Range: {rw}")

    fv_all["factor_score_raw"] = 0.0
    weight_used_total = 0.0
    for f, w in rw.items():
        if f in fv_all.columns:
            fv_all[f"_r_{f}"] = fv_all[f].rank(pct=True, na_option="bottom")
            fv_all["factor_score_raw"] += w * fv_all[f"_r_{f}"]
            weight_used_total += w
        else:
            print(f"  [⚠️] 权重中的因子 {f} 不在 factor_values 表列中，权重 {w} 被跳过")
    print(f"  实际生效的权重合计: {weight_used_total:.3f} (期望≈1.0)")

    fs_min = fv_all["factor_score_raw"].min()
    fs_max = fv_all["factor_score_raw"].max()
    fs_mean = fv_all["factor_score_raw"].mean()
    fs_std = fv_all["factor_score_raw"].std()
    fs_rng = fs_max - fs_min
    fv_all["factor_score_norm01"] = (fv_all["factor_score_raw"] - fs_min) / fs_rng if fs_rng > 1e-9 else 0.5
    fv_all["factor_score_pct"] = fv_all["factor_score_norm01"] * 100

    qtiles = [0, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0]
    qt_raw = fv_all["factor_score_raw"].quantile(qtiles)
    qt_pct = fv_all["factor_score_pct"].quantile(qtiles)

    print(f"\n  factor_score 分布（RAW：加权百分位和；PCT：归一化到 0-100 分）")
    print(f"  RAW range = [{fs_min:.5f}, {fs_max:.5f}]  μ={fs_mean:.5f}  σ={fs_std:.5f}")
    print(f"  {'分位':<6}  {'RAW':>10}   {'PCT(0-100)':>10}")
    for q in qtiles:
        print(f"  P{q*100:<5.0f}  {qt_raw[q]:>10.5f}   {qt_pct[q]:>10.2f}")

    # 3.3 对比 API 返回的 factor_score：是 RAW 还是 PCT？
    print(f"\n  扫描选出股票的 factor_score 核查（前端显示为 '%'）：")
    score_map = {row["stock_code"]: (row["factor_score_raw"], row["factor_score_pct"])
                 for _, row in fv_all.iterrows()}
    print(f"  {'排名':<4} {'代码':<14} {'API返回':>10} {'全市场RAW':>12} {'全市场PCT':>12} {'语义判定'}")
    print("  " + "-" * 70)
    factor_score_semantics = "UNKNOWN"
    for s in stocks:
        api_fs = s.get("factor_score")
        code = s["ts_code"]
        raw_v, pct_v = score_map.get(code, (None, None))
        # 语义判断：API接近 RAW 小值(0~1)还是百分位 0~100
        close_raw = abs(api_fs - raw_v) < 0.05 if raw_v is not None else False
        close_pct = abs(api_fs - pct_v) < 2.0  if pct_v is not None else False
        if close_raw and not close_pct:
            sem = "❌ RAW小数(前端写%)"
            factor_score_semantics = "RAW_MISPLACED_PERCENT"
        elif close_pct and not close_raw:
            sem = "✅ 百分位0-100"
            factor_score_semantics = "OK_PERCENT" if factor_score_semantics != "RAW_MISPLACED_PERCENT" else factor_score_semantics
        else:
            sem = "⚠️ 边界/需核对"
        print(f"  {s['rank']:<4} {code:<14} {str(api_fs):>10} "
              f"{f'{raw_v:.5f}' if raw_v is not None else 'None':>12} "
              f"{f'{pct_v:.2f}' if pct_v is not None else 'None':>12} {sem}")

    print(f"\n  ➜ factor_score 语义: {factor_score_semantics}")
    if factor_score_semantics == "RAW_MISPLACED_PERCENT":
        print("     ❗ 选出股票的前端显示会是 '-0.1%'、'0.3%' 之类的极小数")
        print("     ❗ 实际语义是 RAW 加权和（~0.4-0.9 小数）→ 前端 % 误导")
        print("     建议：API 返回 factor_score_pct (0~100)，前端正常加 %")

    # 3.4 选出股票在全市场的真实百分位 → 验证"前5%"筛选口径
    print(f"\n  选出股票的真实因子百分位（全市场排名 / 总样本 × 100%）：")
    fv_all["_rank_asc"] = fv_all["factor_score_raw"].rank(ascending=True, method="min")
    rank_map = {row["stock_code"]: (row["_rank_asc"], len(fv_all)) for _, row in fv_all.iterrows()}
    for s in stocks:
        code = s["ts_code"]
        rk_asc, N = rank_map.get(code, (None, None))
        if rk_asc is None:
            print(f"    {s['rank']:>2}.{code:<14} 不在因子表中！")
            continue
        pctile = (rk_asc / N) * 100
        print(f"    {s['rank']:>2}.{code:<14} 排名 {int(rk_asc):>5d}/{N}  ≈  Top {100 - pctile:.2f}%  "
              f"{'✅<5%' if (100-pctile) <= 5 else ('⚠️<10%' if (100-pctile) <= 10 else '❌>10% 未进前列')}")

except Exception as _e:
    import traceback
    print(f"  [诊断异常] {_e}\n{traceback.format_exc()}")

# ──────────────────────────── 4. MVO 权重诊断 ────────────────────────────
section("4 · MVO 权重：是否真的跑了 optimizer，还是等权兜底？")

mvo_vals = [s.get("mvo_weight") for s in stocks]
mvo_unique = len(set(mvo_vals))
avg_w = np.mean(mvo_vals) if mvo_vals else 0
equal_w = 100.0 / max(len(stocks), 1)
is_equal = all(abs(w - equal_w) < 0.1 for w in mvo_vals) if mvo_vals else False

print(f"  选出 {len(stocks)} 只：权重值 = {mvo_vals}")
print(f"  唯一权重数={mvo_unique}  |  理论等权 = {equal_w:.2f}%  |  实际平均 = {avg_w:.2f}%")
print(f"  是否纯等权：{'❌ 是 — 意味着 optimize_portfolio 抛错走了兜底(详见 scanner.py line 294 Exception)' if is_equal else '✅ 非等权（MVO真正输出差异权重）'}")

try:
    from scripts.portfolio_optimizer import optimize_portfolio
    codes2 = [s["ts_code"] for s in stocks]
    er = {s["ts_code"]: float(s["build_score"]) / 100.0 for s in stocks}
    inds = {s["ts_code"]: str(s.get("industry", "")).split("|")[-1].strip() for s in stocks}
    wts_real = optimize_portfolio(codes2, er, inds, d_date)
    print(f"\n  现场重跑 optimize_portfolio() 返回：")
    for c, w in sorted(wts_real.items(), key=lambda x: -x[1]):
        w_pct = round(w * 100, 2)
        print(f"    {c:<14} {w_pct:>6.2f}%")
    unique2 = len(set(round(v * 100, 2) for v in wts_real.values()))
    print(f"  ➜ optimizer 本身输出唯一权重数: {unique2}  {'（等权兜底触发）' if unique2 == 1 and len(wts_real) > 1 else ''}")
except Exception as _e2:
    import traceback
    print(f"  [MVO重跑异常] {_e2}\n{traceback.format_exc()}")

# ──────────────────────────── 5. 今日涨跌真实性 ────────────────────────────
section("5 · 今日涨跌：pct_chg 真实性 + 涨幅过滤口径")

print(f"  scanner 涨幅过滤门槛（config/thresholds.yaml）读取中...")
try:
    with open(os.path.join(_PROJECT_ROOT, "config", "thresholds.yaml"), "r", encoding="utf-8") as f:
        import yaml
        th_cfg = yaml.safe_load(f)
    scan_cfg = th_cfg.get("scanner", {})
    prefilter = scan_cfg.get("prefilter", {})
    print(f"  prefilter.winner_rate_lo={prefilter.get('winner_rate_lo')} hi={prefilter.get('winner_rate_hi')}")
except Exception:
    print("  (配置读取失败，略过)")

print(f"\n  涨幅过滤实际命中：（scanner 前端说明为 -8%~+5%，但代码 pre 过滤是 winner_rate，非 pct_chg 直接过滤）")
print(f"  scanner.py 的 pct_chg 仅作为 scoring_weights.pct_chg_inv_rank (7%) 的排名维度，未做硬 cutoff")
for s in stocks:
    pct = s.get("pct_chg")
    within_range = -8.0 <= (pct or 0) <= 5.0
    print(f"    {s['rank']:>2}.{s['ts_code']:<14} {s['name']:<10} pct_chg={pct:>6.2f}%  "
          f"{'✅ 在 [-8, +5]' if within_range else '❌ 超出说明文档范围'}")

conn.close()

print("\n" + "=" * 72)
print("▍诊断结束")
print("=" * 72)
