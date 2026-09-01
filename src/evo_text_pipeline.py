# -*- coding: utf-8 -*-
"""
evo_text_pipeline.py —— EVO 阶段 6：文本情绪因子管线
=================================================================
M6.1（本文件当前范围）：P0 双源采集 + evo_text_raw 落库
M6.2~M6.4（后续追加）：match_stocks() / score_texts() / aggregate() / persist()

数据源（P0，稳先于猛；遵守 robots 与站点条款，限速 ≥2s/请求）：
  1. cninfo_announcement：巨潮资讯最新公告（公开接口，自带 secCode → 直接得 ts_code）
  2. sina7x24：新浪财经 7x24 快讯（公开 JSON，全市场叙事，无个股归属 → M6.2 模糊匹配）

设计纪律：
  - 源适配层隔离：单源失败只记 warning 降级，绝不阻塞其他源/管线
  - 去重：UNIQUE(source, url) + INSERT OR IGNORE，幂等可重跑
  - 增量：伪 URL（sina7x24://<id>）+ 公告真实 URL

用法：
  /Users/lyu/miniconda3/bin/python3 src/evo_text_pipeline.py --fetch
"""

import os
import sys
import json
import time
import math
import re
import sqlite3
import logging
import datetime
from typing import Dict, Any, List, Optional, Tuple

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.paths import PATHS, startup_check
startup_check()

DB_PATH = PATHS.database.stock_data

sys.path.insert(0, os.path.join(PROJECT_ROOT, "web", "backend"))
from services.evo import ensure_evo_tables, EvoConfig  # noqa: E402

logger = logging.getLogger("evo_text")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


# ═══════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════
def _code_to_ts_code(code: str) -> Optional[str]:
    """6 位 A 股代码 → ts_code（后缀推断；失败返回 None）"""
    c = (code or "").strip()
    if not (len(c) == 6 and c.isdigit()):
        return None
    if c.startswith("920") or c[0] in "48":
        return f"{c}.BJ"
    if c[0] == "6":
        return f"{c}.SH"
    if c[0] in "03":
        return f"{c}.SZ"
    return None


def _clip(s: Optional[str], n: int) -> Optional[str]:
    if s is None:
        return None
    s = s.strip().replace("\n", " ")
    return s[:n] if len(s) > n else s


# ═══════════════════════════════════════════════════════════
# 源适配器 1：巨潮公告（自带 secCode → 直接映射 ts_code）
# ═══════════════════════════════════════════════════════════
def _fetch_cninfo(pages: int, interval: float, timeout: int,
                  max_title_len: int, days: int = 2) -> List[Tuple]:
    """
    巨潮公告（按日切片突破单查询 40 页上限；接口返回全市场，column 参数无效）。
    查询数 = days × pages，每查询上限 30×pages 条。
    """
    out: List[Tuple] = []
    seen_urls = set()
    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    d1 = datetime.date.today()
    headers = {"User-Agent": UA, "X-Requested-With": "XMLHttpRequest",
               "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"}
    for i in range(days):                          # 近→远按日切片
        day = d1 - datetime.timedelta(days=i)
        se_date = f"{day}~{day}"
        for page in range(1, pages + 1):
            try:
                resp = requests.post(url, timeout=timeout, headers=headers, data={
                    "pageNum": page, "pageSize": 30, "column": "szse",
                    "tabName": "fulltext", "plate": "", "stock": "", "searchkey": "",
                    "secid": "", "category": "", "trade": "", "seDate": se_date,
                    "sortName": "", "sortType": "", "isHLtitle": "true",
                })
                anns = (resp.json() or {}).get("announcements") or []
            except Exception as e:
                logger.warning(f"[cninfo] {se_date} 第 {page} 页失败（源隔离，继续）: {e}")
                break
            if not anns:
                break
            for a in anns:
                title = _clip(a.get("announcementTitle", "").replace(
                    "<em>", "").replace("</em>", ""), max_title_len)
                if not title:
                    continue
                adjunct = a.get("adjunctUrl") or ""
                full_url = f"https://static.cninfo.com.cn/{adjunct}" if adjunct else \
                    f"cninfo://{a.get('announcementId') or title}"
                if full_url in seen_urls:      # 切片边界重复去重
                    continue
                seen_urls.add(full_url)
                ts_code = _code_to_ts_code(a.get("secCode") or "")
                ts_ms = a.get("announcementTime")
                published = (datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
                             if isinstance(ts_ms, (int, float)) and ts_ms > 0 else None)
                out.append(("cninfo_announcement", full_url, title, None,
                            json.dumps([ts_code], ensure_ascii=False) if ts_code else None,
                            published))
            time.sleep(interval)
    logger.info(f"[cninfo] 采集 {len(out)} 条公告（{days} 日切片 × {pages} 页）")
    return out


