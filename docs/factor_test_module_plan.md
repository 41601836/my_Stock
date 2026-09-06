# 因子测试 & 收益验证模块 — 完整实施计划

> 创建日期: 2026-09-02\
> 核心原则: 一套公共因子库，两套入口；原始数据源唯一，保证口径一致\
> 零侵入约束: 不修改现有 `src/feature_engineering.py`、`agent/`、`web/backend/` 任何代码

***

## 一、现状分析与差距

### 1.1 现有因子资产

| 层     | 因子表                 | 因子数 | 计算脚本                             | 入口                          |
| ----- | ------------------- | --- | -------------------------------- | --------------------------- |
| 经典层   | `factor_values`     | 26  | `src/feature_engineering.py`     | `agent/` 推荐系统               |
| EVO 层 | `factor_values_evo` | 14  | `src/feature_engineering_evo.py` | `web/backend/services/evo/` |

### 1.2 现有 IC/回测能力

| 能力    | 现有实现                            | 不足                                                                     |
| ----- | ------------------------------- | ---------------------------------------------------------------------- |
| IC 计算 | `scripts/factor_ic_analysis.py` | 仅 Rank IC + IR，无 Normal IC、IC 衰减曲线、IC 累积图                              |
| IC 衰减 | `agent/validator.py`            | 仅基准期 vs 近 52 周二分法，无多周期 IC 衰减                                           |
| 动态权重  | `src/evo_dynamic_weights.py`    | 滚动 IC/ICIR，但仅服务 EVO 组合，非独立测试                                           |
| 回测    | `agent/backtester.py`           | 与 agent 系统**强耦合**（贝塔剥离、防御切换、误差回响），无法独立测单因子                             |
| 分层测试  | 无                               | 完全缺失                                                                   |
| 多空净值  | 无                               | 完全缺失                                                                   |
| 防过拟合  | 无                               | 无 Walk-Forward、无样本外检验、无置换检验                                            |
| 公共因子库 | 无                               | 因子定义散落在 `feature_engineering.py` 和 `feature_engineering_evo.py` 中，无独立包 |

### 1.3 核心差距

```
缺口1: 无公共因子库包 — 因子定义、元数据（方向/描述/分类）散落，两套系统各自硬编码
缺口2: 无独立回测 — backtester.py 绑定 agent 策略路由，无法剥离测单因子
缺口3: 无分层测试 — 缺少量化投资标准的 N 分组收益/IC 分析
缺口4: 无多空净值 — 缺失做多 Top 分位、做空 Bottom 分位的净值曲线
缺口5: 无防过拟合 — 缺少 Walk-Forward、样本外、置换检验、IC 子周期稳定性
缺口6: 数据口径不统一 — IC 脚本、validator、EVO 各自写 SQL 加载，口径可能不一致
```

***

## 二、架构设计

### 2.1 总体架构

```
┌──────────────────────────────────────────────────────────┐
│                   stock_data.db (唯一数据源)              │
│  daily_prices │ daily_basic │ moneyflow │ factor_values  │
│  factor_values_evo │ stock_list │ trade_cal               │
└──────────────────────┬───────────────────────────────────┘
                       │
          ┌────────────┴───────────┐
          │   factor_lib (公共包)   │
          │                        │
          │  loader.py  (唯一出口)  │ ← 所有数据读取统一入口
          │  registry.py (因子注册) │ ← 因子元数据（名称/方向/分类/描述）
          │  ic_engine.py           │ ← IC/IR/衰减/累积
          │  stratified_tester.py   │ ← N 分组分层测试
          │  backtester.py          │ ← 单因子独立回测
          │  anti_overfit.py        │ ← Walk-Forward/样本外/置换
          │  report.py             │ ← HTML 报告
          │  config.py             │ ← 配置加载
          └───────────┬────────────┘
                      │
         ┌────────────┴────────────┐
         │                         │
    ┌────┴─────┐           ┌──────┴───────┐
    │ 入口一   │           │  入口二      │
    │ agent/   │           │ factor_test/ │
    │ 推荐系统 │           │ 因子测试模块 │
    │(现有不变)│           │  (新建独立)  │
    └──────────┘           └──────────────┘
```

### 2.2 设计原则

