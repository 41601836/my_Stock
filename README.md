# 鞋底刺 向心刺 | 量化策略控制台 V1.0.0

🎉 **项目封顶纪念：极客风量化交易与多因子回测闭环系统**

## 项目架构核心

本项目是一个集“数据治理、因子挖掘、自动寻优、实盘可视化”于一体的高性能量化投研平台。它的主要架构包含：

1. **五维智能扫描引擎 (5-Factor Scanner)**
   - 融合动量、波动率、流动性等五大核心因子。
   - 提供基于板块/题材的精准过滤与评分排行。
   
2. **Win Rate Hunter 遗传进化系统**
   - 采用遗传算法自动回测历史数据，通过群体进化迭代。
   - 自动寻找“胜率最大化”与“卡玛比率最优化”的参数组合（如选股数量 `top_n` 与权重乘数 `multiplier`），并自适应更新系统配置。

3. **数据哨兵与异常熔断机制 (Data Governance)**
   - 每日定时巡检数据断层、停牌异常与涨跌幅不一致性。
   - 前端悬浮状态指示灯：一键查看系统健康度，自动触发策略熔断，防范“脏数据”导致资金被割。

4. **游资与市场情绪全景图 (Market Overview)**
   - 大资金流入流出实时跟踪，点击板块名称即可下钻查看带头吸金/砸盘的具体个股。
   - “90后Jack”游资路线图，精准还原游资大佬的历史操盘心法与资金变动轨迹。

5. **极客级炫酷控制台 (Cyberpunk Dashboard)**
   - 全响应式设计，完美适配 PC 与移动端。
   - 深度融合毛玻璃、霓虹呼吸灯、全动态图表等次世代 UI 设计语言。

## 快速启动指南

### 启动后端引擎 (FastAPI)
```bash
cd web/backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 启动前端控制台 (React + Vite)
```bash
cd web/frontend
npm run dev
```

### 手动触发胜率猎手 (Win Rate Hunter)
```bash
python3 win_rate_hunter.py --start 20250101 --end 20260715 --generations 5 --population 10
```

### 手动触发数据哨兵巡检
```bash
PYTHONPATH=. python3 scripts/data_health_check.py
```

---

> *"The market is a device for transferring money from the impatient to the patient."*
> 
> —— 献给每一位在代码与 K 线中寻找圣杯的宽客。

**V1.0.0 封顶大吉！** 🚀
