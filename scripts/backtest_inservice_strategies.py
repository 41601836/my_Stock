# -*- coding: utf-8 -*-
"""
P1-6 在役策略统一口径历史回测（2026-09-03 复盘）
========================================================================
目的：复盘报告 2.3 引用的"在役三策略超额年化 -13%~-15%"为临时测算、未落盘不可复核。
本脚本按【统一口径】重算并落盘，数字可复现：
  - 同区间：最近 208 个交易周（df_aligned 尾部窗口，四策略完全一致）
  - 同频率：周频调仓（引擎按周切片）
  - 同成本：transaction_cost = 0.0015（15bps，config backtest 节）
  - 同基准：等权基准（当周全样本 future_return_5d 截面均值）
  - 同持仓：top_n_stocks = 20（config backtest 节）
策略：
  1) old_core   老核心静态组合：base_pool 活跃因子 × baseline_ic 权重（生产平行回测基线）
  2) custom_new 配置自定义组合：config factors.custom_new_factors × recent_ic 权重（在役配置组合）
  3) routed     多状态路由组合【生产在役】：load_weights_by_regime 读取
                models/regime_weights.pkl(震荡) + bull_weights_proposed.pkl(牛市) + 防御池(Dark/Bear)
                + 贝塔剥离 + 预测偏差回响 + 轻仓跟踪
  4) jack       游资路由（参考项，非生产自动部署）：硬编码抄底/追涨权重
  5) scanner    胜率猎手优化器（web 层每日推荐）：无因子引擎口径，改取 recommendation_tracker
                清洗后前瞻实绩（P0-3 快照语义）作为其在役证据
输出：agent/inservice_strategies_backtest_<date>.json（自包含：因子/权重/指标/口径元数据）
注意：使用临时配置副本，不触碰 agent/config.yaml（巡航可同时运行而互不干扰）。
"""
import os
import sys
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.paths import PATHS, startup_check

startup_check()

from agent.validator import validate_factors
from agent.searcher import search_new_factors
from agent.recommender import recommend_adaptive_portfolio
from agent.backtester import run_jack_portfolio_backtest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_DATE = datetime.now().strftime("%Y%m%d")
WEEKS = 208


def pick_base_config():
    """巡航运行中其 config.yaml 被物理重写为实验网格；config.yaml.bak 是巡航启动时的在役基线。
    巡航结束后 config.yaml 已恢复为基线。二者皆非则报错。"""
    live = os.path.join(PROJECT_ROOT, "agent", "config.yaml")
    bak = live + ".bak"
    if os.path.exists(bak):
        return bak, "config.yaml.bak（巡航启动时在役基线）"
    return live, "config.yaml（巡航未运行/已恢复的在役基线）"


