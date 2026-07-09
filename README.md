# 灵眸分析策略系统 (my_Stock)

灵眸自适应量化分析策略系统是一个基于 Tushare 数据源的、具备因子自我进化与市场状态自适应路由的工业级量化策略控制平台。

## 系统架构与模块
*   `web/`：包含基于 FastAPI 构建的后端接口层，以及基于 Vite + React 构建的高颜值量化策略监控控制台。
*   `agent/`：内置多轨回测引擎（`backtester.py`）、智能推荐决策器（`recommender.py`）以及自适应策略巡航器。
*   `src/`：包含特征工程因子加工中心（`feature_engineering.py`）与回归训练模型。
*   `scripts/`：包含自动更新最新日线与筹码数据的增量同步脚本。

## 📊 数据置信度保证 (Data Confidence)
为解决数据源（如 Tushare）在增量更新时敏感指标（例如筹码集中度/筹码峰占比 `chips_peak_pct`）缺失或下线导致的零值问题，本系统引入了**高精度本地数据自适应重构技术**。

1. **计算公式**：
   通过大样本回归分析，解密并锁定了筹码集中度的重构算法模型：
   $$chips\_peak\_pct = 100 \times \left(1.0 - \frac{cost\_95pct - cost\_5pct}{cost\_95pct + cost\_5pct}\right)$$
2. **置信度评定**：
   在全市场 **5,508 只股票**的对照样本校验中，重构数据与官方数据的 Pearson 相关系数达 **`0.9983`**，决定系数 $R^2$ 达 **`99.67%`**，平均绝对误差仅 **`0.033%`**。
3. **回归红线拦截**：
   系统在 [tests/test_chip_concentration.py](file:///Users/lyu/Documents/my_Stock/tests/test_chip_concentration.py) 中内置了红线回归断言（`R² > 0.996`），并已与构建/发布管线绑定，防止算法在未来重构中退化。
   
   详细验证推导细节请查阅 [筹码集中度验证归档报告](file:///Users/lyu/Documents/my_Stock/docs/verification/chip_concentration_validation.md)。

## 🚀 启动与部署

### 1. 启动后端服务器
```bash
python3 web/backend/app.py
```

### 2. 启动前端控制台
```bash
cd web/frontend
npm run dev
```
打开浏览器访问 `http://localhost:5173`。
