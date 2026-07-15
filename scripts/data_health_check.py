# -*- coding: utf-8 -*-
"""
data_health_check.py —— 每日数据体检与哨兵监控脚本
执行断层扫描(Gap Detection)与逻辑一致性校验(Consistency Check)
输出体检报告供后端和前端调用，触发熔断机制。
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "db", "stock_data.db")
REPORT_PATH = os.path.join(PROJECT_ROOT, "db", "health_report.json")

def run_health_check():
    report = {
        "score": 100,
        "status": "PASS",
        "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "issues": []
    }
    
    if not os.path.exists(DB_PATH):
        report["score"] = 0
        report["status"] = "ERROR"
        report["issues"].append("数据库文件不存在")
        save_report(report)
        return report

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # 1. 交易日历断层扫描 (Gap Detection)
            # 获取最近 10 个交易日
            today_str = datetime.now().strftime("%Y%m%d")
            cursor.execute("""
                SELECT cal_date FROM trade_cal 
                WHERE is_open = 1 AND cal_date <= ?
                ORDER BY cal_date DESC LIMIT 10
            """, (today_str,))
            recent_trade_dates = [row[0] for row in cursor.fetchall()]
            
            if not recent_trade_dates:
                report["score"] -= 50
                report["issues"].append("交易日历表(trade_cal)缺失近期数据")
            else:
                tables_to_check = ["daily_prices", "moneyflow", "daily_basic"]
                for table in tables_to_check:
                    # 检查表是否存在
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                    if not cursor.fetchone():
                        report["score"] -= 30
                        report["issues"].append(f"缺失核心表: {table}")
                        continue
                        
                    # 检查最近10个交易日中，有哪些交易日在这张表中没有数据
                    cursor.execute(f"SELECT DISTINCT trade_date FROM {table} ORDER BY trade_date DESC LIMIT 30")
                    existing_dates = {row[0] for row in cursor.fetchall()}
                    
                    missing_dates = [d for d in recent_trade_dates if d not in existing_dates]
                    # 如果缺失最新的交易日，可能是还没收盘/还没拉取，适当宽容当天，但如果是历史日缺失，则扣分
                    # 为避免每天下午盘中误报，如果只缺今天，且当前时间早于18:00，不扣分
                    now = datetime.now()
                    is_before_18 = now.hour < 18
                    
                    for md in missing_dates:
                        if md == today_str and is_before_18:
                            continue # 盘中尚未拉取，正常
                        report["score"] -= 10
                        report["issues"].append(f"数据断层漏洞: [{table}] 表缺失交易日 {md} 的数据")

            # 2. 逻辑一致性校验 (Consistency Check)
            # 检查 moneyflow 表是否还有异常的 net_mf_amount (即等于总买入额的 Bug)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='moneyflow'")
            if cursor.fetchone():
                cursor.execute("""
                    SELECT trade_date, COUNT(*) 
                    FROM moneyflow 
                    WHERE abs(net_mf_amount - ((ifnull(buy_lg_amount,0) + ifnull(buy_elg_amount,0)) - (ifnull(sell_lg_amount,0) + ifnull(sell_elg_amount,0)))) > 1
                    GROUP BY trade_date
                """)
                inconsistent_rows = cursor.fetchall()
                if inconsistent_rows:
                    bad_dates = [row[0] for row in inconsistent_rows]
                    report["score"] -= 40
                    report["issues"].append(f"逻辑一致性漏洞: moneyflow 表在 {bad_dates} 存在大单净流出计算恒等式错误(脏数据)")

    except Exception as e:
        report["score"] = 0
        report["status"] = "ERROR"
        report["issues"].append(f"体检脚本运行异常: {str(e)}")

    if report["score"] < 100:
        report["status"] = "ERROR" if report["score"] < 70 else "WARNING"
    else:
        report["status"] = "PASS"
        report["issues"].append("所有核心数据表通过完整性与一致性检验。")

    save_report(report)
    return report

def save_report(report):
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=4)
    print(f"数据体检完成，得分: {report['score']}，状态: {report['status']}")
    for issue in report["issues"]:
        print(f" - {issue}")

if __name__ == "__main__":
    run_health_check()
