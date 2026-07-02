import os
import sys
import yaml
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def load_config(config_path="agent/config.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def compute_ic_for_period(db_path, csv_path, factors, recent_weeks=8):
    conn = sqlite3.connect(db_path)
    
    query_prices = "SELECT ts_code AS stock_code, trade_date, close, adj_factor FROM daily_prices WHERE trade_date >= '20200101'"
    df_prices = pd.read_sql(query_prices, conn)
    df_prices["trade_date"] = df_prices["trade_date"].astype(str)
    df_prices = df_prices.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    df_prices["close_adj"] = df_prices["close"] * df_prices["adj_factor"]
    df_prices["future_return_5d"] = df_prices.groupby("stock_code")["close_adj"].shift(-5) / df_prices["close_adj"] - 1.0
    df_prices["future_return_5d"] = df_prices["future_return_5d"].clip(-0.5, 0.8)
    
    query_factors = f"SELECT * FROM factor_values"
    df_factors = pd.read_sql(query_factors, conn)
    df_factors["trade_date"] = df_factors["trade_date"].astype(str)
    conn.close()
    
    df_regime = pd.read_csv(csv_path)
    df_regime["trade_date"] = df_regime["trade_date"].astype(str)
    
    df_merge = pd.merge(df_factors, df_prices[["stock_code", "trade_date", "future_return_5d"]], on=["stock_code", "trade_date"], how="inner")
    df_aligned = pd.merge(df_merge, df_regime[["trade_date", "regime"]], on="trade_date", how="inner")
    df_aligned = df_aligned.dropna(subset=["future_return_5d"]).reset_index(drop=True)
    
    date_counts = df_aligned["trade_date"].value_counts()
    valid_dates = date_counts[date_counts >= 30].index
    df_valid = df_aligned[df_aligned["trade_date"].isin(valid_dates)].copy()
    
    df_valid["future_return_5d_rank"] = df_valid.groupby("trade_date")["future_return_5d"].rank()
    
    rank_cols = []
    for f in factors:
        rank_col = f + "_rank"
        df_valid[rank_col] = df_valid.groupby("trade_date")[f].rank()
        rank_cols.append(rank_col)
    
    df_ic_grouped = df_valid.groupby("trade_date")[rank_cols].corrwith(df_valid["future_return_5d_rank"], method="pearson")
    df_ic_grouped.columns = [c[:-5] for c in df_ic_grouped.columns]
    df_ic = df_ic_grouped.fillna(0.0).reset_index()
    df_ic = df_ic.sort_values("trade_date").reset_index(drop=True)
    
    return df_ic

def run_audit(config_path="agent/config.yaml", audit_weeks=8):
    config = load_config(config_path)
    paths = config["paths"]
    val_cfg = config["validation"]
    
    all_factors = config["factors"]["base_pool"]
    custom_factors = config["factors"]["custom_new_factors"]
    
    print("=" * 70)
    print(f"📊 因子 IC 衰减审计脚本")
    print(f"📅 审计时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔍 审计窗口: 最新 {audit_weeks} 周")
    print(f"⚠️ 警戒阈值: IC 衰减 > 30%")
    print("=" * 70)
    
    df_ic = compute_ic_for_period(paths["stock_data_db"], paths["market_labels_csv"], all_factors)
    
    base_start = val_cfg["baseline_start_date"]
    base_end = val_cfg["baseline_end_date"]
    df_ic_base = df_ic[(df_ic["trade_date"] >= base_start) & (df_ic["trade_date"] <= base_end)]
    
    df_ic_latest = df_ic.tail(audit_weeks)
    
    print(f"\n📈 数据概览:")
    print(f"   - 基准期: {base_start} ~ {base_end} ({len(df_ic_base)} 周)")
    print(f"   - 审计期: {df_ic_latest['trade_date'].iloc[0]} ~ {df_ic_latest['trade_date'].iloc[-1]} ({len(df_ic_latest)} 周)")
    print(f"   - 监控因子总数: {len(all_factors)}")
    print(f"   - 当前组合因子: {custom_factors}")
    
    print("\n" + "=" * 70)
    print("📋 审计报告详情")
    print("=" * 70)
    
    audit_report = {
        "audit_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "audit_weeks": audit_weeks,
        "total_factors": len(all_factors),
        "custom_factors": custom_factors,
        "warning_count": 0,
        "critical_count": 0,
        "factors": []
    }
    
    header = f"{'因子名称':<24} {'基准IC':>10} {'最新8周IC':>12} {'衰减率':>8} {'状态':<10} {'在组合中':<8}"
    print(header)
    print("-" * 70)
    
    for f in all_factors:
        base_ic_mean = df_ic_base[f].mean() if len(df_ic_base) > 0 else 0.0
        latest_ic_mean = df_ic_latest[f].mean() if len(df_ic_latest) > 0 else 0.0
        
        base_ic_abs = abs(base_ic_mean)
        latest_ic_abs = abs(latest_ic_mean)
        
        if base_ic_abs > 1e-6:
            decay_ratio = 1.0 - (latest_ic_abs / base_ic_abs)
        else:
            decay_ratio = 1.0
        
        if base_ic_abs < 0.015:
            status = "CRITICAL"
            reason = "基准IC过低"
        elif decay_ratio >= 0.50:
            status = "CRITICAL"
            reason = f"衰减>50%"
        elif decay_ratio >= 0.30:
            status = "WARNING"
            reason = f"衰减>30%"
        else:
            status = "HEALTHY"
            reason = "正常"
        
        in_custom = "✅" if f in custom_factors else "❌"
        
        if status == "WARNING":
            audit_report["warning_count"] += 1
        elif status == "CRITICAL":
            audit_report["critical_count"] += 1
        
        audit_report["factors"].append({
            "factor": f,
            "baseline_ic": round(base_ic_mean, 4),
            "latest_ic": round(latest_ic_mean, 4),
            "decay_ratio": round(decay_ratio * 100, 1),
            "status": status,
            "reason": reason,
            "in_custom": f in custom_factors
        })
        
        status_color = {
            "HEALTHY": "🟢",
            "WARNING": "🟡",
            "CRITICAL": "🔴"
        }
        
        print(f"{f:<24} {base_ic_mean:>10.4f} {latest_ic_mean:>12.4f} {decay_ratio*100:>7.1f}% {status_color.get(status, '')} {status:<9} {in_custom:<8}")
    
    print("-" * 70)
    
    print("\n📊 审计汇总:")
    print(f"   - 健康因子: {len([f for f in audit_report['factors'] if f['status'] == 'HEALTHY'])} 个")
    print(f"   - 警戒因子: {audit_report['warning_count']} 个")
    print(f"   - 危急因子: {audit_report['critical_count']} 个")
    
    custom_warnings = [f for f in audit_report['factors'] if f['in_custom'] and f['status'] != 'HEALTHY']
    if custom_warnings:
        print(f"\n⚠️ 当前组合中存在 {len(custom_warnings)} 个非健康因子:")
        for f in custom_warnings:
            print(f"   - {f['factor']}: {f['status']} (衰减 {f['decay_ratio']}%)")
    
    if audit_report["critical_count"] == 0 and audit_report["warning_count"] == 0:
        print("\n🎉 所有因子状态健康，无需干预。")
    else:
        print("\n⚠️ 建议关注上述非健康因子，考虑替换或调整权重。")
    
    report_path = f"audit_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    import json
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(audit_report, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 审计报告已保存至: {report_path}")
    
    return audit_report

if __name__ == "__main__":
    run_audit(audit_weeks=8)