# ═══════════════════════════════════════════════════════════
# 源适配器 2：新浪财经 7x24 快讯（全市场叙事，伪 URL 去重）
# ═══════════════════════════════════════════════════════════
def _fetch_sina7x24(pages: int, interval: float, timeout: int,
                    max_title_len: int) -> List[Tuple]:
    out: List[Tuple] = []
    url = "https://zhibo.sina.com.cn/api/zhibo/feed"
    headers = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn/7x24/"}
    for page in range(1, pages + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers=headers, params={
                "page": page, "page_size": 100, "zhibo_id": 152, "tag_id": 0,
                "dire": "f", "dpc": 1,
            })
            feed = (((resp.json() or {}).get("result") or {}).get("data") or {}).get("feed") or {}
            items = feed.get("list") or []
        except Exception as e:
            logger.warning(f"[sina7x24] 第 {page} 页失败（源隔离，继续）: {e}")
            break
        if not items:
            break
        for it in items:
            text = _clip(it.get("rich_text") or "", max_title_len)
            if not text:
                continue
            out.append(("sina7x24", f"sina7x24://{it.get('id')}",
                        text[:120], text, None,
                        it.get("create_time")))
        time.sleep(interval)
    logger.info(f"[sina7x24] 采集 {len(out)} 条快讯（{pages} 页）")
    return out


# ═══════════════════════════════════════════════════════════
# 主入口：采集 → 去重落库（源隔离：单源挂不阻塞）
# ═══════════════════════════════════════════════════════════
def fetch_news(pages_override: Optional[Dict[str, int]] = None,
               cninfo_days: int = 2) -> Dict[str, Any]:
    if not EvoConfig.get("text_factors.enabled", False):
        logger.info("[Text] text_factors.enabled=false（安全闸 2），跳过采集")
        return {"enabled": False, "inserted": 0}

    cfg = EvoConfig.get("text_factors.fetch", {}) or {}
    ov = pages_override or {}
    pages_cn = int(ov.get("cninfo_pages", cfg.get("cninfo_pages", 10)))
    pages_sina = int(ov.get("sina7x24_pages", cfg.get("sina7x24_pages", 5)))
    interval = float(cfg.get("request_interval_sec", 2.0))
    timeout = int(cfg.get("timeout_sec", 15))
    max_len = int(cfg.get("max_title_len", 500))

    ensure_evo_tables(DB_PATH)
    t0 = time.time()
    rows: List[Tuple] = []
    src_stat: Dict[str, int] = {}

    for fetcher in (_fetch_cninfo, _fetch_sina7x24):   # 源隔离：各自 try/except
        src_name = fetcher.__name__.replace("_fetch_", "")
        try:
            if src_name == "cninfo":
                got = fetcher(pages_cn, interval, timeout, max_len, days=cninfo_days)
            else:
                got = fetcher(pages_sina, interval, timeout, max_len)
            rows.extend(got)
            src_stat[src_name] = len(got)
        except Exception as e:
            logger.warning(f"[Text] 源 {src_name} 整体失败（降级不影响其他源）: {e}")
            src_stat[src_name] = 0

    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        before = conn.execute("SELECT COUNT(*) FROM evo_text_raw").fetchone()[0]
        inserted = 0
        for i in range(0, len(rows), 2000):     # 分批 INSERT OR IGNORE（UNIQUE 去重）
            batch = rows[i:i + 2000]
            cur = conn.executemany(
                "INSERT OR IGNORE INTO evo_text_raw "
                "(source, url, title, content, stock_codes, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?)", batch)
            inserted += cur.rowcount if cur.rowcount > 0 else 0
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM evo_text_raw").fetchone()[0]
    finally:
        conn.close()

    total_seen = max(1, len(rows))
    out = {
        "enabled": True,
        "fetched": len(rows), "inserted": inserted,
        "dup_rate": round(1 - inserted / total_seen, 4),
        "by_source": src_stat,
        "table_total": after, "table_before": before,
        "duration_sec": round(time.time() - t0, 1),
    }
    logger.info(f"[Text] 采集完成: {out}")
    return out


