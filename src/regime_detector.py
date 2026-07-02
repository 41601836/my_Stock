# -*- coding: utf-8 -*-
"""
regime_detector.py —— 市场状态分类器模块 (周度绩效监测增强版)
========================================
实现 `classify_market(df_benchmark)` 函数。
基于全市场等权指数，计算 20 日收益率、20 日滚动波动率、5 日最大回撤。
增加“当日上涨家数占比 < 30%”作为黑市（Dark）一票否决的优先触发条件。
增加周度绩效监测：当周度收益率 < -4.5% 时强制触发 Dark 状态。
支持在重采样至周度后，将状态及指标向后平移一周 (shift(1))，以消除未来函数。
"""

import pandas as pd
import numpy as np

def calculate_indicators(df_benchmark):
    """
    计算分类所需指标：
    1. return_20d: 过去 20 日收益率
    2. vol_20d: 20 日滚动波动率 (基于日百分比收益率 pct_chg 的 rolling std)
    3. mdd_5d: 过去 5 日的最大回撤 (当前收盘价相对于 5 日最高价的回撤，并在 5 日内取最小值)
    4. up_ratio: 全市场上涨家数占比 (输入中已包含)
    """
    df = df_benchmark.copy()
    df = df.sort_values("trade_date").reset_index(drop=True)
    
    # 1. 20 日收益率
    df["return_20d"] = df["close"].pct_change(20)
    
    # 2. 20 日滚动波动率
    df["vol_20d"] = df["pct_chg"].rolling(20).std()
    
    # 3. 过去 5 日最大回撤
    roll_max_5d = df["close"].rolling(5).max()
    drawdown = (df["close"] - roll_max_5d) / roll_max_5d
    df["mdd_5d"] = drawdown.rolling(5).min()
    
    return df

def classify_market(df_benchmark):
    """
    市场状态分类器主函数。
    输入：包含 trade_date, close, pct_chg, up_ratio 的 DataFrame
    """
    # 计算技术指标
    df = calculate_indicators(df_benchmark)
    
    # 计算周度收益率（过去5个交易日）
    df["return_5d_weekly"] = df["close"].pct_change(5)
    
    # 计算波动率历史中位数及 75% 分位数
    valid_vol = df["vol_20d"].dropna()
    if len(valid_vol) > 0:
        vol_50pct = valid_vol.quantile(0.50)
        vol_75pct = valid_vol.quantile(0.75)
    else:
        vol_50pct = 0.0
        vol_75pct = 0.0
        
    print(f"ℹ️ [Detector] 等权指数 20日波动率历史中位数 (50%分位数): {vol_50pct:.4f}%")
    print(f"ℹ️ [Detector] 等权指数 20日波动率历史 75%分位数: {vol_75pct:.4f}%")
    
    regimes = []
    dark_triggers = []
    for i in range(len(df)):
        mdd = df["mdd_5d"].iloc[i]
        vol = df["vol_20d"].iloc[i]
        ret = df["return_20d"].iloc[i]
        up_ratio = df["up_ratio"].iloc[i]
        weekly_ret = df["return_5d_weekly"].iloc[i]
        
        # 数据不足
        if pd.isna(mdd) or pd.isna(vol) or pd.isna(ret) or pd.isna(up_ratio):
            regimes.append(None)
            dark_triggers.append(None)
            continue
            
        trigger_reason = ""
        
        # 1. 优先触发 Dark 条件：周度绩效 < -4.5% 强制触发
        if weekly_ret < -0.045:
            regimes.append("Dark")
            trigger_reason = f"weekly_return_{weekly_ret:.2%}"
        # 2. 回撤大，或者波动率极高，或者当日上涨家数占比 < 30%
        elif mdd < -0.05 or vol > vol_75pct or up_ratio < 0.30:
            regimes.append("Dark")
            if mdd < -0.05:
                trigger_reason = f"mdd_{mdd:.2%}"
            elif vol > vol_75pct:
                trigger_reason = f"vol_{vol:.4f}>{vol_75pct:.4f}"
            else:
                trigger_reason = f"up_ratio_{up_ratio:.2f}"
        # 3. 判断牛市 (Bull)
        elif ret > 0.05 and vol < vol_50pct:
            regimes.append("Bull")
            trigger_reason = "bull"
        # 4. 判断熊市 (Bear)
        elif ret < -0.03 and vol > vol_50pct:
            regimes.append("Bear")
            trigger_reason = "bear"
        # 5. 震荡市 (Range)
        else:
            regimes.append("Range")
            trigger_reason = "range"
            
        dark_triggers.append(trigger_reason)
            
    df["regime"] = regimes
    df["dark_trigger_reason"] = dark_triggers
    df["vol_50pct"] = vol_50pct
    df["vol_75pct"] = vol_75pct
    
    return df

def resample_to_weekly(df_daily):
    """
    将日度状态重采样为周度数据，并执行平移一周 (shift(1))。
    这样：本周五对应的记录，其状态和指标都是上周五（即上周最后一个交易日）的值，消除未来函数。
    """
    df = df_daily.copy()
    df["dt"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    
    # 提取年份和 ISO 周
    df["year"] = df["dt"].dt.isocalendar().year
    df["week"] = df["dt"].dt.isocalendar().week
    
    # 取每周最后一个交易日
    weekly_idx = df.groupby(["year", "week"]).apply(lambda x: x.index[-1], include_groups=False).tolist()
    df_weekly = df.loc[weekly_idx].copy().reset_index(drop=True)
    df_weekly = df_weekly.drop(columns=["dt", "year", "week"])
    
    # 对预测状态标签及核心市场行情特征全部向后平移一周 (shift(1))
    # 确保本周的标签和输入特征不包含本周的任何未来信息
    df_weekly["regime"] = df_weekly["regime"].shift(1)
    df_weekly["return_20d"] = df_weekly["return_20d"].shift(1)
    df_weekly["vol_20d"] = df_weekly["vol_20d"].shift(1)
    df_weekly["mdd_5d"] = df_weekly["mdd_5d"].shift(1)
    
    # 剔除因为平移导致 regime 为 NaN 的首周数据
    df_weekly = df_weekly.dropna(subset=["regime"]).reset_index(drop=True)
    return df_weekly
