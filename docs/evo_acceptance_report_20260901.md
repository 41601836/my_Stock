# EVO 层全量建设验收总结报告

> 日期：2026-09-01
> 范围：阶段 0（骨架）→ 阶段 1-1（因子工程）→ 阶段 2（动态权重）→ 阶段 2.5（每日调度）→ 阶段 3（拥挤度+衰减）→ 阶段 5（ML 排序 M5.1~M5.4）→ 阶段 6（文本因子 M6.1~M6.4）
> 核心约束：**零侵入经典层**（所有改动均在新增 EVO 路由层内完成）

---

## 一、总体结论

| 项 | 结论 |
|---|---|
| 建设完成度 | 规划 8 模块全部落地（阶段 0/1-1/2/2.5/3/5/6），仅 M6.4（local/LLM 升级）按规划跳过 |
| 最终验收 | **12/12 PASS**（TestClient 真实调用 app，覆盖调度、8 组 API、零侵入确认） |
| 零侵入确认 | 经典 30+ 路由 0 改动、services 0 改动、14 个前端页面 0 改动、经典表 0 写入 |
| 自动化 | 每晚 19:30/21:30 五步管线全自动，失败隔离，零人工干预 |

---

## 二、双轨平行架构（零侵入证据）

```
经典层（未动）                          EVO 层（全部新增）
/api/*（30+ 路由）                     /api/evo/*（22+ 接口）
/dashboard 等 14 页面                  /evo/*（Dashboard/Compare/Graham）
services/*（经典逻辑）                 services/evo/（独立包）+ routers/evo.py
factor_values（316 万行，只读）         factor_values_evo（316 万行 UPSERT）
19:30/20:30 经典调度                   19:30/21:30 EVO 调度（独立实例）
```

**唯一接入点**（共 2 处，均 try/except 包裹）：
- 后端：`app.py` 末尾 `include_router(evo_router)`
- 前端：`App.jsx` 末尾一条 `/evo/*` 条件路由 + 顶栏开关按钮（localStorage）

### 三道安全闸（全部实测触发过）

| 闸 | 机制 | 实测证据 |
|---|---|---|
| 1 前端开关 | localStorage + 条件路由，关 EVO 强制回 /dashboard | 构建通过 + 路由守卫生效 |
| 2 模块开关 | evo.yaml 8 模块 enabled，全关时调度自动跳过 | lambdarank 默认关 → 灰度前 ML 只写表不进组合 |
| 3 重合度熔断 | EVO 与经典推荐 overlap < 20% → `fused_by_fallback=True` 降级标记 | 实测 overlap=0 → 正确触发 |
| ＋新增 | 拥挤度自动降权（≥0.85 disable / ≥0.70 half_weight） | `surprise_roe_qoq` 拥挤度 0.968 → 组合端自动置 0 |

---

## 三、各阶段交付与验收数据

### 阶段 1-1：EVO 因子工程
- 10 交叉因子（两两 rank 乘积再归一）+ 3 预期差代理 + Graham 7 项防御评分
- `factor_values_evo`：3,157,334 行（20200302~20260831），UPSERT 28s
- 最新日交叉因子覆盖率 10/10=100%，预期差 99.8~100%，Graham 4+ 项股票 3,687 只

### 阶段 2：IC/ICIR 动态权重
- 160 交易日窗口向量化 Spearman IC → 20 日 ICMean/ICIR 加权 → water-filling 上限约束 → 权重和严格=1.0
- 真实发现：2026 年动量/价值/筹码类因子 IC 全为负，仅「反转三兄弟」有效（超跌反转 IC=+0.154/ICIR=0.60 等），引擎自动完成降权

### 阶段 2.5：每日调度
- 周一~五 19:30/21:30，防重入锁 + misfire 补跑 + 1800s 超时
- 实测手动触发全管线 186s（现五步约 8~9min，余量 2 倍）

### 阶段 3：拥挤度监控 + 因子衰减预警
- 拥挤度 = 因子截面 rank 日间自相关（10 日均值）；衰减 = 滚动 20 日 RankIC（连续 5 日 <0 → red）
- 实测：disable×5 / half_weight×6 / normal×3；市场警报（成交额前 5% 占比 45.6%>45%）；red×2 / yellow×8
- 与组合端联动验证：crowding_filter=True 生效，TopN 名单正确换血

### 阶段 5：LambdaRank ML 排序

| 里程碑 | 结果 |
|---|---|
| M5.1 数据集 | 3,207,324 样本（>300 万线），严格时间序 70/15/15，无未来函数，10 档标签均衡 |
| M5.2 训练+回测 | 测试段 NDCG@10 **0.3580 vs IC 基线 0.1802（+98.7%，验收线 +2%）**；Top5 组合 29.5% vs 4.7%；best_iter=11 仅 21s |
| M5.3 每日推理 | 5,529 行/日 + 17 项 SHAP + PSI 漂移检测（已自动产出 4 条 red 警报）落 `evo_ml_predictions` |
| M5.4 β 灰度 | mixer 公式完整化：`dyn + β×ml_rank + δ×surprise_mean + graham_adj`；β=0.1 起步，一行配置可回滚（改回 0） |

> ⚠️ 右尾警示（详见 docs/evo_ml_report_20260901.md）：回测经过 3 层口径修正（T+1 成交 + 涨停剔除）后仍有题材市连板暴利票集中在标签右尾，**灰度期以相对基线超额为决策依据，绝对收益不作预期**（未建模交易成本/容量/滑点）。

### 阶段 6：文本情绪因子

