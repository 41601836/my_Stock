# S4 回归测试 Top 10 总结报告

> 生成日期：2026-09-01
> 测试文件：`tests/test_s4_regression_top10.py`（11 用例，498 行，unittest 风格）
> 结论：**五个维度 100% 覆盖，11/11 测试通过，Smoke 19/19 全绿，无遗留事项**

---

## 一、覆盖矩阵

| # | 维度 | 用例 | 状态 | 本轮深查结果 |
|---|------|------|------|--------------|
| 1 | 画像分 5 维边界值 | TC01-TC03 | ✅ | 静态审查 + 5000 样本 fuzz，发现并修复 1 个生产缺陷 |
| 2 | 三层漏斗通过率 | TC04-TC06 | ✅ | 实现审查无缺陷，生产链路通过率实测 |
| 3 | Regime 判定样本 | TC07-TC08 | ✅ | helper 设计审查通过，生产 regime=Bull 一致 |
| 4 | IC/IR 计算基准 | TC09 | ✅ | 三处实现一致性审查 + 生产快照实测，补 TC11 固化 cap 自适应 |
| 5 | 权重 approve 覆盖流程 | TC10 | ✅ | yaml/pkl/热加载全流程通过 |

---

## 二、各维度检查详情

### 1. 画像分 5 维边界值（TC01-TC03）

**测试设计**
- TC01：5 维甜区中心输入 → 总分 ≥90、等级 A、标签"强烈推荐"、单维 [0,20]
- TC02：5 维零分输入（高位/高估值/过热/涣散/明牌）→ 总分 ≤35、等级 D
- TC03：因子分 0.30→0.95 梯度单调（低分段 < 甜区分段）、明细合计==总分

**深查发现与修复**
- 静态边界审查：5 维全部分段边界连续（位置 0.25/0.55/0.85、估值 55/95/160、筹码 70/76/86/92、因子 0.68/0.78/0.90/0.94），仅筹码 <70→0、>92→6 为刻意实证阶梯
- Fuzz 扫描（5000 随机样本含越界输入）：**发现因子分负值外推缺陷**——`fs < 0.68` 分支线性外推 `20×(fs/0.68)×0.6`，负输入产生负分（实测因子分 -1.1，415 次单维越界、9 次总分 <0）
- 修复：`fs = max(0.0, _safe_float(factor_score, 0.0))`（portrait_router.py L267，一行）
- 修复后 fuzz 违规全部归零；精确边界点：甜区下界=100（封顶）、上界=78（过热回落）、零分区=25、负PE/涣散=71
- 等级 A/B/C/D 与 4 个标签全覆盖
- **后端已重启使修复生效**（旧进程 43616 无 --reload，新 pid=71682），Smoke 19/19 复验通过

### 2. 三层漏斗通过率（TC04-TC06）

**测试设计**
- TC04：20 只含 6 只 D 级 → D 级硬排除 100%，通过池无 D
- TC05：20 只线性因子分布 → 尾 5%/20% 分位剔除 + min_size=30>20 触发高分回补
- TC06：5 只 EW=20% ≤30% 帽、Σw=100%、prev 插值后换手 ≤55%

**实现审查**（portfolio_constructor.py L150-201）
- Layer 1：`grade.upper()=="D"` 大小写防御 ✅
- Layer 2：`fillna(0.5)` 防 NaN、`len(df)>=5` 样本保护、`threshold<0.3` 只在真存在差等生时剔除、与 D 级排除不重复计数 ✅
- Layer 3 回补：不足 min_size 按 portrait_score 降序从拒绝池补回，杜绝空组合 ✅
- 权重层：`cap = max(max_weight, 1/N)` 自适应、换手 α=min(1, 2T/Σ|Δ|) 线性插值 ✅

**生产链路实测**（scratch/verify_funnel_passrate.py）

| 接口 | in_count | 过滤剔除 | out_count | 通过率 | EW 目标 | 换手 |
|------|-----:|----:|-----:|----:|----:|----:|
| 仓位推荐 | 5 | 0 | 5 | 100% | 20.0% | 0.5 |
| 建仓扫描 | 9 | 0 | 9 | 100% | 11.11% | 0.5 |

- 输出 grades=[B×3, C×6]，无 D 级泄漏；`cap_weight_pct=30.0`、phase 合同字段齐备
- 当日通过率 100% 属正常（候选池无 D 级、无 <0.3 分位差等生），闸门在位未触发

