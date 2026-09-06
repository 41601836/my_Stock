# 项目复盘报告（2026-09-03）

> 范围：四层系统（经典决策层 / EVO 进化层 / Agent 巡航寻优层 / 因子检验层）效果验证优先，工程债概要盘点。
> 原则：所有结论均来自库内真实数据（db/stock_data.db、factor_test_reports/、agent/、logs/evo/），不引用任何无法复核的数字。
> 复现命令与数据坐标见文末附录。

> **修订记录（2026-09-03 质询修订 v2）**：本版对 v1 全部关键数字回库重算后修订，主要更正：
> 1. 因子层"仅 2 个显著有效"表述过度 → 严格 alpha（eff.IC>0 且 ICIR≥0.30）仅 1 个；补充 8 个高 Sharpe 但 IC≈0 的防御类因子定位；
> 2. 推荐层统计改用 P0-3 清洗后快照口径（1609 行；v1 的 1648 行为含并集重复的清洗前口径），分组/胜率数字同步更新；
> 3. 巡航格点 75→**45**（15 组合×3 top_n）、正超额卡玛格点 3→**2**；"在役三策略 -13.4%~-14.7%"因无落盘来源、不可复核，降级为待重算项（P1-6）；
> 4. Graham 通过率口径澄清（当日评分股 66.7% vs 全市场分母 64%）；
> 5. 新增第三口径（EVO 引擎 20 日滚动 IC）作为翻转佐证；权重 20 日快照机制说明；
> 6. 三口径差异（集成 CSV / factor_lib 审计 / EVO 引擎）从一句话备注扩展为显式清单。

> **修订记录（2026-09-03 P1 处置后 v3）**：
> 1. 巡航格点更正：报告随续跑跨会话累积，最终为 **22 组合 × 3 top_n = 66 格点**（v2 记 45/15 为会话中途快照）；三档全正组合 **0 个**；
> 2. 2.1 集成 CSV 口径更正：窗口为 **20250101~20250630（2025H1，ic_n_days=112）**，非"2020-01~2026-09/1617 交易日"（后者是底层全量面板口径）；
> 3. P1-5 根因更正：三口径差异 = **窗口长度差异**（集成 CSV=6 个月 / 三段审计=6.5 年 / EVO=20 日），ST/次新过滤由 factor_lib loader 在两口径同源施加，**不是差异源**；
> 4. P1 各项处置结果见第四章（winner_rate 置零、跨 top_n 闸门、Graham 4→6、在役策略统一口径回测落盘等）。

---

## 一、复盘方法

| 线 | 数据源 | 核心问题 |
|---|---|---|
| 因子层 | factor_test_reports/all_factors_integration_test.csv（46 行）+ 本次三段 IC 审计（scratch/audit_direction_result.csv） | 46 个因子哪些真有效？方向元数据对不对？ |
| 推荐层 | recommendation_tracker 表（P0-3 清洗后 1609 行快照口径，20260709~20260902；清洗前 1648 行含并集重复） | 已部署推荐的真实 5 日胜率/超额是多少？ |
| 巡航层 | agent/auto_cruise_report_20260903.json（22 组合 × 3 top_n = 66 格点，跨会话续跑累积） | 寻优结论是真信号还是过拟合？ |
| EVO 层 | evo_dynamic_weights_log / evo_ml_predictions / docs/evo_ml_report_20260901.md / logs/evo/scheduler_20260903.log | 动态权重与 ML 增量是否兑现？ |

---

## 二、四线效果量化结论

### 2.1 因子层：严格 alpha 仅 1 个，"追强"类因子方向系统性做反

集成测试口径（factor_test_reports/all_factors_integration_test.csv，由 scratch/verify_s7_integration.py 经 factor_lib loader 生成；**IC/回测窗口 = 20250101~20250630（2025H1，ic_n_days=112 个 IC 交易日）**，周频 Top10、15bps 成本、等权基准；v2 误写为"2020-01~2026-09/1617 交易日"——1617 交易日/5774 股是 loader 底层全量面板口径，非该 CSV 的测试窗口）：

- **截面选股能力显著（effective IC>0 且 ICIR≥0.30）的严格 alpha 因子仅 1 个**：
  - `inter_overshoot_reversal`（超跌反弹）：IC +0.071，ICIR 0.59，Sharpe 2.18，年化 +103%
