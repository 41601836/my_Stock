# -*- coding: utf-8 -*-
"""
tracker_updater.py —— 增量归因结算器 (已注入防幸存者偏差与退市惩罚结算)
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "db", "stock_data.db")

def update_recommendation_performance():
    """
    增量计算历史推荐记录的远期收益及 Alpha
    """
    print("\n🚀 [Tracker] 启动归因数据终结结算引擎...")
    if not os.path.exists(DB_PATH):
        print("⚠️ 数据库不存在，退出结算")
        return
        
    conn = sqlite3.connect(DB_PATH)
    try:
        # 1. 找出所有尚未结算完全 (即 alpha_20d 为空) 的记录
        df_pending = pd.read_sql(
            "SELECT recommend_date, ts_code, base_price FROM recommendation_tracker "
            "WHERE alpha_20d IS NULL", conn
        )
        
        if df_pending.empty:
            print("✅ 没有需要结算的推荐记录。")
            return
            
        print(f"📥 共有 {len(df_pending)} 条记录等待增量结算...")
        
        # 2. 获取所有的交易日历以计算基准累计收益
        # 为防止幸存者偏差，我们将计算每日全市场的平均累计收益作为基准 (Benchmark)
        df_all_dates = pd.read_sql("SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date", conn)
        dates_list = df_all_dates["trade_date"].tolist()
        
        # 3. 逐条计算
        for _, row in df_pending.iterrows():
            rec_date = row["recommend_date"]
            ts_code = row["ts_code"]
            base_price = row["base_price"]
            
            # 获取该股票在推荐日之后的所有真实交易价格序列 (按日期正序)
            df_prices = pd.read_sql(
                "SELECT trade_date, open, close FROM daily_prices "
                "WHERE ts_code = ? AND trade_date > ? ORDER BY trade_date",
                conn, params=(ts_code, rec_date)
            )
            
            if df_prices.empty:
                # 区分“尚未交易”与“真正退市”：
                # 只有当最新日线数据的日期已推进到推荐日之后，但个股仍无后续日线，才判定为退市
                if dates_list and rec_date >= dates_list[-1]:
                    # 属于今日最新推荐，未来交易日还没发生，跳过结算，不予标记退市
                    continue
                
                # 确认退市，强制以 -100% 收益惩罚结算，消灭退市造成的幸存者偏差
                print(f"🚨 [退市拦截] 股票 {ts_code} 在推荐日 {rec_date} 后无任何价格序列，触发归零惩罚")
                conn.execute(
                    "UPDATE recommendation_tracker SET "
                    "base_price=0.0, ret_1d=-1.0, ret_3d=-1.0, ret_5d=-1.0, ret_10d=-1.0, ret_20d=-1.0, "
                    "alpha_1d=-1.0, alpha_3d=-1.0, alpha_5d=-1.0, alpha_10d=-1.0, alpha_20d=-1.0 "
                    "WHERE recommend_date = ? AND ts_code = ?",
                    (rec_date, ts_code)
                )
                continue
                
            # 4. 填充基准买入价 (base_price，即 T+1 日开盘价)
            if base_price is None or pd.isna(base_price) or base_price <= 0:
                base_price = float(df_prices.iloc[0]["open"])
                # 避免开盘价为 0 或 NaN
                if pd.isna(base_price) or base_price <= 0:
                    base_price = float(df_prices.iloc[0]["close"])
                conn.execute(
                    "UPDATE recommendation_tracker SET base_price = ? "
                    "WHERE recommend_date = ? AND ts_code = ?",
                    (base_price, rec_date, ts_code)
                )
            
            # 5. 分别提取 T+1, T+3, T+5, T+10, T+20 交易日的价格
            windows = [1, 3, 5, 10, 20]
            updates = {}
            
            for w in windows:
                # 如果当前可用的历史交易日不足以结算当前窗口 (例如推荐只有 3 天，无法结算 T+5)
                # 则暂不结算此窗口，跳过
                if len(df_prices) < w:
                    continue
                    
                target_row = df_prices.iloc[w - 1]
                target_date = target_row["trade_date"]
                target_close = float(target_row["close"])
                
                # 绝对收益率
                ret_val = (target_close - base_price) / (base_price + 1e-8)
                updates[f"ret_{w}d"] = ret_val
                
                # 计算这期间的等权大盘基准收益率 (Benchmark Return)
                # 以防大盘暴跌时错怪策略。基准为期间全市场所有股票日度平均涨幅的累计和
                try:
                    # 找到推荐日次日到结算日之间的交易日序列
                    rec_idx = dates_list.index(rec_date)
                    t_idx = dates_list.index(target_date)
                    sub_dates = dates_list[rec_idx + 1 : t_idx + 1]
                    
                    if sub_dates:
                        ph = ",".join(["?" for _ in sub_dates])
                        df_bench = pd.read_sql(
                            f"SELECT trade_date, AVG(pct_chg) as avg_chg FROM daily_prices "
                            f"WHERE trade_date IN ({ph}) GROUP BY trade_date",
                            conn, params=sub_dates
                        )
                        # 将平均涨跌幅（百分数，如 1.5%）转化为小数并累计相乘计算基准复利收益
                        bench_ret = 1.0
                        for chg in df_bench["avg_chg"].fillna(0.0).tolist():
                            bench_ret *= (1.0 + chg / 100.0)
                        bench_ret -= 1.0
                    else:
                        bench_ret = 0.0
                except Exception:
                    bench_ret = 0.0
                    
                # 计算超额 Alpha
                alpha_val = ret_val - bench_ret
                updates[f"alpha_{w}d"] = alpha_val
                
            # 6. 将已算出的字段更新回数据库
            if updates:
                set_clauses = []
                params = []
                for col, val in updates.items():
                    set_clauses.append(f"{col} = ?")
                    params.append(val)
                params.extend([rec_date, ts_code])
                
                sql_update = f"UPDATE recommendation_tracker SET {', '.join(set_clauses)} WHERE recommend_date = ? AND ts_code = ?"
                conn.execute(sql_update, params)
                
        conn.commit()
        print("🎉 [Tracker] 所有历史推荐记录的归因数据均已增量结算并入库！")
        
    except Exception as e:
        print(f"❌ [Tracker] 结算异常: {e}")
        import traceback; traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    update_recommendation_performance()
