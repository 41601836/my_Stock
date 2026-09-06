# 因子测试 & 收益验证模块

> 独立于股票推荐软件的因子回测系统，提供严谨的 IC 计算、分层测试、防过拟合校验和单因子回测。

## 一、架构

```
项目根/
├── factor_lib/               # 公共因子库 (核心包)
│   ├── __init__.py           # 包入口，导出全部公共接口
│   ├── registry.py           # 因子注册表 (46 个因子元数据)
│   ├── config.py             # 配置加载器 (热加载)
│   ├── loader.py             # 数据加载器 (唯一读写 stock_data.db 的出口)
│   ├── ic_engine.py          # IC 计算引擎 (Rank IC + Normal IC + 衰减 + 累积)
│   ├── stratified_tester.py # 分层测试引擎 (N 组分层 + 多空 + 单调性)
│   ├── backtester.py         # 单因子回测器 (Top-N 等权 + 绩效统计)
│   ├── anti_overfit.py       # 防过拟合校验 (5 项独立校验)
│   └── reporter.py           # HTML 报告生成器 (ECharts 图表)
├── factor_test/              # CLI 入口
│   ├── __init__.py
│   └── cli.py                # test / batch / compare 三种模式
├── config/
│   └── factor_test.yaml      # 独立配置文件
└── factor_test_reports/      # 报告输出目录
```

### 设计原则

1. **一套公共因子库，两套入口** — `factor_lib/` 是公共包，`factor_test/cli.py` 是独立入口，现有 `agent/` 系统不依赖它
2. **原始数据源唯一** — `factor_lib/loader.py` 是唯一直接读取 `stock_data.db` 的出口，保证口径一致
3. **零侵入** — `factor_lib/` 不 import 任何 `agent/` 或 `web/` 代码；删除 `factor_lib/` + `factor_test/` 后现有系统不受影响

## 二、快速开始

### 2.1 环境要求

- Python 3.11+
- 依赖: numpy, pandas, scipy, pyyaml
- 数据库: `stock_data.db` (含 `factor_values`, `factor_values_evo`, `daily_prices`, `stock_list`, `trade_cal` 表)

### 2.2 CLI 用法

#### 单因子测试

```bash
python factor_test/cli.py test volatility_20d
```

可选参数:
```bash
python factor_test/cli.py test volatility_20d \
  --start 20240101 \
  --end 20260630 \
  --n-perm 200 \
  --top-n 10 \
  --n-groups 5 \
  --cost-bps 15.0
```

输出: `factor_test_reports/volatility_20d_report.html`

#### 批量测试

```bash
python factor_test/cli.py batch volatility_20d,return_20d,pe_ttm,pb,roe
```

输出: 各因子 HTML 报告 + `factor_test_reports/comparison_report.html`

#### 多因子对比

```bash
python factor_test/cli.py compare volatility_20d,return_20d,pe_ttm,pb,roe
```

输出: 仅对比表 `factor_test_reports/comparison_report.html`

### 2.3 Python API

```python
from factor_lib import FactorDataLoader, ICEngine, StratifiedTester, FactorBacktester, AntiOverfitChecker, FactorReporter

# 1. 加载数据
loader = FactorDataLoader()
df = loader.load_factor_values(["volatility_20d"], "20240101", "20260630")
df = loader.compute_forward_returns(df, [5])

# 2. IC 分析
ic_engine = ICEngine()
ic_result = ic_engine.compute_full_report(df, "volatility_20d", "fwd_ret_5d")

# 3. 分层测试
strat = StratifiedTester(loader=loader)
strat_result = strat.run_stratified_test(df, "volatility_20d", n_groups=5)

# 4. 回测
bt = FactorBacktester(loader=loader)
bt_result = bt.run_backtest(df, "volatility_20d", top_n=10)

# 5. 防过拟合
checker = AntiOverfitChecker(ic_engine=ic_engine)
ao_result = checker.run_full_check(df, "volatility_20d", "fwd_ret_5d", n_perm=100)

# 6. 生成报告
reporter = FactorReporter()
html = reporter.generate_single_report(
    "volatility_20d", ic_result, strat_result, bt_result, ao_result,
    start_date="20240101", end_date="20260630"
)
```

## 三、API 参考

### 3.1 registry.py — 因子注册表

```python
from factor_lib.registry import FACTOR_REGISTRY, FactorMeta, get_factor, get_factors_by_table, get_factors_by_category
```

| 接口 | 说明 |
|---|---|
| `FACTOR_REGISTRY` | 字典: {因子名: FactorMeta} |
| `FactorMeta` | dataclass: name, table, column, direction(+1/-1), category, description |
| `get_factor(name)` | 获取单个因子元数据 |
| `get_factors_by_table(table)` | 按表筛选因子 |
| `get_factors_by_category(cat)` | 按分类筛选因子 |