- **回测好但 IC 稳定性不足**：`inter_turnover_reversal`（换手反转）IC +0.041、Sharpe 1.46、年化 +63%，但 ICIR 仅 0.23（<0.30 阈值），且与 factor_lib 审计口径矛盾（见口径备注）
- **高 Sharpe ≠ 截面 alpha**：另有 8 个因子 Sharpe>1（max_drawdown_20d/60d、atr_ratio、pe_ttm、roe、chip_concentration、inter_chip_volume 等，Sharpe 1.0~1.58、年化 +12%~+76%），但其 IC 均接近 0（effective IC 0.002~0.05，ICIR 0.04~0.27）——收益来自低波动/低估值/低回撤的防御属性（低回撤分母推高 Sharpe），而非截面排序能力。这类因子适合作为风控/筛选组件，不应按 alpha 因子加权
- **方向做反/无效（重点）**：动量族 return_5d/10d/20d 集成口径 IC -0.05~-0.09 但注册 direction=+1；`hot_money_score` Sharpe -2.59、`main_force_score` -1.87、`surprise_price_vote` -4.56；north_net_inflow_ratio（IC -0.049, ICIR **-1.03**）/profit_ratio_estimate（-0.069, -0.50）/vol_ratio（-0.077, -0.62）集成口径全负；`text_sentiment_score` 数据不足（INSUFFICIENT）

> **三口径差异说明（P1-5 已查明根因：窗口长度差异，非 ST 过滤）**：
> 1. 三个口径 = 三个不同窗口长度：集成 CSV=**2025H1 六个月**（ic_n_days=112）/ 三段审计=**6.5 年**（全样本 2020 起；近期段为 ≥20250101）/ EVO 引擎=**20 日滚动**。集成 CSV 与审计同样走 factor_lib loader（ST/次新过滤同源施加，loader 全样本剔除 149,831 行在两口径一致），**ST 过滤不是差异源**；
> 2. IC 强度差异 = 窗口效应：集成 CSV（2025H1）强度与审计"近期段"（≥20250101）最接近、且显著强于 6.5 年全样本（如 vol_ratio：集成 -0.077/-0.62 ≈ 审计近期 -0.060/-0.54，而审计全样本仅 -0.049/-0.43；return_5d 集成 -0.052/-0.42 ≈ 近期段水平）——2025 年后动量/追强类因子反向加剧，短窗口放大了该效应；方向符号三口径一致；
> 3. `north_net_inflow_ratio`、`profit_ratio_estimate` 集成强负（ICIR -1.03/-0.50）vs 全样本审计弱负（-0.19/-0.25），同为近期窗口效应，**按保守原则不翻转**；vol_ratio 三窗口均过阈值（集成 -0.62 / 审计近期 -0.54 / 全样本 -0.43）才翻转；
> 4. `inter_turnover_reversal` 三窗口结论分歧（2025H1 IC +0.041/Sharpe 1.46、6.5 年全样本 -0.004/WEAK、20 日 IC +0.078/ICIR 0.29）——符号随窗口摆动，保持观察项，任何权重决策暂不依赖其稳定性结论。

**三段 IC 审计结果**（scratch/audit_direction_result.csv，46 因子 × 全样本/基准期≤20241231/近期≥20250101）：

| verdict | 数量 | 含义 |
|---|---|---|
| FLIP | 5 | 三段 IC 同向为负且 \|ICIR\| 全 ≥0.30，方向应翻转 |
| WEAK | 11 | \|IC\|<0.02 且 \|ICIR\|<0.15，无统计证据，方向不动 |
| KEEP | 28 | 其余（含证据偏弱但未达翻转阈值者） |
| INSUFFICIENT | 2 | timeliness_decay（占位常数）、text_sentiment_score（缺数据） |

### 2.2 推荐层：整体超额为负，打分不单调，winner_rate 方向反

recommendation_tracker（P0-3 修复后为当日最终组合快照落库；tracker_updater.py 回填 1/3/5/10/20 日收益，T+1 开盘买入、等权全市场基准。以下统计为清洗后口径：1609 行、alpha_5d 已回填 1510 条、覆盖 32 个推荐日；五分位为等频分组 rank(method='first')）：

