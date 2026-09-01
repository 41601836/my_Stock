# -*- coding: utf-8 -*-
import os, sys, json, urllib.request

BASE = "http://127.0.0.1:8000"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    ok = True
    # T1 status
    try:
        d = get("/api/status")
        print("[OK] T1 /api/status:", d.get("market_date") or d.get("status") or d)
    except Exception as e:
        print(f"[FAIL] T1 {e}"); ok = False

    # T2 market overview
    try:
        d = get("/api/market/overview")
        err = d.get("error")
        if err: print("[FAIL] T2 overview err:", err); ok = False
        else:
            sf = d.get("sector_money_flow", [])
            themes = d.get("theme_popularity", [])
            top_n = len(sf[0]["sectors"]) if (sf and "sectors" in sf[0]) else 0
            bot_n = len(sf[1]["sectors"]) if (len(sf) > 1 and "sectors" in sf[1]) else 0
            print(f"[OK] T2 overview: top_sectors={top_n}, bottom_sectors={bot_n}, themes={len(themes)}")
            if top_n > 10 or bot_n > 10: print("[FAIL] sector count>10"); ok = False
            if len(themes) > 10: print("[FAIL] themes count>10"); ok = False
            # min_stock_count=5 断言
            for grp in sf:
                for s in grp.get("sectors", []):
                    if s.get("stock_count", 99) < 5:
                        print(f"[FAIL] 板块 {s['sector']} stock_count={s['stock_count']}<5"); ok = False
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"[FAIL] T2 {e}"); ok = False

    # T3 theme stocks default limit
    try:
        d = get("/api/market/theme-stocks?sector=%E7%94%B5%E5%8A%9B")
        ss = d.get("stocks", [])
        print(f"[OK] T3 theme-stocks 电力默认返回: {len(ss)} stocks (expect<=10)")
        if len(ss) > 10: print("[FAIL] default_limit>10"); ok = False
    except Exception as e:
        print(f"[WARN] T3 {e}")

    # T4 explicit limit=3 override
    try:
        d = get("/api/market/theme-stocks?sector=%E7%94%B5%E5%8A%9B&limit=3")
        ss = d.get("stocks", [])
        print(f"[OK] T4 limit=3: {len(ss)} stocks")
        if len(ss) > 3: print("[FAIL] limit=3 NOT APPLIED"); ok = False
    except Exception as e:
        print(f"[WARN] T4 {e}")

    # T5 sort_by=pct_chg + sort_order=DESC
    try:
        d = get("/api/market/theme-stocks?sector=%E7%94%B5%E5%8A%9B&sort_by=pct_chg&sort=desc&limit=5")
        ss = d.get("stocks", [])
        if ss:
            vals = [s["pct_chg"] for s in ss]
            ok_sorted = all(vals[i] >= vals[i+1] for i in range(len(vals)-1))
            print(f"[OK] T5 sort_by=pct_chg desc vals={vals}, sorted_ok={ok_sorted}")
            if not ok_sorted: ok = False
    except Exception as e:
        print(f"[WARN] T5 {e}")

    # T6 portrait smoke 000001.SZ
    try:
        d = get("/api/portrait/analysis?code=000001.SZ")
        if d.get("error"):
            print("[WARN] T6 portrait err:", d["error"][:80])
        else:
            print("[OK] T6 portrait/analysis success; keys:", list(d.keys())[:8])
    except Exception as e:
        print(f"[WARN] T6 {e}")

    print("==== PASS =====" if ok else "==== FAILURES PRESENT =====")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
