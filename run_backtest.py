# -*- coding: utf-8 -*-
"""
run_backtest.py —— 回测系统主入口与数据探索脚本 (修正版)
================================================
修正版功能包括：
1. 从中性化因子数据中自动导入并读取因子统计 (market_data.db)。
2. 加载由 stock_data.db 计算的“全市场等权指数”及每日“上涨家数占比”。
3. 调用增强版分类器（包含上涨家数占比一票否决 Dark 条件）进行日度状态标记。
4. 进行周度重采样并向后平移一周 (shift(1))，以消除未来函数。
5. 导出 market_regime_labels.csv (包含平移后的 regime 及 ret_20d, vol_20d, drawdown_5d 特征)。
6. 绘制无乱码豆腐块的全市场等权指数背景彩色走势图 (使用日度实时分类状态)。
"""

import os
import shutil
import pandas as pd
import numpy as np
import matplotlib
# 设置无 GUI 的 backend
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from src.data_loader import load_config, init_factor_db, load_neutral_factors, load_benchmark_data
from src.regime_detector import classify_market, resample_to_weekly

# 配置中文字体，防止保存的图表出现豆腐块/乱码
plt.rcParams["font.sans-serif"] = ["Heiti TC", "PingFang HK", "STHeiti", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

def plot_market_regime(df_daily, save_path):
    """
    绘制全市场等权指数价格走势图，背景用不同颜色标识日度实时分类的市场状态：
    - 牛市 (Bull)：淡薄荷绿
    - 熊市 (Bear)：淡绯红
    - 震荡 (Range)：淡灰
    - 黑市/空仓 (Dark)：淡黑色/暗灰色
    """
    df = df_daily.copy()
    df["dt"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values("dt").reset_index(drop=True)
    
    # 定义漂亮的色彩体系 (极客/专业风)
    colors = {
        "Bull": "#e2f0d9",    # 淡薄荷绿
        "Bear": "#f8d7da",    # 淡绯红
        "Range": "#f1f3f5",   # 极浅灰色
        "Dark": "#d6d8db"     # 暗灰色（黑市空仓）
    }
    
    regime_labels = {
        "Bull": "牛市 (Bull)",
        "Bear": "熊市 (Bear)",
        "Range": "震荡 (Range)",
        "Dark": "黑市/空仓 (Dark)"
    }
    
    fig, ax = plt.subplots(figsize=(14, 7), dpi=200)
    
    # 绘制指数价格走势 (深石板灰，线宽 2)
    ax.plot(df["dt"], df["close"], color="#2c3e50", label="全市场等权指数 (Close)", linewidth=2.0)
    
    # 合并连续相同 regime 的区间，用于高效绘制背景颜色
    intervals = []
    if len(df) > 0:
        start_dt = df["dt"].iloc[0]
        current_regime = df["regime"].iloc[0]
        
        for i in range(1, len(df)):
            dt = df["dt"].iloc[i]
            reg = df["regime"].iloc[i]
            if reg != current_regime:
                intervals.append((start_dt, df["dt"].iloc[i-1], current_regime))
                start_dt = dt
                current_regime = reg
        intervals.append((start_dt, df["dt"].iloc[-1], current_regime))
    
    # 绘制背景填充色
    added_legends = set()
    for start, end, reg in intervals:
        if reg in colors and not pd.isna(reg):
            label = regime_labels[reg] if regime_labels[reg] not in added_legends else ""
            if label:
                added_legends.add(regime_labels[reg])
            ax.axvspan(start, end, color=colors[reg], alpha=0.7, edgecolor="none", label=label)
            
    # 图表美化
    ax.set_title("全市场等权指数自适应分类走势图 (修正版 - 引入上涨占比过滤)", fontsize=16, fontweight="bold", pad=15)
    ax.set_xlabel("交易日期", fontsize=12, labelpad=10)
    ax.set_ylabel("等权指数点数", fontsize=12, labelpad=10)
    
    # X 轴日期格式化
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))  # 每3个月显示一个刻度
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=45)
    
    # 网格线
    ax.grid(True, linestyle="--", alpha=0.3, color="#868e96")
    
    # 图例
    ax.legend(loc="upper left", frameon=True, facecolor="white", edgecolor="#dee2e6", fontsize=10)
    
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()
    print(f"📊 [Plot] 修正版可视化图表已成功保存至: {save_path}")

