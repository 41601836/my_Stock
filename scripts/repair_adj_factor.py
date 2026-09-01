# -*- coding: utf-8 -*-
"""
repair_adj_factor.py —— 修复 daily_prices.adj_factor 块状跳变与 NULL
====================================================================
背景: 20260520-0525 / 20260618-0702 期间 adj_factor 被错误写入为 1.0,
      20260728+ 仍为 NULL, 导致 close_adj 跨块边界 ±99% 跳变,
      Jack 回测 future_return_5d 触达 ±clip, 超额净值伪影 -73%.

策略: 从 Tushare adj_factor 接口按日重拉 20260501~latest,
      幂等替换 (DELETE + INSERT) 异常区间。
      仅替换 adj_factor 异常 (NULL 或 |Δ|>20% 跳变) 的行, 保留正常行不动,
      减小 Tushare 配额消耗。
"""

import os
import json
import time
import sqlite3
import pandas as pd
import tushare as ts
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "db", "stock_data.db")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

JUMP_RATIO_MAX = 0.20  # adj_factor 环比 |Δ| > 20% 视为跳变
START_DATE = "20260501"


class RateLimiter:
    def __init__(self, qps=6):
        self.interval = 1.0 / qps
        self.last_call = time.time()

    def wait(self):
        now = time.time()
        elapsed = now - self.last_call
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self.last_call = time.time()


limiter = RateLimiter(qps=6.5)


def load_tushare_token():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"❌ 未找到配置文件: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    token = config.get("api", {}).get("tushare_token", "")
    if not token:
        raise ValueError("❌ config.json 中未找到 api.tushare_token")
    return token


def detect_anomalies(conn):
    """检测 adj_factor 跳变、NULL、孤立 1.0 与整日缺失, 返回需重拉的 trade_date 集合"""
    print("🔍 [1/4] 扫描 adj_factor 异常行 (NULL + 跳变 + 孤立1.0 + 整日缺失)...")
    # 先检测整日缺失 (对照 trade_cal)
    try:
        cal_df = pd.read_sql(
            "SELECT cal_date FROM trade_cal WHERE is_open=1 "
            "AND cal_date BETWEEN ? AND strftime('%Y%m%d','now')",
            conn, params=(START_DATE,)
        )
        actual_df = pd.read_sql(
            "SELECT DISTINCT trade_date FROM daily_prices WHERE trade_date >= ?",
            conn, params=(START_DATE,)
        )
        missing_dates = set(cal_df["cal_date"].astype(str).tolist()) - set(
            actual_df["trade_date"].astype(str).tolist()
        )
        if missing_dates:
            print(f"   ⚠️ 检测到 {len(missing_dates)} 个整日缺失交易日, 将重拉完整数据")
            print(f"   样例: {sorted(missing_dates)[:10]}")
    except Exception:
        missing_dates = set()

    df = pd.read_sql(
        "SELECT ts_code, trade_date, adj_factor FROM daily_prices "
        "WHERE trade_date >= ? ORDER BY ts_code, CAST(trade_date AS INTEGER)",
        conn, params=(START_DATE,)
    )
    if df.empty:
        return missing_dates

    df["adj_factor"] = pd.to_numeric(df["adj_factor"], errors="coerce")
    null_dates = set(df.loc[df["adj_factor"].isna(), "trade_date"].unique().tolist())

    df_sorted = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    df_sorted["prev_af"] = df_sorted.groupby("ts_code")["adj_factor"].shift(1)
    df_sorted["next_af"] = df_sorted.groupby("ts_code")["adj_factor"].shift(-1)
    df_sorted["jump_prev"] = (
        (df_sorted["adj_factor"] - df_sorted["prev_af"]).abs()
        / df_sorted["prev_af"].replace(0, 1.0)
    )
    df_sorted["jump_next"] = (
        (df_sorted["adj_factor"] - df_sorted["next_af"]).abs()
        / df_sorted["next_af"].replace(0, 1.0)
    )

    jump_mask = (
        ((df_sorted["jump_prev"] > JUMP_RATIO_MAX) & df_sorted["prev_af"].notna())
        | ((df_sorted["jump_next"] > JUMP_RATIO_MAX) & df_sorted["next_af"].notna())
    )
    jump_dates = set(df_sorted.loc[jump_mask, "trade_date"].unique().tolist())

    isolated_1_mask = (df_sorted["adj_factor"] == 1.0) & (
        ((df_sorted["prev_af"] > 1.5) | (df_sorted["prev_af"] < 0.8))
        | ((df_sorted["next_af"] > 1.5) | (df_sorted["next_af"] < 0.8))
    )
    isolated_1_dates = set(df_sorted.loc[isolated_1_mask, "trade_date"].unique().tolist())

    anomaly_dates = sorted(missing_dates | null_dates | jump_dates | isolated_1_dates)
    print(
        f"   整日缺失: {len(missing_dates)} | NULL: {len(null_dates)} | "
        f"跳变: {len(jump_dates)} | 孤立1.0: {len(isolated_1_dates)} | "
        f"合并去重: {len(anomaly_dates)}"
    )
    return set(anomaly_dates)


