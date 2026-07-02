# -*- coding: utf-8 -*-
"""
test_tushare_fetch.py —— Tushare 5000 积分核心接口拉取测试与时延评估 (修正优化版)
================================================================================
1. 支持从 config.json 自动载入 tushare_token。
2. 特征工程前置需求：日线 (daily) 和复权因子 (stk_factor) 拉取范围延伸至 2025-09-15 至 2026-01-31。
3. 财务指标规避：fina_indicator 仅针对茅台、宁德时代等 3 只测试个股拉取，防止全市场大批量报错。
4. 极致并发与限速器 (Rate Limiter)：引入 ThreadPoolExecutor 并发下载，辅以 QPS=6 锁限速器。
5. 统计每个接口的耗时，将数据写入本地 db/stock_data.db 供后续特征工程调用。
"""

import os
import sys
import json
import time
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import numpy as np
import tushare as ts

class RateLimiter:
    """
    多线程安全限速器 (Rate Limiter)，通过锁机制限制 QPS (每秒请求数)
    """
    def __init__(self, qps=6):
        self.interval = 1.0 / qps
        self.lock = threading.Lock()
        self.last_call = time.time()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_call
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_call = time.time()

# 初始化全局限速器
limiter = RateLimiter(qps=6.5)

def load_tushare_token(config_path="config.json"):
    """从 config.json 中载入 tushare_token"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"❌ 未找到配置文件: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    token = config.get("api", {}).get("tushare_token", "")
    if not token:
        raise ValueError("❌ 配置文件中没有找到 tushare_token")
    return token

def get_trading_dates(db_path, start_date, end_date):
    """从本地数据库获取交易日历列表"""
    if not os.path.exists(db_path):
        # 兜底生成自然交易日 (以防数据库无数据)
        print("⚠️ 数据库尚未初始化，生成测试月份默认日历。")
        return pd.date_range(start=start_date, end=end_date, freq="B").strftime("%Y%m%d").tolist()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT cal_date FROM trade_cal 
            WHERE is_open = 1 AND cal_date BETWEEN ? AND ? 
            ORDER BY cal_date;
        """, (start_date, end_date))
        dates = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        print(f"⚠️ 从本地读取交易日历出错 ({e})，使用工作日日历兜底。")
        dates = pd.date_range(start=start_date, end=end_date, freq="B").strftime("%Y%m%d").tolist()
    finally:
        conn.close()
    return dates

def fetch_single_date(pro, interface_func, date_val, date_param_name, interface_name):
    """
    拉取单个日期的任务单元 (带限速器和重试机制)
    """
    for retry in range(3):
        try:
            # 申请通过限速器
            limiter.wait()
            
            # 发起 API 请求
            params = {date_param_name: date_val}
            df = interface_func(**params)
            
            return df, True
        except Exception as e:
            # 针对特定接口超限 (如 stk_mins 限制1次/分钟)，休眠更久
            if "超限" in str(e) or "频率" in str(e):
                time.sleep(2.0)
            else:
                time.sleep(0.5)
            if retry == 2:
                print(f"  ❌ 接口 [{interface_name}] 日期 {date_val} 拉取彻底失败: {e}")
                return None, False

def fetch_and_save_concurrent(pro, db_path, interface_name, dates, fetch_func, date_param_name="trade_date", max_workers=5):
    """
    使用线程池并发拉取并保存到 SQLite
    """
    print(f"\n🚀 开始拉取接口 [{interface_name}] (数据天数: {len(dates)})，启用并发...")
    start_time = time.time()
    
    df_list = []
    success_count = 0
    
    # 线程池并发调用
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_date = {
            executor.submit(fetch_single_date, pro, fetch_func, d, date_param_name, interface_name): d 
            for d in dates
        }
        
        for future in as_completed(future_to_date):
            d = future_to_date[future]
            try:
                df, success = future.result()
                if success:
                    success_count += 1
                    if df is not None and not df.empty:
                        df_list.append(df)
            except Exception as exc:
                print(f"  ❌ 线程执行日期 {d} 产生未捕获异常: {exc}")
                
    duration = time.time() - start_time
    total_rows = 0
    
    if df_list:
        df_all = pd.concat(df_list, ignore_index=True)
        total_rows = len(df_all)
        
        # 写入本地数据库，表名统一叫 fetch_test_{interface_name}
        conn = sqlite3.connect(db_path)
        table_name = f"fetch_test_{interface_name}"
        df_all.to_sql(table_name, conn, if_exists="replace", index=False)
        conn.close()
        print(f"✅ 接口 [{interface_name}] 导入完成，表 [{table_name}] 记录数: {total_rows} 行")
    else:
        print(f"⚠️ 接口 [{interface_name}] 未拉取到有效数据")
        
    print(f"⏱️ 接口 [{interface_name}] 耗时: {duration:.2f} 秒 | 成功率: {success_count}/{len(dates)} | 吞吐率: {total_rows/max(0.1, duration):.1f} 行/秒")
    
    return {
        "interface": interface_name,
        "duration": duration,
        "rows": total_rows,
        "requests": len(dates),
        "success_rate": (success_count / len(dates)) * 100 if len(dates) > 0 else 0
    }

