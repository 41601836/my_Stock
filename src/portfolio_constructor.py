# -*- coding: utf-8 -*-
"""
portfolio_constructor.py —— 投资组合构建模块 (修正版)
========================================
规范投资组合构建规则：
1. 每日/每周输出 3-5 只股票。
2. 投资组合为等权配置，且单只股票仓位不超过 30%。
3. 预设换手率惩罚限制 (max_turnover=0.5)。
"""

import pandas as pd
import numpy as np

def construct_portfolio(df_signals, max_turnover=0.5):
    """
    根据输入选股信号，构建等权配置的投资组合，并加入调仓换手率惩罚限制。
    
    参数:
    - df_signals: pd.DataFrame, 包含候选个股信号与得分数据
    - max_turnover: float, 单次换手率限制，默认 0.5 (50% 换手惩罚)
    
    返回:
    - df_portfolio: pd.DataFrame, 包含选中的 3-5 只股票代码、等权比例及仓位信息
    """
    # TODO: 在 Phase 3 中实现基于具体因子得分的过滤和多周滚动等权持仓分配逻辑
    print(f"ℹ️ [Portfolio] 收到 {len(df_signals)} 条信号，当前最大换手率约束: {max_turnover * 100:.1f}%")
    return pd.DataFrame()
