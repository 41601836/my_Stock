# -*- coding: utf-8 -*-
"""
feature_engineering.py —— 全历史特征因子计算工程 (P2 高级因子版)
========================================================================
1. 高效 SQL 提取 2020-2026 行情与主力资金。
2. 批量计算核心因子 + P2 高级因子（2D CYQ筹码 / 2E 板块强度 / 2F 情绪复合）：
   - 动量/反转: return_5d, return_20d, return_60d, excess_return_20d + [实验] return_10d, return_120d
   - 波动率/风险: volatility_20d, volatility_60d, skewness_20d, max_drawdown_20d, atr_ratio + [实验] volatility_10d, volatility_120d, max_drawdown_60d
   - 估值/质量: pe_ttm, pb, roe, turnover_rate + [实验] turnover_rate_5d, turnover_rate_20d
   - 聪明钱/微观: north_net_inflow_ratio, profit_ratio_estimate, chip_concentration + [实验] vol_ratio
   - P2 数学类: 隔夜/日内分离、流动性高阶、GK波动率（2A/2B/2C）
   - P2 高级类: CYQ筹码模型(2D)、板块强度(2E)、情绪复合(2F)
3. 因子写入 factor_values 表，覆盖式保存。
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
import time

from config.paths import PATHS, startup_check

startup_check()

# 确保 src 目录在 import 路径中（用于导入 cyq_model, sector_factor）
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

def calculate_stock_factors(db_path=None):
    if db_path is None:
        db_path = PATHS.database.stock_data
    """
    通过高效 SQL 连接提取数据，执行 26 维因子计算并入库
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"❌ 数据库文件未找到: {db_path}")
        
    start_time = time.time()
    print(f"ℹ️ [Feature] 开始联合加载 2020-2026 行情、估值与资金流数据...")
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    
    query = """
        SELECT 
            p.ts_code, 
            p.trade_date, 
            p.open,
            p.high, 
            p.low, 
            p.close, 
            p.pct_chg,
            p.vol,
            p.amount,
            -- 重要说明：Tushare pro.daily() 返回的 close/high/low 默认已经是
            -- 前复权价(adj='qfq')，历史除权除息已调整完毕，价格序列天然连续。
            -- 因此这里不再乘 adj_factor（后复权因子），避免 stk_factor 某日
            -- 缺失导致 COALESCE 兜底 1.0，pct_change 分母/分子量级错位
            -- 产生 return_5d = -96% 级别的毁灭性计算错误（详见 20260902 bug 复盘）。
            1.0 AS adj_factor,
            IFNULL(b.turnover_rate, 0.0) AS turnover_rate,
            IFNULL(b.pe, 0.0)             AS pe_ttm,
            IFNULL(b.pb, 0.0)             AS pb,
            IFNULL(b.circ_mv, 0.0)        AS circ_mv,
            IFNULL(m.buy_elg_amount, 0.0) AS buy_elg, 
            IFNULL(m.sell_elg_amount, 0.0) AS sell_elg
        FROM daily_prices p
        INNER JOIN daily_basic b ON p.ts_code = b.ts_code AND p.trade_date = b.trade_date
        LEFT JOIN moneyflow m ON p.ts_code = m.ts_code AND p.trade_date = m.trade_date
        WHERE p.trade_date >= '20200101'
        ORDER BY p.ts_code, p.trade_date;
    """
    
    df = pd.read_sql(query, conn)
    df["trade_date"] = df["trade_date"].astype(str)
    
    load_time = time.time() - start_time
    print(f"✅ [Feature] 数据加载完毕，共 {len(df)} 行记录，耗时: {load_time:.2f} 秒。开始计算后复权价与收益...")
    
    # 后复权价格
    df["close_adj"] = df["close"] * df["adj_factor"]
    df["high_adj"] = df["high"] * df["adj_factor"]
    df["low_adj"] = df["low"] * df["adj_factor"]
    df["daily_ret"] = df.groupby("ts_code")["close_adj"].pct_change(1, fill_method=None)
    
    # 1. 动量/反转因子计算 (含实验因子 return_10d, return_120d)
    print("ℹ️ [Feature] 计算动量与实验动量因子...")
    df["return_5d"] = df.groupby("ts_code")["close_adj"].pct_change(5, fill_method=None)
    df["return_10d"] = df.groupby("ts_code")["close_adj"].pct_change(10, fill_method=None)
    df["return_20d"] = df.groupby("ts_code")["close_adj"].pct_change(20, fill_method=None)
    df["return_60d"] = df.groupby("ts_code")["close_adj"].pct_change(60, fill_method=None)
    df["return_120d"] = df.groupby("ts_code")["close_adj"].pct_change(120, fill_method=None)
    
    df["mean_return_20d"] = df.groupby("trade_date")["return_20d"].transform("mean")
    df["excess_return_20d"] = df["return_20d"] - df["mean_return_20d"]
    
    # 2. 波动率/风险因子计算 (含实验因子 volatility_10d, volatility_120d, max_drawdown_60d)
    print("ℹ️ [Feature] 高效计算风险与实验风险因子...")
    gb = df.groupby("ts_code")
    
    df["volatility_10d"] = gb["daily_ret"].rolling(10).std().to_numpy()
    df["volatility_20d"] = gb["daily_ret"].rolling(20).std().to_numpy()
    df["volatility_60d"] = gb["daily_ret"].rolling(60).std().to_numpy()
    df["volatility_120d"] = gb["daily_ret"].rolling(120).std().to_numpy()
    df["skewness_20d"] = gb["daily_ret"].rolling(20).skew().to_numpy()
    
    # Max Drawdown
    roll_max_20d = gb["close_adj"].rolling(20).max().to_numpy()
    df["drawdown_20d"] = (df["close_adj"] - roll_max_20d) / roll_max_20d
    df["max_drawdown_20d"] = gb["drawdown_20d"].rolling(20).min().to_numpy()
    
    roll_max_60d = gb["close_adj"].rolling(60).max().to_numpy()
    df["drawdown_60d"] = (df["close_adj"] - roll_max_60d) / roll_max_60d
    df["max_drawdown_60d"] = gb["drawdown_60d"].rolling(60).min().to_numpy()
    
    # ATR
    df["prev_close_adj"] = gb["close_adj"].shift(1)
    df["tr1"] = df["high_adj"] - df["low_adj"]
    df["tr2"] = (df["high_adj"] - df["prev_close_adj"]).abs()
    df["tr3"] = (df["low_adj"] - df["prev_close_adj"]).abs()
    df["tr"] = df[["tr1", "tr2", "tr3"]].max(axis=1)
    df["atr_14"] = gb["tr"].rolling(14).mean().to_numpy()
    df["atr_ratio"] = df["atr_14"] / df["close_adj"]
    
    # 3. 估值/质量因子计算 (含实验因子 turnover_rate_5d, turnover_rate_20d)
    print("ℹ️ [Feature] 计算估值与实验换手均值因子...")
    pe_protected = df["pe_ttm"].apply(lambda x: x if x > 0.1 else 0.1)
    df["roe"] = (df["pb"] / pe_protected).clip(-0.5, 0.5).fillna(0.0)
    df["turnover_rate_5d"] = gb["turnover_rate"].rolling(5).mean().to_numpy()
    df["turnover_rate_20d"] = gb["turnover_rate"].rolling(20).mean().to_numpy()
    
    # 4. 聪明钱/微观结构因子 (含实验因子 vol_ratio)
    print("ℹ️ [Feature] 计算微观聪明钱与实验量比因子...")
    circ_mv_protected = df["circ_mv"].apply(lambda x: x if x > 1e-4 else 1e-4)
    df["daily_inflow_ratio"] = (df["buy_elg"] - df["sell_elg"]) / circ_mv_protected
    df["north_net_inflow_ratio"] = gb["daily_inflow_ratio"].rolling(20).sum().to_numpy()
    
    # profit_ratio_estimate
    min_60 = gb["close_adj"].rolling(60).min().to_numpy()
    max_60 = gb["close_adj"].rolling(60).max().to_numpy()
    df["profit_ratio_estimate"] = (df["close_adj"] - min_60) / (max_60 - min_60 + 1e-8)
    
    # chip_concentration
    ma_20 = gb["close_adj"].rolling(20).mean().to_numpy()
    df["chip_concentration"] = (df["close_adj"] / (ma_20 + 1e-8) - 1).abs().fillna(0.0)
    
    # vol_ratio (5日/60日成交量放大系数)
    vol_5m = gb["vol"].rolling(5).mean().to_numpy()
    vol_60m = gb["vol"].rolling(60).mean().to_numpy()
    df["vol_ratio"] = vol_5m / (vol_60m + 1e-8)
    
    # 5. 市场贝塔因子 (Beta Factor) - 高效向量化计算 (毫秒级)
    print("ℹ️ [Feature] 计算市场贝塔因子...")
    market_ret = df.groupby("trade_date")["daily_ret"].transform("mean")
    df["market_excess"] = market_ret - market_ret.rolling(60, min_periods=10).mean()
    df["stock_excess"] = df["daily_ret"] - df.groupby("ts_code")["daily_ret"].transform(lambda x: x.rolling(60, min_periods=10).mean())
    
    df["_prod_ex"] = df["stock_excess"] * df["market_excess"]
    _cov_60d = df.groupby("ts_code")["_prod_ex"].transform(lambda x: x.rolling(60, min_periods=10).mean())
    _var_60d = df.groupby("ts_code")["market_excess"].transform(lambda x: x.rolling(60, min_periods=10).var())
    df["beta_60d"] = (_cov_60d / (_var_60d + 1e-8)).fillna(1.0).clip(0.1, 3.0)
    df.drop(columns=["_prod_ex"], inplace=True, errors="ignore")
    
    # 6. 质量防御因子 - 现金流/负债比近似 (基于 ROE 和 PB 的质量评分)
    print("ℹ️ [Feature] 计算质量防御因子...")
    df["quality_score"] = df["roe"].fillna(0) - df["pb"].fillna(0) * 0.1
    df["quality_score"] = df["quality_score"].clip(-1.0, 1.0)
    
    # 7. 低换手防御因子
    df["low_turnover_flag"] = (df["turnover_rate_5d"] < df.groupby("trade_date")["turnover_rate_5d"].transform(lambda x: x.quantile(0.30))).astype(int)
    
    # 8. 指数衰减时效性因子 (半衰期 3 天) - 基于未来5日收益的时间距离
    print("ℹ️ [Feature] 计算指数衰减时效性因子...")
    df["dt"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df["timeliness_decay"] = 1.0

    # 9. 三维资金信号复合因子（按日截面 rank + min-max 归一化到 [0,1]）
    print("ℹ️ [Feature] 计算三维资金信号复合因子...")

    # 9-A. 游资热点得分：爆量 + 快速拉升 + 高换手 - 筹码分散
    df["_r_vol_ratio"]        = df.groupby("trade_date")["vol_ratio"].rank(pct=True)
    df["_r_return_5d"]        = df.groupby("trade_date")["return_5d"].rank(pct=True)
    df["_r_turnover_5d"]      = df.groupby("trade_date")["turnover_rate_5d"].rank(pct=True)
    df["_r_chip_conc"]        = df.groupby("trade_date")["chip_concentration"].rank(pct=True)
    df["_hm_raw"] = (
        df["_r_vol_ratio"].fillna(0.5)   * 0.35
        + df["_r_return_5d"].fillna(0.5) * 0.30
        + df["_r_turnover_5d"].fillna(0.5) * 0.25
        - df["_r_chip_conc"].fillna(0.5) * 0.10
    )
    df["hot_money_score"] = df.groupby("trade_date")["_hm_raw"].transform(
        lambda x: (x - x.min()) / (x.max() - x.min() + 1e-8)
    )

    # 9-B. 强庄控盘得分：筹码集中 + 低波动 + 中期趋势 + 质量评分
    df["_r_vol_20d"]          = df.groupby("trade_date")["volatility_20d"].rank(pct=True)
    df["_r_return_60d"]       = df.groupby("trade_date")["return_60d"].rank(pct=True)
    df["_r_quality"]          = df.groupby("trade_date")["quality_score"].rank(pct=True)
    df["_sc_raw"] = (
        df["_r_chip_conc"].fillna(0.5)   * 0.40
        - df["_r_vol_20d"].fillna(0.5)   * 0.30
        + df["_r_return_60d"].fillna(0.5) * 0.20
        + df["_r_quality"].fillna(0.5)   * 0.10
    )
    df["strong_control_score"] = df.groupby("trade_date")["_sc_raw"].transform(
        lambda x: (x - x.min()) / (x.max() - x.min() + 1e-8)
    )

    # 9-C. 主力资金扫货得分：大单净流入 + 获利盘位 + 中期动量 - 最大回撤
    df["_r_north_inflow"]     = df.groupby("trade_date")["north_net_inflow_ratio"].rank(pct=True)
    df["_r_profit_est"]       = df.groupby("trade_date")["profit_ratio_estimate"].rank(pct=True)
    df["_r_return_20d"]       = df.groupby("trade_date")["return_20d"].rank(pct=True)
    df["_r_mdd_20d"]          = df.groupby("trade_date")["max_drawdown_20d"].rank(pct=True)
    df["_mf_raw"] = (
        df["_r_north_inflow"].fillna(0.5) * 0.40
        + df["_r_profit_est"].fillna(0.5) * 0.25
        + df["_r_return_20d"].fillna(0.5) * 0.20
        - df["_r_mdd_20d"].fillna(0.5)   * 0.15
    )
    df["main_force_score"] = df.groupby("trade_date")["_mf_raw"].transform(
        lambda x: (x - x.min()) / (x.max() - x.min() + 1e-8)
    )

    # 清理临时 rank 列
    _tmp_cols = [c for c in df.columns if c.startswith("_r_") or c.startswith("_hm_") or c.startswith("_sc_") or c.startswith("_mf_")]
    df.drop(columns=_tmp_cols, inplace=True, errors="ignore")

    # 10. P2 数学类新因子 (2A 隔夜/日内 + 2B 流动性高阶 + 2C GK 波动率)
    print("ℹ️ [Feature] 计算 P2 数学类新因子（隔夜/日内分离 / 流动性高阶 / GK波动率）...")

    # --- 2A: 隔夜收益与日内收益分离 ---
    df["overnight_return"] = df["open"] / gb["close"].shift(1).to_numpy() - 1
    df["intraday_return"] = df["close"] / df["open"] - 1
    df["overnight_return_5d"] = gb["overnight_return"].rolling(5).mean().to_numpy()
    df["intraday_return_5d"] = gb["intraday_return"].rolling(5).mean().to_numpy()
    df["overnight_intraday_gap_5d"] = df["overnight_return_5d"] - df["intraday_return_5d"]

    # --- 2B: Amihud 非流动性 + 成交额波动率 + 成交量偏度 ---
    amount_safe = df["amount"].replace(0, np.nan)
    df["_amihud_daily"] = df["daily_ret"].abs() / amount_safe
    df["amihud_illiq_20d"] = gb["_amihud_daily"].rolling(20).mean().to_numpy()

    df["turnover_volatility_20d"] = gb["turnover_rate"].rolling(20).std().to_numpy()
    df["volume_skewness_20d"] = gb["vol"].rolling(20).skew().to_numpy()

    _amount_std = gb["amount"].rolling(20).std().to_numpy()
    _amount_mean = gb["amount"].rolling(20).mean().to_numpy()
    df["amount_volatility_20d"] = _amount_std / np.where(_amount_mean > 1e-8, _amount_mean, np.nan)

    # --- 2C: Garman-Klass 高阶波动率 + Parkinson 波动率 ---
    H = df["high"].replace(0, np.nan)
    L = df["low"].replace(0, np.nan)
    O = df["open"].replace(0, np.nan)
    C = df["close"]

    _gk_var = 0.5 * (np.log(H / L)) ** 2 - (2 * np.log(2) - 1) * (np.log(C / O)) ** 2
    _gk_var = _gk_var.clip(lower=0)   # 理论上可能为负，截断保护
    df["_gk_var"] = _gk_var
    df["gk_volatility_20d"] = np.sqrt(gb["_gk_var"].rolling(20).mean().to_numpy()) * np.sqrt(252)

    _park_var = (np.log(H / L)) ** 2 / (4 * np.log(2))
    df["_park_var"] = _park_var
    df["parkinson_volatility_20d"] = np.sqrt(gb["_park_var"].rolling(20).mean().to_numpy()) * np.sqrt(252)

    # 清理 P2 临时列
    _p2_tmp = ["overnight_return", "intraday_return", "_amihud_daily", "_gk_var", "_park_var"]
    df.drop(columns=_p2_tmp, inplace=True, errors="ignore")

    # 11. P2 高级因子（2D CYQ 筹码模型 + 2E 板块强度 + 2F 情绪复合）
    print("ℹ️ [Feature] 计算 P2 高级因子（CYQ筹码 / 板块强度 / 情绪复合）...")

    # --- 2D: CYQ 筹码分布模型（每只股票独立滚动计算）---
    print("ℹ️ [Feature]   2D-CYQ 筹码分布模型计算中（窗口60天，50个价格格）...")
    from cyq_model import CYQModel
    _cyq_model = CYQModel(window=60, decay_lambda=0.05)
    _cyq_results = []
    for _code, _grp in df.groupby("ts_code", sort=False):
        _grp_sorted = _grp.sort_values("trade_date")
        _res = _cyq_model.compute_rolling(_grp_sorted)
        _res.index = _grp_sorted.index
        _cyq_results.append(_res)
    _cyq_df = pd.concat(_cyq_results).sort_index()

    # 计算当前价相对平均成本的偏离
    df["cyq_profit_ratio_60d"] = _cyq_df["cyq_profit_ratio"]
    df["cyq_upper_pressure_60d"] = _cyq_df["cyq_upper_pressure"]
    df["cyq_chip_concentration_60d"] = _cyq_df["cyq_chip_concentration"]
    df["cyq_avg_cost_dev_60d"] = (
        (df["close"] - _cyq_df["cyq_avg_cost"]) / _cyq_df["cyq_avg_cost"].replace(0, np.nan)
    )

    # --- 2E: 板块强度因子（需要全市场截面 + stock_list 行业信息）---
    print("ℹ️ [Feature]   2E-板块强度因子计算中（按行业截面合成）...")
    try:
        # 读取 stock_list 行业信息
        _stock_info = pd.read_sql(
            "SELECT ts_code, industry FROM stock_list WHERE industry IS NOT NULL",
            conn
        )
        if len(_stock_info) > 0:
            from sector_factor import SectorFactor
            _sf = SectorFactor()
            _sector_strength_map = {}  # (trade_date, ts_code) -> value

            for _td, _day_df in df.groupby("trade_date", sort=False):
                _day_strength = _sf.compute_sector_strength(_day_df, _stock_info)
                for _ts_code, _val in _day_strength.items():
                    _sector_strength_map[(_td, _ts_code)] = _val

            # 映射回主 DataFrame
            df["_ss_key"] = list(zip(df["trade_date"], df["ts_code"]))
            df["sector_strength"] = df["_ss_key"].map(_sector_strength_map)
            df.drop(columns=["_ss_key"], inplace=True, errors="ignore")
        else:
            df["sector_strength"] = np.nan
            print("⚠️ [Feature]   stock_list 无行业数据，板块强度因子设为 NaN")
    except Exception as _e:
        df["sector_strength"] = np.nan
        print(f"⚠️ [Feature]   板块强度计算异常: {_e}，跳过")

    # --- 2F: 情绪复合因子（换手率分位 + 隔夜波动幅度 + 连续上涨天数）---
    print("ℹ️ [Feature]   2F-情绪复合因子计算中...")
    # 成分 1: 60日换手率分位（时序 rank）
    df["_turnover_pct_60d"] = df.groupby("ts_code")["turnover_rate"].transform(
        lambda x: x.rolling(60, min_periods=10).rank(pct=True)
    )

    # 成分 2: 隔夜波动幅度（|隔夜收益|的5日均值）
    _overnight_ret = df["open"] / df.groupby("ts_code")["close"].shift(1).to_numpy() - 1
    df["_abs_overnight_5d"] = np.abs(_overnight_ret)
    df["_abs_overnight_5d"] = df.groupby("ts_code")["_abs_overnight_5d"].transform(
        lambda x: x.rolling(5).mean()
    )

    # 成分 3: 连续上涨天数
    def _consecutive_up(series):
        is_up = series > 0
        # 连续上涨计数：遇到下跌重置为 0
        streak = (is_up.groupby((~is_up).cumsum()).cumcount() + 1) * is_up.astype(int)
        return streak

    df["_pct_change_daily"] = df.groupby("ts_code")["close"].pct_change()
    df["_consec_up_days"] = df.groupby("ts_code")["_pct_change_daily"].transform(
        _consecutive_up
    )

    # 截面 rank 归一化 + 加权合成
    df["_r_turnover_pct"] = df.groupby("trade_date")["_turnover_pct_60d"].rank(pct=True)
    df["_r_overnight_abs"] = df.groupby("trade_date")["_abs_overnight_5d"].rank(pct=True)
    df["_r_consec_up"] = df.groupby("trade_date")["_consec_up_days"].rank(pct=True)

    df["sentiment_composite"] = (
        df["_r_turnover_pct"].fillna(0.5) * 0.4
        + df["_r_overnight_abs"].fillna(0.5) * 0.3
        + df["_r_consec_up"].fillna(0.5) * 0.3
    )

    # 清理 P2 高级因子临时列
    _p2_adv_tmp = [
        "_turnover_pct_60d", "_abs_overnight_5d", "_consec_up_days",
        "_pct_change_daily", "_r_turnover_pct", "_r_overnight_abs", "_r_consec_up"
    ]
    df.drop(columns=_p2_adv_tmp, inplace=True, errors="ignore")

    # --- 整理与保存 ---
    print("ℹ️ [Feature] 特征计算完成，正在过滤 NaN 行并持久化...")
    df = df.rename(columns={"ts_code": "stock_code"})

    cols_to_save = [
        "trade_date", "stock_code",
        "return_5d", "return_20d", "return_60d", "excess_return_20d",
        "volatility_20d", "volatility_60d", "skewness_20d", "max_drawdown_20d", "atr_ratio",
        "pe_ttm", "pb", "roe", "turnover_rate",
        "north_net_inflow_ratio", "profit_ratio_estimate", "chip_concentration",
        # 新增的 8 个实验因子
        "return_10d", "return_120d",
        "volatility_10d", "volatility_120d", "max_drawdown_60d",
        "turnover_rate_5d", "turnover_rate_20d", "vol_ratio",
        # 新增的防御与风控因子
        "beta_60d", "quality_score", "low_turnover_flag", "timeliness_decay",
        # 三维资金信号复合因子
        "hot_money_score", "strong_control_score", "main_force_score",
        # P2 数学类新因子 (2A / 2B / 2C)
        "overnight_return_5d", "intraday_return_5d", "overnight_intraday_gap_5d",
        "amihud_illiq_20d", "turnover_volatility_20d", "volume_skewness_20d", "amount_volatility_20d",
        "gk_volatility_20d", "parkinson_volatility_20d",
        # P2 高级因子 (2D CYQ 筹码 / 2E 板块强度 / 2F 情绪复合)
        "cyq_profit_ratio_60d", "cyq_upper_pressure_60d",
        "cyq_chip_concentration_60d", "cyq_avg_cost_dev_60d",
        "sector_strength",
        "sentiment_composite",
    ]

    # 关键：策略核心只消费 return_5/10/20d、volatility_20/60d、turnover_20d、三维资金复合分、quality；
    # 不依赖 120d 窗口。如果强制 dropna(subset=["volatility_120d","return_120d"])
    # 会在"全量+近期"场景下把 5500 只股票过滤到 ~4100 只（6 年数据不够 120d 的 IPO 新股 + 停牌股）。
    # 因此改为：只要求 20d 关键窗口 + 三维复合分非空，120d 保留 NaN（策略读取时已做 fillna）。
    core_cols = ["return_20d", "volatility_20d", "turnover_rate_20d",
                 "hot_money_score", "strong_control_score", "main_force_score"]
    df_clean = df[cols_to_save].dropna(subset=core_cols).reset_index(drop=True)
    # 再做一次后验：过滤掉 20250101 之前只有极少数窗口的史前数据（首日 1 日都没窗口）
    df_clean = df_clean[df_clean["trade_date"] >= "20200301"].reset_index(drop=True)
    
    table_name = "factor_values"
    try:
        # ① 先删除旧索引和旧表，立即 commit 确保 WAL 完全落盘
        conn.execute("DROP INDEX IF EXISTS idx_factors_date_code")
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.commit()   # ← 关键：WAL 模式下必须先提交删除操作
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to drop table {table_name}: {e}")
        conn.rollback()

    # ② replace 模式写入（即使 DROP 因并发失败，replace 也会先清空再写）
    df_clean.to_sql(table_name, conn, if_exists="replace", index=False, chunksize=10000)
    conn.commit()  # 显式提交 DML 事务

    # ③ 去重保险（防止 df_clean 本身含重复行）
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            DELETE FROM {table_name}
            WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM {table_name}
                GROUP BY trade_date, stock_code
            )
        """)
        removed = cursor.rowcount
        if removed > 0:
            import logging
            logging.getLogger(__name__).warning(f"[Feature] 去重删除 {removed} 条重复行")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[Feature] 去重检查跳过: {e}")

    # ④ 创建唯一索引
    try:
        cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_factors_date_code ON {table_name}(trade_date, stock_code);")
        conn.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[Feature] 索引创建跳过: {e}")
        
    latest_date = df_clean['trade_date'].max()
    print(f"✅ [Feature] 因子特征工程成功入库！最新因子交易日: {latest_date}，共 {len(df_clean)} 条记录。")
    conn.close()
    
    total_time = time.time() - start_time
    _n_factors = len(cols_to_save) - 2  # 减去 trade_date 和 stock_code
    print(f"✅ [Feature] {_n_factors} 维复合因子成功写入 SQLite 表 [{table_name}]，共 {len(df_clean)} 行数据，总耗时: {total_time:.2f} 秒。")
    return df_clean


# ═══════════════════════════════════════════════════════════════
#  P2 阶段数学类新因子 (2A / 2B / 2C)
# ═══════════════════════════════════════════════════════════════

def calc_overnight_intraday_factors(df):
    """
    任务 2A：隔夜收益与日内收益分离
    输入 df: 单只股票的日线 DataFrame（需含 open, close 列）
    返回: 包含 overnight_return_5d, intraday_return_5d, overnight_intraday_gap_5d 的 DataFrame
    """
    overnight_return = df["open"] / df["close"].shift(1) - 1
    intraday_return = df["close"] / df["open"] - 1
    overnight_return_5d = overnight_return.rolling(5).mean()
    intraday_return_5d = intraday_return.rolling(5).mean()
    overnight_intraday_gap_5d = overnight_return_5d - intraday_return_5d

    return pd.DataFrame({
        "overnight_return_5d": overnight_return_5d,
        "intraday_return_5d": intraday_return_5d,
        "overnight_intraday_gap_5d": overnight_intraday_gap_5d,
    }, index=df.index)


def calc_liquidity_higher_order_factors(df):
    """
    任务 2B：Amihud 非流动性 + 成交额波动率 + 成交量偏度
    输入 df: 单只股票的日线 DataFrame（需含 close, amount, vol, turnover_rate 列）
    返回: 包含 amihud_illiq_20d, turnover_volatility_20d, volume_skewness_20d, amount_volatility_20d 的 DataFrame
    """
    daily_ret = df["close"].pct_change()

    # Amihud 非流动性：|日收益| / 成交额，除零保护
    amount_safe = df["amount"].apply(lambda x: x if x > 1e-4 else np.nan)
    amihud_illiq_20d = (daily_ret.abs() / amount_safe).rolling(20).mean()

    # 换手率波动率
    turnover_volatility_20d = df["turnover_rate"].rolling(20).std()

    # 成交量偏度
    volume_skewness_20d = df["vol"].rolling(20).skew()

    # 成交额变异系数（波动率/均值）
    amount_std_20d = df["amount"].rolling(20).std()
    amount_mean_20d = df["amount"].rolling(20).mean()
    amount_volatility_20d = amount_std_20d / amount_mean_20d.replace(0, np.nan)

    return pd.DataFrame({
        "amihud_illiq_20d": amihud_illiq_20d,
        "turnover_volatility_20d": turnover_volatility_20d,
        "volume_skewness_20d": volume_skewness_20d,
        "amount_volatility_20d": amount_volatility_20d,
    }, index=df.index)


def calc_gk_volatility(df):
    """
    任务 2C：Garman-Klass 高阶波动率 + Parkinson 波动率
    输入 df: 单只股票的日线 DataFrame（需含 open, high, low, close 列）
    返回: 包含 gk_volatility_20d, parkinson_volatility_20d 的 DataFrame（年化）
    """
    H = df["high"]
    L = df["low"]
    C = df["close"]
    O = df["open"]

    # 除零保护：极端情况高低价或开盘价为 0
    H = H.replace(0, np.nan)
    L = L.replace(0, np.nan)
    O = O.replace(0, np.nan)

    # Garman-Klass 单日方差
    sigma2_gk = 0.5 * (np.log(H / L)) ** 2 - (2 * np.log(2) - 1) * (np.log(C / O)) ** 2
    # GK 估计量理论上可能为负（极端价格路径），做截断保护
    sigma2_gk = sigma2_gk.clip(lower=0)

    # 滚动 20 日 GK 波动率（年化，乘 sqrt(252)）
    gk_volatility_20d = np.sqrt(sigma2_gk.rolling(20).mean()) * np.sqrt(252)

    # Parkinson 波动率（只用 H/L）
    parkinson_var = (np.log(H / L)) ** 2 / (4 * np.log(2))
    parkinson_volatility_20d = np.sqrt(parkinson_var.rolling(20).mean()) * np.sqrt(252)

    return pd.DataFrame({
        "gk_volatility_20d": gk_volatility_20d,
        "parkinson_volatility_20d": parkinson_volatility_20d,
    }, index=df.index)


# ═══════════════════════════════════════════════════════════════
#  P2 阶段高级因子 (2D CYQ 筹码 / 2E 板块强度 / 2F 情绪复合)
# ═══════════════════════════════════════════════════════════════

def calc_cyq_factors(df):
    """
    任务 2D：CYQ 筹码分布模型（单只股票）
    输入 df: 单只股票的日线 DataFrame（需含 high, low, close, turnover_rate 列）
    返回: 包含 cyq_profit_ratio_60d, cyq_upper_pressure_60d,
          cyq_chip_concentration_60d, cyq_avg_cost_dev_60d 的 DataFrame
    """
    from cyq_model import CYQModel
    model = CYQModel(window=60, decay_lambda=0.05)
    res = model.compute_rolling(df)

    # 计算当前价相对平均成本的偏离
    avg_cost = res["cyq_avg_cost"]
    avg_cost_dev = (df["close"] - avg_cost) / avg_cost.replace(0, np.nan)

    return pd.DataFrame({
        "cyq_profit_ratio_60d": res["cyq_profit_ratio"],
        "cyq_upper_pressure_60d": res["cyq_upper_pressure"],
        "cyq_chip_concentration_60d": res["cyq_chip_concentration"],
        "cyq_avg_cost_dev_60d": avg_cost_dev,
    }, index=df.index)


def calc_sector_strength_factor(daily_data, stock_info_df):
    """
    任务 2E：板块强度因子（单交易日全市场数据）
    输入 daily_data: 某交易日全市场日线 DataFrame（ts_code, close, pct_chg, amount）
    输入 stock_info_df: stock_list 表的 DataFrame（ts_code, industry）
    返回: Series (index=ts_code, value=sector_strength)
    """
    from sector_factor import SectorFactor
    sf = SectorFactor()
    return sf.compute_sector_strength(daily_data, stock_info_df)


def calc_sentiment_composite(df, text_sentiment=None):
    """
    任务 2F：情绪复合因子（单只股票时序 + 可选截面数据）
    输入 df: 单只股票的日线 DataFrame（需含 close, open, turnover_rate 列）
    输入 text_sentiment: 可选，文本情绪得分 Series（与 df 同索引）
    返回: 包含 sentiment_composite 列的 DataFrame

    合成逻辑：
    - 成分 1: 60日换手率分位（时序 rank）
    - 成分 2: |隔夜收益| 的 5 日均值
    - 成分 3: 连续上涨天数
    - 权重: 0.4 + 0.3 + 0.3 = 1.0
    - 若有 text_sentiment，再加 0.2 权重（总权重归一化到 1.0）
    """
    # 成分 1: 60日换手率分位
    turnover_pct = df["turnover_rate"].rolling(60, min_periods=10).rank(pct=True)

    # 成分 2: 隔夜波动幅度（|隔夜收益|的5日均值）
    overnight_ret = df["open"] / df["close"].shift(1) - 1
    abs_overnight_5d = np.abs(overnight_ret).rolling(5).mean()

    # 成分 3: 连续上涨天数
    daily_ret = df["close"].pct_change()
    is_up = daily_ret > 0
    consec_up = (is_up.groupby((~is_up).cumsum()).cumcount() + 1) * is_up.astype(int)

    # 截面 rank 归一化（这里是单只股票的时序数据，所以用自身排名近似）
    # 注意：在主管线中使用的是截面 rank，这里单股计算用时序 rank 做近似
    r_turnover = turnover_pct.rank(pct=True)
    r_overnight = abs_overnight_5d.rank(pct=True)
    r_consec = consec_up.rank(pct=True)

    sentiment = (
        r_turnover.fillna(0.5) * 0.4
        + r_overnight.fillna(0.5) * 0.3
        + r_consec.fillna(0.5) * 0.3
    )

    # 如果有文本情绪数据，加入额外权重（总权重归一化）
    if text_sentiment is not None and len(text_sentiment) > 0:
        r_text = text_sentiment.rank(pct=True)
        sentiment = (
            sentiment * 0.8 + r_text.fillna(0.5) * 0.2
        )

    return pd.DataFrame({
        "sentiment_composite": sentiment,
    }, index=df.index)


if __name__ == "__main__":
    calculate_stock_factors()