- 整体 avg alpha_5d = **-0.40%**（中位数 -0.87%），胜率（alpha_5d>0）**43.3%**
- 每日 Top10（按 factor_score 当日排名前 10，314 条有 alpha）：avg **+1.30%**、中位数 **-0.35%**、胜率 47.8%、**65.6% 的推荐日为正**（21/32 日）——均值被少数大涨拉高、中位数为负，典型右尾偏态
- factor_score 五分组 avg alpha_5d **非单调**（Q1低~Q5高: +0.36% / -0.93% / -2.29% / -0.55% / +1.45%）：最高分組确为最高、但 Q3 反而最差，打分与收益无稳定单调关系
- winner_rate 五分组方向反：最低组 W1 **+1.23%**，最高组 W5 **-1.62%**（高获利盘位置的股票未来 5 日跑输，与 2.1 profit_ratio_estimate 负 IC 互证）
- regime 分布：BEAR 1535 / BULL 44 / DARK 30（样本几乎全在熊市/震荡市，BULL 仅 44 条，结论外推至牛市需谨慎）
- 数据质量（清洗前问题，P0-3 已修复）：3 只 -100% 中 2 只为真退市（002808.SZ、002898.SZ「赛隆退」，base_price 已修为推荐日收盘 0.22/0.37，-100% 惩罚保留防幸存者偏差），1 只为停牌误判（688237.SH 超卓航科，停牌 6 交易日后复牌，已自愈为 ret_5d +21.7%）；并集污染曾导致单日 4~135 条记录（如 20260902 清洗前 69 行→清洗后 30 行）

### 2.3 巡航层：最优组合呈刀刃状过拟合

auto_cruise_report_20260903.json，**22 组合 × 3 top_n = 66 格点**（total_loops_tried=66；v2 记 45/15 为会话中途快照，报告随断点续跑跨会话累积）：

- 仅 **2 个格点**正超额卡玛（66 格点中 64 个为负），且全部集中在 combo 10（excess_return_20d / max_drawdown_20d / north_net_inflow_ratio / vol_ratio）
- 三档全正（跨 top_n 稳健）的组合数 = **0**——P1-3 闸门口径下无组合可部署（详见第四章 P1-3）
- 同一组合随 top_n 急剧衰减：top_n=10 超额卡玛 **+0.198**、top_n=20 **+0.006**、top_n=30 **-0.049**（刀刃状，无稳健平台；三档绝对卡玛分别为 +0.59/+0.39/+0.35，均为正——绝对收益不差但跑不赢等权基准）
- 最优权重对 4 因子中 3 个给负权重（excess_return_20d -0.277、north_net_inflow_ratio -0.205、vol_ratio -0.361 为负，仅 max_drawdown_20d +0.156 为正；与"追强"设计意图相反，反向印证 2.1）
- **在役策略统一口径回测（2026-09-03 晚已落盘，详见第四章 P1-6 / agent/inservice_strategies_backtest_20260903.json）**：生产实盘路径 routed 超额年化 **-11.79%**、超额卡玛 -0.212；老核心 old_core **-14.22%**；被部署的 combo10 固定组合样本内 **+5.44%** 但实盘未兑现；jack 参考项 -21.08%——与本节"刀刃过拟合"结论互证

### 2.4 EVO 层：动态权重机制方向正确，ML 验收 FAIL 且静默停摆

- 动态权重（最新快照 20260826，mode=icir_weighted）：ICIR 机制把 14 因子中 11 个置零，权重集中到 inter_overshoot_reversal / inter_turnover_reversal / surprise_roe_qoq 各 0.333 —— 与 2.1 的有效因子结论一致，机制方向正确。权重为 **20 个交易日快照**重算（非每日重写，故调度日 rc=0 但日志表不新增日期属设计行为）
- 独立第三口径佐证翻转：EVO 引擎自身 20 日滚动 IC（logs/evo/scheduler_20260903.log 中 dynamic_weights 步输出）显示 surprise_earnings_gap ICIR **-1.51**、surprise_price_vote -0.90、inter_chip_break_right -0.85、inter_quality_momentum -0.96——与因子测试审计同向，且 surprise_earnings_gap 为全部三口径中最强反向证据
- ML（LambdaRank）：M5.2 验收 **FAIL** —— NDCG@10 0.355 vs IC 基线 0.195（相对提升 +82.4%，PASS），但可执行 Top5 五日收益 **0.07%** vs IC 基线 0.26% vs 随机 0.46%（Top5 年化差 -9.32%，FAIL；报告右尾警示：2026 题材市连板/复牌暴利票集中在右尾，ML Top5 已剔除涨停但未含成本/容量建模）
- evo_ml_predictions **修复前**仅有 20260901 一天 5529 行（09-01 后预测静默失败，根因与修复见 P0-4）；修复后已恢复每日落库
- Graham 过滤无选择性：最新评分日 20260902，当日有评分的 5,530 只股票中 graham_score≥4 的 3,688 只（**66.7%**；复盘初次汇报的"3,687 只约 64%"是以全市场 ~5,775 只为分母的口径，两口径分母不同，特此澄清）

