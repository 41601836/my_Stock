/**
 * EvoApi.js —— EVO 进化层前端 API 统一封装
 * 所有请求统一走 /api/evo/* 前缀，永不污染经典层 /api/* 调用
 *
 * 设计：
 *   - 全部 Promise-based；响应体自动解包一层 JSON
 *   - 失败返回 { error: msg } 而不是 throw，便于页面显示模块未就绪的灰色提示
 *   - 与经典层 fetch('/api/xxx') 完全解耦：页面如果要 EVO 数据，只能 import EvoApi
 *   - 每个方法 1:1 对应 routers/evo.py 中的路由
 */

const BASE = '/api/evo'

async function _get (url, opts = {}) {
  try {
    const res = await fetch(BASE + url, { method: 'GET', ...opts })
    if (!res.ok) return { error: `HTTP ${res.status}`, _status: res.status }
    return await res.json()
  } catch (e) {
    return { error: e.message || String(e) }
  }
}

// ================== 状态 & 对比 ==================
export const status         = () => _get('/status')
export const comparePortfolio = (topN = 10) => _get(`/compare/portfolio?top_n=${topN}`)
export const compareScan      = () => _get('/compare/scan')

// ================== 动态权重 ==================
export const weightsDynamic  = () => _get('/weights/dynamic')
export const weightsHistory  = (days = 30) => _get(`/weights/history?days=${days}`)

// ================== 交叉因子 & 因子清单 ==================
export const factorsList    = () => _get('/factors/list')
export const factorsCross   = (date = '', topN = 20) =>
  _get(`/factors/cross?trade_date=${encodeURIComponent(date)}&top_n=${topN}`)

// ================== 拥挤度 ==================
export const crowdingStatus  = () => _get('/crowding/status')
export const crowdingHistory = (factor = '', days = 30) =>
  _get(`/crowding/history?factor_name=${encodeURIComponent(factor)}&days=${days}`)

// ================== Graham 价值雷达 ==================
export const grahamScreen     = (minChecks = 4, topN = 30, date = '') =>
  _get(`/graham/screen?min_checks=${minChecks}&top_n=${topN}&trade_date=${encodeURIComponent(date)}`)
export const grahamScore      = (tsCode, date = '') =>
  _get(`/graham/score/${encodeURIComponent(tsCode)}?trade_date=${encodeURIComponent(date)}`)

// ================== ML 排序学习 ==================
export const mlPortfolio    = (topN = 30) => _get(`/ml/portfolio?top_n=${topN}`)
export const mlShap         = (tsCode, date = '') =>
  _get(`/ml/shap/${encodeURIComponent(tsCode)}?trade_date=${encodeURIComponent(date)}`)

// ================== 预期差 ==================
export const surpriseTop    = (topN = 20, date = '') =>
  _get(`/surprise/top?top_n=${topN}&trade_date=${encodeURIComponent(date)}`)

// ================== 因子衰减预警 ==================
export const decayAlerts    = () => _get('/decay/alerts')
export const decayHistory   = (factor = '', days = 60) =>
  _get(`/decay/history?factor_name=${encodeURIComponent(factor)}&days=${days}`)

// ================== EVO 核心业务接口 ==================
export const portfolio      = (topN = 10) => _get(`/portfolio?top_n=${topN}`)
export const scanOpportunities = (topN = 30) => _get(`/scan-opportunities?top_n=${topN}`)
export const portraitPick   = (topN = 30, strategy = 'left') =>
  _get(`/portrait/position-pick?top_n=${topN}&strategy=${strategy}`)

// ================== 东方财富行情链接 ==================
// ts_code（600363.SH / 300274.SZ / 920206.BJ）→ 东方财富个股页
export const emStockUrl = (tsCode) => {
  if (!tsCode) return '#'
  const [code, exch] = String(tsCode).split('.')
  const p = exch === 'SH' ? 'sh' : exch === 'BJ' ? 'bj' : 'sz'
  return `https://quote.eastmoney.com/${p}${code}.html`
}

// 模块标签图标映射（UI 渲染 badge 用）
export const MODULE_META = {
  dynamic_weights:  { label: '动态权重',  icon: '⚖️',  color: 'text-sky-300' },
  cross_factors:    { label: '交叉因子',  icon: '🔀',  color: 'text-purple-300' },
  crowding_monitor: { label: '拥挤度监控', icon: '🧍',  color: 'text-amber-300' },
  lambdarank:       { label: 'ML排序',    icon: '🧠',  color: 'text-emerald-300' },
  surprise_factors: { label: '预期差',    icon: '🎯',  color: 'text-fuchsia-300' },
  text_factors:     { label: '文本因子',  icon: '📰',  color: 'text-indigo-300' },
  graham_filter:    { label: 'Graham',    icon: '🛡️',  color: 'text-rose-300' },
  decay_monitor:    { label: '衰减预警',  icon: '📉',  color: 'text-orange-300' },
}

export default {
  status, comparePortfolio, compareScan,
  weightsDynamic, weightsHistory,
  factorsList, factorsCross,
  crowdingStatus, crowdingHistory,
  grahamScreen, grahamScore,
  mlPortfolio, mlShap,
  surpriseTop,
  decayAlerts, decayHistory,
  portfolio, scanOpportunities, portraitPick,
  MODULE_META,
}
