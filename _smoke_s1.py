import sys, os, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'web/backend'))
names = ['get_market_status','get_deployed_factors','get_today_portfolio','get_performance_data',
         'get_agent_logs','get_jack_performance_data','get_build_position_opportunities',
         'get_tracker_attribution_data','determine_adaptive_hold_period','get_market_overview_data',
         'get_regime_dashboard','get_theme_stocks','search_stock','diagnose_stock','get_style_stocks',
         'record_visitor','get_visitor_stats','save_scan_history','get_scan_history',
         'get_timing_alerts','get_portrait_analysis','get_portrait_position_pick',
         'clean_nan_inf','PROJECT_ROOT','compute_live_regime','get_recommendation_history','record_alerts_feedback']
try:
    import services
    print('OK services imported, __name__ =', services.__name__)
    print('  __file__ =', getattr(services, '__file__', ''))
    missing = [n for n in names if not hasattr(services, n)]
    if missing:
        print('MISSING:', missing)
    else:
        print(f'ALL {len(names)} public interfaces present')
except Exception:
    traceback.print_exc()
    sys.exit(1)
