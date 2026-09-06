# -*- coding: utf-8 -*-
"""
registry.py — 因子注册表（单一事实来源）
=================================================
声明全部因子元数据，供推荐系统和因子测试模块共享。
因子值由现有 feature_engineering.py / feature_engineering_evo.py 计算并入库，
本模块只读元数据，不计算因子值。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FactorMeta:
    name: str
    direction: int          # +1 正向（值大越好），-1 反向（值小越好）
    category: str           # 动量/波动率/估值/流动性/聪明钱/防御/复合/交叉/预期差
    table: str              # "factor_values" 或 "factor_values_evo"
    description: str
    direction_note: str = ""


_FACTOR_LIST: List[FactorMeta] = [
    # ═══════════ 动量/反转 (6) ═══════════
    FactorMeta("return_5d", +1, "动量", "factor_values",
               "5日收益率", "短期动量，值越大预期未来收益越高"),
    FactorMeta("return_10d", +1, "动量", "factor_values",
               "10日收益率", "中短期动量"),
    FactorMeta("return_20d", +1, "动量", "factor_values",
               "20日收益率", "中期动量"),
    FactorMeta("return_60d", +1, "动量", "factor_values",
               "60日收益率", "中长期动量"),
    FactorMeta("return_120d", +1, "动量", "factor_values",
               "120日收益率", "长期动量"),
    FactorMeta("excess_return_20d", +1, "动量", "factor_values",
               "20日超额收益（个股-全市场均值）", "跑赢市场的股票持续跑赢"),

    # ═══════════ 波动率/风险 (8) ═══════════
    FactorMeta("volatility_10d", -1, "波动率", "factor_values",
               "10日收益率标准差", "低波动异象，低波动股票长期更优"),
    FactorMeta("volatility_20d", -1, "波动率", "factor_values",
               "20日收益率标准差", "低波动异象"),
    FactorMeta("volatility_60d", -1, "波动率", "factor_values",
               "60日收益率标准差", "中期波动率"),
    FactorMeta("volatility_120d", -1, "波动率", "factor_values",
               "120日收益率标准差", "长期波动率"),
    FactorMeta("skewness_20d", -1, "波动率", "factor_values",
               "20日收益率偏度", "左偏分布更稳健，右偏有尾部风险"),
    FactorMeta("max_drawdown_20d", -1, "波动率", "factor_values",
               "20日最大回撤", "回撤越小越好"),
    FactorMeta("max_drawdown_60d", -1, "波动率", "factor_values",
               "60日最大回撤", "中长期回撤控制"),
    FactorMeta("atr_ratio", -1, "波动率", "factor_values",
               "ATR(14)/收盘价", "波动幅度比率，越低越稳"),
    # P2-2C: 高阶波动率 (2)
    FactorMeta("gk_volatility_20d", -1, "波动率", "factor_values",
               "20日Garman-Klass波动率（年化）",
               "基于OHLC的高阶波动率估计，比收盘波动率更精确，波动高=风险大"),
    FactorMeta("parkinson_volatility_20d", -1, "波动率", "factor_values",
               "20日Parkinson波动率（年化）",
               "仅用高低价的波动率估计，备用对比，波动高=风险大"),

    # ═══════════ 估值/质量 (3) ═══════════
    FactorMeta("pe_ttm", -1, "估值", "factor_values",
               "PE(TTM)", "低估值股票长期超额收益"),
    FactorMeta("pb", -1, "估值", "factor_values",
               "PB", "低市净率价值因子"),
    FactorMeta("roe", +1, "估值", "factor_values",
               "ROE代理(PB/pe_ttm)", "高ROE代表盈利能力强"),

    # ═══════════ 流动性 (3) ═══════════
    FactorMeta("turnover_rate", -1, "流动性", "factor_values",
               "当日换手率", "低换手率股票长期更优（流动性溢价）"),
    FactorMeta("turnover_rate_5d", -1, "流动性", "factor_values",
               "5日平均换手率", "短期流动性代理"),
    FactorMeta("turnover_rate_20d", -1, "流动性", "factor_values",
               "20日平均换手率", "中期流动性代理"),
    # P2-2B: 流动性高阶因子 (4)
    FactorMeta("amihud_illiq_20d", -1, "流动性", "factor_values",
               "20日Amihud非流动性比率",
               "|日收益|/成交额的均值，非流动性越高，冲击成本越高，反向"),
    FactorMeta("turnover_volatility_20d", -1, "流动性", "factor_values",
               "20日换手率标准差",
               "换手波动大代表筹码松动，资金分歧大，反向"),
    FactorMeta("volume_skewness_20d", +1, "流动性", "factor_values",
               "20日成交量偏度",
               "正偏意味着放量上涨居多，量价配合好，正向"),
    FactorMeta("amount_volatility_20d", -1, "流动性", "factor_values",
               "20日成交额变异系数（std/mean）",
               "成交额波动大代表多空分歧大，反向"),

    # ═══════════ 聪明钱/微观 (4) ═══════════
    FactorMeta("north_net_inflow_ratio", +1, "聪明钱", "factor_values",
               "52日大单净流入占比", "聪明钱流入越多越好"),
    FactorMeta("profit_ratio_estimate", +1, "聪明钱", "factor_values",
               "获利盘位置(0-1)", "筹码分布获利位置"),
    FactorMeta("chip_concentration", -1, "聪明钱", "factor_values",
               "筹码集中度(偏离20日均线绝对值)", "集中度越高风险越大"),
    FactorMeta("vol_ratio", -1, "聪明钱", "factor_values",
               "量比(5日均量/60日均量)",
               "2026-09-03 三段IC审计翻转(+1→-1)：全样本/基准期/近期 RankIC 全负(-0.049/-0.045/-0.060)，"
               "|ICIR| 0.40~0.54 均≥0.30；放量股未来5日显著跑输（天量见顶/低量溢价）"),

    # ═══════════ 情绪 (3) — P2-2A 隔夜/日内收益分离 ═══════════
    FactorMeta("overnight_return_5d", -1, "情绪", "factor_values",
               "5日平均隔夜收益率（开盘/昨收-1）",
               "隔夜跳空高代表散户情绪过热，反向因子"),
    FactorMeta("intraday_return_5d", +1, "情绪", "factor_values",
               "5日平均日内收益率（收盘/开盘-1）",
               "日内动量代表机构主导方向，正向因子"),
    FactorMeta("overnight_intraday_gap_5d", -1, "情绪", "factor_values",
               "5日隔夜收益-日内收益之差",
               "差值越大说明散户越主导（隔夜情绪化），反向因子"),

    # ═══════════ 筹码 (4) — P2-2D CYQ 筹码分布模型 ═══════════
    FactorMeta("cyq_profit_ratio_60d", -1, "筹码", "factor_values",
               "CYQ浮盈比例（60日窗口）",
               "当前价以下筹码占比，浮盈比例高=抛压大，反向因子"),
    FactorMeta("cyq_upper_pressure_60d", -1, "筹码", "factor_values",
               "CYQ上方抛压（60日窗口）",
               "当前价以上套牢盘占比，套牢盘多=阻力大，反向因子"),
    FactorMeta("cyq_chip_concentration_60d", +1, "筹码", "factor_values",
               "CYQ筹码集中度（±10%价格区间，60日窗口）",
               "筹码集中代表庄家控盘程度高，正向因子"),
    FactorMeta("cyq_avg_cost_dev_60d", -1, "筹码", "factor_values",
               "CYQ当前价相对平均成本偏离率（60日窗口）",
               "偏离成本太远=风险高，反向因子"),

    # ═══════════ 板块 (1) — P2-2E 板块强度 ═══════════
    FactorMeta("sector_strength", +1, "板块", "factor_values",
               "板块强度（收益+宽度+成交额合成）",
               "板块强则个股大概率跟随，正向因子"),

    # ═══════════ 情绪 (1) — P2-2F 情绪复合 ═══════════
    FactorMeta("sentiment_composite", -1, "情绪", "factor_values",
               "情绪复合因子（换手分位+隔夜波动+连涨天数）",
               "情绪越高亢=风险越大，反向因子（A 股情绪过热见顶效应）"),

    # ═══════════ 防御 (4) ═══════════
    FactorMeta("beta_60d", -1, "防御", "factor_values",
               "60日个股vs市场贝塔", "低贝塔股票防御性更强"),
    FactorMeta("quality_score", +1, "防御", "factor_values",
               "质量评分(ROE-PB*0.1)", "综合质量得分"),
    FactorMeta("low_turnover_flag", +1, "防御", "factor_values",
               "低换手标记(0/1)", "低换手股票更稳健"),
    FactorMeta("timeliness_decay", +1, "防御", "factor_values",
               "时效性衰减因子(常数占位)", "占位因子，IC预期接近0"),

    # ═══════════ 复合/辅助 (3) ═══════════
    FactorMeta("hot_money_score", -1, "复合", "factor_values",
               "游资热点得分",
               "2026-09-03 三段IC审计翻转(+1→-1)：RankIC 全负(-0.060/-0.059/-0.063)，|ICIR| 0.48~0.53；"
               "追热点组合未来5日显著跑输（量比+5日动量+换手-筹码集中）"),
    FactorMeta("strong_control_score", +1, "复合", "factor_values",
               "强庄控盘得分", "筹码集中+低波动+60日动量+质量"),
    FactorMeta("main_force_score", -1, "复合", "factor_values",
               "主力资金得分",
               "2026-09-03 三段IC审计翻转(+1→-1)：RankIC 全负(-0.053/-0.052/-0.055)，|ICIR| 0.37~0.50；"
               "高分股未来5日跑输（北向+获利盘+20日动量-回撤）"),

    # ═══════════ EVO 交叉因子 (10) ═══════════
    FactorMeta("inter_quality_momentum", +1, "交叉", "factor_values_evo",
               "质量×动量(ROE×20日动量)", "高质量+高动量双重确认"),
    FactorMeta("inter_value_excess", +1, "交叉", "factor_values_evo",
               "价值×超额((1-PB_rank)×超额收益)", "低估值+跑赢市场"),
    FactorMeta("inter_chip_volume", +1, "交叉", "factor_values_evo",
               "筹码×放量((1-集中度)×量比)", "筹码分散+放量确认"),
    FactorMeta("inter_smart_defense", +1, "交叉", "factor_values_evo",
               "聪明钱×防御(北向×低换手)", "外资关注+低换手防御"),
    FactorMeta("inter_overshoot_reversal", +1, "交叉", "factor_values_evo",
               "超跌反弹((1-获利盘)×(1-5日收益))", "低位超跌反弹机会"),
    FactorMeta("triple_value_mom_quality", +1, "交叉", "factor_values_evo",
               "三重交互(PB倒数×20日动量×ROE)", "价值+动量+质量三重确认"),
    FactorMeta("inter_mom_skew_neg", +1, "交叉", "factor_values_evo",
               "动量×左偏(10日动量×(1-20日偏度))", "上涨+左偏更稳健"),
    FactorMeta("inter_lowvol_profit", +1, "交叉", "factor_values_evo",
               "低波×获利((1-低波动)×获利盘)", "低波动+筹码好"),
    FactorMeta("inter_turnover_reversal", +1, "交叉", "factor_values_evo",
               "换手反转(5日换手×(1-5日收益))", "放量超跌反弹"),
    FactorMeta("inter_chip_break_right", -1, "交叉", "factor_values_evo",
               "筹码突破(获利盘×主力资金)",
               "2026-09-03 三段IC审计翻转(+1→-1)：RankIC 全负(-0.047/-0.044/-0.056)，|ICIR| 0.30~0.43；"
               "筹码+资金双高分股未来5日跑输，突破多为假信号"),

    # ═══════════ EVO 预期差因子 (3) ═══════════
    FactorMeta("surprise_price_vote", +1, "预期差", "factor_values_evo",
               "价格投票偏离(偏离20日均价×量比排名)", "价格与量的预期差"),
    FactorMeta("surprise_earnings_gap", -1, "预期差", "factor_values_evo",
               "跳空缺口标记(0/1, >3%+量比>1.5)",
               "2026-09-03 三段IC审计翻转(+1→-1)：RankIC 全负(-0.040/-0.040/-0.039)，|ICIR| 0.64~0.68（最强）；"
               "跳空高开股未来5日显著跑输，A 股缺口回补效应占主导"),
    FactorMeta("surprise_roe_qoq", +1, "预期差", "factor_values_evo",
               "ROE环比Z-Score(120日滚动)", "盈利超预期"),

    # ═══════════ EVO 其他 (2) ═══════════
    FactorMeta("graham_score", +1, "防御", "factor_values_evo",
               "Graham 7项防御评分(0-7整数)", "Graham价值防御综合评分"),
    FactorMeta("text_sentiment_score", +1, "复合", "factor_values_evo",
               "文本情绪因子(规则打分)", "新闻/公告情绪因子，部分日期可能缺失"),
]


FACTOR_REGISTRY: Dict[str, FactorMeta] = {f.name: f for f in _FACTOR_LIST}


def get_factor(name: str) -> Optional[FactorMeta]:
    return FACTOR_REGISTRY.get(name)


def get_factors_by_table(table: str) -> List[FactorMeta]:
    return [f for f in _FACTOR_LIST if f.table == table]


def get_factors_by_category(category: str) -> List[FactorMeta]:
    return [f for f in _FACTOR_LIST if f.category == category]


def get_all_factor_names() -> List[str]:
    return [f.name for f in _FACTOR_LIST]


def get_classic_factor_names() -> List[str]:
    return [f.name for f in _FACTOR_LIST if f.table == "factor_values"]


def get_evo_factor_names() -> List[str]:
    return [f.name for f in _FACTOR_LIST if f.table == "factor_values_evo"]
