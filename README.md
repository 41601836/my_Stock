# 鞋底刺 向心刺 | 量化策略控制台 V1.0.0

🎉 **项目封顶纪念：极客风量化交易与多因子回测闭环系统**

> 策略引擎状态：**ONLINE** | 数据截止：**2026-08-31** | 当前市场状态：**Bear（熊市）**

---

## 项目架构核心

本项目是一个集**数据治理、因子挖掘、自动寻优、实盘可视化**于一体的高性能量化投研闭环平台。主要架构包含七大核心模块：

### 1. 五维智能扫描引擎 (5-Factor Scanner)
- 融合动量、波动率、流动性、估值、偏度五大维度核心因子
- 基于板块/题材的精准过滤与评分排行，支持 T+1 画像三层漏斗建仓

### 2. T+1 上涨画像分析系统 (Portrait Analysis)
- **多维上涨因子画像**：动量结构、筹码集中度、波动率健康度、流动性潮汐
- **三层漏斗建仓决策**：机会池 → 画像筛选 → 综合评分 / 风险预警
- 自动输出高置信度建仓清单与风险预警信号

### 3. Win Rate Hunter 遗传进化系统
- 采用遗传算法自动回测历史数据，通过群体进化迭代寻优
- 自动寻找**胜率最大化**与**卡玛比率最优化**的参数组合（如 `top_n` 选股数量、`multiplier` 权重乘数）
- 自适应更新系统配置，实现策略自我进化

### 4. 数据哨兵与异常熔断机制 (Data Governance)
- 每日定时巡检数据断层、停牌异常、涨跌幅不一致性
- 前端悬浮状态指示灯：一键查看系统健康度
- 自动触发策略熔断，防范"脏数据"导致资金被割

### 5. 游资与市场情绪全景图 (Market Overview)
- 大资金流入流出实时跟踪，点击板块名称下钻查看带头吸金/砸盘个股
- **"90后Jack"游资路线图**：还原游资大佬历史操盘心法与资金变动轨迹
- 筹码温度、赚钱效应、涨停情绪综合监控

### 6. 因子自适应权重监控 (Factor Adaptative Weights)
- 分市场状态（Range / Bull / Bear / Dark）独立部署因子权重模型
- Rank IC 负值自动翻转，确保信号方向统一
- 特权因子自动施加 1.5x multiplier 权重乘数放大 Alpha 暴露

### 7. 极客级炫酷控制台 (Cyberpunk Dashboard)
- 全响应式设计，完美适配 PC 与移动端
- 深度融合毛玻璃、霓虹呼吸灯、全动态图表等次世代 UI 设计语言
- 底部 Tab 导航 + 全局缩放控制器，移动端操作流畅

---

## 快速启动指南

### ⚡ 一键启动（推荐）
```bash
./start.sh
```
自动并行启动：
- 后端 API (FastAPI :8000)
- 前端控制台 (Vite :5173)
- cloudflared 穿网隧道（可选公网访问）

### 单独启动后端引擎 (FastAPI)
```bash
cd web/backend
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 单独启动前端控制台 (React + Vite)
```bash
cd web/frontend
npm install    # 首次运行安装依赖
npm run dev
```

### 手动触发胜率猎手 (Win Rate Hunter)
```bash
python3 win_rate_hunter.py --start 20250101 --end 20260715 --generations 5 --population 10
```

### 手动触发因子有效性扫描 (Agent Search)
```bash
python3 agent/run_agent.py --mode search
```

### 因子 IC/IR 全量有效性分析
```bash
PYTHONPATH=. python3 scripts/factor_ic_analysis.py
```

### 因子衰减率审计
```bash
PYTHONPATH=. python3 scripts/factor_decay_audit.py
```

### 手动触发数据哨兵巡检
```bash
PYTHONPATH=. python3 scripts/data_health_check.py
```

---

## 分支管理策略

| 分支 | 用途 | 合并条件 |
|------|------|----------|
| `main` / `release/v1.0.0` | 只读/生产分支 | **绝对禁止直接修改**，仅用于封版快照 |
| `develop` | 日常开发与优化分支 | 所有第 1-5 周任务均在此分支进行 |
| `feature/*` | 具体功能开发分支 | 每个新因子或 Bug 修复单独开分支，测试通过后合并到 develop |

> 💡 **V1.0.0 已封版归档于 `release/v1.0.0` 分支，包含 models/regime_weights.pkl、回测成绩单、配置文件等完整快照。**

---

## 因子池说明

### 核心因子 (5 个)
| 因子名 | 类型 | 说明 |
|--------|------|------|
| `turnover_rate` | 流动性 | 换手率，衡量交投活跃度 |
| `volatility_10d` | 波动率 | 10日收益率标准差，短期风险度量 |
| `volatility_60d` | 波动率 | 60日收益率标准差，中长期风险度量 |
| `pb` | 估值 | 市净率，衡量估值水平 |
| `skewness_20d` | 动量结构 | 20日收益偏度，捕捉不对称上涨机会 |

### 实验因子池 (24 个全量因子)
动量类：`return_5d` `return_10d` `return_20d` `return_60d` `return_120d` `excess_return_20d`

波动率类：`volatility_10d` `volatility_20d` `volatility_60d` `volatility_120d`

风险类：`skewness_20d` `max_drawdown_20d` `max_drawdown_60d` `atr_ratio`

估值/基本面：`pe_ttm` `pb` `roe`

流动性：`turnover_rate` `turnover_rate_5d` `turnover_rate_20d` `vol_ratio`

资金流/特殊：`north_net_inflow_ratio` `profit_ratio_estimate` `chip_concentration`

### 当前部署的模型权重

| 市场状态 | 因子与权重 |
|----------|------------|
| **Range 震荡市** | return_60d (-0.6161) · volatility_10d (+0.0191) · volatility_20d (-0.1497) · north_net_inflow_ratio (-0.1988) · volatility_60d (-0.0494) |
| **Bull 牛市** | volatility_60d (-0.6000) · volatility_20d (+0.1800) · turnover_rate (-0.2100) |
| **Bear / Dark 熊市** | 触发半仓避险模式，跳过个股打分，跟踪基准 |

---

## 目录结构

```
my_Stock/
├── agent/                  # Agent 寻优引擎、因子有效性验证、配置
│   ├── run_agent.py        # Agent 入口：search/simulation/hunter/decay
│   ├── validator.py        # 因子 IC 衰减检验
│   └── config.yaml         # 因子池、参数空间、特殊加成配置
├── archives/v1.0.0/        # V1.0.0 封版归档：权重、回测报告、配置
├── config/                 # 全局配置：路径管理、候选因子池
│   ├── paths.py            # 统一路径配置
│   └── candidate_factors.yaml  # 24个候选因子 + 核心/失效因子分类
├── db/                     # SQLite 数据库、健康巡检报告
├── logs/                   # Agent 日志、寻优结果、审计报告
├── models/                 # 已训练权重模型（regime_weights.pkl 等）
├── scripts/                # 工具脚本：IC分析、衰减审计、数据健康检查
├── src/                    # 核心算法：特征工程、数据管道
├── web/
│   ├── backend/            # FastAPI 后端：app.py / services.py / portrait_router.py
│   └── frontend/           # React + Vite 前端：Dashboard/Overview/Scanner/Diagnose...
├── start.sh                # 一键启动脚本
└── README.md               # 本文件
```

---

> *"The market is a device for transferring money from the impatient to the patient."*
> 
> —— 献给每一位在代码与 K 线中寻找圣杯的宽客。

**V1.0.0 封顶大吉！** 🚀
