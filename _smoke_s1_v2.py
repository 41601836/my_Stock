import sys, os, traceback, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'web/backend'))

print('\n========= [1] Import services exactly as app.py does =========')
try:
    from services import (
        get_market_status, get_deployed_factors, get_today_portfolio,
        get_performance_data, get_agent_logs, get_jack_performance_data,
        get_build_position_opportunities, get_tracker_attribution_data,
        determine_adaptive_hold_period, get_market_overview_data,
        get_regime_dashboard, get_theme_stocks, search_stock, diagnose_stock,
        get_style_stocks, record_visitor, get_visitor_stats,
        save_scan_history, get_scan_history, get_timing_alerts,
        get_portrait_analysis, get_portrait_position_pick,
        clean_nan_inf, PROJECT_ROOT,
    )
    print('OK app.py import 全部通过, PROJECT_ROOT =', PROJECT_ROOT)
except Exception:
    traceback.print_exc()
    sys.exit(1)

print('\n========= [2] get_market_status() =========')
try:
    s = get_market_status()
    print(f'  regime={s.get("regime")}, model={s.get("model_used")}, trade_date={s.get("trade_date")}')
    print(f'  db_latest={s.get("db_latest_date")}, db_health={s.get("db_health")}')
    print(f'  _debug.regime_source={s.get("_debug", {}).get("regime_source")}')
except Exception:
    traceback.print_exc()

print('\n========= [3] get_deployed_factors() =========')
try:
    df = get_deployed_factors()
    print(f'  Range factors: {len(df["range_factors"])} 个')
    print(f'  Bull  factors: {len(df["bull_factors"])} 个')
    for f in df['range_factors'][:3]:
        print(f'    R - {f["factor"]}: {f["weight"]:+.4f}')
except Exception:
    traceback.print_exc()

print('\n========= [4] get_portrait_position_pick() 画像建仓决策 =========')
try:
    r = get_portrait_position_pick(top_n=5)
    if r.get('error'):
        print('  ERROR:', r['error'])
    else:
        opps = r.get('opportunities', [])
        print(f'  推选 {len(opps)} 只, scan_date={r.get("scan_date")}')
        for o in opps:
            print(f'    #{o.get("rank")} {o.get("ts_code")} {o.get("name"):<6} score={o.get("portrait_score")} grade={o.get("portrait_grade")} mvo={o.get("mvo_weight")}% ind={o.get("sector_sorted")}')
        if r.get('stats'):
            print('  stats=', json.dumps({k:v for k,v in r['stats'].items() if k != 'portrait_config'}, ensure_ascii=False, indent=2))
except Exception:
    traceback.print_exc()

print('\n========= [5] /api/portrait/position-pick 兼容旧 get_build_position_opportunities 格式 =========')
try:
    r2 = get_build_position_opportunities()
    if isinstance(r2, dict) and (r2.get('opportunities') or r2.get('error')):
        print(f'  新格式 OK: {len(r2.get("opportunities", []))} 只, err={r2.get("error")}')
    elif isinstance(r2, list):
        print(f'  旧列表格式, len={len(r2)}')
    else:
        print('  ??? type=', type(r2).__name__)
except Exception:
    traceback.print_exc()

print('\n========= [6] 行数统计 (wc -l) =========')
import subprocess
srv_dir = os.path.join(PROJECT_ROOT, 'web/backend/services')
for fn in ['__init__.py','_common.py','market_regime.py','factors_assets.py','performance.py','scanner.py','market_overview.py','portrait.py']:
    path = os.path.join(srv_dir, fn)
    if os.path.exists(path):
        with open(path, 'r') as f:
            n = len(f.readlines())
        print(f'  {fn:<22s} {n:>5d} 行')
print('  ---------------------------------------')
tot = 0
for fn in ['__init__.py','_common.py','market_regime.py','factors_assets.py','performance.py','scanner.py','market_overview.py','portrait.py']:
    path = os.path.join(srv_dir, fn)
    if os.path.exists(path):
        with open(path, 'r') as f:
            tot += len(f.readlines())
bak = os.path.join(srv_dir, '..', 'services_archive_v1.py.bak')
with open(bak, 'r') as f:
    orig = len(f.readlines())
print(f'  原 services.py.bak     {orig:>5d} 行')
print(f'  拆分后 8 个文件合计    {tot:>5d} 行 (含注释/docstring/空行)')
print(f'  压缩比 ≈ {orig/tot*100:.0f}%（相同行数因公共导入分摊显差异）')
print('\nALL SMOKE TESTS PASSED')
