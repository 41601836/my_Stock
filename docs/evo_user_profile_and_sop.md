# EVO 层用户画像 & 运营 SOP

> 生成日期：2026-09-02 ｜ 依据：EVO 层阶段 0~6 全程协作记录
> 配套文档：[evo_roadmap_stage5_6.md](evo_roadmap_stage5_6.md) ｜ [evo_ml_report_20260901.md](evo_ml_report_20260901.md) ｜ [evo_acceptance_report_20260901.md](evo_acceptance_report_20260901.md)

---

## 第一部分：用户画像

### 1.1 投资者/决策者画像

| 维度 | 画像 | 证据（来自实际决策） |
|------|------|---------------------|
| 风险风格 | **稳健偏理性，先防错后求收益** | 要求三道安全闸、拥挤度熔断、管线失败隔离；Graham 防御池优先级高 |
| 创新态度 | **愿试新但零风险试错** | 接受 AI/ML/文本因子全部新模块，前提是「平行层 + 一行配置回滚」 |
| 决策模式 | **建议→我来决定→开工；里程碑逐个验收** | 「你只要给出建议，我来做决定」→「按这个方案开始实现」→ 逐阶段下指令（M5.1、M5.2…） |
| 授权深度 | **后期全权委托，但要证据链** | 「我不再值守，由你全权完成剩余任务，不再向我询问或确认，直至新增项目完成验证」 |
| 使用习惯 | **移动端查看，重视可达性** | 主动反馈「手机端 evo 按钮无法显示」并要求补齐 |
| 严谨性要求 | **拒绝无依据数字，要真实数据** | 逐项审计要求「完整性、引用数据严谨性」→ 虚构统计（如「降低回撤 20-30%」）必须清除 |

### 1.2 协作偏好（对 AI 助手的期望）

1. **先规划后动手**：大改动先出方案文本，确认后再写代码（「给出建议，暂不操作！」）
2. **最小增量修改**：偏好小段 Edit 补丁，反对整文件重写（历史回退教训）
3. **零侵入红线**：经典层路由/服务/配置/UI 一律不碰，新功能全部走独立前缀 + 独立目录
4. **验收驱动**：每个阶段以「冒烟 PASS + 真实非空数据」收尾，不接受只看 HTTP 200
5. **沟通语言**：中文，简洁直接，表格化汇报

### 1.3 技术环境画像

- 解释器：`/Users/lyu/miniconda3/bin/python3`（3.13.5；系统 3.9.6 缺依赖不可用）
- 服务形态：后端 `python3 app.py`（8000 端口）+ 前端 vite dev（5173，开发态）
- 数据库：SQLite WAL，`db/stock_data.db`（63+8 张表，factor_values 316 万行）
- 配置中心：`config/evo.yaml`（所有 EVO 调整只动这一个文件）

---

## 第二部分：EVO 层日常运营 SOP

### SOP-1 每日自动流程（无需人工干预）

```
交易日 19:30 / 21:30  经典层：数据更新 → 因子工程 → 健康检查（原有流程）
交易日 20:30 / 22:30  EVO 层五步管线（scheduler_evo.py，失败逐级隔离）：
  ① 因子工程 feature_engineering_evo.py   ~4min  UPSERT factor_values_evo
  ② 动态权重 evo_dynamic_weights.py       ~20s   20 日快照 REPLACE
  ③ 监控 evo_monitors.py                  ~35s   拥挤度 + 衰减 + IC 序列
  ④ ML 推理 evo_ml_rank.py --predict      ~15s   rank_score + SHAP + PSI
  ⑤ 文本 evo_text_pipeline.py --daily     ~4min  采集 → 打分 → 回填
```

- 管线状态：`GET /api/evo/scheduler/status`（下次执行时间 / 最近结果）
- 手动补跑：`POST /api/evo/scheduler/run`（幂等，可重复执行）

### SOP-2 每日人工巡检（5 分钟清单）

