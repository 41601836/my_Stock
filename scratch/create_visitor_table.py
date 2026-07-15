import sqlite3

DB_PATH = 'db/stock_data.db'

def init_visitor_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visitor_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            ip TEXT,
            device_id TEXT,
            path TEXT,
            user_agent TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("Table visitor_logs created or verified.")

if __name__ == "__main__":
    init_visitor_table()