def fetch_full_day(pro, d):
    """拉取单日完整 daily + adj_factor, 返回合并后的 DataFrame"""
    df_daily = None
    df_adj = None
    for retry in range(5):
        try:
            limiter.wait()
            df_daily = pro.daily(trade_date=d)
            break
        except Exception as e:
            print(f"   ⚠️ {d} daily 拉取失败重试 {retry+1}/5: {e}")
            time.sleep(2 ** retry)
    for retry in range(5):
        try:
            limiter.wait()
            df_adj = pro.adj_factor(trade_date=d)
            break
        except Exception as e:
            print(f"   ⚠️ {d} adj_factor 拉取失败重试 {retry+1}/5: {e}")
            time.sleep(2 ** retry)

    if df_daily is None or df_daily.empty:
        return pd.DataFrame(), pd.DataFrame()

    if df_adj is not None and not df_adj.empty:
        df_merged = pd.merge(
            df_daily, df_adj[["ts_code", "adj_factor"]], on="ts_code", how="left"
        )
    else:
        df_merged = df_daily.copy()
        df_merged["adj_factor"] = None

    df_basic = None
    for retry in range(5):
        try:
            limiter.wait()
            df_basic = pro.daily_basic(trade_date=d)
            break
        except Exception as e:
            print(f"   ⚠️ {d} daily_basic 拉取失败重试 {retry+1}/5: {e}")
            time.sleep(2 ** retry)
    return df_merged, df_basic