def main():
    print("=" * 60)
    print("🚀 开始执行市场状态自适应选股系统 (修正版 - Phase 1)")
    print("=" * 60)
    
    # 1. 加载配置
    config = load_config()
    db_cfg = config["database"]
    reg_cfg = config["regime_classifier"]
    
    print(f"ℹ️ [Main] 主日线数据库统一使用: {db_cfg['stock_data_db']}")
    print(f"ℹ️ [Main] 因子IC统计数据库统一使用: {db_cfg['market_data_db']}")
    
    # 2. 初始化因子IC库
    init_factor_db(db_cfg["market_data_db"], db_cfg["factor_ic_csv_source"])
    
    # 3. 加载全市场等权指数 (包含上涨占比 up_ratio)
    df_benchmark = load_benchmark_data(db_cfg["stock_data_db"], "equal_weight")
    
    # 4. 运行分类器，进行日度分类
    print("\nℹ️ [Main] 开始对日度市场行情进行增强分类（添加上涨占比 < 30% 过滤）...")
    df_daily = classify_market(df_benchmark)
    
    # 5. 过滤出 2020 年以后的行情数据 (与全历史对齐)
    df_daily_filtered = df_daily[df_daily["trade_date"] >= "20200101"].copy()
    
    # 6. 周度重采样，并执行平移一周 (shift(1)) 消除未来函数
    print("ℹ️ [Main] 开始重采样至周度并进行 shift(1) 平移标签...")
    df_weekly = resample_to_weekly(df_daily_filtered)
    
    # 7. 统计平移后的周度状态分布
    print("\n" + "=" * 50)
    print("📈 修正版周度平移状态 (用于预测) 分布统计:")
    print("=" * 50)
    total_weeks = len(df_weekly)
    counts = df_weekly["regime"].value_counts()
    
    for state in ["Bull", "Bear", "Range", "Dark"]:
        if state not in counts:
            counts[state] = 0
            
    order = ["Bull", "Range", "Bear", "Dark"]
    state_names = {
        "Bull": "牛市 (Bull)",
        "Range": "震荡 (Range)",
        "Bear": "熊市 (Bear)",
        "Dark": "黑市/空仓 (Dark)"
    }
    
    for state in order:
        count = counts[state]
        pct = (count / total_weeks) * 100 if total_weeks > 0 else 0.0
        print(f"  - {state_names[state]:<15} : {count:>3} 周 | 占比: {pct:>6.2f}%")
    print(f"  * 平移后有效总周数: {total_weeks} 周 (已剔除首周NaN记录)")
    print("=" * 50)
    
    # 8. 导出 market_regime_labels_v2.csv
    # 包含字段：trade_date, regime, ret_20d, vol_20d, drawdown_5d
    df_export = df_weekly[["trade_date", "regime", "return_20d", "vol_20d", "mdd_5d"]].copy()
    df_export = df_export.rename(columns={"return_20d": "ret_20d", "mdd_5d": "drawdown_5d"})
    
    local_csv_path = "market_regime_labels_v2.csv"
    df_export.to_csv(local_csv_path, index=False, encoding="utf-8-sig")
    print(f"📄 [CSV] 已导出预测标签表格至: {local_csv_path}")
    
    # 9. 复制到 artifacts 目录
    artifacts_dir = "/Users/lyu/.gemini/antigravity-ide/brain/d3f0a68a-e0fc-4c46-a86d-237ba92450bc"
    if os.path.exists(artifacts_dir):
        # 复制 CSV
        try:
            shutil.copy(local_csv_path, os.path.join(artifacts_dir, local_csv_path))
            print(f"📄 [CSV] 预测标签表格已同步复制到 Artifacts 目录。")
        except PermissionError:
            print(f"⚠️ [CSV] 无权限复制到 Artifacts 目录，跳过。")
        
    # 10. 绘制可视化走势图
    # 走势图使用日度无平移状态作为背景，可以最直观展现价格波动和对应分类器的分类敏锐度
    local_plot_path = "market_regime_classification.png"
    plot_market_regime(df_daily_filtered, local_plot_path)
    
    if os.path.exists(artifacts_dir):
        # 复制图片
        try:
            shutil.copy(local_plot_path, os.path.join(artifacts_dir, local_plot_path))
            print(f"🖼️ [Main] 修正版可视化图已同步复制到 Artifacts 目录。")
        except PermissionError:
            print(f"⚠️ [Main] 无权限复制图片到 Artifacts 目录，跳过。")
        
    print("\n✅ [Main] 修正版 Phase 1 运行完毕！")
    print("=" * 60)

if __name__ == "__main__":
    main()