### 3.2 config.py — 配置加载器

```python
from factor_lib.config import FactorTestConfig
```

| 方法 | 说明 | 默认值 |
|---|---|---|
| `db_path()` | 数据库路径 | 从 paths.yaml 读取 |
| `start_date()` | 测试起始日期 | 20240101 |
| `end_date()` | 测试结束日期 | 最新 |
| `min_cross_section_size()` | 最小截面股票数 | 100 |
| `top_n()` | Top-N 选股数 | 10 |
| `n_groups()` | 分层组数 | 5 |
| `bt_cost_bps()` | 单边交易成本(bp) | 15.0 |
| `bt_rebalance_freq()` | 回测调仓频率 | weekly |
| `n_permutations()` | 置换检验次数 | 200 |
| `report_dir()` | 报告输出目录 | factor_test_reports |

### 3.3 loader.py — 数据加载器

```python
from factor_lib.loader import FactorDataLoader
```

| 方法 | 说明 |
|---|---|
| `load_factor_values(factor_names, start, end)` | 加载因子值 (自动分表加载 + 合并) |
| `compute_forward_returns(df, periods)` | 计算未来 N 日收益率 |
| `get_weekly_rebalance_dates(start, end)` | 获取周调仓日列表 |
| `filter_st_stocks(df)` | 过滤 ST 股票 |
| `filter_new_stocks(df, days=60)` | 过滤次新股 |

### 3.4 ic_engine.py — IC 计算引擎

```python
from factor_lib.ic_engine import ICEngine
```

| 方法 | 说明 |
|---|---|
| `compute_ic_series(df, factor, ic_type, return_col)` | 计算 IC 时序 |
| `compute_ic_summary(ic_series)` | IC 统计摘要 (均值/标准差/ICIR/t/p/正比例) |
| `compute_ic_decay(df, factor, periods, return_col)` | IC 衰减曲线 (多周期) |
| `compute_ic_cumulative(ic_series)` | IC 累积曲线 |
| `compute_yearly_stability(ic_series)` | 分年度 IC 稳定性 |
| `compute_full_report(df, factor, return_col)` | 一次性输出全部 IC 指标 |

### 3.5 stratified_tester.py — 分层测试引擎

```python
from factor_lib.stratified_tester import StratifiedTester, StratifiedTestResult
```

| 方法 | 说明 |
|---|---|
| `run_stratified_test(df, factor, n_groups, return_col, rebalance_freq, cost_bps)` | 完整分层测试 |

返回 `StratifiedTestResult`:
- `group_nav`: 各组净值
- `group_returns`: 各组每期收益
- `long_short_nav`: 多空净值
- `long_short_returns`: 多空每期收益
- `monotonicity_score`: 单调性评分 (-1~1)
- `monotonicity_pvalue`: 单调性 p 值
- `avg_turnover`: 平均换手率

### 3.6 backtester.py — 单因子回测器

```python
from factor_lib.backtester import FactorBacktester, BacktestResult
```

| 方法 | 说明 |
|---|---|
| `run_backtest(df, factor, top_n, return_col, rebalance_freq, cost_bps, benchmark)` | Top-N 等权回测 |

返回 `BacktestResult`:
- `nav`: 组合净值 (起点=1.0)
- `returns`: 每期收益 (扣成本)
- `benchmark_nav`: 基准净值
- `performance`: 13 项绩效统计
- `yearly_returns`: 分年度收益
- `turnover`: 每期换手率
- `holdings`: 持仓明细

### 3.7 anti_overfit.py — 防过拟合校验

```python
from factor_lib.anti_overfit import AntiOverfitChecker
```

| 方法 | 说明 | 判定标准 |
|---|---|---|
| `check_in_sample_oos(df, factor, return_col, train_ratio)` | 样本内外对比 | ICIR 衰减 < 50% |
| `walk_forward(df, factor, return_col, train_days, test_days)` | Walk-Forward 滚动 | IC 正比例 ≥ 60% |
| `permutation_test(df, factor, return_col, n_perm)` | 置换检验 | p < 0.05 |
| `check_subperiod_stability(ic_series)` | 子周期稳定性 | 方向一致 ≥ 70% |
| `check_ic_autocorrelation(ic_series)` | IC 自相关 | |AC(1)| > 0.1 |
| `run_full_check(df, factor, return_col, n_perm)` | 全部 5 项校验 | — |

### 3.8 reporter.py — 报告生成器

```python
from factor_lib.reporter import FactorReporter
```

| 方法 | 说明 |
|---|---|
| `generate_single_report(factor_name, ic_result, stratified_result, backtest_result, anti_overfit_result, start_date, end_date)` | 单因子 HTML 报告 |
| `generate_comparison_report(factor_results)` | 多因子对比 HTML 报告 |

## 四、因子列表

