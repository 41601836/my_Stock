# -*- coding: utf-8 -*-
"""
update_daily_data.py —— 增量拉取最新行情、资金流、筹码数据并追加到本地数据库
"""

import os
import sys
import json
import time
import sqlite3
import pandas as pd
import tushare as ts
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "db", "stock_data.db")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

def load_tushare_token():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"❌ 未找到配置文件: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    token = config.get("api", {}).get("tushare_token", "")
    if not token:
        raise ValueError("❌ config.json 中未找到 api.tushare_token")
    return token

def fetch_table_data(pro, conn, table_name, fetch_func, dates, date_param="trade_date"):
    """按日期抓取并追加到数据库"""
    print(f"\n🚀 开始拉取 {table_name}...")
    df_list = []
    for d in dates:
        print(f"   => 正在拉取 {d}")
        max_retries = 5
        for retry in range(max_retries):
            try:
                # 简单限速
                time.sleep(0.3)
                kwargs = {date_param: d}
                # Pro API 默认 timeout (需tushare支持，若不支持可忽略，这里通过 requests timeout在底层处理)
                df = fetch_func(**kwargs)
                if df is not None and not df.empty:
                    df_list.append(df)
                break
            except Exception as e:
                wait_time = 2 ** retry
                print(f"      拉取失败重试 {retry+1}/{max_retries} (等待 {wait_time}s): {e}")
                time.sleep(wait_time)
                if retry == max_retries - 1:
                    print(f"❌ 拉取 {table_name} 数据失败，已达到最大重试次数。")
                    raise e
    
    if df_list:
        df_all = pd.concat(df_list, ignore_index=True)
        date_str_list = ",".join([f"'{d}'" for d in dates])
        try:
            conn.execute(f"DELETE FROM {table_name} WHERE {date_param} IN ({date_str_list})")
            conn.commit()
        except sqlite3.OperationalError as e:
            # 如果是表不存在等正常情况可忽略，若是 locked 则抛出
            if "no such table" not in str(e).lower():
                print(f"❌ 数据库操作失败: {e}")
                raise e
        
        if table_name == "moneyflow":
            # 修复 Tushare API net_mf_amount 为 0 或等于总买入金额的 Bug，手动重构真实的净大单流入
            required_cols = ["buy_lg_amount", "buy_elg_amount", "sell_lg_amount", "sell_elg_amount"]
            if all(col in df_all.columns for col in required_cols):
                df_all["net_mf_amount"] = (
                    df_all["buy_lg_amount"].fillna(0) + df_all["buy_elg_amount"].fillna(0)
                    - df_all["sell_lg_amount"].fillna(0) - df_all["sell_elg_amount"].fillna(0)
                )
        
        if table_name == "stock_cyq_perf":
            # 兼容处理: 若 Tushare 增量数据不含 chips_peak_pct，利用 cost_95pct 和 cost_5pct 本地重构计算，保障界面数据完整
            if "chips_peak_pct" not in df_all.columns or df_all["chips_peak_pct"].isnull().all():
                if "cost_95pct" in df_all.columns and "cost_5pct" in df_all.columns:
                    denom = df_all["cost_95pct"] + df_all["cost_5pct"]
                    denom_protected = denom.apply(lambda x: x if x > 1e-5 else 1e-5)
                    df_all["chips_peak_pct"] = 100.0 * (1.0 - (df_all["cost_95pct"] - df_all["cost_5pct"]) / denom_protected)
                else:
                    df_all["chips_peak_pct"] = 0.0
            cols = ["ts_code", "trade_date", "winner_rate", "chips_peak_pct"]
            df_all = df_all[[c for c in cols if c in df_all.columns]]
            
        if table_name == "daily_basic":
            cols = ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "ps", "total_share", "float_share", "free_share", "total_mv", "circ_mv"]
            df_all = df_all[[c for c in cols if c in df_all.columns]]

        df_all.to_sql(table_name, conn, if_exists="append", index=False)
        print(f"✅ {table_name} 写入成功: {len(df_all)} 行")
    else:
        print(f"⚠️ {table_name} 未拉取到新数据")

def main():
    print("=" * 60)
    print("🌟 开始执行增量数据拉取任务 (Tushare)")
    print("=" * 60)
    
    try:
        token = load_tushare_token()
        try:
            # 尽力写入 tushare 本地 token 缓存 (~/tk.csv)；
            # 沙箱/权限受限环境下可能 Permission denied，但不影响拉取，忽略即可
            ts.set_token(token)
        except Exception as e:
            print(f"⚠️ set_token 本地缓存写入失败(不影响拉取): {e}")
        # 直接将 token 传给 pro_api，避免对 ~/tk.csv 可写性的依赖
        pro = ts.pro_api(token)
    except Exception as e:
        print(f"❌ 载入 Tushare Token 失败: {e}")
        # 以非零码退出：中断后续 && 链，并让前端任务状态显示 ERROR 而非"成功"
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH, timeout=20)
    try:
        # 开启 WAL 模式以支持高并发读取和写入
        conn.execute("PRAGMA journal_mode=WAL;")
        
        end_date = datetime.now().strftime("%Y%m%d")

        def fetch_for_table(table_name, fetch_func):
            try:
                cursor = conn.cursor()
                cursor.execute(f"SELECT MAX(trade_date) FROM {table_name}")
                max_date = cursor.fetchone()[0]
            except Exception as e:
                max_date = None

            if not max_date:
                max_date = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")

            start_dt = datetime.strptime(max_date, "%Y%m%d") + timedelta(days=1)
            start_date = start_dt.strftime("%Y%m%d")
            
            if start_date > end_date:
                print(f"✅ {table_name} 数据已是最新 (截止 {max_date})")
                return

            try:
                cal_df = pro.trade_cal(exchange='', start_date=start_date, end_date=end_date)
                open_cal = cal_df[cal_df['is_open'] == 1]
                target_dates = open_cal['cal_date'].tolist()
                target_dates.sort()
            except Exception as e:
                print(f"⚠️ 获取交易日历失败: {e}，将采用周末排除降级方案")
                d_range = pd.date_range(start=pd.to_datetime(start_date), end=pd.to_datetime(end_date))
                target_dates = [d.strftime("%Y%m%d") for d in d_range if d.weekday() < 5]

            if not target_dates:
                print(f"✅ {table_name} 数据已是最新 (无新交易日)")
                return

            print(f"🎯 {table_name} 需要拉取: {target_dates}")
            fetch_table_data(pro, conn, table_name, fetch_func, target_dates)

        fetch_for_table("daily_prices", pro.daily)
        fetch_for_table("daily_basic", pro.daily_basic)
        fetch_for_table("moneyflow", pro.moneyflow)
        fetch_for_table("stock_cyq_perf", pro.cyq_perf)
        fetch_for_table("stk_factor", pro.stk_factor)
        
    finally:
        conn.close()
        try:
            # 自动联动运行归因结算器，结算历史推荐在样本外的远期超额表现
            import importlib.util
            _spec = importlib.util.spec_from_file_location(
                "tracker_updater",
                os.path.join(PROJECT_ROOT, "scripts", "tracker_updater.py")
            )
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _mod.update_recommendation_performance()
        except Exception as e:
            print(f"⚠️ 推荐跟踪结算异常: {e}")
        
    print("=" * 60)
    print("🎉 增量数据拉取任务完成！")

if __name__ == "__main__":
    main()