def fetch_fina_indicator_spec(pro, db_path):
    """
    单独为 fina_indicator 进行个股接口拉取 (避免全市场按日拉取报错)
    """
    print("\n🚀 开始拉取个股财务指标 [fina_indicator] (茅台、宁德、平安银行)...")
    start_time = time.time()
    
    test_codes = ["600519.SH", "300750.SZ", "000001.SZ"]
    df_list = []
    success_count = 0
    
    for code in test_codes:
        for retry in range(3):
            try:
                limiter.wait()
                df = pro.fina_indicator(ts_code=code, start_date="20260101", end_date="20260131")
                if df is not None and not df.empty:
                    df_list.append(df)
                success_count += 1
                break
            except Exception as e:
                time.sleep(1.0)
                if retry == 2:
                    print(f"  ❌ fina_indicator 个股 {code} 访问失败: {e}")
                    
    duration = time.time() - start_time
    total_rows = 0
    if df_list:
        df_all = pd.concat(df_list, ignore_index=True)
        total_rows = len(df_all)
        conn = sqlite3.connect(db_path)
        df_all.to_sql("fetch_test_fina_indicator", conn, if_exists="replace", index=False)
        conn.close()
        print(f"✅ fina_indicator 个股导入完成，表 [fetch_test_fina_indicator] 记录数: {total_rows} 行")
        
    return {
        "interface": "fina_indicator",
        "duration": duration,
        "rows": total_rows,
        "requests": len(test_codes),
        "success_rate": (success_count / len(test_codes)) * 100
    }

def main():
    print("=" * 70)
    print("🌟 Tushare 5000 积分接口全量拉取与时延优化评估 (修正版)")
    print("=" * 70)
    
    db_path = "db/stock_data.db"
    
    # 1. 载入 Token
    try:
        token = load_tushare_token()
        ts.set_token(token)
        pro = ts.pro_api()
    except Exception as e:
        print(f"❌ 载入 Tushare Token 失败: {e}")
        return
        
    # 2. 获取测试日期
    # 2026 年 1 月日历
    trade_dates_jan = get_trading_dates(db_path, "20260101", "20260131")
    all_days_jan = pd.date_range(start="20260101", end="20260131").strftime("%Y%m%d").tolist()
    
    # 特征工程前置滚动需求 (2025-09-15 至 2026-01-31)
    trade_dates_extended = get_trading_dates(db_path, "20250915", "20260131")
    
    print(f"ℹ️ 前置滚动日线拉取范围: 20250915 ~ 20260131 (共 {len(trade_dates_extended)} 交易日)")
    print(f"ℹ️ 其他指标拉取范围: 20260101 ~ 20260131 (共 {len(trade_dates_jan)} 交易日 / {len(all_days_jan)} 自然日)")
    
    # 3. 定义并发拉取接口集合
    # 财务指标单独调用，龙虎榜和股东数等按常规区间
    test_suite = [
        # 行情与复权因子 (使用扩展区间计算波动率与累计收益率)
        {"name": "daily", "dates": trade_dates_extended, "func": pro.daily, "param": "trade_date"},
        {"name": "stk_factor", "dates": trade_dates_extended, "func": pro.stk_factor, "param": "trade_date"},
        # 1月份其他数据 (按天拉取)
        {"name": "daily_basic", "dates": trade_dates_jan, "func": pro.daily_basic, "param": "trade_date"},
        {"name": "moneyflow", "dates": trade_dates_jan, "func": pro.moneyflow, "param": "trade_date"},
        {"name": "margin_detail", "dates": trade_dates_jan, "func": pro.margin_detail, "param": "trade_date"},
        {"name": "block_trade", "dates": trade_dates_jan, "func": pro.block_trade, "param": "trade_date"},
        {"name": "top_inst", "dates": trade_dates_jan, "func": pro.top_inst, "param": "trade_date"},
        {"name": "hsgt_top10", "dates": trade_dates_jan, "func": pro.hsgt_top10, "param": "trade_date"},
        {"name": "stk_holdernumber", "dates": all_days_jan, "func": pro.stk_holdernumber, "param": "ann_date"},
    ]
    
    results = []
    total_start_time = time.time()
    
    # 串行触发各接口，但每个接口内部交易日采用多线程并发拉取
    for suite in test_suite:
        # daily 和 stk_factor 因为范围大（90天），线程数设为 6 以增加并行度，其余设为 4
        workers = 6 if suite["name"] in ["daily", "stk_factor"] else 4
        res = fetch_and_save_concurrent(
            pro=pro,
            db_path=db_path,
            interface_name=suite["name"],
            dates=suite["dates"],
            fetch_func=suite["func"],
            date_param_name=suite["param"],
            max_workers=workers
        )
        results.append(res)
        
    # 财务数据进行特殊拉取
    res_fina = fetch_fina_indicator_spec(pro, db_path)
    results.append(res_fina)
    
    total_duration = time.time() - total_start_time
    
    # 4. 打印汇总报告
    print("\n" + "=" * 80)
    print("📊 修正版数据拉取与时延统计汇总报告:")
    print("=" * 80)
    print(f"| {'接口名称':<18} | {'耗时(秒)':<9} | {'请求次数':<8} | {'成功率':<7} | {'数据条数':<10} |")
    print("-" * 80)
    
    total_rows = 0
    total_requests = 0
    for r in results:
        total_rows += r["rows"]
        total_requests += r["requests"]
        print(f"| {r['interface']:<18} | {r['duration']:>8.2f}s | {r['requests']:>8} | {r['success_rate']:>6.1f}% | {r['rows']:>10} |")
        
    print("-" * 80)
    print(f"🌟 总拉取耗时: {total_duration:.2f} 秒 | 总请求次数: {total_requests} 次 | 总写入行数: {total_rows} 行")
    print(f"🚀 优化方案整体平均吞吐率: {total_rows / total_duration:.2f} 条/秒")
    print("=" * 80)

if __name__ == "__main__":
    main()
