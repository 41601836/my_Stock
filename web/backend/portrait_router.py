# -*- coding: utf-8 -*-
"""
portrait_router.py —— T+1 上涨画像过滤路由层
========================================================================
基于最近10天319条推荐记录的实证分析，发现了以下T+1上涨高相关特征：
  - profit_ratio_estimate 低（≤0.30）→ 低位筹码，上涨组中位数0.178
  - pe_ttm 低（≤60）          → 估值合理，上涨组均值56.9 vs 下跌组115.7
  - hot_money_score 低（≤0.55）→ 游资未过热，上涨组0.516 vs 下跌组0.626
  - return_5d 低（≤5%）        → 近期未暴涨，上涨组1.6% vs 下跌组6.3%
  - factor_score 极高（≥0.90）→ 胜率73.1%，0.8-0.9区间反而只有51.9%

画像过滤逻辑（方案B）：
  1. 对每支候选股计算 portrait_score（0-100分，5维各20分）
  2. portrait_score < 40 的股票被过滤，从下一名补充
  3. 最终输出带 portrait_score、portrait_grade 字段的推荐列表
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# S2：优先通过 services 包读取 config/thresholds.yaml（热加载 + 默认值兜底）
# 若 services 包导入失败（脚本环境），则回退到本文件硬编码
try:
    import sys, os
    _sys_path_appended = False
    if "web/backend" not in sys.path:
        _here = os.path.dirname(os.path.abspath(__file__))
        if os.path.isdir(_here):
            sys.path.insert(0, _here)
            _sys_path_appended = True
    from services import (
        get_left_portrait_cfg as _get_left,
        get_right_portrait_cfg as _get_right,
        get_grade_map as _get_gmap,
    )
    _PORTRAIT_FROM_CFG = True
except Exception as _e:
    logger.debug(f"[portrait_router] 回退到内置硬编码阈值: {_e}")
    _PORTRAIT_FROM_CFG = False
    if _sys_path_appended:
        sys.path.pop(0)

# ── 画像参数配置（根据 343 条 T+1 实证数据深度校准）────────────────────────
PORTRAIT_CONFIG = {
    # 1. 位置分：获利筹码比例（低位筹码，上涨组中位数更优）
    #   放宽：牛市初期获利盘90%+常见，0分门槛从75%→85%
    "profit_ratio_full": 0.25,   # ≤ 此值 → 满分20分
    "profit_ratio_half": 0.55,   # ≤ 此值 → 12分（原50%→55%）
    "profit_ratio_zero": 0.85,   # > 此值 → 0分（高位警戒，原0.75→0.85）
    "profit_ratio_weight": 20,

    # 2. 估值分：PE TTM（上涨组均值 45.35 vs 下跌组 49.62，低估值更抗跌）
    "pe_ttm_full": 55.0,    # ≤ 此值 → 满分20分（原45→55）
    "pe_ttm_half": 95.0,    # ≤ 此值 → 12分（原75→95）
    "pe_ttm_zero": 160.0,   # > 此值 → 0分（原120→160，科技股PE普遍偏高）
    "pe_ttm_weight": 20,

    # 3. 温度与活力分：游资热度(0.35-0.55安全) + 5日涨幅(未暴涨) + 股性弹性(60日高波动)
    "hot_score_safe_lo": 0.28,
    "hot_score_safe_hi": 0.60,  # 适度活跃且未过热（原0.55→0.60）
    "return_5d_safe": 0.045,    # 5日涨幅 ≤ 4.5%（原3.5%→4.5%，牛市允许略高）
    "return_5d_max":  0.075,    # 5日涨幅 > 7.5% 归零（原6%→7.5%）
    "temp_weight": 20,

    # 4. 筹码分：筹码集中度（实证上涨组均值 79.18 vs 下跌组 83.15）
    #   放宽：牛市强势股筹码集中度90%属正常现象，黄金区扩大+上移
    "chip_best_lo": 76.0,   # [76.0, 86.0] 黄金区间 → 满分20分（原82→86）
    "chip_best_hi": 86.0,
    "chip_mid_lo":  70.0,   # [70.0, 76.0) 或 (86.0, 92.0] → 12分（原86→92）
    "chip_mid_hi":  92.0,
    "chip_weight": 20,

    # 5. 因子分：综合因子得分（实证上涨组 0.8544 vs 下跌组 0.9050）
    # 采用黄金甜区机制：[0.80, 0.89] 满分；>0.91 过度一致性兑现适当扣分
    "factor_sweet_lo": 0.78, # [0.78, 0.90] → 满分20分（扩大甜区）
    "factor_sweet_hi": 0.90,
    "factor_overheat": 0.94, # > 0.94 → 12分（原0.92→0.94）
    "factor_half":     0.68, # [0.68, 0.78) → 14分
    "factor_weight": 20,

    # 过滤阈值：portrait_score 低于此值的股票被剔除
    "filter_threshold": 48,  # 原50→48，层一同步放宽
    "expand_ratio": 3,
}

# 等级划分
GRADE_MAP = [
    (80, "A", "🔥 强烈推荐"),
    (60, "B", "✅ 符合画像"),
    (40, "C", "⚠️ 勉强通过"),
    (0,  "D", "❌ 画像不符"),
]

# ── 右侧趋势突破画像参数配置 ────────────────────────────────────────────
RIGHT_PORTRAIT_CONFIG = {
    # 1. 突破分：获利筹码比例（越高越好，上方无套牢盘）
    "winner_rate_full": 90.0,   # ≥ 此值 → 满分20分
    "winner_rate_half": 75.0,   # ≥ 此值 → 10分
    "winner_rate_zero": 50.0,   # < 此值 → 0分（左侧特征）
    "winner_rate_weight": 20,

    # 2. 动能分：近期收益率 (return_5d) （抛物线打分，防接盘）
    "return_5d_full_lo": 0.03,  # [3%, 12%] → 满分20分
    "return_5d_full_hi": 0.12,
    "return_5d_half_lo": 0.00,  # [0%, 3%) → 10分
    "return_5d_half_hi": 0.15,  # (12%, 15%] → 10分
    "return_5d_zero_lo": -0.05, # < -5% → 0分
    "return_5d_zero_hi": 0.20,  # > 20% → 0分（甚至负分）
    "momentum_weight": 20,

    # 3. 活跃分：游资热度 (hot_money_score) （抛物线打分，防狂热派发）
    "hot_score_full_lo": 0.60,  # [0.60, 0.85] → 满分20分
    "hot_score_full_hi": 0.85,
    "hot_score_half_lo": 0.50,  # [0.50, 0.60) → 10分
    "hot_score_half_hi": 0.92,  # (0.85, 0.92] → 10分
    "hot_score_zero_hi": 0.96,  # > 0.96 → 0分（严重过热）
    "activity_weight": 20,

    # 4. 流入分：大单净流入（相对概念，我们在具体函数里可以借用 inflow_norm 代替绝对值）
    "inflow_full": 0.85,        # 排名 ≥ 85% → 满分
    "inflow_half": 0.50,        # 排名 ≥ 50% → 10分
    "inflow_weight": 20,

    # 5. 集中分：筹码集中度 (chips_peak_pct)
    "chip_best_lo": 82.0,       # [82, 95] 区间 → 满分20分
    "chip_best_hi": 95.0,
    "chip_mid_lo":  75.0,       # [75, 82) 或 (95, 100] → 10分
    "chip_weight": 20,
}


def _grade(score: float):
    """将数值分转换为等级和说明（S2：优先读配置，无则回退硬编码）"""
    gmap = _get_gmap() if _PORTRAIT_FROM_CFG else GRADE_MAP
    for threshold, grade, label in gmap:
        if score >= threshold:
            return grade, label
    return "D", "❌ 画像不符"


def _safe_float(val, default=np.nan):
    """安全类型转换"""
    if val is None:
        return default
    try:
        v = float(val)
        return default if np.isnan(v) else v
    except (TypeError, ValueError):
        return default


def compute_portrait_score(
    factor_score,
    profit_ratio_estimate,
    pe_ttm,
    hot_money_score,
    return_5d,
    chips_concentration,
    volatility_60d=None,
    cfg=None,
):
    """
    对单支股票计算T+1上涨画像得分（实证数据校准版）。

    参数：
        factor_score            : 五维因子综合得分 [0,1]
        profit_ratio_estimate   : 获利筹码比例 [0,1]
        pe_ttm                  : 市盈率 TTM
        hot_money_score         : 游资热度综合评分 [0,1]
        return_5d               : 近5日涨幅（小数形式，如0.05表示5%）
        chips_concentration     : 筹码集中度（百分比，如79.0）
        volatility_60d          : 60日波动率（可选，股性弹性指标）
        cfg                     : 画像参数配置，不传则使用默认配置
    """
    if cfg is None:
        cfg = _get_left() if _PORTRAIT_FROM_CFG else PORTRAIT_CONFIG

    details = {}

    # ── 1. 位置分：获利筹码比例（低位筹码更易拉升）───────────────────────
    p = _safe_float(profit_ratio_estimate, 0.5)
    if p <= cfg["profit_ratio_full"]:
        pos_score = cfg["profit_ratio_weight"]
    elif p <= cfg["profit_ratio_half"]:
        ratio = (p - cfg["profit_ratio_full"]) / (cfg["profit_ratio_half"] - cfg["profit_ratio_full"])
        pos_score = cfg["profit_ratio_weight"] * (1.0 - ratio * 0.4) # 12~20分
    elif p <= cfg["profit_ratio_zero"]:
        ratio = (p - cfg["profit_ratio_half"]) / (cfg["profit_ratio_zero"] - cfg["profit_ratio_half"])
        pos_score = cfg["profit_ratio_weight"] * 0.6 * (1.0 - ratio) # 0~12分
    else:
        pos_score = 0.0
    details["位置分"] = round(pos_score, 1)

    # ── 2. 估值分：PE TTM（低估值抗跌）───────────────────────────────────
    pe = _safe_float(pe_ttm, np.nan)
    if np.isnan(pe) or pe <= 0:
        _neg_ratio = float(cfg.get("neg_pe_neutral_ratio", 0.5))
        val_score = cfg["pe_ttm_weight"] * _neg_ratio
    elif pe <= cfg["pe_ttm_full"]:
        val_score = cfg["pe_ttm_weight"]
    elif pe <= cfg["pe_ttm_half"]:
        ratio = (pe - cfg["pe_ttm_full"]) / (cfg["pe_ttm_half"] - cfg["pe_ttm_full"])
        val_score = cfg["pe_ttm_weight"] * (1.0 - ratio * 0.4)
    elif pe <= cfg["pe_ttm_zero"]:
        ratio = (pe - cfg["pe_ttm_half"]) / (cfg["pe_ttm_zero"] - cfg["pe_ttm_half"])
        val_score = cfg["pe_ttm_weight"] * 0.6 * (1.0 - ratio)
    else:
        val_score = 0.0
    details["估值分"] = round(val_score, 1)

    # ── 3. 温度与活力分：游资热度(适度蓄势) + 5日涨幅(未暴涨) + 股性弹性 ─────
    hs = _safe_float(hot_money_score, 0.5)
    r5 = _safe_float(return_5d, 0.0)
    vol = _safe_float(volatility_60d, 1.4)

    # 游资状态：0.30~0.55 为最佳吸筹蓄势区
    hot_safe = cfg["hot_score_safe_lo"] <= hs <= cfg["hot_score_safe_hi"]
    # 涨幅状态：5日涨幅 ≤ 3.5% 为安全区间
    return_safe = r5 <= cfg["return_5d_safe"]
    
    if hot_safe and return_safe:
        temp_base = cfg["temp_weight"]
    elif return_safe:
        temp_base = cfg["temp_weight"] * 0.75
    elif hot_safe:
        temp_base = cfg["temp_weight"] * 0.60
    elif r5 <= cfg["return_5d_max"]:
        temp_base = cfg["temp_weight"] * 0.30
    else:
        temp_base = 0.0 # 5日涨幅过大直接零分

    # 股性弹性加分：实证中上涨组波动率高达 1.76 vs 下跌组 1.09
    _vol_bonus_above = float(cfg.get("vol_bonus_above", 1.50))
    _vol_bonus_points = float(cfg.get("vol_bonus_points", 2.0))
    _vol_penalty_below = float(cfg.get("vol_penalty_below", 1.0))
    _vol_penalty_points = float(cfg.get("vol_penalty_points", 3.0))
    if vol >= _vol_bonus_above and temp_base > 0:
        temp_score = min(cfg["temp_weight"], temp_base + _vol_bonus_points)
    elif vol < _vol_penalty_below and temp_base > 0:
        temp_score = max(0.0, temp_base - _vol_penalty_points)
    else:
        temp_score = temp_base
        
    details["温度分"] = round(temp_score, 1)

    # ── 4. 筹码分：筹码集中度（黄金甜区 76-82）───────────────────────────
    cc = _safe_float(chips_concentration, 0.0)
    if cfg["chip_best_lo"] <= cc <= cfg["chip_best_hi"]:
        chip_score = cfg["chip_weight"] # 满分20分
    elif cfg["chip_mid_lo"] <= cc < cfg["chip_best_lo"]:
        ratio = (cc - cfg["chip_mid_lo"]) / (cfg["chip_best_lo"] - cfg["chip_mid_lo"])
        chip_score = cfg["chip_weight"] * (0.6 + 0.4 * ratio) # 12~20分
    elif cfg["chip_best_hi"] < cc <= cfg["chip_mid_hi"]:
        ratio = (cfg["chip_mid_hi"] - cc) / (cfg["chip_mid_hi"] - cfg["chip_best_hi"])
        chip_score = cfg["chip_weight"] * (0.6 + 0.4 * ratio) # 12~20分
    elif cc > cfg["chip_mid_hi"]:
        _over_ratio = float(cfg.get("overconcentration_ratio", 0.3))
        chip_score = cfg["chip_weight"] * _over_ratio
    else:
        chip_score = 0.0 # 过于涣散
    details["筹码分"] = round(chip_score, 1)

    # ── 5. 因子分：综合因子得分（实证上涨组均值 0.8544 甜区机制）─────────
    fs = max(0.0, _safe_float(factor_score, 0.0))  # 下限截断：负值外推会产生负分（fuzz 发现）
    if cfg["factor_sweet_lo"] <= fs <= cfg["factor_sweet_hi"]:
        fac_score = cfg["factor_weight"] # 0.80~0.89 黄金甜区满分20分
    elif fs > cfg["factor_sweet_hi"]:
        if fs >= cfg["factor_overheat"]:
            # >0.92 极度一致明牌，下调至 13 分，防利好兑现被砸
            fac_score = cfg["factor_weight"] * 0.65
        else:
            ratio = (cfg["factor_overheat"] - fs) / (cfg["factor_overheat"] - cfg["factor_sweet_hi"])
            fac_score = cfg["factor_weight"] * (0.65 + 0.35 * ratio)
    elif fs >= cfg["factor_half"]:
        ratio = (fs - cfg["factor_half"]) / (cfg["factor_sweet_lo"] - cfg["factor_half"])
        fac_score = cfg["factor_weight"] * (0.60 + 0.40 * ratio) # 0.70~0.80 给 12~20分
    else:
        fac_score = cfg["factor_weight"] * (fs / (cfg["factor_half"] + 1e-9)) * 0.6
    details["因子分"] = round(fac_score, 1)

    # ── 汇总 ──────────────────────────────────────────────────────────────
    total = pos_score + val_score + temp_score + chip_score + fac_score
    grade, label = _grade(total)

    return {
        "portrait_score":   round(total, 1),
        "portrait_grade":   grade,
        "portrait_label":   label,
        "portrait_details": details,
    }


def compute_right_side_portrait_score(
    winner_rate,
    return_5d,
    hot_money_score,
    inflow_norm,
    chips_peak_pct,
    cfg=None,
):
    """
    对单支股票计算T+1右侧突破画像得分。

    参数：
        winner_rate       : 获利筹码比例百分比（如 85.0）
        return_5d         : 近5日涨幅（小数，如 0.05）
        hot_money_score   : 游资热度评分 [0,1]
        inflow_norm       : 净流入横截面排名 [0,1]
        chips_peak_pct    : 筹码集中度（如 85.0）
    """
    if cfg is None:
        cfg = _get_right() if _PORTRAIT_FROM_CFG else RIGHT_PORTRAIT_CONFIG

    details = {}

    # ── 1. 突破分：筹码胜率（winner_rate）────────────────────────────
    wr = _safe_float(winner_rate, 0.0)
    if wr >= cfg["winner_rate_full"]:
        pos_score = cfg["winner_rate_weight"]
    elif wr >= cfg["winner_rate_half"]:
        ratio = (wr - cfg["winner_rate_half"]) / (cfg["winner_rate_full"] - cfg["winner_rate_half"])
        pos_score = cfg["winner_rate_weight"] * (0.5 + 0.5 * ratio)
    elif wr >= cfg["winner_rate_zero"]:
        ratio = (wr - cfg["winner_rate_zero"]) / (cfg["winner_rate_half"] - cfg["winner_rate_zero"])
        pos_score = cfg["winner_rate_weight"] * 0.5 * ratio
    else:
        pos_score = 0.0
    details["突破分"] = round(pos_score, 1)

    # ── 2. 动能分：近期收益率（return_5d）─────────────────────────────
    r5 = _safe_float(return_5d, 0.0)
    if cfg["return_5d_full_lo"] <= r5 <= cfg["return_5d_full_hi"]:
        mom_score = cfg["momentum_weight"]
    elif cfg["return_5d_half_lo"] <= r5 < cfg["return_5d_full_lo"]:
        # 低于甜区，按比例给分
        ratio = (r5 - cfg["return_5d_half_lo"]) / (cfg["return_5d_full_lo"] - cfg["return_5d_half_lo"])
        mom_score = cfg["momentum_weight"] * (0.5 + 0.5 * ratio)
    elif cfg["return_5d_full_hi"] < r5 <= cfg["return_5d_half_hi"]:
        # 高于甜区，开始减分
        ratio = (cfg["return_5d_half_hi"] - r5) / (cfg["return_5d_half_hi"] - cfg["return_5d_full_hi"])
        mom_score = cfg["momentum_weight"] * (0.5 + 0.5 * ratio)
    elif cfg["return_5d_half_hi"] < r5 <= cfg["return_5d_zero_hi"]:
        # 高度透支，快速扣分到0
        ratio = (cfg["return_5d_zero_hi"] - r5) / (cfg["return_5d_zero_hi"] - cfg["return_5d_half_hi"])
        mom_score = cfg["momentum_weight"] * 0.5 * ratio
    elif r5 > cfg["return_5d_zero_hi"]:
        # 极度透支，倒扣分
        mom_score = float(cfg.get("overshoot_penalty", -10.0))
    elif r5 >= cfg["return_5d_zero_lo"]:
        ratio = (r5 - cfg["return_5d_zero_lo"]) / (cfg["return_5d_half_lo"] - cfg["return_5d_zero_lo"])
        mom_score = cfg["momentum_weight"] * 0.5 * ratio
    else:
        mom_score = 0.0
    details["动能分"] = round(mom_score, 1)

    # ── 3. 活跃分：游资热度（hot_money_score）─────────────────────────
    hm = _safe_float(hot_money_score, 0.0)
    if cfg["hot_score_full_lo"] <= hm <= cfg["hot_score_full_hi"]:
        act_score = cfg["activity_weight"]
    elif cfg["hot_score_half_lo"] <= hm < cfg["hot_score_full_lo"]:
        ratio = (hm - cfg["hot_score_half_lo"]) / (cfg["hot_score_full_lo"] - cfg["hot_score_half_lo"])
        act_score = cfg["activity_weight"] * (0.5 + 0.5 * ratio)
    elif cfg["hot_score_full_hi"] < hm <= cfg["hot_score_half_hi"]:
        ratio = (cfg["hot_score_half_hi"] - hm) / (cfg["hot_score_half_hi"] - cfg["hot_score_full_hi"])
        act_score = cfg["activity_weight"] * (0.5 + 0.5 * ratio)
    elif cfg["hot_score_half_hi"] < hm <= cfg["hot_score_zero_hi"]:
        ratio = (cfg["hot_score_zero_hi"] - hm) / (cfg["hot_score_zero_hi"] - cfg["hot_score_half_hi"])
        act_score = cfg["activity_weight"] * 0.5 * ratio
    elif hm > cfg["hot_score_zero_hi"]:
        act_score = float(cfg.get("overshoot_penalty_activity", -5.0))
    else:
        ratio = hm / (cfg["hot_score_half_lo"] + 1e-9)
        act_score = cfg["activity_weight"] * 0.5 * ratio
    details["活跃分"] = round(act_score, 1)

    # ── 4. 流入分：大单净流入（inflow_norm）───────────────────────────
    inf = _safe_float(inflow_norm, 0.0)
    if inf >= cfg["inflow_full"]:
        inf_score = cfg["inflow_weight"]
    elif inf >= cfg["inflow_half"]:
        ratio = (inf - cfg["inflow_half"]) / (cfg["inflow_full"] - cfg["inflow_half"])
        inf_score = cfg["inflow_weight"] * (0.5 + 0.5 * ratio)
    else:
        ratio = inf / (cfg["inflow_half"] + 1e-9)
        inf_score = cfg["inflow_weight"] * 0.5 * ratio
    details["流入分"] = round(inf_score, 1)

    # ── 5. 集中分：筹码集中度（chips_peak_pct）─────────────────────────
    cc = _safe_float(chips_peak_pct, 0.0)
    if cfg["chip_best_lo"] <= cc <= cfg["chip_best_hi"]:
        chip_score = cfg["chip_weight"]
    elif cfg["chip_mid_lo"] <= cc < cfg["chip_best_lo"]:
        chip_score = cfg["chip_weight"] * 0.5
    elif cc > cfg["chip_best_hi"]:
        chip_score = cfg["chip_weight"] * 0.5
    else:
        chip_score = 0.0
    details["集中分"] = round(chip_score, 1)

    # ── 汇总 ─────────────────────────────────────────────────────────
    total = pos_score + mom_score + act_score + inf_score + chip_score
    grade, label = _grade(total)

    return {
        "portrait_score":   round(total, 1),
        "portrait_grade":   grade,
        "portrait_label":   label,
        "portrait_details": details,
    }


def apply_portrait_filter(df_top, df_fv, conn=None, cfg=None, filter_mode=True):
    """
    对候选股票列表批量计算画像分，并按过滤模式处理。

    参数：
        df_top      : 因子打分后的候选股 DataFrame，包含 stock_code、score/score_norm 等字段
        df_fv       : factor_values 表当日全量数据（含 profit_ratio_estimate、pe_ttm 等）
        conn        : SQLite 连接（用于查询 stock_cyq_perf 获取真实筹码集中度）
        cfg         : 画像参数配置，不传则使用默认配置
        filter_mode : True=过滤模式（剔除 D 级 portrait_score < threshold）

    返回：
        DataFrame，追加了 portrait_score、portrait_grade、portrait_label 字段
    """
    import pandas as pd
    if cfg is None:
        cfg = _get_left() if _PORTRAIT_FROM_CFG else PORTRAIT_CONFIG

    # 将 factor_values 转为以 stock_code 为 key 的 dict
    fv_dict = {}
    if df_fv is not None and not df_fv.empty:
        code_col = "stock_code" if "stock_code" in df_fv.columns else "ts_code"
        for _, row in df_fv.iterrows():
            fv_dict[str(row[code_col])] = row

    # ── 批量查询真实筹码集中度（stock_cyq_perf.chips_peak_pct）────────────────
    # factor_values.chip_concentration 是归一化小数（0-1），与筹码集中度百分比含义不同
    # 必须从 stock_cyq_perf 读取 chips_peak_pct（如 85.0 表示85%）
    cyq_dict = {}
    if conn is not None:
        try:
            code_col = "stock_code" if "stock_code" in df_top.columns else "ts_code"
            codes = df_top[code_col].unique().tolist()
            # 获取因子日期
            trade_date = None
            if df_fv is not None and not df_fv.empty and "trade_date" in df_fv.columns:
                trade_date = df_fv["trade_date"].iloc[0]
            if trade_date:
                ph = ",".join([f"'{c}'" for c in codes])
                df_cyq = pd.read_sql(
                    f"SELECT ts_code, chips_peak_pct FROM stock_cyq_perf "
                    f"WHERE trade_date = '{trade_date}' AND ts_code IN ({ph})",
                    conn
                )
                cyq_dict = dict(zip(df_cyq["ts_code"], df_cyq["chips_peak_pct"]))
                logger.info(f"[PortraitRouter] 从 stock_cyq_perf 获取 {len(cyq_dict)} 支股票筹码集中度")
        except Exception as e:
            logger.warning(f"[PortraitRouter] 查询 stock_cyq_perf 失败: {e}")

    portrait_rows = []
    for _, row in df_top.iterrows():
        code = str(row.get("stock_code") or row.get("ts_code", ""))
        fv   = fv_dict.get(code, {})

        def fv_get(key, default=np.nan):
            """从 factor_values 行安全取值"""
            val = fv.get(key, default) if isinstance(fv, dict) else (
                fv[key] if key in fv.index else default
            )
            return _safe_float(val, default)

        # factor_score 优先从 row 取（已归一化的 score_norm），再查 fv
        factor_score_val = _safe_float(
            row.get("score") or row.get("score_norm"), 0.0
        )

        # chips_concentration 优先用 stock_cyq_perf 的真实百分比数据
        # 次选用 recommendation_tracker 中已存的值（也是百分比）
        chips_val = cyq_dict.get(code, 0.0)
        if chips_val == 0.0:
            chips_val = _safe_float(row.get("chips_concentration"), 0.0)

        result = compute_portrait_score(
            factor_score          = factor_score_val,
            profit_ratio_estimate = fv_get("profit_ratio_estimate", 0.5),
            pe_ttm                = fv_get("pe_ttm", 9999.0),
            hot_money_score       = fv_get("hot_money_score", 0.5),
            return_5d             = fv_get("return_5d", 0.0),
            chips_concentration   = chips_val,
            cfg=cfg,
        )
        portrait_rows.append(result)

    # 合并画像结果
    df_result = df_top.copy().reset_index(drop=True)
    df_result["portrait_score"]   = [r["portrait_score"]   for r in portrait_rows]
    df_result["portrait_grade"]   = [r["portrait_grade"]   for r in portrait_rows]
    df_result["portrait_label"]   = [r["portrait_label"]   for r in portrait_rows]
    df_result["portrait_details"] = [r["portrait_details"] for r in portrait_rows]

    # 输出画像分布日志
    grade_cnt = df_result["portrait_grade"].value_counts().to_dict()
    logger.info(
        f"[PortraitRouter] 画像评分完成，等级分布：A={grade_cnt.get('A',0)} "
        f"B={grade_cnt.get('B',0)} C={grade_cnt.get('C',0)} D={grade_cnt.get('D',0)}"
    )

    if not filter_mode:
        return df_result

    # ── 过滤模式：剔除 D 级（portrait_score < threshold）────────────────────
    threshold = cfg["filter_threshold"]
    mask_pass = df_result["portrait_score"] >= threshold
    df_pass   = df_result[mask_pass].copy()
    df_reject = df_result[~mask_pass].copy()

    if not df_reject.empty:
        reject_codes = df_reject.get("stock_code", df_reject.get("ts_code", pd.Series())).tolist()
        reject_scores = df_reject["portrait_score"].tolist()
        logger.info(
            f"[PortraitRouter] 🚫 过滤 {len(df_reject)} 只画像不符股票 "
            f"(portrait_score < {threshold})：{list(zip(reject_codes, reject_scores))}"
        )

    logger.info(
        f"[PortraitRouter] ✅ 通过画像过滤：{len(df_pass)}/{len(df_result)} 只"
    )
    return df_pass.reset_index(drop=True)
