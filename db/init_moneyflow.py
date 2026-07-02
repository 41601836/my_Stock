import sqlite3
import os

from config.paths import PATHS

DB_PATH = PATHS.database.stock_daily

def init_moneyflow_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 东方财富个股资金流向表
    # 字段含义：
    # ts_code: 股票代码
    # trade_date: 交易日期
    # buy_sm_vol, buy_sm_amount, sell_sm_vol, sell_sm_amount: 小单买卖量额
    # buy_md_vol, buy_md_amount, sell_md_vol, sell_md_amount: 中单买卖量额
    # buy_lg_vol, buy_lg_amount, sell_lg_vol, sell_lg_amount: 大单买卖量额
    # buy_elg_vol, buy_elg_amount, sell_elg_vol, sell_elg_amount: 特大单买卖量额
    # net_mf_vol: 主力净流入量 (大单+特大单净买入量)
    # net_mf_amount: 主力净流入额 (大单+特大单净买入额)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_moneyflow_dc (
        ts_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        buy_elg_amount REAL,
        buy_elg_amount_rate REAL,
        buy_lg_amount REAL,
        buy_lg_amount_rate REAL,
        buy_md_amount REAL,
        buy_md_amount_rate REAL,
        buy_sm_amount REAL,
        buy_sm_amount_rate REAL,
        net_amount REAL,
        net_amount_rate REAL,
        PRIMARY KEY (ts_code, trade_date)
    )
    """)
    
    # Create indexes to speed up backtest querying
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_moneyflow_dc_date ON stock_moneyflow_dc (trade_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_moneyflow_dc_code ON stock_moneyflow_dc (ts_code)")
    
    conn.commit()
    conn.close()
    print("stock_moneyflow_dc table created successfully.")

if __name__ == "__main__":
    init_moneyflow_table()
