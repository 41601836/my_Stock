# -*- coding: utf-8 -*-
"""
verify_db.py —— 验证 Tushare 拉取的数据是否成功入库及条数统计
"""

import sqlite3

def main():
    db_path = "db/stock_data.db"
    tables = [
        "fetch_test_daily",
        "fetch_test_daily_basic",
        "fetch_test_stk_factor",
        "fetch_test_moneyflow",
        "fetch_test_margin_detail",
        "fetch_test_block_trade",
        "fetch_test_top_inst",
        "fetch_test_hsgt_top10",
        "fetch_test_stk_holdernumber",
        "fetch_test_fina_indicator"
    ]
    
    print("=" * 60)
    print("🔍 验证拉取数据在本地 SQLite 中的入库情况:")
    print("=" * 60)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    for t in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {t};")
            count = cursor.fetchone()[0]
            
            # 查一下前几个字段
            cursor.execute(f"PRAGMA table_info({t});")
            cols = [col[1] for col in cursor.fetchall()]
            cols_str = ", ".join(cols[:5]) + "..." if len(cols) > 5 else ", ".join(cols)
            
            print(f"✅ 表 [{t:<26}] : 写入成功 | 记录数: {count:>7} 行 | 字段样例: {cols_str}")
        except Exception as e:
            print(f"❌ 表 [{t:<26}] : 读取失败，原因: {e}")
            
    conn.close()
    print("=" * 60)

if __name__ == "__main__":
    main()
