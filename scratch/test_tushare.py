import os, sys, json, sqlite3
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import tushare as ts
from scripts.update_daily_data import load_tushare_token
try:
    ts.set_token(load_tushare_token())
    pro = ts.pro_api()
    df = pro.moneyflow(trade_date='20260714')
    print(f"Moneyflow rows for 20260714: {len(df) if df is not None else 0}")
except Exception as e:
    print(f"Error: {e}")