# ═══════════════════════════════════════════════════════════
# M6.2：rules 词典打分 + 个股匹配聚合（确定性、可解释、无 LLM 依赖）
# ═══════════════════════════════════════════════════════════
# 词典（代码内置 A 股语境扩充版 ⊕ evo.yaml text_factors.keyword_libraries 合并）
_DEFAULT_BULL = [
    "超预期", "业绩大增", "扭亏", "高增长", "订单饱满", "扩产", "技术突破", "签署协议", "回购", "增持",
    "预增", "中标", "净利增长", "营收增长", "分红", "派息", "获批", "涨价", "提价", "战略合作",
    "并购", "重组", "涨停", "创新高", "盈利", "利好", "突破", "签约", "产能爬坡", "满产满销",
    "需求旺盛", "政府补助", "税收优惠", "摘帽", "解除质押", "入选", "出海", "国产替代", "放量上涨", "净流入",
]
_DEFAULT_BEAR = [
    "下修业绩", "预亏", "立案", "监管", "减持", "商誉减值", "亏损", "退市风险", "质押",
    "预减", "下滑", "下降", "终止", "失败", "解除协议", "诉讼", "仲裁", "冻结", "处罚",
    "违规", "警示", "问询", "关注函", "跌停", "下跌", "利空", "违约", "逾期", "退市",
    "破产", "清算", "停牌核查", "清仓", "解禁", "资金占用", "违规担保", "被执行人", "净流出",
]
_DEFAULT_CATAL = ["政策", "补贴", "规划", "试点", "涨价", "AI", "算力", "出海", "国产替代",
                  "重组", "新能源", "芯片", "机器人", "低空经济", "固态电池"]
_DEGREE = {"大幅": 2.0, "显著": 2.0, "暴涨": 2.0, "暴跌": 2.0, "巨额": 2.5, "重磅": 2.5,
           "重大": 2.0, "严重": 2.0, "快速": 1.5, "剧烈": 2.0, "小幅": 0.5, "略微": 0.5, "微": 0.5}
_NEGATION = ("不", "未", "无", "非", "难", "缺", "没有", "未能")
_BRACKET_RE = re.compile(r"【([^【】：:]{2,14})[:：]")


def _kw_libs() -> Tuple[List[str], List[str], List[str]]:
    """内置词典 ⊕ evo.yaml keyword_libraries，长词优先"""
    lib = EvoConfig.get("text_factors.keyword_libraries", {}) or {}
    bull = sorted(set(_DEFAULT_BULL) | set(lib.get("bullish", [])), key=len, reverse=True)
    bear = sorted(set(_DEFAULT_BEAR) | set(lib.get("bearish", [])), key=len, reverse=True)
    catal = sorted(set(_DEFAULT_CATAL) | set(lib.get("catalyst", [])), key=len, reverse=True)
    return bull, bear, catal


def _hits(text: str, words: List[str]) -> List[Tuple[str, bool, float]]:
    """词命中扫描：返回 [(word, negated, degree)]；否定检测=词前 3 字符，程度副词=词前 4 字符"""
    out = []
    for w in words:
        start = 0
        while True:
            i = text.find(w, start)
            if i < 0:
                break
            start = i + len(w)
            prefix = text[max(0, i - 3):i]
            negated = any(n in prefix for n in _NEGATION)
            deg = 1.0
            for d, mul in _DEGREE.items():
                if d in text[max(0, i - 4):i]:
                    deg = mul
                    break
            out.append((w, negated, deg))
    return out


