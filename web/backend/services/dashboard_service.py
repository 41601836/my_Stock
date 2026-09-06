# -*- coding: utf-8 -*-
"""
dashboard_service.py — 指挥中心服务层
========================================
每日选股 → 次日验证 → 性能归因 → 参数调整 闭环系统

核心表:
  - selection_log:   每日选股记录（谁被选中、为什么、维度分数）
  - performance_log:  次日表现（涨跌幅、超额收益、命中判定）

零侵入：独立表，独立 API，不修改任何现有表结构。
"""

import os, sys, json, sqlite3, logging
import datetime
from typing import Dict, Any, List, Optional

import pandas as pd
import numpy as np

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_DB_PATH = os.path.join(_PROJECT_ROOT, "db", "stock_data.db")

_logger = logging.getLogger("services.dashboard_service")

# ═══════════════════════════════════════════
#  DDL
# ═══════════════════════════════════════════

_DDL_SELECTION_LOG = """
CREATE TABLE IF NOT EXISTS selection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,              -- 选股日期
    ts_code TEXT NOT NULL,                -- 股票代码
    name TEXT,                            -- 股票名称
    rank INTEGER,                         -- 当日排名
    resonance_score REAL,                 -- 共振总分
    resonance_level TEXT,                 -- 等级
    chip_score REAL,                      -- 筹码维度分
    capital_score REAL,                   -- 资金维度分
    sector_score REAL,                    -- 板块维度分
    sentiment_score REAL,                 -- 情绪维度分
    position_low REAL,                    -- 建议仓位下限
    position_high REAL,                   -- 建议仓位上限
    pool TEXT DEFAULT 'all',              -- 股票池
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(trade_date, ts_code)
);
CREATE INDEX IF NOT EXISTS idx_sel_date ON selection_log(trade_date);
CREATE INDEX IF NOT EXISTS idx_sel_code ON selection_log(ts_code);
"""

_DDL_PERFORMANCE_LOG = """
CREATE TABLE IF NOT EXISTS performance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    selection_date TEXT NOT NULL,         -- 选股日期
    ts_code TEXT NOT NULL,                -- 股票代码
    name TEXT,                            -- 股票名称
    rank INTEGER,                         -- 当日排名
    resonance_score REAL,                 -- 选股时共振分
    resonance_level TEXT,                 -- 选股时等级
    next_trade_date TEXT,                 -- 次一交易日
    pct_chg REAL,                         -- 次日涨跌幅%
    benchmark_chg REAL,                   -- 基准涨跌幅%
    excess_return REAL,                   -- 超额收益%
    is_hit BOOLEAN DEFAULT 0,             -- 是否跑赢基准
    holding_period INTEGER DEFAULT 1,     -- 持有天数
    cumulative_return REAL,              -- 累计收益%
    cumulative_excess REAL,              -- 累计超额%
    verified_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(selection_date, ts_code)
);
CREATE INDEX IF NOT EXISTS idx_perf_date ON performance_log(selection_date);
CREATE INDEX IF NOT EXISTS idx_perf_code ON performance_log(ts_code);
"""

def ensure_tables():
    """创建闭环表（幂等）"""
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.executescript(_DDL_SELECTION_LOG)
        conn.executescript(_DDL_PERFORMANCE_LOG)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════
#  1. 记录选股结果
# ═══════════════════════════════════════════