---

## 三、P0 修复（本次执行第 1、3、4 项，均已真实数据验证）

### P0-1 因子方向纠偏 ✅

**1) registry 翻转 5 个因子**（factor_lib/registry.py，判据：三段窗口 IC 同向为负且 |ICIR| 全 ≥0.30）：

| 因子 | 类型 | 全样本 IC/ICIR | 基准期 IC/ICIR | 近期 IC/ICIR | EVO引擎20日ICIR（第三口径） | 翻转后含义 |
|---|---|---|---|---|---|---|
| surprise_earnings_gap | EVO预期差 | -0.040 / **-0.65** | -0.040 / -0.64 | -0.039 / -0.68 | **-1.51** | 跳空高开回补效应（三口径证据最强） |
| hot_money_score | 复合 | -0.060 / -0.49 | -0.059 / -0.48 | -0.063 / -0.53 | —（classic 因子） | 追游资热点亏钱 |
| vol_ratio | 聪明钱 | -0.049 / -0.43 | -0.045 / -0.40 | -0.060 / -0.54 | —（classic 因子） | 天量见顶/低量溢价；近期窗口回测年化 **+4.98%**（旧方向为负） |
| main_force_score | 复合 | -0.053 / -0.40 | -0.052 / -0.37 | -0.055 / -0.50 | —（classic 因子） | "主力"高分反向 |
| inter_chip_break_right | EVO交叉 | -0.047 / -0.33 | -0.044 / -0.30 | -0.056 / -0.43 | -0.85 | 筹码突破多为假信号 |

每个因子的 direction_note 已写入翻转日期与三段证据。**保守未翻转**：
- 动量族 return_5d/10d/20d/60d：全样本 |ICIR| 0.19~0.29 差阈值（return_20d 近期窗口已达 0.38）
- north_net_inflow_ratio、profit_ratio_estimate：集成口径强负（ICIR -1.03/-0.50）但审计口径弱负（-0.19/-0.25），口径矛盾不翻转
- surprise_price_vote：审计全样本 |ICIR| 0.24（近期 0.30）、EVO 20 日窗口 -0.90——近期反向强但全样本未达阈值，不翻转，由自动告警持续盯防

**2) 方向 vs 实测 IC 自动告警接线**（今后方向错配自动暴露，不再依赖人工审计）：
- factor_lib/ic_engine.py `check_direction_consistency()`：effective_ic = ic_mean × direction；mismatch（eff<0 且 |ICIR|≥0.30）/ suspect（证据偏弱）/ ok
- factor_test/cli.py：单因子测试 IC 分析后打印 ❌/⚠️ 告警
- factor_lib/reporter.py：HTML 报告红/橙告警横幅（ok 不渲染）

**验证**：
- 翻转后 5 因子用全样本 IC 重跑校验全部 ok（eff_ic 转正）；registry 因子数 46 不变
- cli 冒烟：return_20d 近期窗口报 ❌ mismatch（IC=-0.0597, ICIR=-0.38）；翻转后的 vol_ratio 无告警、HTML 横幅 0 处
- **零侵入**：全库 grep 确认 agent/、web/、src/ 均不引用 factor_lib.registry，direction 仅被因子检验层（backtester/stratified 选 Top/Bottom）消费；回滚 = 5 行 direction 改回 +1

### P0-3 tracker 脏数据修复 ✅