1. **数据源唯一**: `factor_lib/loader.py` 是唯一直接读写 `stock_data.db` 的模块，所有 IC/分层/回测均通过它取数
2. **因子库公共**: `factor_lib/registry.py` 声明全部因子元数据，推荐系统和因子测试共享同一份定义
3. **两套入口隔离**: `agent/` 现有推荐入口不改一行代码；`factor_test/` 是全新独立入口
4. **零侵入**: 不修改 `src/`、`agent/`、`web/` 任何现有文件
5. **配置独立**: `config/factor_test.yaml` 独立配置，与 `thresholds.yaml`、`evo.yaml` 平行
6. **一行回滚**: 删除 `factor_lib/`、`factor_test/`、`config/factor_test.yaml`、`factor_test_reports/` 即可完全回滚

### 2.3 目录结构

```
my_Stock/
├── factor_lib/                       # 公共因子库包（新建）
│   ├── __init__.py
│   ├── registry.py                   # 因子注册表
│   ├── loader.py                     # 统一数据加载器
│   ├── ic_engine.py                  # IC 计算引擎
│   ├── stratified_tester.py          # 分层测试引擎
│   ├── backtester.py                 # 单因子回测器
│   ├── anti_overfit.py               # 防过拟合校验
│   ├── report.py                     # HTML 报告生成
│   └── config.py                     # 配置加载
│
├── factor_test/                      # 因子测试模块入口（新建）
│   ├── __init__.py
│   ├── cli.py                        # CLI 入口
│   ├── run_single_factor.py          # 单因子测试
│   ├── run_batch_screening.py        # 批量因子筛选
│   └── run_comparison.py             # 因子间对比
│
├── config/
│   └── factor_test.yaml              # 因子测试独立配置（新建）
│
├── factor_test_reports/              # 报告输出目录（新建，自动创建）
│   ├── single/                       # 单因子报告
│   ├── batch/                        # 批量筛选报告
│   └── comparison/                   # 对比报告
│
├── src/                              # 现有（不改）
├── agent/                            # 现有（不改）
├── web/                              # 现有（不改）
└── config/                           # 现有（只新增 factor_test.yaml）
```

***

## 三、模块详细设计

### 3.1 `factor_lib/registry.py` — 因子注册表

**职责**: 声明全部因子的元数据，是两套入口共享的"单一事实来源"。

```python
# 数据结构
@dataclass
class FactorMeta:
    name: str                    # 因子名（对应数据库列名）
    direction: int               # +1 = 正向因子（值越大越好），-1 = 反向因子（值越小越好）
    category: str                # 动量/波动率/估值/流动性/聪明钱/交叉/预期差/防御
    table: str                   # 来源表: "factor_values" 或 "factor_values_evo"
    description: str             # 因子描述
    direction_note: str          # 方向说明（为什么正向/反向）
```

**因子清单（37 个 = 26 经典 + 11 EVO 有效因子）**:

| 分类  | 因子                          | 方向 | 来源表                 |
| --- | --------------------------- | -- | ------------------- |
| 动量  | return\_5d                  | +1 | factor\_values      |
| 动量  | return\_10d                 | +1 | factor\_values      |
| 动量  | return\_20d                 | +1 | factor\_values      |
| 动量  | return\_60d                 | +1 | factor\_values      |
| 动量  | return\_120d                | +1 | factor\_values      |
| 动量  | excess\_return\_20d         | +1 | factor\_values      |
| 波动率 | volatility\_10d             | -1 | factor\_values      |
| 波动率 | volatility\_20d             | -1 | factor\_values      |
| 波动率 | volatility\_60d             | -1 | factor\_values      |
| 波动率 | volatility\_120d            | -1 | factor\_values      |
| 波动率 | skewness\_20d               | -1 | factor\_values      |
| 波动率 | max\_drawdown\_20d          | -1 | factor\_values      |
| 波动率 | max\_drawdown\_60d          | -1 | factor\_values      |
| 波动率 | atr\_ratio                  | -1 | factor\_values      |
| 估值  | pe\_ttm                     | -1 | factor\_values      |
| 估值  | pb                          | -1 | factor\_values      |
| 估值  | roe                         | +1 | factor\_values      |
| 流动性 | turnover\_rate              | -1 | factor\_values      |
| 流动性 | turnover\_rate\_5d          | -1 | factor\_values      |
| 流动性 | turnover\_rate\_20d         | -1 | factor\_values      |
| 聪明钱 | north\_net\_inflow\_ratio   | +1 | factor\_values      |
| 聪明钱 | profit\_ratio\_estimate     | +1 | factor\_values      |
| 聪明钱 | chip\_concentration         | -1 | factor\_values      |
| 聪明钱 | vol\_ratio                  | +1 | factor\_values      |
| 防御  | beta\_60d                   | -1 | factor\_values      |
| 防御  | quality\_score              | +1 | factor\_values      |
| 防御  | low\_turnover\_flag         | +1 | factor\_values      |
| 防御  | timeliness\_decay           | +1 | factor\_values      |
| 复合  | hot\_money\_score           | +1 | factor\_values      |
| 复合  | strong\_control\_score      | +1 | factor\_values      |
| 复合  | main\_force\_score          | +1 | factor\_values      |
| 交叉  | inter\_quality\_momentum    | +1 | factor\_values\_evo |
| 交叉  | inter\_value\_excess        | +1 | factor\_values\_evo |
| 交叉  | inter\_chip\_volume         | +1 | factor\_values\_evo |
| 交叉  | inter\_smart\_defense       | +1 | factor\_values\_evo |
| 交叉  | inter\_overshoot\_reversal  | +1 | factor\_values\_evo |
| 交叉  | triple\_value\_mom\_quality | +1 | factor\_values\_evo |
| 交叉  | inter\_mom\_skew\_neg       | +1 | factor\_values\_evo |
| 交叉  | inter\_lowvol\_profit       | +1 | factor\_values\_evo |
| 交叉  | inter\_turnover\_reversal   | +1 | factor\_values\_evo |
| 交叉  | inter\_chip\_break\_right   | +1 | factor\_values\_evo |
| 预期差 | surprise\_price\_vote       | +1 | factor\_values\_evo |
| 预期差 | surprise\_earnings\_gap     | +1 | factor\_values\_evo |
| 预期差 | surprise\_roe\_qoq          | +1 | factor\_values\_evo |

**关键设计**: registry 不计算因子值，只声明元数据。因子值由现有 `feature_engineering.py` 和 `feature_engineering_evo.py` 计算并写入数据库，factor\_lib 只读不写。

### 3.2 `factor_lib/loader.py` — 统一数据加载器

**职责**: 唯一直接访问 `stock_data.db` 的模块，对上层提供统一的数据接口。

**核心函数**:

```python
class FactorDataLoader:
    def __init__(self, db_path=None):
        # 从 config/paths.yaml 读取 db_path，确保与现有系统一致

    def load_factor_values(
        self,
        factor_names: list[str],
        start_date: str = "20200101",
        end_date: str = None,
        table: str = "factor_values",
    ) -> pd.DataFrame:
        """加载因子值 + 后复权收盘价（用于计算未来收益率）"""
        # 返回: [ts_code, trade_date, factor1, factor2, ..., close_adj]

    def load_daily_prices(
        self,
        start_date: str = "20200101",
        end_date: str = None,
    ) -> pd.DataFrame:
        """加载日K线（close, adj_factor, vol, pct_chg）"""

    def compute_forward_returns(
        self,
        df: pd.DataFrame,
        periods: list[int] = [1, 3, 5, 10, 20],
    ) -> pd.DataFrame:
        """计算多周期未来收益率（复权）"""
        # 基于后复权收盘价 shift(-N) / close_adj - 1

    def load_trade_calendar(
        self,
        start_date: str = "20200101",
        end_date: str = None,
    ) -> list[str]:
        """加载交易日历，用于调仓日确定"""

    def load_stock_filter(self) -> set[str]:
        """加载 ST/退市/次新股过滤名单"""
        # 从 stock_list 读取 name LIKE '%ST%' 或 list_date < cutoff
```

**口径一致性保证**:

- `adj_factor` 三级兜底逻辑与 `feature_engineering.py` 完全一致: `stk_factor` 优先 → `daily_prices.adj_factor` → 1.0

- 未来收益率计算逻辑与 `scripts/factor_ic_analysis.py` 一致: `close_adj.shift(-N) / close_adj - 1`，clip(-0.5, 0.8)

- ST 过滤逻辑与 `agent/validator.py` 一致

### 3.3 `factor_lib/ic_engine.py` — IC 计算引擎

**职责**: 全面的 IC 分析，超越现有 `factor_ic_analysis.py` 的能力。

**核心功能**:

| 功能           | 方法                                 | 输出           |
| ------------ | ---------------------------------- | ------------ |
| Normal IC    | Pearson 相关（因子值 vs 未来收益）            | 每日 IC 序列     |
| Rank IC      | Spearman 相关（因子排名 vs 收益排名）          | 每日 RankIC 序列 |
| IC 均值 & ICIR | 每日 IC 序列的均值和均值/标准差                 | 统计表          |
| IC 衰减曲线      | 不同持仓周期(1d/3d/5d/10d/20d)的 IC       | 衰减曲线         |
| IC 累积曲线      | 每日 IC 累积求和                         | 累积图          |
| IC 子周期稳定性    | 分年度 IC 均值/标准差                      | 年度统计表        |
| IC 显著性 t 检验  | t = IC\_mean / (IC\_std / sqrt(N)) | t 值 & p 值    |
| IC 正负比例      | IC > 0 的天数占比                       | 比例值          |

**接口设计**:

```python
class ICEngine:
    def compute_ic_series(
        self,
        df: pd.DataFrame,          # loader 返回的含因子+收益的 DataFrame
        factor_name: str,
        ic_type: str = "rank",     # "rank" or "normal"
        return_col: str = "fwd_ret_5d",
    ) -> pd.Series:
        """计算每日截面 IC 序列"""

    def compute_ic_summary(
        self,
        ic_series: pd.Series,
    ) -> dict:
        """IC 统计摘要: 均值、标准差、ICIR、t值、p值、正比例、胜率"""

    def compute_ic_decay(
        self,
        df: pd.DataFrame,
        factor_name: str,
        periods: list[int] = [1, 3, 5, 10, 20],
    ) -> pd.DataFrame:
        """多周期 IC 衰减分析"""

    def compute_ic_cumulative(self, ic_series: pd.Series) -> pd.Series:
        """IC 累积曲线"""

    def compute_yearly_stability(
        self,
        ic_series: pd.Series,
        dates: pd.Series,
    ) -> pd.DataFrame:
        """分年度 IC 稳定性"""
```

**与现有代码区别**:

- 现有: 仅 Rank IC + IR + abs(IC)>0.025 初筛 + 相关性去冗余

- 新增: Normal IC、多周期衰减、累积曲线、t 检验、年度稳定性、正负比例

### 3.4 `factor_lib/stratified_tester.py` — 分层测试引擎

**职责**: 按因子值将股票分为 N 组，计算各组收益，验证单调性。

**核心功能**:

| 功能    | 说明                        |
| ----- | ------------------------- |
| 分组    | 按因子值截面排名分为 N 组（默认 5/10 组） |
| 各组收益  | 每组等权组合的多周期平均收益            |
| 多空收益  | Top 组 - Bottom 组的每期收益     |
| 多空净值  | 多空组合的累积净值曲线               |
| 单调性检验 | 各组收益是否随因子值单调递增/递减         |
| 分组换手率 | 各组的调仓换手率（衡量策略可执行性）        |
| 分组 IC | 各组内因子的 IC（验证组内区分度）        |

**接口设计**:

```python
class StratifiedTester:
    def run_stratified_test(
        self,
        df: pd.DataFrame,
        factor_name: str,
        n_groups: int = 5,
        return_col: str = "fwd_ret_5d",
        rebalance_freq: str = "weekly",  # "daily" or "weekly"
        cost_bps: float = 15.0,         # 单边交易成本（bp）
    ) -> StratifiedTestResult:
        """
        完整分层测试
        返回: 各组收益序列、多空净值曲线、单调性 p-value、换手率
        """

    def compute_monotonicity(self, group_returns: pd.DataFrame) -> dict:
        """单调性检验: Spearman 相关(组序号 vs 平均收益) + p-value"""

    def compute_long_short_nav(self, top_returns: pd.Series, bottom_returns: pd.Series) -> pd.Series:
        """多空净值曲线（扣除交易成本）"""
```

**输出结构**:

```python
@dataclass
class StratifiedTestResult:
    factor_name: str
    n_groups: int
    group_returns: pd.DataFrame     # 每期每组的收益率
    group_nav: pd.DataFrame         # 每组净值曲线
    long_short_returns: pd.Series   # 多空每期收益
    long_short_nav: pd.Series       # 多空净值曲线
    monotonicity_score: float       # 单调性得分
    monotonicity_pvalue: float      # 单调性 p 值
    turnover: pd.Series            # 各组换手率
    summary: dict                   # 统计摘要
```