def fetch_adj_factor_for_dates(pro, dates):
    """按日拉取 adj_factor, 返回 DataFrame"""
    frames = []
    for idx, d in enumerate(sorted(dates)):
        for retry in range(5):
            try:
                limiter.wait()
                df = pro.adj_factor(trade_date=d)
                if df is not None and not df.empty:
                    frames.append(df)
                break
            except Exception as e:
                wait = 2 ** retry
                print(f"   ⚠️ {d} adj_factor 拉取失败重试 {retry+1}/5 (等待 {wait}s): {e}")
                time.sleep(wait)
                if retry == 4:
                    print(f"   ❌ {d} 放弃")
        if (idx + 1) % 10 == 0:
            print(f"   进度: {idx+1}/{len(dates)}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def apply_fix(conn, df_adj):
    """幂等替换异常区间的 adj_factor (持久临时表 + 索引加速, 单事务 UPDATE)"""
    print(f"🔧 [3/4] 幂等替换异常区间 adj_factor...")
    if df_adj.empty:
        print("   无新数据可写入")
        return 0

    df_adj = df_adj[["ts_code", "trade_date", "adj_factor"]].copy()
    df_adj["adj_factor"] = pd.to_numeric(df_adj["adj_factor"], errors="coerce")
    df_adj = df_adj.dropna(subset=["adj_factor"])
    df_adj["trade_date"] = df_adj["trade_date"].astype(str)
    df_adj = df_adj.drop_duplicates(
        subset=["ts_code", "trade_date"], keep="last"
    )
    print(f"   待写入临时表: {len(df_adj)} 行")

    cursor = conn.cursor()
    try:
        # 持久临时表 (非 TEMP, 避免连接断开即消失, 配合索引加速 UPDATE)
        cursor.execute("DROP TABLE IF EXISTS _tmp_adj_fix;")
        cursor.execute(
            "CREATE TABLE _tmp_adj_fix "
            "(ts_code TEXT, trade_date TEXT, adj_factor REAL);"
        )
        # 用 pandas to_sql 分批写入 (内部 executemany, chunksize 控制内存)
        df_adj.to_sql(
            "_tmp_adj_fix", conn, if_exists="append",
            index=False, chunksize=10000, method="multi"
        )
        cursor.execute(
            "CREATE INDEX idx_tmp_adj_fix ON _tmp_adj_fix(ts_code, trade_date);"
        )

        # 单事务 UPDATE (走索引)
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            UPDATE daily_prices
            SET adj_factor = (
                SELECT adj_factor FROM _tmp_adj_fix
                WHERE _tmp_adj_fix.ts_code = daily_prices.ts_code
                  AND _tmp_adj_fix.trade_date = daily_prices.trade_date
            )
            WHERE EXISTS (
                SELECT 1 FROM _tmp_adj_fix
                WHERE _tmp_adj_fix.ts_code = daily_prices.ts_code
                  AND _tmp_adj_fix.trade_date = daily_prices.trade_date
            );
            """
        )
        updated = cursor.rowcount
        cursor.execute("DROP TABLE IF EXISTS _tmp_adj_fix;")
        cursor.execute("COMMIT")
        affected_dates = sorted(df_adj["trade_date"].unique().tolist())
        print(f"   受影响日期: {len(affected_dates)} | UPDATE 行数: {updated}")
        return updated
    except Exception as e:
        cursor.execute("ROLLBACK")
        cursor.execute("DROP TABLE IF EXISTS _tmp_adj_fix;")
        raise


def verify(conn):
    print("✅ [4/4] 验证修复结果...")
    # 000001.SZ 序列
    df = pd.read_sql(
        "SELECT trade_date, adj_factor FROM daily_prices "
        "WHERE ts_code='000001.SZ' AND trade_date BETWEEN '20260510' AND '20260705' "
        "ORDER BY CAST(trade_date AS INTEGER)",
        conn
    )
    print("   000001.SZ 2026/05-07 adj_factor 序列:")
    print(df.to_string(index=False))
    # 剩余 NULL
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM daily_prices WHERE adj_factor IS NULL AND trade_date >= '20260701'"
    )
    remaining_null = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM daily_prices WHERE adj_factor IS NULL"
    )
    total_null = cur.fetchone()[0]
    print(f"   剩余 NULL (>=20260701): {remaining_null} | 总 NULL: {total_null}")


def restore_full_days(conn, pro, dates):
    """整日缺失: 重拉完整 daily_prices + daily_basic + adj_factor 并幂等写入"""
    print(f"\n📡 完整重拉 {len(dates)} 个缺失交易日...")
    cols_basic = ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb",
                  "ps", "total_share", "float_share", "free_share", "total_mv", "circ_mv"]

    # 进入 autocommit 模式: to_sql 的 method=multi 会自己管理事务,
    # 手动 BEGIN/COMMIT 会与之冲突, 故用 isolation_level=None 让每条语句即时生效
    conn.isolation_level = None
    cursor = conn.cursor()
    for idx, d in enumerate(sorted(dates)):
        df_merged, df_basic = fetch_full_day(pro, d)
        if df_merged.empty:
            print(f"   [{idx+1}/{len(dates)}] {d} 拉取失败, 跳过")
            continue

        try:
            cursor.execute("DELETE FROM daily_prices WHERE trade_date = ?", (d,))
            cursor.execute("DELETE FROM daily_basic WHERE trade_date = ?", (d,))
            df_merged.to_sql(
                "daily_prices", conn, if_exists="append",
                index=False, chunksize=10000, method="multi"
            )
            if df_basic is not None and not df_basic.empty:
                df_basic_clean = df_basic[[c for c in cols_basic if c in df_basic.columns]]
                df_basic_clean.to_sql(
                    "daily_basic", conn, if_exists="append",
                    index=False, chunksize=10000, method="multi"
                )
            print(f"   [{idx+1}/{len(dates)}] {d} 写入 daily_prices {len(df_merged)}行")
        except Exception as e:
            print(f"   ❌ {d} 写入失败: {e}")
    conn.isolation_level = ""


def main():
    print("=" * 60)
    print("🚀 启动 adj_factor 块状跳变与 NULL 修复任务")
    print("=" * 60)
    print(f"   起始日期: {START_DATE}")
    print(f"   跳变阈值: |Δ| > {JUMP_RATIO_MAX*100:.0f}%")

    try:
        token = load_tushare_token()
        ts.set_token(token)
        pro = ts.pro_api()
    except Exception as e:
        print(f"❌ 载入 Tushare Token 失败: {e}")
        return

    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        anomaly_dates = detect_anomalies(conn)
        if not anomaly_dates:
            print("✅ 未检测到 adj_factor 异常, 无需修复")
            verify(conn)
            return

        # 区分整日缺失 vs 仅 adj_factor 异常
        try:
            actual_dates = set(pd.read_sql(
                "SELECT DISTINCT trade_date FROM daily_prices WHERE trade_date >= ?",
                conn, params=(START_DATE,)
            )["trade_date"].astype(str).tolist())
        except Exception:
            actual_dates = set()
        full_restore_dates = anomaly_dates - actual_dates
        adj_only_dates = anomaly_dates & actual_dates

        # 步骤 A: 完整重拉缺失交易日 (含 daily_prices + daily_basic + adj_factor)
        if full_restore_dates:
            restore_full_days(conn, pro, full_restore_dates)

        # 步骤 B: 仅修复 adj_factor 异常 (跳变/孤立1.0/NULL 但行存在)
        if adj_only_dates:
            print(f"\n📡 仅修复 {len(adj_only_dates)} 个日期的 adj_factor...")
            df_adj = fetch_adj_factor_for_dates(pro, adj_only_dates)
            print(f"   拉取到 {len(df_adj)} 行")
            apply_fix(conn, df_adj)

        verify(conn)
    except Exception as e:
        conn.rollback()
        print(f"❌ 修复失败: {e}")
        raise
    finally:
        conn.close()

    print("=" * 60)
    print("🎉 adj_factor 修复任务完成!")


if __name__ == "__main__":
    main()