| 问题 | 修复 | 验证证据 |
|---|---|---|
| 假退市 -100% 误判（688237 停牌 6 日复牌被判退市） | tracker_updater.py：30 交易日宽限期 + 假退市自愈 SQL（ret_5d≤-0.999 且 base_price≤0 且推荐日后 ≥5 条行情 → 重置重算）+ 买入价 open→close 兜底、绝不写 0 价 | 688237 自愈：base 55.8 / ret5d +21.7% / alpha +25.9%；677 条结算完成 |
| 真退市 base_price 被写 0 | 退市惩罚 base_price 取推荐日收盘价；手工 SQL 修 002808→0.22、002898→0.37（-1.0 惩罚保留，防幸存者偏差） | "settled rows with bad base_price remaining: 0" |
| 单日 4~135 条并集污染（INSERT OR IGNORE 累积同日多次调用） | _common.py 改快照语义：落库前 `DELETE FROM recommendation_tracker WHERE recommend_date=? AND alpha_20d IS NULL`（已结算历史受保护）再 INSERT | 重启后端实测：20260902 原有 **69 行 → 两次调 /api/portfolio 后恰好 30 行**（= 最终组合，非累加）；历史日期行数不变 |

### P0-4 ML 步骤可观测性 ✅

**根因**：evo/datasets/ds_f5_b10.npz 缓存缺失（.gitignore 第 23 行 `evo/datasets/*.npz` 不入库，工作区仅有 .meta.json），`--predict` 抛 RuntimeError 被调度链 `; (cmd || echo ...)` 静默吞掉，整体 exit=0。

| 修复 | 验证证据 |
|---|---|
| 重建数据集缓存 | 321.8 万行 × 17 特征；切分 train 1,833,581 / valid 190,883 / test 1,193,922；M5.1 五项验收全过（标签 10 档均衡、索引可逆、无未来函数） |
| predict 恢复落库 | evo_ml_predictions 从仅 20260901 → 新增 **20260902 共 5,530 行**；PSI 漂移告警 4 条显式输出（inter_smart_defense / surprise_earnings_gap / mkt_breadth_20d / mkt_vol_ratio） |
| 调度器分步可观测（scheduler_evo.py） | E2E 实跑 5 步全绿：feature_evo 330.5s / dynamic_weights 35.7s / monitors 50.5s / ml_predict 38.9s / text_daily 66.0s，status=ok；每步完整输出落 logs/evo/scheduler_20260903.log，steps 实时刷新 |
| 失败不再被吞 | 状态机验证：可选步失败 → **partial（exit 2）**且后续可选步继续；必需步失败 → **error（exit 1）**立即终止；步骤清单实时读 evo.yaml（热加载） |
| 顺带修复 | scheduler.log 0 字节问题（独立脚本运行时 logger 默认 WARNING 级别，已 setLevel(INFO)）；config/evo.yaml 重复 lambdarank 键（P1 区 enabled:false 被 P3 区静默覆盖）已删 |

**β 建议：维持 lambdarank_beta = 0.10 灰度，不归零。** 理由：ML 链路已恢复、每日落库可积累真实样本供 M5.2 复评，归零会中断样本积累；但 4 条 PSI 漂移需盯防，若漂移扩大或 M5.2 复评仍 FAIL 再归零（一行配置回滚）。

---

## 四、P1 处置结果（2026-09-03 晚，均已真实数据验证）

### P1-1 动量族方向 → 观察项（告警覆盖）
return_20d 近期窗口 |ICIR| 0.38（全样本 0.29）未达三段翻转判据，**不翻转**；P0-1 接线的 `check_direction_consistency()` 已在 factor_test CLI/HTML 每次测试自动告警（本次冒烟 return_20d 近期窗口已报 ❌ mismatch），下季度审计随样本累积再定。

### P1-2 winner_rate 正向打分权重置零 ✅
证据（2.2）：最低获利盘组 W1 alpha_5d **+1.23%** vs 最高组 W5 **-1.62%**——"获利盘越高越好"的单调正向打分为错。处置（config/thresholds.yaml，三处，各带证据注释）：

| 位置 | 字段 | 改动 |
|---|---|---|
| build_score_left | winner_rate_score | 0.25 → **0.00** |
| build_score_right | winner_rate_rank | 0.25 → **0.00** |
| scanner.scoring_weights | winner_rate_rank | 0.23 → **0.00** |

