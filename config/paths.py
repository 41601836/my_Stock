# -*- coding: utf-8 -*-
"""
paths.py —— 项目路径配置统一加载器
==================================================
1. 从 config/paths.yaml 集中加载所有路径配置
2. 将相对路径解析为基于 PROJECT_ROOT 的绝对路径
3. 支持环境变量替换：${ENV_VAR:-default}
4. 支持日期模板：{date} -> YYYYMMDD
5. 启动时自动检查关键路径是否存在
"""

import os
import re
import yaml
from datetime import datetime
from typing import Dict, Any

PROJECT_ROOT = None
_PATHS_DATA = None
_PATHS_FLATTENED = None


def _find_project_root() -> str:
    current = os.path.dirname(os.path.abspath(__file__))
    while current != os.path.dirname(current):
        if os.path.isdir(os.path.join(current, "config")) and os.path.isfile(os.path.join(current, "config", "paths.yaml")):
            return current
        current = os.path.dirname(current)
    raise RuntimeError("无法找到项目根目录：未找到包含 config/paths.yaml 的目录")


def _resolve_env_var(value: str) -> str:
    if not isinstance(value, str):
        return value
    def replacer(match):
        env_var = match.group(1)
        default = match.group(3) if match.group(3) else ""
        return os.environ.get(env_var, default)
    return re.sub(r"\$\{([^}:-]+)(:-([^}]+))?\}", replacer, value)


def _resolve_date_template(value: str) -> str:
    if not isinstance(value, str):
        return value
    today = datetime.now().strftime("%Y%m%d")
    return value.replace("{date}", today)


def _flatten_dict(d: Dict[str, Any], parent_key: str = "") -> Dict[str, str]:
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}.{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key))
        elif isinstance(v, str):
            items[new_key] = v
    return items


def load_paths() -> Dict[str, Any]:
    global PROJECT_ROOT, _PATHS_DATA, _PATHS_FLATTENED
    
    if PROJECT_ROOT is None:
        PROJECT_ROOT = _find_project_root()
    
    if _PATHS_DATA is None:
        yaml_path = os.path.join(PROJECT_ROOT, "config", "paths.yaml")
        with open(yaml_path, "r", encoding="utf-8") as f:
            _PATHS_DATA = yaml.safe_load(f)
        
        _PATHS_FLATTENED = _flatten_dict(_PATHS_DATA)
    
    return _PATHS_DATA


def get_path(key: str) -> str:
    load_paths()
    if key not in _PATHS_FLATTENED:
        raise KeyError(f"路径配置键不存在: {key}")
    
    relative_path = _PATHS_FLATTENED[key]
    resolved = _resolve_env_var(relative_path)
    resolved = _resolve_date_template(resolved)
    
    if resolved.startswith("/"):
        return resolved
    
    return os.path.join(PROJECT_ROOT, resolved)


def startup_check(logger=None) -> bool:
    load_paths()
    must_exist_keys = _PATHS_DATA.get("must_exist", [])
    missing = []
    
    for key in must_exist_keys:
        try:
            path = get_path(key)
            if not os.path.exists(path):
                missing.append((key, path))
        except KeyError:
            missing.append((key, "配置键不存在"))
    
    if missing:
        msg = "\n".join([f"  - [{key}] 路径不存在: {path}" for key, path in missing])
        if logger:
            logger.warning(f"⚠️ [路径自检] 发现 {len(missing)} 个关键路径缺失:\n{msg}")
        else:
            print(f"⚠️ [路径自检] 发现 {len(missing)} 个关键路径缺失:\n{msg}")
        return False
    
    if logger:
        logger.info("✅ [路径自检] 所有关键路径验证通过")
    else:
        print("✅ [路径自检] 所有关键路径验证通过")
    return True


class PATHS:
    database = type('DatabasePaths', (), {
        'stock_data': property(lambda self: get_path('database.stock_data')),
        'stock_daily': property(lambda self: get_path('database.stock_daily')),
        'strategy': property(lambda self: get_path('database.strategy')),
        'market_data': property(lambda self: get_path('database.market_data')),
    })()
    
    models = type('ModelsPaths', (), {
        'regime_weights': property(lambda self: get_path('models.regime_weights')),
        'regime_weights_proposed': property(lambda self: get_path('models.regime_weights_proposed')),
        'bull_weights_proposed': property(lambda self: get_path('models.bull_weights_proposed')),
    })()
    
    data = type('DataPaths', (), {
        'market_regime_labels': property(lambda self: get_path('data.market_regime_labels')),
        'market_regime_labels_v2': property(lambda self: get_path('data.market_regime_labels_v2')),
        'factor_ic_csv_source': property(lambda self: get_path('data.factor_ic_csv_source')),
        'backtest_results': property(lambda self: get_path('data.backtest_results')),
    })()
    
    logs = type('LogsPaths', (), {
        'scheduler': property(lambda self: get_path('logs.scheduler')),
        'agent_auto_run': property(lambda self: get_path('logs.agent_auto_run')),
    })()
    
    reports = type('ReportsPaths', (), {
        'agent_cruise': property(lambda self: get_path('reports.agent_cruise')),
        'agent_report': property(lambda self: get_path('reports.agent_report')),
    })()
    
    config = type('ConfigPaths', (), {
        'agent': property(lambda self: get_path('config.agent')),
        'candidate_factors': property(lambda self: get_path('config.candidate_factors')),
        'market_regime': property(lambda self: get_path('config.market_regime')),
    })()


if __name__ == "__main__":
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"\n数据库路径:")
    print(f"  stock_data: {PATHS.database.stock_data}")
    print(f"  stock_daily: {PATHS.database.stock_daily}")
    print(f"  strategy: {PATHS.database.strategy}")
    print(f"  market_data: {PATHS.database.market_data}")
    
    print(f"\n模型路径:")
    print(f"  regime_weights: {PATHS.models.regime_weights}")
    print(f"  regime_weights_proposed: {PATHS.models.regime_weights_proposed}")
    print(f"  bull_weights_proposed: {PATHS.models.bull_weights_proposed}")
    
    print(f"\n数据路径:")
    print(f"  market_regime_labels: {PATHS.data.market_regime_labels}")
    print(f"  market_regime_labels_v2: {PATHS.data.market_regime_labels_v2}")
    print(f"  factor_ic_csv_source: {PATHS.data.factor_ic_csv_source}")
    print(f"  backtest_results: {PATHS.data.backtest_results}")
    
    print(f"\n日志路径:")
    print(f"  scheduler: {PATHS.logs.scheduler}")
    print(f"  agent_auto_run: {PATHS.logs.agent_auto_run}")
    
    print(f"\n配置路径:")
    print(f"  agent: {PATHS.config.agent}")
    print(f"  candidate_factors: {PATHS.config.candidate_factors}")
    print(f"  market_regime: {PATHS.config.market_regime}")
    
    print(f"\n--- 启动自检 ---")
    startup_check()