def record_selections(stocks: List[Dict], date: str, pool: str = "all"):
    """将共振扫描结果写入 selection_log

    Parameters
    ----------
    stocks : list of dict, 来自 /api/resonance/scan 的 stocks 数组
    date : str, 选股日期 YYYYMMDD
    pool : str, 股票池名称
    """
    ensure_tables()
    conn = sqlite3.connect(_DB_PATH)
    try:
        for s in stocks:
            ds = s.get("dimension_scores", {})
            conn.execute("""
                INSERT OR REPLACE INTO selection_log
                (trade_date, ts_code, name, rank, resonance_score, resonance_level,
                 chip_score, capital_score, sector_score, sentiment_score,
                 position_low, position_high, pool)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                date, s.get("ts_code", ""), s.get("name", ""),
                s.get("rank", 0), s.get("resonance_score", 0),
                s.get("resonance_level", ""),
                ds.get("chip"), ds.get("capital"), ds.get("sector"), ds.get("sentiment"),
                s.get("position_low", 0), s.get("position_high", 0),
                pool,
            ])
        conn.commit()
        _logger.info(f"记录 {len(stocks)} 只选股到 selection_log (date={date})")
    finally:
        conn.close()


# ═══════════════════════════════════════════
#  2. 次日验证
# ═══════════════════════════════════════════

def verify_previous_selections():
    """验证所有未验证的选股记录

    找到 selection_log 中没有对应 performance_log 的记录，
    查找其次一交易日的涨跌幅，计算超额收益。
    """
    ensure_tables()
    conn = sqlite3.connect(_DB_PATH)
    try:
        # 找未验证的选股记录
        pending = pd.read_sql("""
            SELECT sl.* FROM selection_log sl
            LEFT JOIN performance_log pl ON sl.trade_date = pl.selection_date AND sl.ts_code = pl.ts_code
            WHERE pl.id IS NULL
            ORDER BY sl.trade_date
        """, conn)

        if pending.empty:
            return {"verified": 0, "message": "无待验证记录"}

        # 获取交易日历
        all_dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM daily_prices ORDER BY trade_date"
        ).fetchall()]

        verified = 0
        for _, row in pending.iterrows():
            sel_date = row["trade_date"]
            ts_code = row["ts_code"]

            # 找次一交易日
            if sel_date not in all_dates:
                # 选股日期不在交易日历中，找下一个交易日
                next_dates = [d for d in all_dates if d > sel_date]
                if not next_dates:
                    continue
                next_date = next_dates[0]
            else:
                idx = all_dates.index(sel_date)
                if idx + 1 >= len(all_dates):
                    continue  # 没有次日数据
                next_date = all_dates[idx + 1]

            # 查次日涨跌幅
            price_data = pd.read_sql("""
                SELECT pct_chg FROM daily_prices
                WHERE ts_code = ? AND trade_date = ?
            """, conn, params=[ts_code, next_date])

            if price_data.empty:
                continue

            pct_chg = float(price_data.iloc[0]["pct_chg"])

            # 基准涨跌幅（用沪深300近似：取当日所有股票均值）
            benchmark_data = pd.read_sql("""
                SELECT AVG(pct_chg) as avg_chg FROM daily_prices
                WHERE trade_date = ?
            """, conn, params=[next_date])
            benchmark_chg = float(benchmark_data.iloc[0]["avg_chg"]) if not benchmark_data.empty else 0.0

            excess = pct_chg - benchmark_chg
            is_hit = 1 if excess > 0 else 0

            conn.execute("""
                INSERT OR REPLACE INTO performance_log
                (selection_date, ts_code, name, rank, resonance_score, resonance_level,
                 next_trade_date, pct_chg, benchmark_chg, excess_return, is_hit, holding_period)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, [
                sel_date, ts_code, row.get("name", ""), row.get("rank", 0),
                row.get("resonance_score", 0), row.get("resonance_level", ""),
                next_date, pct_chg, benchmark_chg, excess, is_hit,
            ])
            verified += 1

        conn.commit()
        return {
            "verified": verified,
            "message": f"验证了 {verified} 条选股记录",
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════
#  3. 指挥中心仪表盘数据
# ═══════════════════════════════════════════

def get_dashboard() -> Dict[str, Any]:
    """指挥中心总览数据"""
    ensure_tables()
    conn = sqlite3.connect(_DB_PATH)
    try:
        # ── 今日选股 ──
        latest_date = None
        today_sel = pd.read_sql("""
            SELECT * FROM selection_log
            ORDER BY trade_date DESC, rank ASC
            LIMIT 20
        """, conn)
        if not today_sel.empty:
            latest_date = today_sel.iloc[0]["trade_date"]

        # ── 昨日表现 ──
        perf = pd.read_sql("""
            SELECT * FROM performance_log
            ORDER BY selection_date DESC, rank ASC
            LIMIT 20
        """, conn)

        # ── 命中率统计 ──
        stats = {}
        if not perf.empty:
            stats["total_verified"] = len(perf)
            stats["total_hits"] = int(perf["is_hit"].sum())
            stats["hit_rate"] = float(perf["is_hit"].mean())
            stats["avg_excess"] = float(perf["excess_return"].mean())
            stats["avg_pct_chg"] = float(perf["pct_chg"].mean())
            stats["avg_benchmark"] = float(perf["benchmark_chg"].mean())

        # ── 近 N 天命中率趋势 ──
        trend = pd.read_sql("""
            SELECT selection_date,
                   COUNT(*) as total,
                   SUM(is_hit) as hits,
                   AVG(excess_return) as avg_excess,
                   AVG(pct_chg) as avg_return
            FROM performance_log
            GROUP BY selection_date
            ORDER BY selection_date DESC
            LIMIT 30
        """, conn)
        trend_list = trend.to_dict("records") if not trend.empty else []

        # ── 维度贡献分析（哪个维度选得准）──
        dim_analysis = {}
        if not perf.empty:
            # JOIN selection_log 拿维度分
            dim_df = pd.read_sql("""
                SELECT pl.is_hit, pl.excess_return,
                       sl.chip_score, sl.capital_score, sl.sector_score, sl.sentiment_score
                FROM performance_log pl
                JOIN selection_log sl ON pl.selection_date = sl.trade_date AND pl.ts_code = sl.ts_code
            """, conn)
            if not dim_df.empty:
                for dim in ["chip", "capital", "sector", "sentiment"]:
                    col = f"{dim}_score"
                    if col in dim_df.columns:
                        hit_mask = dim_df["is_hit"] == 1
                        hit_avg = dim_df.loc[hit_mask, col].mean()
                        miss_avg = dim_df.loc[~hit_mask, col].mean()
                        dim_analysis[dim] = {
                            "hit_avg_score": float(hit_avg) if pd.notna(hit_avg) else 0,
                            "miss_avg_score": float(miss_avg) if pd.notna(miss_avg) else 0,
                            "edge": float(hit_avg - miss_avg) if pd.notna(hit_avg) and pd.notna(miss_avg) else 0,
                        }

        # ── Agent 状态 ──
        heartbeat_path = os.path.join(_PROJECT_ROOT, "agent", "cruise_heartbeat")
        agent_running = os.path.exists(heartbeat_path)
        agent_status = "RUNNING" if agent_running else "IDLE"

        return {
            "success": True,
            "data": {
                "latest_selection_date": latest_date,
                "today_selections": today_sel.to_dict("records"),
                "latest_performance": perf.to_dict("records"),
                "stats": stats,
                "trend": trend_list,
                "dimension_analysis": dim_analysis,
                "agent_status": agent_status,
            },
        }
    except Exception as e:
        _logger.error(f"get_dashboard error: {e}", exc_info=True)
        return {"success": False, "error": str(e), "data": {}}
    finally:
        conn.close()


# ═══════════════════════════════════════════
#  4. 每日闭环执行
# ═══════════════════════════════════════════

def run_daily_loop(top_n: int = 20, pool: str = "all"):
    """每日闭环：选股 → 记录 → 验证昨日

    调用顺序：
    1. verify_previous_selections()  — 验证昨日选股
    2. resonance scan                — 今日选股
    3. record_selections()           — 记录今日选股
    """
    # 1. 验证昨日
    verify_result = verify_previous_selections()

    # 2. 今日选股
    from web.backend.services.resonance_service import get_resonance_scan
    scan_result = get_resonance_scan(top_n=top_n, pool=pool)

    # 3. 记录
    if scan_result.get("success") and scan_result.get("stocks"):
        date = scan_result.get("meta", {}).get("scan_date", "")
        record_selections(scan_result["stocks"], date, pool)

    return {
        "verify": verify_result,
        "scan": {
            "success": scan_result.get("success", False),
            "date": scan_result.get("meta", {}).get("scan_date", ""),
            "count": len(scan_result.get("stocks", [])),
        },
    }