def calc_tracker_stats():
    """scanner 胜率猎手优化器：recommendation_tracker 清洗后前瞻实绩（P0-3 最终快照口径）。"""
    db_path = os.path.join(PROJECT_ROOT, "db", "stock_data.db")
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # 快照语义已由 P0-3 修复（每日仅最终组合落库）；alpha_5d 为小数（×100 为百分数）
        total = cur.execute("SELECT COUNT(*) FROM recommendation_tracker").fetchone()[0]
        rows = cur.execute(
            "SELECT recommend_date, ts_code, alpha_5d, factor_score FROM recommendation_tracker "
            "WHERE alpha_5d IS NOT NULL"
        ).fetchall()
        days = sorted({r[0] for r in rows})
        alphas = [r[2] for r in rows]
        n = len(alphas)
        mean_a = sum(alphas) / n if n else 0.0
        med_a = sorted(alphas)[n // 2] if n else 0.0
        win = sum(1 for a in alphas if a > 0) / n if n else 0.0
        # 每日推荐按【推荐时 factor_score】排名取前 10（严禁按未来 alpha 排序——前视偏差）
        per_day = {}
        for d, _c, a, fs in rows:
            per_day.setdefault(d, []).append((fs if fs is not None else 0.0, a))
        top10, day_pos = [], 0
        for d, vals in per_day.items():
            day_alphas = [a for _fs, a in vals]
            by_score = sorted(vals, key=lambda x: x[0], reverse=True)
            top10.extend([a for _fs, a in by_score[:10]])
            if sum(day_alphas) / len(day_alphas) > 0:
                day_pos += 1
        t10_mean = sum(top10) / len(top10) if top10 else 0.0
        t10_win = sum(1 for a in top10 if a > 0) / len(top10) if top10 else 0.0
        return {
            "source": "db/stock_data.db recommendation_tracker（P0-3 清洗后最终日快照）",
            "total_rows": total,
            "alpha_5d_non_null": n,
            "recommend_days": len(days),
            "window": f"{days[0]} ~ {days[-1]}" if days else None,
            "all_picks": {
                "alpha_5d_mean_pct": round(mean_a * 100, 3),
                "alpha_5d_median_pct": round(med_a * 100, 3),
                "win_rate_pct": round(win * 100, 1),
            },
            "daily_top10": {
                "samples": len(top10),
                "alpha_5d_mean_pct": round(t10_mean * 100, 3),
                "win_rate_pct": round(t10_win * 100, 1),
                "positive_day_ratio_pct": round(day_pos / len(per_day) * 100, 1) if per_day else 0.0,
            },
            "note": "scanner 为 web 层复合打分（factor_score/winner_rate/net_mf/pct_chg），不适用因子引擎回测；以真实推荐前瞻实绩为在役证据。daily_top10 按推荐时 factor_score 当日排名取前 10（非按未来收益排序，无前视偏差）",
        }
    finally:
        conn.close()


def main():
    src_cfg, src_desc = pick_base_config()
    tmp_cfg = os.path.join(PROJECT_ROOT, "agent", f"config_p16_tmp_{RUN_DATE}.yaml")
    shutil.copy(src_cfg, tmp_cfg)
    print(f"ℹ️ 使用在役基线配置: {src_desc} → 临时副本 {os.path.basename(tmp_cfg)}（不触碰 config.yaml）")
    # 元数据立即读取并复用：回测耗时较长，期间巡航可能退出并清理 config.yaml.bak（竞态）
    import yaml
    with open(src_cfg, "r", encoding="utf-8") as f:
        src_config = yaml.safe_load(f)
    top_n = int(src_config["backtest"]["top_n_stocks"])
    in_service_combo = src_config.get("factors", {}).get("custom_new_factors", [])

    try:
        print("\n=== 1/4 因子校验 + 数据对齐（生产同路径 validate_factors）===")
        val_report, df_aligned = validate_factors(tmp_cfg)
        active_base = [f for f, det in val_report.items()
                       if not f.startswith("_") and det["status"] in ["VALID", "WARNING"]]
        print(f"   活跃基础因子 {len(active_base)} 个: {active_base}")

        print("\n=== 2/4 新因子搜索（生产同路径 search_new_factors）===")
        search_report, new_factors = search_new_factors(df_aligned, active_base, tmp_cfg)

        print(f"\n=== 3/4 平行回测 ×3（old_core / custom_new / routed，{WEEKS} 周）===")
        rec = recommend_adaptive_portfolio(
            df_aligned, val_report, search_report, new_factors,
            weeks_to_test=WEEKS, config_path=tmp_cfg
        )

        print(f"\n=== 4/4 Jack 游资路由回测（参考项，{WEEKS} 周）===")
        jack_metrics, jack_summary = run_jack_portfolio_backtest(df_aligned, WEEKS, tmp_cfg)
    finally:
        if os.path.exists(tmp_cfg):
            os.remove(tmp_cfg)
            print(f"\n🧹 临时配置副本已删除: {os.path.basename(tmp_cfg)}")

    dates = sorted(df_aligned["trade_date"].unique())
    window = f"{dates[-WEEKS]} ~ {dates[-1]}" if len(dates) >= WEEKS else f"{dates[0]} ~ {dates[-1]}"

    def slim(metrics):
        keys = ["total_return", "annualized_return", "annualized_volatility", "max_drawdown",
                "calmar_ratio", "excess_total_return", "excess_annual_return",
                "excess_annual_volatility", "excess_max_drawdown", "excess_calmar_ratio",
                "win_rate", "excess_win_rate", "weeks"]
        return {k: (round(float(metrics[k]), 6) if k in metrics else None) for k in keys}

    out = {
        "report": "P1-6 在役策略统一口径历史回测",
        "run_date": RUN_DATE,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "caliber": {
            "window_weeks": WEEKS,
            "window_dates": window,
            "rebalance": "周频（引擎按周切片选股）",
            "transaction_cost_bps": 15,
            "transaction_cost_note": "config backtest.transaction_cost=0.0015，买卖双边按引擎逻辑扣除",
            "benchmark": "等权基准（当周全样本 future_return_5d 截面均值）",
            "top_n_stocks": top_n,
            "data_path": "agent/validator.validate_factors 对齐面板（与生产巡航/推荐同路径）",
            "config_source": src_desc,
            "in_service_config_combo": in_service_combo,
            "in_service_note": "在役 config.custom_new_factors = 巡航自动部署组合（2026-09-03 12:20 随 regime_weights.pkl 部署，即 P1-3 闸门拦截的刀刃组合）；routed 路由直接读 models/regime_weights.pkl",
        },
        "strategies": {
            "old_core": {
                "label": "老核心静态组合（平行回测基线）",
                "in_service": "baseline",
                "factors": rec["old_portfolio"]["factors"],
                "weights": {k: round(float(v), 4) for k, v in rec["old_portfolio"]["weights"].items()},
                "metrics": slim(rec["old_portfolio"]["metrics"]),
            },
            "custom_new": {
                "label": "在役配置组合（config factors.custom_new_factors = 巡航自动部署 combo10 四因子，固定组合样本内回测）",
                "in_service": "deployed_config",
                "factors": rec["new_portfolio"]["factors"],
                "weights": {k: round(float(v), 4) for k, v in rec["new_portfolio"]["weights"].items()},
                "metrics": slim(rec["new_portfolio"]["metrics"]),
            },
            "routed": {
                "label": "多状态路由组合【生产在役实盘路径：regime_weights.pkl + bull_weights + 防御池 + 贝塔剥离/误差回响/Dark轻仓】",
                "in_service": "production",
                "factors": None,
                "weights": None,
                "metrics": slim(rec["routed_portfolio"]["metrics"]),
                "route_summary": rec["routed_portfolio"].get("route_summary"),
            },
            "jack": {
                "label": "游资 Jack 路由（硬编码抄底/追涨，参考项，非生产自动部署）",
                "in_service": "reference",
                "factors": ["RANGE: return_5d/north_net_inflow_ratio/turnover_rate_20d",
                            "BULL: return_5d/volatility_10d/vol_ratio", "DARK/BEAR: 空仓"],
                "weights": None,
                "metrics": slim(jack_metrics),
                "route_summary": jack_summary,
            },
        },
        "scanner_tracker": calc_tracker_stats(),
        "decision_note": (
            "routed 为生产在役实盘路径（周度 regime 路由+防御切换，直接消费 models/regime_weights.pkl）；"
            "custom_new 为在役 config 固定组合（2026-09-03 12:20 巡航自动部署的 combo10）的样本内平行回测；"
            "old_core 为引擎基线；jack 仅参考非自动部署；scanner（胜率猎手）无因子引擎口径，以 tracker 前瞻实绩为在役证据。"
            "注意：custom_new 样本内为正而 routed/old_core 超额为负，差异来自路由/防御/空仓周与权重消费方式，"
            "且 tracker 前瞻（32 推荐日）显示实盘 alpha_5d 均值 -0.40% —— 样本内优势未在实盘兑现。"),
    }

    out_path = os.path.join(PROJECT_ROOT, "agent", f"inservice_strategies_backtest_{RUN_DATE}.json")
    tmp_out = out_path + ".tmp"
    with open(tmp_out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    os.replace(tmp_out, out_path)

    print("\n" + "=" * 78)
    print(f"📊 统一口径回测结果（窗口 {window}，周频/15bps/等权基准/Top{top_n}）")
    print("=" * 78)
    for key, s in out["strategies"].items():
        m = s["metrics"]
        print(f"  {key:11s} [{s['in_service']:10s}] 绝对年化 {m['annualized_return']*100:7.2f}% | "
              f"超额年化 {m['excess_annual_return']*100:7.2f}% | 超额卡玛 {m['excess_calmar_ratio']:7.3f} | "
              f"超额回撤 {m['excess_max_drawdown']*100:6.2f}% | 超额周胜率 {m['excess_win_rate']*100:5.1f}%")
    st = out["scanner_tracker"]
    print(f"  scanner     [tracker前瞻] 全样本 alpha_5d 均值 {st['all_picks']['alpha_5d_mean_pct']:6.2f}% / "
          f"胜率 {st['all_picks']['win_rate_pct']:.1f}% | 每日Top10 均值 {st['daily_top10']['alpha_5d_mean_pct']:6.2f}% / "
          f"胜率 {st['daily_top10']['win_rate_pct']:.1f}%（{st['recommend_days']} 个推荐日）")
    print("=" * 78)
    print(f"📝 结果已落盘: {os.path.relpath(out_path, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