**保留不动**：硬过滤区间（scanner 25~85、右侧 ≥60 入场门槛、左侧 25~85）与左侧画像的钟形偏好（中枢 60、非单调，与反转证据不冲突）——过滤与钟形不主张"越高越好"。回滚：yaml 三行改回原值。

### P1-3 巡航跨 top_n 稳健性闸门 ✅
- **agent/run_agent.py**：同一因子组合三档 top_n(10/20/30) 超额卡玛**最小值需 ≥ 阈值（0.0）**才可进入全局最优评选/达标部署/续跑历史最优种子；三档未齐者 pending 不入选（续跑补齐后再评）；轨迹报告新增 `robustness_gate` 节逐组落盘；无组合过闸时本次巡航**不部署**（旧行为为自动部署单点最优）。
- **agent/config.yaml 新增 `cruise.robustness_gate`**（enabled: true / min_excess_calmar: 0.0）；回滚 = enabled 改 false。
- **验证**：离线 scratch/verify_p1_3_gate.py 复算 66 格点/22 组合——**0 个组合三档全正**，旧最优 combo10（+0.1977/+0.0063/-0.0495）被正确拦截，yaml 往返不丢配置；新代码巡航完整实跑收官——续跑种子 combo10 弃用、22 个历史组合整组跳过逐组判 fail、3 个新组合（23: pe_ttm/return_5d/turnover_rate {-0.326/-0.372/-0.311}；24: max_drawdown_20d/roe/turnover_rate_20d {-0.229/-0.225/-0.232}；25: max_drawdown_60d/profit_ratio_estimate/return_120d/roe {-0.255/-0.293/-0.252}）全部 fail，**最终 25 组合 75 格点 0 通过**，巡航打印"🛡️ 无任何因子组合通过闸门→本次巡航不部署权重"、best_overall 全部为 None、config.yaml 优雅恢复且 cruise 节保留（logs/cruise_p13_verify_20260903.log）。
- **附带处置**：终止了一个 19:10 启动的旧代码巡航进程（SIGTERM 优雅退出、config 自动恢复），其旧逻辑在收尾会无人确认自动部署刀刃组合。

### P1-4 Graham 加分阈值 4→6 ✅
config/evo.yaml `graham_filter.scoring.bonus_min_checks: 4 → 6`（bonus 为加分项、非硬过滤）。依据 20260902 全市场分布：≥4 项 3,688 只（66.7%，无选择性）/ ≥5 项 1,124（20.3%）/ ≥6 项 507（**9.2%**）/ 7 项 0。penalty（≤1 项 -10 分）不动。回滚：改回 4。

### P1-5 三口径差异根因查明 ✅
根因 = **窗口长度差异**：集成 CSV = 2025H1 六个月（ic_n_days=112）/ 三段审计 = 6.5 年 / EVO 引擎 = 20 日滚动。集成 CSV 与审计同走 factor_lib loader，ST/次新过滤同源施加，**ST 过滤不是差异源**；集成口径强度与审计"近期段"（≥20250101）接近（2025 年后动量/追强反向加剧）。2.1 窗口描述与三口径备注已更正。

### P1-6 在役策略统一口径回测重算落盘 ✅
脚本 scripts/backtest_inservice_strategies.py（临时配置副本、不触碰 config.yaml），结果 **agent/inservice_strategies_backtest_20260903.json**。统一口径：208 周（20220610~20260702）、周频、15bps、等权基准、Top10（在役配置）。

| 策略 | 定位 | 绝对年化 | 超额年化 | 超额卡玛 | 超额回撤 | 超额周胜率 |
|---|---|---|---|---|---|---|
| old_core 老核心静态 | 引擎基线 | -0.16% | **-14.22%** | -0.271 | -52.50% | 41.3% |
| custom_new（在役 config 固定组合）| deployed | +18.60% | **+5.44%** | 0.198 | -27.51% | 49.5% |
| routed 多状态路由 | **生产在役实盘路径** | -0.14% | **-11.79%** | -0.212 | -55.56% | 38.9% |
| jack 游资路由 | 参考（非自动部署）| -7.65% | -21.08% | -0.328 | -64.22% | 40.4% |
| scanner 胜率猎手 | tracker 前瞻 33 推荐日 | — | 全样本 -0.40%（胜率 43.2%）；每日 Top10 +1.22%（胜率 47.2%，按推荐时 factor_score 排名） |