| # | 检查项 | 入口 | 合格标准 |
|---|--------|------|---------|
| 1 | 管线最新数据日期 | `/api/evo/factors/cross` 的 trade_date | = 最近交易日 |
| 2 | EVO 组合有值 | `/evo/compare` 右表 | 名称/因子分/等级非「—」 |
| 3 | 衰减红色警报 | `/api/evo/decay/alerts` 中 level=red | 有则评估是否手动降权 |
| 4 | PSI 漂移 | `evo_decay_alerts` 表 metric=psi | >0.25 的因子进入观察名单 |
| 5 | 熔断状态 | `/evo/compare` 顶部徽章 | 熔断时以经典组合为主决策 |

### SOP-3 常见调整操作（全部只改 config/evo.yaml）

| 意图 | 操作 | 生效 |
|------|------|------|
| ML 权重加码/回退 | `portfolio_mixer.lambdarank_beta: 0.10 → 0.30`（或 `0` 回纯动态权重） | 即时（组合实时计算） |
| 关闭某模块 | 对应模块 `enabled: false` | 即时 + 管线跳过该步 |
| 放宽 Graham | `graham_filter.min_checks: 4 → 3` | 即时 |
| 拥挤度阈值 | `crowding_monitor.half_weight_threshold / disable_threshold` | 次日管线 |
| 换 NLP 模式 | `text_factors.mode: rules → local/llm`（需先装依赖/配 provider） | 次日管线 |

> 调整后验证：`GET /api/evo/status` 看 modules 布尔；`/evo/compare` 看组合变化。

### SOP-4 故障处理 Runbook

**F1 接口返回空/页面显示「—」**，按顺序排查：
1. 数据未生成 → 查 `SELECT MAX(trade_date) FROM factor_values_evo` 是否落后
2. 参数校验 422 → top_n 有 `ge` 下限（如 graham/screen top_n≥5），看响应 detail
3. 前后端键不匹配 → 打印接口原始 JSON，对照前端取值键（本项目已发生 3 次，均有 `||` 兜底）
4. 旧进程未重启 → 改过后端代码必须重启 `python3 app.py`（kill 旧 PID → 重新启动）

**F2 管线某步失败**：
- 看后端日志该步异常；单步失败不影响其余步（`|| true` 隔离）
- 因子步失败常见 = 新列缺失/列名冲突 → 检查 merge suffixes 与兜底补列逻辑
- 修复后 `POST /api/evo/scheduler/run` 补跑（幂等）

**F3 页面行为与代码不符**：
- vite dev 看护进程可能陈旧 → 重启 vite；或浏览器强刷（Cmd+Shift+R）
- 后端改代码未重启（本项目最高频坑）→ 重启后端

**F4 数据库锁/任务卡死**：
- 查僵尸 python 进程（`ps aux | grep python`）；SQLite WAL 下修复脚本持锁会阻塞写入

### SOP-5 升级新能力（沿用里程碑式流程）

```
M.x.1 数据/管道 → M.x.2 训练/验证（先回测达标）→ M.x.3 接口/落库 → M.x.4 灰度接入（β 从小到大）
```
- 验收标准先行（如 M5.2 的「NDCG 相对基线 +2%」），不达标不进下一步
- 新因子自动进全链：`_common.get_enabled_factor_cols()` 动态发现，非空率达标自动激活
- 每个新能力：独立开关 + 独立表 + 失败隔离 + 一行回滚

### SOP-6 红线清单（每次改动前自查）

- [ ] 经典层 `/api/*` 路由、`services/*`（evo 包除外）、`thresholds.yaml` 零改动
- [ ] 经典前端页面与 `fetch('/api/*')` 调用零改动
- [ ] EVO 表只带 `_evo` 后缀；对 `factor_values` 等经典表只读不写
- [ ] UI 文案不出现无依据统计数字；画像/Graham 量纲明确区分（0~100 vs X/7）
- [ ] 改后端必重启；改前端验证 vite build；收尾必跑冒烟三件套（status / factors/cross / compare）

---

## 附：当前系统基线（2026-09-02）

- 模块状态：8 模块 7 开 1 关（lambdarank=true β=0.1 灰度；text=rules 模式）
- 数据规模：factor_values_evo 316 万行（20200302~20260831）；EVO 表 8 张
- 关键阈值：拥挤度 0.70/0.85；熔断 20%；Graham min_checks=4；β=0.10
- 权重引擎：ICIR 加权，当前有效因子 3 个（超跌反转/换手反转/ROE 预期差），其余因 IC 为负自动置 0