### 经典因子 (factor_values 表, 31 个)

| 分类 | 因子 | 方向 | 说明 |
|---|---|---|---|
| 价值 | pe_ttm, pb, ps_ttm, dv_ratio, sp | 反向 | 低估值股票收益更高 |
| 成长 | revenue_growth, profit_growth, eps_growth | 正向 | 高增长股票收益更高 |
| 盈利 | roe, roa, gross_margin, net_margin | 正向 | 高盈利股票收益更高 |
| 动量 | return_20d, return_60d, return_120d | 正向 | 强势股延续 |
| 波动 | volatility_20d, volatility_60d, amplitude | 反向 | 低波动异象 |
| 流动 | turnover_rate, free_float_ratio | 反向 | 低流动性溢价 |
| 规模 | total_mv, circulation_mv | 反向 | 小盘股溢价 |
| 质量 | debt_ratio, current_ratio, quick_ratio | 反向 | 低杠杆更稳健 |
| 技术 | rsi_14, cci_14, wr_14, boll_percent | 混合 | 技术指标 |
| 换手 | turnover_20d, turnover_60d | 反向 | 低换手率溢价 |

### EVO 因子 (factor_values_evo 表, 15 个)

| 分类 | 因子 | 方向 | 说明 |
|---|---|---|---|
| 基本面 | eps_growth_evo, revenue_growth_evo, roe_evo | 正向 | EVO 增强基本面 |
| 技术面 | momentum_20d_evo, volatility_20d_evo | 混合 | EVO 增强技术面 |
| 资金面 | net_inflow_20d_evo, big_order_net_evo | 正向 | 主力资金净流入 |
| 风险 | beta_evo, drawdown_20d_evo | 反向 | 低风险溢价 |
| 综合 | alpha_evo, sharpe_evo, info_ratio_evo | 正向 | 风险调整后收益 |
| 超额 | excess_return_20d_evo, max_return_20d_evo | 正向 | 超额收益因子 |
| 量价 | volume_price_corr_evo | 反向 | 量价相关性 |

> **direction**: +1 表示因子值越大越好（选最高值），-1 表示越小越好（选最低值）

## 五、配置

配置文件: `config/factor_test.yaml`

```yaml
# 数据源
db_path: null  # null = 从 config/paths.yaml 读取 stock_data.db 路径

# 测试区间
start_date: "20240101"
end_date: null  # null = 最新

# IC 计算
ic_type: "rank"  # rank | normal
forward_return_days: [1, 3, 5, 10, 20]  # IC 衰减周期

# 分层测试
n_groups: 5
stratified_rebalance_freq: "weekly"
stratified_cost_bps: 15.0

# 回测
top_n: 10
bt_cost_bps: 15.0
bt_rebalance_freq: "weekly"
bt_benchmark: "equal_weight"

# 防过拟合
min_cross_section_size: 100
n_permutations: 200
significance_level: 0.05
train_ratio: 0.6
wf_train: 252
wf_test: 63
ic_positive_ratio: 0.6
yearly_consistency_ratio: 0.7

# 输出
report_dir: "factor_test_reports"
```

## 六、报告说明

### 单因子报告

- **IC 分析**: IC 时序图、IC 衰减柱状图、IC 累积曲线、统计摘要表、分年度稳定性表
- **分层测试**: 分组净值曲线、多空净值曲线、分组收益表（含单调性检验）
- **回测**: 组合 vs 基准净值曲线、13 项绩效表（年化/夏普/Sortino/回撤/卡玛/胜率/盈亏比）、分年度收益表
- **防过拟合**: 样本内外对比表、Walk-Forward 结果表、置换检验表+分布图、子周期稳定性表、IC 自相关表

### 多因子对比报告

按评级排序的横向对比表，包含:
- IC 均值 / ICIR / IC p 值
- 夏普 / 最大回撤 / 年化收益
- 单调性 p 值 / 置换检验 p 值 / 子周期一致率
- 综合评级 (★ ~ ★★★★★)

## 七、与现有系统的关系

| 维度 | 因子测试模块 | 股票推荐系统 |
|---|---|---|
| 代码位置 | `factor_lib/` + `factor_test/` | `agent/` + `web/` |
| 数据来源 | `stock_data.db` (通过 loader.py) | `stock_data.db` (直接访问) |
| 因子计算 | 独立计算 IC/分层/回测 | 绑定策略上下文 |
| 回测方式 | 纯因子排名 Top-N | 贝塔剥离/防御切换/误差回响 |
| 配置文件 | `config/factor_test.yaml` | `config/thresholds.yaml` |
| 日志目录 | `logs/factor_test/` | `logs/` |
| 互相依赖 | 无 | 无 |

> **一行回滚**: `rm -rf factor_lib/ factor_test/ config/factor_test.yaml` 后现有系统完全不受影响。