**关键发现**：
1. 在役 config 自定义组合 = **巡航自动部署的 combo10 四因子**（在役基线 config.yaml 的 custom_new_factors = excess_return_20d/max_drawdown_20d/north_net_inflow_ratio/vol_ratio，回测启动时经 config.yaml.bak 取证并已固化进结果 JSON 的 caliber.in_service_config_combo；2026-09-03 12:20 随 regime_weights.pkl 部署）——正是 P1-3 闸门今后拦截的刀刃组合；
2. custom_new 样本内超额 +5.44%，但**生产实盘路径 routed（直接消费 regime_weights.pkl + 路由/防御/轻仓）超额 -11.79%**，且 tracker 前瞻 33 个推荐日 alpha_5d 均值 -0.40%——样本内优势未在实盘兑现，与 2.2/2.3 的过拟合结论互证；
3. 旧临时测算"-13%~-15% 量级"与 old_core(-14.22%)/routed(-11.79%) 实算同量级，**现已有落盘、可复现**。

### P1-7 EVO 近期强负因子 → 观察项（告警覆盖）
inter_quality_momentum（20 日 ICIR -0.96）、surprise_price_vote（-0.90）等不翻转；EVO decay_monitor（20 日滚动 IC、连续 5 日负红警、config/evo.yaml 可配 auto_disable）+ 因子方向告警双盯防；持续 2~3 个权重快照仍为负则下批审计优先复核。

### P2-10 tracker factor_score 单调性监控 ✅（P2 提前处置，2026-09-03 深夜）
- **动机**：P1-2 证明打分权重方向错误要等季度审计才暴露；在 tracker 统计层加"按 factor_score 分组的 alpha 单调性"检查实现早发现。
- **口径**（web/backend/services/performance.py `_calc_score_monotonicity`）：当日内 factor_score pct rank 五分位（消除跨日分数漂移）× 前瞻 alpha(1/3/5/10/20d) 均值 → Spearman(组序, alpha)；主判定 alpha_5d；双窗口 = 全样本 + 近 N 个推荐日（预警）。挂载于 /api/tracker/attribution 追加 `score_monotonicity` 键（前端零影响），reversed 时打 🚨 告警日志。阈值集中在 config/thresholds.yaml `tracker_monotonicity`（enabled:false 一行关闭，只读监控不影响任何链路）。
- **首跑真实结果**：全样本（33 日，n=1518）rho_5d=+0.600 → ok（10d/20d 单调性更好 rho=1.0，打分在中长周期仍有效）；**近 10 推荐日 rho_5d=-0.900 → reversed 告警**（Q5 高分组 alpha +0.39% < Q1 低分组 +1.02%，打分近期反向）——与 2.1"2025 年后追强反向加剧"互证，且被监控在当日捕获而非等待下批审计。

---

## 五、未决项与后续建议

**P1 —— 已全部处置（2026-09-03 晚，详见第四章）**：
1. 动量族方向 → 观察项，方向告警已覆盖（P1-1）
2. winner_rate 正向打分 → 三处权重置零（config/thresholds.yaml，P1-2）
3. 巡航刀刃过拟合 → 跨 top_n 稳健性闸门上线（run_agent.py + config.yaml，P1-3）
4. Graham 无选择性 → bonus_min_checks 4→6（config/evo.yaml，P1-4）
5. 三口径差异 → 根因查明=窗口长度，文档已更正（P1-5）
6. 在役三策略回测 → 统一口径重算落盘（agent/inservice_strategies_backtest_20260903.json，P1-6）
7. EVO 近期强负因子 → 观察项，decay_monitor + 方向告警双盯防（P1-7）

**在役权重处置（已执行，用户授权）**：regime_weights.pkl 系今日 12:20 旧巡航自动部署的刀刃 combo10（样本内 +5.44%，实盘路由口径 -11.79%、tracker 前瞻 -0.40%）。2026-09-03 晚已**回滚为金牌默认权重**（model_trainer 兜底同款：excess_return_20d/north_net_inflow_ratio/profit_ratio_estimate/return_60d/volatility_60d 五因子反转向）；原 combo10 权重备份于 models/regime_weights.pkl.20260903_combo10.bak 与 models/regime_weights_proposed.pkl.20260903_combo10.bak（可回滚）；已验证生产加载路径 load_weights_by_regime('Range') 返回金牌权重、/api/portfolio 10 只真实持仓正常。P1-3 闸门防止今后同类自动部署。