### 3. Regime 判定样本（TC07-TC08）

**测试设计**
- TC07：合成 60 天行情 → Bull（40 天高波动筑底 + 20 天低波动稳步上涨）/ Range（横盘小幅震荡）
- TC08：Dark 优先级最高（30 天暴跌 + 上涨占比 20%）；中等熊市不应误判 Bull/Dark

**helper 审查**（`_regime_assert_with`）
- 合成 SQLite `daily_prices`（10 股 × 60 天），上涨组 `max(base, 0.3)`、下跌组 `min(base, -0.3)`，**严格保证 DB 中 `CASE WHEN pct_chg>0` 统计与 up_ratio 参数对齐**
- `cmn.DB_PATH` + `m_reg.DB_PATH` 双替换 monkey-patch，finally 恢复，临时目录清理

**生产验证**：`/api/market/regime-dashboard` 当前 regime=**Bull**，历史含 Range，与测试覆盖状态一致

### 4. IC/IR 计算基准（TC09 + TC11）

**测试设计**
- 正向单调 → IC=+1.0；反向单调 → IC=-1.0；样本 <30 → None；20 期弱信号（理论 IC≈0.03）→ mean IC 合理、IR=mean/std 稳定

**三处实现一致性审查**

| 实现 | 位置 | 结论 |
|------|------|------|
| `calc_rank_ic` | web/backend/services/evo/_common.py L229 | 对齐 dropna，n<30→None ✅ |
| `daily_rank_ic_series` | src/evo_dynamic_weights.py L85 | pct-rank 中心化，数学等价 Spearman，逐日 min_samples ✅ |
| `compute_rank_ic_ir` | scripts/factor_ic_analysis.py L74 | 分 Regime 分组，n<30 剔除 ✅ |

**生产快照实测**（evo_dynamic_weights_log，trade_date=20260824）
- 3/13 因子存活（inter_overshoot_reversal 0.3333 / surprise_roe_qoq 0.3333 / inter_turnover_reversal 0.3333），ICIR ∈ [0.337, 0.600] 均 > min_ir 0.10
- 10 个负 IC 因子被 `zero_negative_ic` 闸门正确置 0，权重归一 sum=1.0，mode=icir_weighted

**cap 自适应确认与固化**
- 确认 `cap = max(0.30, 1/n_eff)` 已实现（evo_dynamic_weights.py L174-176）；n_eff=3 时 cap→1/3，生产快照 0.3333 恰在 cap 内
- 4 场景验证全绿（n_eff=3 自适应 / n_eff=5 cap=0.30 严格 / skew 极不均匀 water-filling 收敛 / 全负 IC uniform_fallback 兜底）
- **新增 TC11** 固化此行为

### 5. 权重 approve 覆盖流程（TC10）

- 5 个阈值 getter（scanner/funnel/left/right/regime）默认值可用
- `scoring_weights` 5 项和 ≈1（thresholds.yaml 键值或默认兜底）
- pkl 权重加载归一 Σ≈1；损坏 pkl 返回 {} 不抛异常
- 热加载：mtime 置脏 → 缓存失效 → 重读成功，结构一致

---

## 三、本轮净产出

| 类型 | 内容 |
|------|------|
| 缺陷修复 | portrait_router.py L267 因子分下限截断（fuzz 发现，fuzz 违规 424→0） |
| 新增测试 | TC11 `test_TC11_evo_cap_adaptive`（4 断言场景） |
| 验证脚本 | scratch/verify_cap_adaptive.py、verify_portrait_5d_boundary.py、verify_funnel_passrate.py、restart_backend.sh |
| 后端重启 | pid 43616→71682，使画像分修复在生产进程生效 |

---

## 四、最终验证状态

| 验证项 | 结果 |
|--------|------|
| S4 全量单元测试 | **11/11 OK**（0.181s） |
| 全链路 Smoke（7 页面 + 12 接口） | **19/19 全绿**（后端重启后复验） |
| Fuzz 边界扫描（5000 样本） | 违规 0 |
| 生产链路抽查 | regime=Bull、漏斗通过率合同齐备、IC/IR 权重快照正确 |

## 五、遗留事项

无。S4 Top 10 五维覆盖全部完成，检查中发现的问题均已修复并回归验证。