### 3.5 `factor_lib/backtester.py` — 单因子独立回测器

**职责**: 完全独立的单因子回测，不依赖 `agent/backtester.py` 的任何逻辑。

**核心功能**:

| 功能    | 说明                     |
| ----- | ---------------------- |
| 组合构建  | 按因子值排名选 Top-N 股票，等权配置  |
| 调仓    | 日调/周调，可配置              |
| 交易成本  | 可配置双边费率（默认 15bp 单边）    |
| 涨跌停处理 | 涨停不买入、跌停不卖出            |
| 净值曲线  | 组合净值、基准净值、超额净值         |
| 绩效统计  | 年化收益、最大回撤、夏普、卡玛、胜率、盈亏比 |
| 分年度绩效 | 每年收益、回撤、夏普             |
| 持仓记录  | 每期持仓明细                 |
| 换手率   | 组合换手率序列                |

**与** **`agent/backtester.py`** **区别**:

- `agent/backtester.py`: 贝塔剥离、防御切换、误差回响、多轨路由 → 服务于推荐系统

- `factor_lib/backtester.py`: 纯因子排名选股、等权配置、无额外修饰 → 服务于因子测试

```python
class FactorBacktester:
    def run_backtest(
        self,
        df: pd.DataFrame,
        factor_name: str,
        top_n: int = 10,
        rebalance_freq: str = "weekly",
        cost_bps: float = 15.0,
        benchmark: str = "equal_weight",  # 等权基准
    ) -> BacktestResult:
        """单因子回测"""

    def compute_performance(self, returns: pd.Series, benchmark: pd.Series = None) -> dict:
        """绩效统计"""
```

### 3.6 `factor_lib/anti_overfit.py` — 防过拟合校验

**职责**: 多维度防过拟合检验，确保因子有效性不是偶然。

**校验维度**:

| 校验               | 方法                                | 判定标准                         |
| ---------------- | --------------------------------- | ---------------------------- |
| **样本外检验**        | 前 60% 数据训练（IC 方向），后 40% 验证 IC 一致性 | 样本外 IC 同方向且 ICIR > 0.3       |
| **Walk-Forward** | 滚动窗口（如 52 周训练 + 13 周预测）           | 各窗口 IC 正比例 > 60%             |
| **置换检验**         | 随机打乱因子值 1000 次，计算原始 IC 的分位数       | p < 0.05（IC 显著高于随机）          |
| **子周期稳定性**       | 分年度 IC 的均值和方向一致性                  | 同方向年份 > 70%，年度 IC 标准差 < 0.05 |
| **持仓周期衰减**       | 1d/3d/5d/10d/20d IC 衰减曲线          | IC 单调衰减，无突变                  |
| **样本量充足性**       | 有效截面数、每截面股票数                      | 截面数 > 100，每截面 > 300 只        |
| **IC 自相关**       | IC 序列的 Ljung-Box 检验               | p < 0.05（IC 非白噪声）            |

```python
class AntiOverfitChecker:
    def run_sample_split_test(
        self, df, factor_name, train_ratio=0.6
    ) -> dict:
        """样本内/外分割检验"""

    def run_walk_forward_test(
        self, df, factor_name, train_window=252, test_window=63
    ) -> dict:
        """Walk-Forward 滚动检验"""

    def run_permutation_test(
        self, df, factor_name, n_permutations=1000
    ) -> dict:
        """置换检验"""

    def run_subperiod_stability(
        self, df, factor_name
    ) -> dict:
        """分年度子周期稳定性"""

    def run_ic_autocorrelation(
        self, ic_series: pd.Series, lags=[1, 5, 10, 20]
    ) -> dict:
        """IC 序列自相关检验（Ljung-Box）"""

    def generate_verdict(self, all_results: dict) -> dict:
        """综合判定: PASS / WARNING / FAIL"""
```

### 3.7 `factor_lib/report.py` — HTML 报告生成器

**职责**: 生成自包含的 HTML 报告，包含图表和分析结论。

**报告结构**:

```
单因子报告 HTML:
├── 1. 因子概览（名称/方向/分类/描述/数据范围）
├── 2. IC 分析
│   ├── IC 统计表（均值/ICIR/t值/p值/正比例）
│   ├── 每日 IC 序列柱状图
│   ├── IC 累积曲线
│   ├── IC 衰减曲线（1d~20d）
│   └── 分年度 IC 热力图
├── 3. 分层测试
│   ├── 各组净值曲线
│   ├── 各组平均收益柱状图
│   ├── 多空净值曲线
│   ├── 单调性检验结果
│   └── 分组换手率
├── 4. 回测绩效
│   ├── 组合净值 vs 基准净值
│   ├── 超额收益曲线
│   ├── 绩效统计表（年化/回撤/夏普/卡玛/胜率）
│   └── 分年度绩效
├── 5. 防过拟合校验
│   ├── 样本内外 IC 对比
│   ├── Walk-Forward IC 序列
│   ├── 置换检验分布图
│   ├── 子周期稳定性热力图
│   └── IC 自相关检验
├── 6. 综合评级
│   └── 有效/警告/失效 + 评级理由
└── 7. 附录：原始数据统计
```

**图表实现**: 全部用内联 SVG 或 ECharts CDN，不依赖本地 JS 文件，确保报告可独立打开。

### 3.8 `factor_lib/config.py` — 配置加载

```python
# config/factor_test.yaml 结构
version: "1.0"

data:
  db_path: null          # null = 从 paths.yaml 读取，确保口径一致
  start_date: "20200101"
  end_date: null         # null = 最新交易日
  exclude_st: true
  exclude_new_stock_days: 365  # 次新股过滤天数

ic:
  type: "rank"           # "rank" or "normal" or "both"
  return_periods: [1, 3, 5, 10, 20]
  min_cross_section_size: 30
  clip_return: [-0.5, 0.8]

stratified:
  n_groups: 5
  rebalance_freq: "weekly"  # "daily" or "weekly"
  cost_bps: 15.0

backtest:
  top_n: 10
  rebalance_freq: "weekly"
  cost_bps: 15.0
  benchmark: "equal_weight"
  handle_limit: true       # 涨跌停处理

anti_overfit:
  train_ratio: 0.6
  walk_forward_train: 252
  walk_forward_test: 63
  n_permutations: 1000
  yearly_consistency_ratio: 0.70
  ic_positive_ratio: 0.60
  icir_min: 0.30
  significance_level: 0.05

report:
  output_dir: "factor_test_reports"
  language: "zh"
  charts: "echarts"        # "echarts" or "svg"
```

***

## 四、实施阶段

### 阶段 1: 公共因子库骨架 + 数据管道 (S1)

**交付物**:

- `factor_lib/__init__.py`

- `factor_lib/registry.py` — 全部 37 个因子元数据声明

- `factor_lib/loader.py` — 统一数据加载器

- `factor_lib/config.py` — 配置加载

- `config/factor_test.yaml` — 独立配置文件

**验收标准**:

1. `python -c "from factor_lib.registry import FACTOR_REGISTRY; print(len(FACTOR_REGISTRY))"` 输出 37
2. Loader 能加载 `factor_values` 表中任意因子列 + 后复权收盘价
3. Loader 计算的未来 5 日收益率与 `scripts/factor_ic_analysis.py` 中的 `future_return_5d` 数值一致（抽样 5 只股票对比）
4. ST/次新股过滤名单与 `agent/validator.py` 的过滤逻辑一致
5. 配置文件热加载生效（修改 `factor_test.yaml` 后无需重启）

### 阶段 2: IC 计算引擎 (S2)

**交付物**:

- `factor_lib/ic_engine.py`

**验收标准**:

1. Rank IC 计算结果与 `scripts/factor_ic_analysis.py` 的 `compute_rank_ic_ir` 输出一致（抽样验证）
2. Normal IC 可计算且数值合理（-1 \~ 1）
3. IC 衰减曲线覆盖 1d/3d/5d/10d/20d 五个周期
4. IC 累积曲线单调递增（对正向有效因子）
5. 分年度 IC 统计表可输出，每年度有均值/标准差/ICIR
6. t 检验 p 值与 scipy.stats.ttest\_1samp 结果一致

### 阶段 3: 分层测试引擎 (S3)

**交付物**:

- `factor_lib/stratified_tester.py`

**验收标准**:

1. 5 组分层测试，各组等权收益可计算
2. 多空净值曲线（Top 组 - Bottom 组）扣除 15bp 交易成本后仍为正（对有效因子）
3. 单调性检验：有效因子 p < 0.05，无效因子 p > 0.1
4. 换手率可计算，数值合理（10%\~80% 范围）
5. 周调/日调均可配置