**P2**
8. M5.2 FAIL 的 ML 模型：Top5 可执行收益 0.07% 低于随机 0.46%，建议重训标签（fwd_period/分档）或在复评通过前保持 β=0.1 不上调；同时盯防 4 条 PSI 漂移
9. text_sentiment_score 100% 缺失：文本因子管线覆盖率排查
10. ~~tracker 统计层可增加 factor_score 分组单调性监控~~ → **已上线**（2026-09-03 深夜，P2-10 节）：/api/tracker/attribution 新增 score_monotonicity 监控，首跑即捕获近 10 推荐日打分反向（rho=-0.900）
11. 防御类高 Sharpe 因子（max_drawdown/atr/pe/roe 等 IC≈0 但 Sharpe 1.0~1.58）的定位：明确作为风控/筛选组件而非 alpha 加权，避免巡航/打分误用

**环境铁律（运维备忘）**
- 后端必须用 /Users/lyu/miniconda3/bin/python3（3.13.5），系统 python3 为 3.9.6 不支持 `int | None`；sandbox 内须 `env -i HOME=$HOME PATH=... PYTHONPATH=.` 前缀
- 后端代码改动必须 kill 重启 app.py（cwd=web/backend），旧进程服务旧代码
- 后端当前 PID 22778（2026-09-03 深夜重启，已加载全部 P0/P1 修复 + P2-10 单调性监控；在役权重已回滚为金牌默认）

---

## 附录：证据坐标

| 类别 | 路径 |
|---|---|
| 三段方向审计脚本/结果 | scratch/audit_factor_direction.py、scratch/audit_direction_result.csv、scratch/audit_direction.log |
| 集成因子测试 | factor_test_reports/all_factors_integration_test.csv |
| 翻转的注册表 | factor_lib/registry.py（5 因子 direction_note 含证据） |
| 方向告警代码 | factor_lib/ic_engine.py（check_direction_consistency）、factor_test/cli.py、factor_lib/reporter.py |
| tracker 修复 | scripts/tracker_updater.py、web/backend/services/_common.py |
| ML 数据集/模型 | evo/datasets/ds_f5_b10.npz（重建）、evo/models/lgbmr_20260901.txt |
| 调度器 | web/backend/services/evo/scheduler_evo.py、logs/evo/scheduler.log、logs/evo/scheduler_20260903.log |
| 巡航报告 | agent/auto_cruise_report_20260903.json（66 格点/22 组合，含 robustness_gate 节） |
| P1-3 稳健性闸门 | agent/run_agent.py（闸门逻辑）、agent/config.yaml（cruise.robustness_gate）、scratch/verify_p1_3_gate.py（离线验证）、logs/cruise_p13_verify_20260903.log（在线冒烟） |
| P1-6 在役策略回测 | scripts/backtest_inservice_strategies.py、agent/inservice_strategies_backtest_20260903.json、logs/p16_inservice_backtest_20260903.log、backtest_results_jack.csv、agent/backtest_performance_jack.png |
| P1-2/P1-4 配置改动 | config/thresholds.yaml（winner_rate 三处置零）、config/evo.yaml（bonus_min_checks: 6）、agent/config.yaml（在役基线：top_n 10/multiplier 1.32/combo10 因子，cruise.robustness_gate 闸门开关） |
| P2-10 单调性监控 | web/backend/services/performance.py（_calc_score_monotonicity）、config/thresholds.yaml（tracker_monotonicity 节）、/api/tracker/attribution（score_monotonicity 键） |
| 在役权重回滚凭证 | models/regime_weights.pkl（金牌默认权重）、models/regime_weights.pkl.20260903_combo10.bak 与 models/regime_weights_proposed.pkl.20260903_combo10.bak（原 combo10 备份，可回滚） |
| EVO 验收 | docs/evo_acceptance_report_20260901.md、docs/evo_ml_report_20260901.md |
| 主数据库 | db/stock_data.db（recommendation_tracker / evo_ml_predictions / evo_dynamic_weights_log 等） |
