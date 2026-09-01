# EVO 进化层 — 阶段 5 / 阶段 6 长期规划

> 范围：LambdaRank 排序学习（阶段 5）+ 文本情绪因子（阶段 6）
> 硬约束（沿用）：**零侵入经典层** —— 所有代码、表、路由、前端变更全部在 EVO 层内
> （`/api/evo/*` 路由、`services/evo/`、`src/evo_*.py`、`evo_*` 表、`/evo/*` 前端页）。
> 本文替代早期「需积累 120 日数据」的说法：`factor_values_evo` 已含 20200302~20260831
> 全历史因子值（约 1560 交易日 × 5000+ 股），**训练数据已充足**，阶段 5 可直接进入
> 回测验证；真正需要「积累」的是每日调度下动态权重基线的实盘运行记录，用于对比。

---

## 0. 当前基线（阶段 0~3 已交付）

| 已有能力 | 位置 | 关键数字 |
|---|---|---|
| 13 因子全历史（10 交叉 + 3 预期差 + Graham 7 项） | `factor_values_evo` 315 万行 | 20200302~20260831 |
| IC/ICIR 动态权重（20 日滚动，water-filling 上限） | `evo_dynamic_weights_log` | 3 有效因子，权重和=1 |
| 拥挤度监控（rank 日间自相关 + 全局成交额集中度） | `evo_crowding_log` | disable×5 / half×6 |
| 因子衰减预警（滚动 20 日 RankIC 黄/红） | `evo_decay_alerts` / `evo_factor_ic_daily` | 2 红 8 黄 |
| 每日调度（19:30/21:30 三步管线） | `services/evo/scheduler_evo.py` | 因子→权重→监控，186s |
| EVO 组合雏形（动态权重×截面 rank + Graham ±0.5） | `services/evo/portfolio_evo.py` | 熔断联动已验证 |
| 预留骨架 | `evo_ml_predictions` / `evo_text_sentiment_scores` 表、`text_sentiment_score` 列、`/ml/*` `/decay/*` 接口 | 待本文两阶段填充 |
| 组合融合配置 | `evo.yaml → portfolio_mixer` | α=0.5 β=0.3 γ=0.1 δ=0.1 ε=0.15 |

**已知市场事实（2026 年前 8 个月）**：动量/价值/筹码类因子截面 IC 为负，仅
「超跌反转 / 放量换手反转 / ROE 预期差」有效 → 静态权重不可行，动态权重与 ML
排序是正确的进化方向；2026 市场成交额前 5% 占比 45.6% 已触发全局拥挤警报。

---

## 1. 阶段 5：LambdaRank 排序学习（ML 排序层）

### 5.1 目标

用排序学习模型（LambdaRank 目标）替代/增强「IC 加权线性打分」：
- 直接优化 **TopN 排序质量**（NDCG@10），而非全截面相关性；
- 自动学习**非线性因子交互**（如「低位 × 超跌」的阈值效应，线性加权无法表达）；
- 与动态权重形成**双引擎对比**：β 权重灰度切换，谁好用谁上。

### 5.2 数据与标签

- **特征（X）**：13 个 EVO 因子（当日截面 pct rank 统一量纲）+ `graham_score`
  + `text_sentiment_score`（阶段 6 上线后自动纳入）+ 2 个市场状态特征
  （`regime_detector` 的标签？→ 不依赖经典层，用 EVO 自己算的指数 20 日趋势
  与波动率分位，仅 2 列，只读 daily_prices）。
- **标签（y）**：未来 `fwd_period=5` 日复权收益 → 当日截面分 10 档（0~9），
  与权重引擎的 fwd_period 保持一致，避免周期错配。
- **query group**：每个交易日 = 一个 query（LambdaRank 按 query 内排序）。
- **切分（严格时间序，防前视）**：
  - 训练：20200302 ~ 20241231（~70%）
  - 验证：20250101 ~ 20250630（~15%，早停 + 调参）
  - 测试：20250701 ~ 20260831（~15%，只评估一次，绝不回头调参）

### 5.3 技术方案与依赖决策

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 纯 numpy 手写 LambdaRank | 零新依赖 | 实现复杂、训练慢、易写错梯度 | 不采用 |
| **LightGBM `objective=lambdarank`** | 成熟稳定、单包无重依赖、CPU 快、自带 NDCG | 新增一个 pip 依赖 | **采用** |
| XGBoost `rank:pairwise` | 同上 | pairwise 在 5000 股大 query 上更慢 | 备选 |

**依赖策略**：`pip install lightgbm` 由用户手动安装；代码侧 **lazy import + 优雅
降级**——未安装时即便 `lambdarank.enabled=true` 也只记 warning 跳过，绝不影响
其他模块与后端启动（沿用阶段 1 的依赖纪律）。