def _score_text(text: str, libs) -> Tuple[float, float, Dict[str, int]]:
    """→ (score ∈ [-1,1], confidence ∈ [0,1], 词频明细)；否定词翻转方向"""
    bull, bear, catal = libs
    ph, nh, ch = _hits(text, bull), _hits(text, bear), _hits(text, catal)
    pos = sum(d for _, neg, d in ph if not neg) + sum(d for _, neg, d in nh if neg)
    neg = sum(d for _, neg, d in nh if not neg) + sum(d for _, neg, d in ph if neg)
    score = math.tanh((pos - neg) / 2.0)
    hits = len(ph) + len(nh) + len(ch)
    conf = min(1.0, math.log(1 + hits) / math.log(9))   # 8 词命中 → 置信 1.0
    freq: Dict[str, int] = {}
    for w, _, _ in ph + nh + ch:
        freq[w] = freq.get(w, 0) + 1
    return score, conf, freq


def _load_name_index(conn: sqlite3.Connection) -> Dict[str, List[Tuple[str, str]]]:
    """stock_list（EVO 只读）→ 首字索引 {首字: [(简称, ts_code)]}，长简称优先"""
    idx: Dict[str, List[Tuple[str, str]]] = {}
    try:
        for ts, name in conn.execute("SELECT ts_code, name FROM stock_list"):
            name = (name or "").strip()
            if len(name) >= 2:
                idx.setdefault(name[0], []).append((name, ts))
        for v in idx.values():
            v.sort(key=lambda x: -len(x[0]))
    except Exception as e:
        logger.warning(f"[Text] stock_list 读取失败（快讯匹配降级，公告不受影响）: {e}")
    return idx


def match_stocks(text: str, idx: Dict[str, List[Tuple[str, str]]], limit: int = 3) -> List[str]:
    """① 【公司：…】精确提取 → ② 首字索引全文扫描（长优先），每文本归属 ≤limit 只"""
    found, seen = [], set()
    for cand in _BRACKET_RE.findall(text):
        for name, ts in idx.get(cand[0], ()):
            if name == cand and ts not in seen:
                found.append(ts)
                seen.add(ts)
    if len(found) >= limit:
        return found[:limit]
    for c in text:
        for name, ts in idx.get(c, ()):
            if ts not in seen and name in text:
                found.append(ts)
                seen.add(ts)
                if len(found) >= limit:
                    return found
    return found