### 阶段 4: 单因子回测器 (S4)

**交付物**:

- `factor_lib/backtester.py`

**验收标准**:

1. Top-10 等权组合净值曲线可输出
2. 年化收益、最大回撤、夏普、卡玛、胜率、盈亏比均可计算
3. 分年度绩效表可输出
4. 交易成本 15bp 扣除后绩效合理
5. 涨跌停处理：涨停日不买入标记正确
6. 与 `agent/backtester.py` 完全独立，零依赖

### 阶段 5: 防过拟合校验 (S5)

**交付物**:

- `factor_lib/anti_overfit.py`

**验收标准**:

1. 样本外检验: 前 60% / 后 40% 分割，样本外 IC 可计算
2. Walk-Forward: 252 日训练 + 63 日预测，滚动窗口 IC 正比例可输出
3. 置换检验: 1000 次随机打乱，原始 IC 的分位数 > 0.95（对有效因子）
4. 子周期稳定性: 分年度 IC 同方向比例 > 70%
5. IC 自相关: Ljung-Box 检验 p 值可输出
6. 综合判定: PASS / WARNING / FAIL 逻辑正确

### 阶段 6: HTML 报告 + CLI 入口 (S6)

**交付物**:

- `factor_lib/report.py`

- `factor_test/cli.py`

- `factor_test/run_single_factor.py`

- `factor_test/run_batch_screening.py`

- `factor_test/run_comparison.py`

**验收标准**:

1. `python factor_test/cli.py test --factor return_5d` 生成完整 HTML 报告
2. `python factor_test/cli.py batch --factors all` 批量测试并生成汇总表
3. `python factor_test/cli.py compare --factors return_5d,return_20d,volatility_20d` 生成对比报告
4. HTML 报告可独立打开，图表正常渲染
5. 报告中所有数值与代码输出一致（无编造）

### 阶段 7: 集成测试 + 文档 (S7)

**交付物**:

- `factor_test_reports/` 示例报告

- `docs/factor_test_module_guide.md` 使用指南

**验收标准**:

1. 全部 37 个因子均可完成单因子测试无报错
2. 批量筛选报告含因子排名表（按 ICIR 排序）
3. 零侵入验证: `git diff` 确认未修改 `src/`、`agent/`、`web/` 任何文件
4. 一行回滚: 删除 `factor_lib/`、`factor_test/`、`config/factor_test.yaml` 后现有系统不受影响

***

## 五、数据流详解

### 5.1 单因子测试完整流程

```
用户执行:
  python factor_test/cli.py test --factor return_5d --period 20200101-20260831

数据流:
  1. cli.py 读取 config/factor_test.yaml
  2. loader.py 从 stock_data.db 加载:
     a. factor_values.return_5d (因子值)
     b. daily_prices.close + adj_factor (后复权价)
     c. stock_list (ST 过滤)
     d. trade_cal (调仓日)
  3. loader.py 计算多周期未来收益率 (1d/3d/5d/10d/20d)
  4. ic_engine.py:
     a. 每日截面 Rank IC + Normal IC
     b. IC 统计: 均值/ICIR/t值/p值
     c. IC 衰减: 5 个周期
     d. IC 累积曲线
     e. 分年度 IC
  5. stratified_tester.py:
     a. 5 组分层，计算每组收益
     b. 多空净值曲线
     c. 单调性检验
     d. 换手率
  6. backtester.py:
     a. Top-10 等权组合
     b. 周调仓 + 15bp 成本
     c. 净值/绩效/分年度
  7. anti_overfit.py:
     a. 样本外检验
     b. Walk-Forward
     c. 置换检验
     d. 子周期稳定性
     e. IC 自相关
  8. report.py:
     a. 汇总所有结果
     b. 生成 HTML 报告
     c. 保存到 factor_test_reports/single/return_5d_20260902.html
  9. 输出报告路径
```

### 5.2 批量因子筛选流程

```
用户执行:
  python factor_test/cli.py batch --factors all

数据流:
  1. 遍历 registry 中 37 个因子
  2. 每个因子执行 IC + 分层 + 防过拟合（跳过回测，加速）
  3. 汇总排名表:
     | 因子 | IC均值 | ICIR | t值 | p值 | 单调性 | 样本外IC | 置换p值 | 年度一致性 | 综合评级 |
  4. 生成 batch 筛选报告 HTML
```