| 里程碑 | 结果 |
|---|---|
| M6.1 采集 | P0 双源：巨潮公告（secCode 直出 100% 个股归属）+ 新浪 7x24（伪 URL 去重）；限速 2s、源隔离降级 |
| M6.2 打分聚合 | 词典 40 利好+38 利空+15 催化（⊕yaml 可扩充），否定词翻转+程度副词+tanh+置信收缩；0.6^天衰减聚合 → [0,1] 截面 rank 回填 `factor_values_evo`；**覆盖 1,915 只 ≥1,500 ✅，非空率 34.2% ≥30% ✅**；语料 `evo_text_raw` 10,038 条 |
| M6.3 进全链 | `get_enabled_factor_cols` 纳入 text → IC/权重/ML 三链自动发现；ML 数据集 17 特征含 text；**SHAP 18 项全表 5,529 行均含 text_sentiment_score** |
| M6.4 local/LLM | transformers/torch 未安装、llm_provider 未配置 → 按规划跳过，rules 模式已可用 |

---

## 四、最终验收清单（12/12 PASS）

```
[PASS] scheduler.五步管线     因子→权重→监控→ML推理→文本（失败隔离）
[PASS] status.8模块
[PASS] factors.cross         date=20260901 count=5
[PASS] graham.screen         total=5 count=5
[PASS] weights.dynamic       factors=14（含 text w=0）
[PASS] crowding.status       factors=15
[PASS] ml.portfolio          date=20260901 count=5
[PASS] ml.shap+text因子      shap=18 text=True
[PASS] compare.portfolio+mixer  evo=5 ml=True dyn=True β=0.1
[PASS] decay.alerts          alerts=15
[PASS] 零侵入.经典路由        /api/portfolio 200
[PASS] 零侵入.EVO表独立       8 张 EVO 表；经典 316 万行未受影响
```

---

## 五、8 张 EVO 表

`factor_values_evo` / `evo_dynamic_weights_log` / `evo_crowding_log` / `evo_decay_alerts` / `evo_ml_predictions` / `evo_text_sentiment_scores` / `evo_factor_ic_daily` / `evo_text_raw`（全部 UNIQUE/主键幂等，重复运行安全）

---

## 六、过程中发现并修复的关键问题（工程经验沉淀）

| # | 问题 | 修复 |
|---|---|---|
| 1 | `vol_ratio` 列因 merge suffixes 冲突 KeyError | 按缺列按需 merge + COALESCE 兜底 |
| 2 | sqlite3 默认 tuple 连接 `dict(r)` 崩溃 | 统一 RowFactory / 手动 zip 列名 |
| 3 | 权重归一在少量有效因子时失败（3×0.30<1） | water-filling + 上限自适应放宽 |
| 4 | Z-score(±5) 混入 rank(0~1) 池导致权重越界 | 打分前统一当日截面 pct rank |
| 5 | 经典层 `stock_code` vs EVO `ts_code` 重合度恒 0 | 双键兼容提取 |
| 6 | **巨潮接口 `column` 参数无效且单查询上限 40 页**（覆盖率卡 1,180 只） | 按日切片查询（6 日×40 页）突破，覆盖率 → 1,915 只 |
| 7 | **`NaN or 0.0` 返回 NaN**（NaN 为 truthy），text 因子全历史 NaN 污染权重归一 → 全部权重 NaN | `fillna(0)` + 显式 NaN 判断 |
| 8 | `INSERT OR REPLACE` 未覆盖旧 schema 行（ALTER 补列后旧行残留 17 项 SHAP） | 清空重写 predict 结果 |
| 9 | pandas 2.x `groupby.apply` include_groups 警告 | 显式 `include_groups=False` |
| 10 | apscheduler Job 在 start() 前无 next_run_time | start 后再收集状态 |

---

## 七、已知限制与后续建议

1. **text 因子尚无历史 IC** → 权重 w=0，属正确行为；随每晚管线积累 `evo_factor_ic_daily`，预计 20 个交易日后自动参与动态权重。若需加速，可对 `evo_text_raw` 补跑历史日回填。
2. **β 灰度观察期**：建议跟踪 3~5 天 `/api/evo/ml/portfolio` 每日 Top5 次日表现；看好 → `lambdarank_beta: 0.30`；不看好 → 改回 0（一行回滚）。
3. **M6.4 升级路径**：安装 `transformers+torch`（local FinBERT）或在 evo.yaml 配置 `llm_provider/llm_api_key_env`（API 模式），代码位已预留。
4. **数据源健壮性**：新浪 7x24 与巨潮为公开接口，无 SLA；采集层已做限速+隔离降级，极端情况仅文本因子停更，不影响其他四步。
5. **ML 模型再训练**：当前为静态模型（20260901 版）；建议每月重跑 `--force + --train` 刷新，或后续挂入月度调度。

---

## 八、关键文件索引

```
config/evo.yaml                              8 模块配置 + 超参（唯一调参入口）
src/feature_engineering_evo.py               因子工程（10 交叉+3 预期差+Graham）
src/evo_dynamic_weights.py                   IC/ICIR 权重引擎 + get_enabled_factor_cols
src/evo_monitors.py                          拥挤度 + 衰减监控
src/evo_ml_rank.py                           ML 数据集/训练/推理/PSI
src/evo_text_pipeline.py                     文本采集/打分/聚合（--fetch/--score/--daily/--backfill）
web/backend/services/evo/                    _common.py（配置+DDL+Graham+熔断）、portfolio_evo.py（mixer）、scheduler_evo.py（调度）
web/backend/routers/evo.py                   22+ 接口（/api/evo/*）
web/frontend/src/evo/                        EvoLayout/Dashboard/Compare/Graham + EvoApi.js
docs/evo_roadmap_stage5_6.md                 阶段 5/6 规划
docs/evo_ml_report_20260901.md               ML 评估报告（含右尾警示）
```