### 5.4 管线与产物

```
src/evo_ml_rank.py            # 新建（阶段 5 唯一主脚本）
  ├─ build_dataset()          # 复用 build_ic_df() 的加载模式 + graham + 市场状态 2 列
  ├─ train()                  # LightGBM lambdarank，时间序切分，早停，模型存 evo/models/lgbmr_YYYYMM.txt
  ├─ evaluate()               # 测试段 NDCG@10 / Top5 收益 vs IC 加权基线 vs 均匀
  ├─ predict_daily()          # 每日推理：预测分 → evo_ml_predictions（UPSERT）
  └─ psi_check()              # 特征/预测分布漂移 PSI > 0.25 → 写 decay_alerts 级别=red 说明
```

- 模型文件放 `evo/models/`（新目录，EVO 专属）。
- `evo_ml_predictions` 表已有骨架，如列与训练输出不匹配，在 M5.1 时以
  `ALTER TABLE ... ADD COLUMN` 增列（EVO 层自有表，允许）。
- 调度：`scheduler_evo.py` 管线扩为四步 `因子 → 权重 → 监控 → [ml 推理]`
  （仅 `lambdarank.enabled=true` 时执行，第四步失败不影响前三步——用 `;`
  而非 `&&` 连接，退出码单独记录）。**重训**：每月第一个交易日跑 `train()`。

### 5.5 里程碑与验收（顺序执行，每步可独立回滚）

| 里程碑 | 内容 | 验收标准（可测） |
|---|---|---|
| M5.1 | 数据集管道 + 标签构造 + 缺失处理 | 测试集构建成功：样本数 > 300 万行、无未来函数泄漏（抽查 t 日特征是否含 t+1 数据） |
| M5.2 | LightGBM 训练 + 回测对比 | 测试段 NDCG@10 ≥ IC 加权基线 +2%；Top5 组合 5 日收益年化差 > 0；报告落 `docs/evo_ml_report_*.md` |
| M5.3 | 每日推理接入 + `/ml/portfolio` `/ml/shap/{code}` 真实化 | TestClient 冒烟 200；shap 输出 top3 贡献因子 |
| M5.4 | 灰度接入组合（β: 0 → 0.1 → 0.3） | `portfolio_mixer.beta` 逐步调大；`/compare/portfolio` 双引擎分数均可见；重合度熔断持续监控 |

**回滚**：任何一步异常 → `evo.yaml lambdarank.enabled=false`（安全闸 2），
管线第四步自动跳过，β 退回 0，回到纯动态权重模式。

---

## 2. 阶段 6：文本情绪因子（NLP 层）

### 6.1 目标

为个股引入「市场叙事温度」：新闻/公告/讨论的情绪分，作为第 14 个因子自动进入
IC 矩阵、动态权重池与 ML 特征（`get_enabled_factor_cols` 是动态列发现，因子列
有值且配置启用即自动纳入——阶段 1 设计的扩展点）。

### 6.2 数据源（分档接入，先稳后猛）

| 优先级 | 数据源 | 获取方式 | 风险 |
|---|---|---|---|
| P0 | 巨潮公告标题/摘要 | 巨潮公开接口（慢速轮询） | 稳定，合规性好 |
| P0 | 财联社电报/新闻标题 | RSS 或公开页面轮询 | 结构可能变，需适配层 |
| P1 | 东财股吧/雪球讨论 | 爬虫 | 反爬脆弱 + 水军噪声 + 合规风险，**后置且仅研究用途** |
| P2 | 龙虎榜异动文本 | Tushare 已有接口 | 文本短、信号弱，可选 |

**采集纪律**：限速（≥2s/请求）、每日增量、源适配层隔离（单一源挂掉只降级不阻塞
管线）、遵守 robots 与站点条款。

### 6.3 NLP 方案三档（`text_factors.mode` 渐进升级）

| mode | 方法 | 依赖 | 预期精度 | 定位 |
|---|---|---|---|---|
| `rules`（当前值，先跑通） | 财经情感词典打分：大连理工情感词汇本体 + 自建 A 股利好/利空词表（涨停、中标、业绩预增 / 立案、减持、商誉减值…），否定词与程度副词处理 | 零依赖，纯 python | 中低但可解释 | M6.1~M6.2 |
| `local` | 本地中文金融 BERT（FinBERT-Chinese 类，CPU 推理批量打分） | transformers + 模型权重（数百 MB） | 高 | 可选，Mac CPU 慢，批量夜跑 |
| `llm` | evo.yaml 已预留 `llm:` null 配置位（OpenAI 兼容接口），批量摘要+情绪+置信度 JSON 输出 | API 费用 | 最高、带理由 | 成本敏感后置 |

### 6.4 管线与表