def score_and_aggregate() -> Dict[str, Any]:
    """
    近窗口文本 → 匹配个股 → rules 打分 → 日/源级明细 REPLACE evo_text_sentiment_scores
    → 个股时间衰减聚合（0.6^天数加权 × 置信收缩）→ [0,1] 截面 rank 回填 factor_values_evo
    """
    if not EvoConfig.get("text_factors.enabled", False):
        logger.info("[Text] text_factors.enabled=false（安全闸 2），跳过打分")
        return {"enabled": False}

    cfg = EvoConfig.get("text_factors", {}) or {}
    window_days = int(cfg.get("aggregate_window_days", 4))
    ensure_evo_tables(DB_PATH)
    t0 = time.time()
    libs = _kw_libs()

    conn = sqlite3.connect(DB_PATH, timeout=120.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        window_start = (datetime.date.today() - datetime.timedelta(days=window_days)) \
            .strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT source, title, content, stock_codes, published_at "
            "FROM evo_text_raw WHERE published_at >= ?", (window_start,)).fetchall()
        idx = _load_name_index(conn)

        # ① 逐文本：匹配 + 打分 → (ts_code, date, source) 单元聚合
        agg: Dict[Tuple[str, str, str], List] = {}
        n_text = n_matched = 0
        matched_codes = set()
        for source, title, content, stock_codes, published in rows:
            text = ((title or "") + " " + (content or "")[:400]).strip()
            if len(text) < 6:
                continue
            n_text += 1
            try:
                codes = json.loads(stock_codes) if stock_codes else None
            except Exception:
                codes = None
            if not codes:
                codes = match_stocks(text, idx)
            codes = [c for c in (codes or []) if c]
            if not codes:
                continue
            n_matched += 1
            score, conf, freq = _score_text(text, libs)
            day = (published or "")[:10]
            if not day:
                continue
            for ts in codes:
                matched_codes.add(ts)
                cell = agg.setdefault((ts, day, source), [0.0, 0, {}])
                cell[0] += score * (conf if conf > 0.05 else 0.05)   # 无词命中文本低权
                cell[1] += 1
                for w, k in freq.items():
                    cell[2][w] = cell[2].get(w, 0) + k

        # ② 日/源级明细 → evo_text_sentiment_scores
        detail = [(ts, day, src, round(ssum / max(1, n), 4), n,
                   json.dumps(dict(sorted(f.items(), key=lambda x: -x[1])[:12]),
                              ensure_ascii=False))
                  for (ts, day, src), (ssum, n, f) in agg.items()]
        conn.execute("DELETE FROM evo_text_sentiment_scores")
        conn.executemany(
            "INSERT OR REPLACE INTO evo_text_sentiment_scores "
            "(ts_code, trade_date, source, sentiment_score, keyword_hits_json) "
            "VALUES (?, ?, ?, ?, ?)",
            [(a, b, c, d, f) for a, b, c, d, _, f in detail])

        # ③ 个股时间衰减聚合（0.6^天数）→ 置信收缩 → [0,1] → 当日截面 rank
        today = datetime.date.today()
        final: Dict[str, List[float]] = {}
        for (ts, day, src), (ssum, n, _f) in agg.items():
            try:
                d_ago = max(0, (today - datetime.date.fromisoformat(day)).days)
            except ValueError:
                continue
            w = 0.6 ** d_ago
            cell = final.setdefault(ts, [0.0, 0.0, 0])
            cell[0] += w * (ssum / max(1, n))
            cell[1] += w
            cell[2] += n
        raw01 = {}
        for ts, (ws, wsum, n) in final.items():
            if wsum <= 0:
                continue
            mean = ws / wsum
            shrink = min(1.0, math.log(1 + n) / math.log(1 + 8))   # 条数少 → 收缩向 0.5
            raw01[ts] = 0.5 + (mean + 1) / 2 * shrink - 0.5 * shrink  # = 0.5 + mean/2*shrink
        codes_sorted = sorted(raw01)
        rank01 = {ts: (i + 1) / len(codes_sorted) for i, ts in enumerate(codes_sorted)} \
            if codes_sorted else {}

        factor_date = conn.execute(
            "SELECT MAX(trade_date) FROM factor_values_evo").fetchone()[0]
        upd = [(rank01[ts], factor_date, ts) for ts in rank01]
        conn.executemany(
            "UPDATE factor_values_evo SET text_sentiment_score = ? "
            "WHERE trade_date = ? AND ts_code = ?", upd)
        total_stocks = conn.execute(
            f"SELECT COUNT(*) FROM factor_values_evo WHERE trade_date = {factor_date}"
        ).fetchone()[0]
        filled = conn.execute(
            f"SELECT COUNT(text_sentiment_score) FROM factor_values_evo "
            f"WHERE trade_date = {factor_date}").fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    out = {
        "enabled": True,
        "window_start": window_start, "texts": n_text, "matched_texts": n_matched,
        "stocks_covered": len(matched_codes),
        "detail_rows": len(detail), "scored_stocks": len(rank01),
        "factor_date": factor_date, "fill_ratio": round(filled / max(1, total_stocks), 4),
        "duration_sec": round(time.time() - t0, 1),
    }
    logger.info(f"[Text] 打分聚合完成: {out}")
    return out


if __name__ == "__main__":
    if "--backfill" in sys.argv:
        # 一次性历史回填：按日切片 × 40 页 × 6 日窗口（匹配聚合窗口）→ 打分聚合
        fetch_news(pages_override={"cninfo_pages": 40, "sina7x24_pages": 40}, cninfo_days=6)
        score_and_aggregate()
    elif "--daily" in sys.argv:
        fetch_news()            # 常规增量（yaml 配置页数）
        score_and_aggregate()   # 打分 + 聚合 + 回填 factor_values_evo
    elif "--score" in sys.argv:
        score_and_aggregate()
    elif "--fetch" in sys.argv:
        fetch_news()
    else:
        print("用法: python3 src/evo_text_pipeline.py --fetch | --score | --daily | --backfill")