### 5.3 因子对比流程

```
用户执行:
  python factor_test/cli.py compare --factors return_5d,return_20d,volatility_20d

数据流:
  1. 对每个因子执行完整测试
  2. 生成对比报告:
     - IC 曲线叠加图
     - 分层收益对比图
     - 回测净值叠加图
     - 绩效对比表
     - 相关性矩阵
```

***

## 六、技术选型

| 组件      | 选择                                      | 理由              |
| ------- | --------------------------------------- | --------------- |
| 数据处理    | pandas + numpy                          | 项目已有依赖，无新增      |
| IC 计算   | pandas.corr + scipy.stats               | 向量化截面计算，与现有代码一致 |
| 统计检验    | scipy.stats (ttest, spearmanr, boxplot) | 标准统计库           |
| HTML 报告 | ECharts CDN + 内联 CSS/JS                 | 自包含、可独立打开、图表交互  |
| CLI     | argparse                                | Python 标准库，无依赖  |
| 配置      | PyYAML                                  | 项目已有依赖          |
| 数据库     | sqlite3                                 | 项目已有依赖          |

**零新增依赖**: 全部使用 `requirements.txt` 中已有的库。

***

## 七、与现有系统的关系

### 7.1 共享层（只读）

```
stock_data.db ← factor_lib/loader.py (只读)
config/paths.yaml ← factor_lib/config.py (只读)
config/candidate_factors.yaml ← factor_lib/registry.py 参考（只读）
```

### 7.2 隔离层（完全独立）

```
factor_lib/     ← 不 import agent/ 任何代码
factor_test/   ← 不 import web/backend/ 任何代码
agent/          ← 不改，不 import factor_lib/（现有推荐系统不受影响）
web/backend/    ← 不改（后续可选接入，但不依赖）
```

### 7.3 未来可选接入

- `agent/` 可选择从 `factor_lib/registry.py` 读取因子元数据（替代硬编码）

- `web/backend/` 可选择添加 `/api/factor-test/` 路由调用 `factor_lib/`

- 以上接入是**可选的**，不接入也不影响因子测试模块独立运行

***

## 八、风险与缓解

| 风险              | 缓解措施                                                      |
| --------------- | --------------------------------------------------------- |
| 置换检验 1000 次计算慢  | 向量化实现 + 可配置次数（默认 200，最大 1000）                             |
| 大数据量内存不足        | `factor_values` 316 万行，分批加载 + dtype 优化 + 按日期过滤            |
| 与现有 IC 结果不一致    | 阶段 2 验收标准明确要求抽样对比一致性                                      |
| ECharts CDN 不可用 | 备选 SVG 静态图表（`config/factor_test.yaml report.charts: svg`） |
| SQLite 并发锁      | 因子测试是离线批处理，不与线上服务并发运行                                     |

***

## 九、实施优先级与时间估算

| 阶段 | 内容               | 优先级 | 预计工作量 |
| -- | ---------------- | --- | ----- |
| S1 | 公共因子库骨架 + 数据管道   | P0  | 中     |
| S2 | IC 计算引擎          | P0  | 中     |
| S3 | 分层测试引擎           | P0  | 中     |
| S4 | 单因子回测器           | P1  | 中     |
| S5 | 防过拟合校验           | P1  | 大     |
| S6 | HTML 报告 + CLI 入口 | P1  | 中     |
| S7 | 集成测试 + 文档        | P2  | 小     |

**建议执行顺序**: S1 → S2 → S3 → S4 → S5 → S6 → S7

每阶段完成后做冒烟验收（真实数据、非空数值），确认通过后再进入下一阶段。

***

## 十、验收清单

- [ ] `factor_lib/` 包含 7 个模块文件

- [ ] `factor_test/` 包含 4 个入口文件

- [ ] `config/factor_test.yaml` 独立配置

- [ ] 37 个因子均可完成单因子测试

- [ ] IC 计算与现有 `factor_ic_analysis.py` 结果一致

- [ ] 分层测试多空净值为正（对有效因子）

- [ ] 防过拟合校验 5 个维度均可运行

- [ ] HTML 报告自包含、可独立打开

- [ ] CLI 入口支持 test/batch/compare 三种模式

- [ ] 零侵入: `git diff` 确认未修改现有代码

- [ ] 一行回滚: 删除新增文件后系统不受影响