```
src/evo_text_pipeline.py     # 新建（阶段 6 唯一主脚本）
  ├─ fetch_news()            # 各源适配器 → evo_text_raw（新增表：source/url/title/content/published_at/ts_code?）
  ├─ match_stocks()          # 股票名/代码/别名匹配（复用 db 层拼音/别名索引，只读）
  ├─ score_texts()           # 按 mode 分档打分（-1~1 + confidence）
  ├─ aggregate()             # 个股近 3 日时间衰减加权均值 × log(1+条数)；条数 <5 → NaN（不硬猜）
  └─ persist()               # evo_text_sentiment_scores（明细）+ 回填 factor_values_evo.text_sentiment_score（当日截面 0~1 rank）
```

新增表仅 `evo_text_raw` 一张（`ensure_evo_tables` 增 DDL，EVO 层自有）。
调度接入同阶段 5：管线第五步，独立失败隔离。

### 6.5 里程碑与验收

| 里程碑 | 内容 | 验收标准（可测） |
|---|---|---|
| M6.1 | P0 数据源采集 + 落库 | `evo_text_raw` 日增 > 500 条；重复 URL 去重率 < 5% |
| M6.2 | rules 词典打分 + 个股聚合 | 有情绪分的股票 ≥ 1500 只/日；`text_sentiment_score` 非空率 ≥ 30% |
| M6.3 | 进因子池验证 | 监控脚本自动纳入后：观察 20 日，IC 序列入 `evo_factor_ic_daily`；ICIR > 0 才保留 |
| M6.4 | 可选升级 local/llm | 对比 rules 的 IC 提升；费效比记录 |

**回滚**：`text_factors.enabled=false` → 采集/打分跳过；`factor_values_evo` 的
text 列停止更新但历史保留；因子池动态发现自动排除（列有值但配置关 → 不进池）。

---

## 3. 组合接入：portfolio_mixer 各项的生效时刻表

| 项 | 含义 | 状态 |
|---|---|---|
| α=0.5 | 动态权重打分 | **已生效**（阶段 2，经 `dynamic_part`） |
| β=0.3 | ML 排序分 | 阶段 5 M5.4 灰度生效 |
| γ=0.1 | Graham 画像分 | **已生效**（阶段 2，`graham_adj` ±0.5） |
| δ=0.1 | 预期差分 | 部分生效（surprise 已在权重池内；δ 预留给独立惊喜度加权） |
| ε=0.15 | 拥挤度惩罚 | **已生效**（阶段 3，`_effective_weights` disable/half） |

> 实现注：当前 `calc_evo_portfolio` 用「dynamic + graham_adj」的简化合成，
> M5.4 时把 β×ml_pred、δ×surprise_bonus 显式展开为完整 mixer 公式，保持
> `evo_score` 可解释输出（`factor_components` 已预留）。

---

## 4. 配置/依赖变更清单（全部 EVO 层内）

| 项 | 变更 | 阶段 |
|---|---|---|
| `config/evo.yaml` | `lambdarank` 段新增超参（num_leaves/lr/num_boost_round/label_gains）；`text_factors` 段新增 sources/fetch_cron/min_posts | M5.1 / M6.1 |
| pip | `lightgbm`（用户手动装，lazy import 降级） | M5.2 |
| `evo_ml_predictions` | 如列不足 `ALTER TABLE` 增列 | M5.1 |
| `ensure_evo_tables` | +`evo_text_raw` DDL | M6.1 |
| `scheduler_evo.py` | 管线 4 步（ml）→ 5 步（text），各自 enabled 判断 + 独立失败隔离 | M5.3 / M6.2 |
| `routers/evo.py` | `/ml/portfolio` `/ml/shap/*` 真实化（骨架已在） | M5.3 |
| 前端 `evo/` | 新页 `EvoML.jsx`（NDCG 曲线 + 预测 TopN + SHAP 卡片）、`EvoText.jsx`（情绪热力榜）；仅追加路由，不动经典 14 页 | M5.3 / M6.3 |

## 5. 执行顺序总览

```
M5.1 数据集 ─→ M5.2 训练+回测 ─→ M5.3 推理接入 ─→ M5.4 β 灰度
                                                      │
M6.1 采集 ─→ M6.2 rules 打分 ─→ M6.3 进池验证 ─→ M6.4 可选升级
```

- 5 与 6 **可并行**（互不依赖）；M6.3 完成后 text 因子自动进入 5 的特征集。
- 每个里程碑完成后跑一次 `scratch/smoke_evo_*.py` 式全链冒烟（5 接口以上）。
- 每月复盘：`evo_factor_ic_daily` 全因子 IC 热力图 + 权重漂移 + 拥挤度分布，
  决定是否调 `min_ir_for_weight` / 拥挤度阈值 / mixer 权重。
