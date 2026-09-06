import React, { useState, useEffect } from 'react'
import {
  Layers, RefreshCw, Info, ChevronRight,
  TrendingUp, AlertTriangle, BarChart2, Activity,
  Target, Shield, Zap, ExternalLink, Sparkles,
} from 'lucide-react'

/**
 * Resonance —— 四维选股 · 四重共振策略看板
 * ============================================
 * 零侵入平行层：独立路由 /resonance，独立组件，删除即回滚。
 *
 * 四维：筹码 × 资金 × 板块 × 情绪
 * 共振越强，仓位越重。
 *
 * 3 个 Tab：
 * - 共振排行：Top-N 共振股票列表 + 四维雷达图展开
 * - 卖出信号：三重铁律卖出信号监控
 * - 四维IC：各维度 IC 表现对比
 */

const API_BASE = '/api/resonance'

// ── 四维配色 ──────────────────────────────────────────────
const DIM_COLORS = {
  chip:      { name: '筹码', color: '#10b981', bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/30' },
  capital:   { name: '资金', color: '#06b6d4', bg: 'bg-cyan-500/20',    text: 'text-cyan-400',    border: 'border-cyan-500/30' },
  sector:    { name: '板块', color: '#f59e0b', bg: 'bg-amber-500/20',   text: 'text-amber-400',   border: 'border-amber-500/30' },
  sentiment: { name: '情绪', color: '#8b5cf6', bg: 'bg-purple-500/20',  text: 'text-purple-400',  border: 'border-purple-500/30' },
}

const DIM_KEYS = ['chip', 'capital', 'sector', 'sentiment']

// ── 共振等级配置 ──────────────────────────────────────────
const RESONANCE_LEVELS = {
  strong: { label: '强共振', color: '#10b981', bg: 'bg-emerald-500/20', text: 'text-emerald-400', border: 'border-emerald-500/30' },
  medium: { label: '中共振', color: '#3b82f6', bg: 'bg-blue-500/20',    text: 'text-blue-400',    border: 'border-blue-500/30' },
  weak:   { label: '弱共振', color: '#eab308', bg: 'bg-yellow-500/20',  text: 'text-yellow-400',  border: 'border-yellow-500/30' },
  none:   { label: '无共振', color: '#64748b', bg: 'bg-slate-500/20',   text: 'text-slate-400',   border: 'border-slate-500/30' },
}

// ── 股票池选项 ────────────────────────────────────────────
const POOL_OPTIONS = [
  { value: 'all',   label: '全部' },
  { value: 'large', label: '大盘' },
  { value: 'mid',   label: '中盘' },
  { value: 'small', label: '小盘' },
  { value: 'micro', label: '微盘' },
]

// ── Tab 配置 ──────────────────────────────────────────────
const TABS = [
  { key: 'scan',    label: '共振排行', icon: TrendingUp },
  { key: 'signals', label: '卖出信号', icon: AlertTriangle },
  { key: 'ic',      label: '四维 IC',  icon: BarChart2 },
]

// 生成东方财富行情链接
const emStockUrl = (tsCode) => {
  if (!tsCode) return '#'
  const [code, exch] = String(tsCode).split('.')
  if (exch === 'BJ') return `https://quote.eastmoney.com/bj/${code}.html`
  const p = exch === 'SH' ? 'sh' : 'sz'
  return `https://quote.eastmoney.com/${p}${code}.html`
}

/**
 * 统一 fetch 封装
 */
async function fetchJSON(url, options = {}) {
  let res
  try {
    res = await fetch(url, options)
  } catch (e) {
    throw new Error(`网络连接失败：${e.message}。请检查后端服务是否启动。`)
  }
  const text = await res.text()
  let data
  try {
    data = JSON.parse(text)
  } catch (e) {
    const preview = text.replace(/\s+/g, ' ').slice(0, 80)
    throw new Error(
      `接口 ${url} 返回了非 JSON 数据（HTTP ${res.status}）。` +
      `这通常意味着后端路由未注册或服务未重启。\n响应预览: ${preview}...`
    )
  }
  if (!res.ok || (data.success === false)) {
    throw new Error(data.detail || data.error || `请求失败 (HTTP ${res.status})`)
  }
  return data
}

/* ================================================================
 * 主组件
 * ============================================================== */
function Resonance() {
  const [activeTab, setActiveTab] = useState('scan')
  const [pool, setPool] = useState('all')
  const [topN, setTopN] = useState(50)
  const [scanData, setScanData] = useState({ stocks: [], meta: {} })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [signalFilter, setSignalFilter] = useState('all')

  const loadScan = (p = pool, n = topN) => {
    setLoading(true)
    setError(null)
    fetchJSON(`${API_BASE}/scan?top_n=${n}&pool=${p}`)
      .then(d => { setScanData(d); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }

  useEffect(() => { loadScan(pool, topN) }, [pool, topN])

  // 计算共振等级分布
  const levelCounts = scanData.stocks?.reduce((acc, s) => {
    const lv = s.resonance_level || 'none'
    acc[lv] = (acc[lv] || 0) + 1
    return acc
  }, { strong: 0, medium: 0, weak: 0, none: 0 }) || { strong: 0, medium: 0, weak: 0, none: 0 }

  const total = scanData.stocks?.length || 1

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* 页头 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 via-cyan-500 to-purple-500 flex items-center justify-center">
            <Sparkles size={22} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-100">四维选股 · 四重共振策略</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              筹码 × 资金 × 板块 × 情绪 — 共振越强仓位越重
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={pool}
            onChange={(e) => setPool(e.target.value)}
            className="bg-[#0E1524] border border-[#222F4C] text-gray-300 text-xs px-3 py-1.5 rounded-lg focus:outline-none focus:border-emerald-500/50"
          >
            {POOL_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <select
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            className="bg-[#0E1524] border border-[#222F4C] text-gray-300 text-xs px-3 py-1.5 rounded-lg focus:outline-none focus:border-emerald-500/50"
          >
            <option value={20}>Top 20</option>
            <option value={50}>Top 50</option>
            <option value={100}>Top 100</option>
            <option value={200}>Top 200</option>
          </select>
          <button
            onClick={() => loadScan(pool, topN)}
            disabled={loading}
            className="flex items-center gap-1.5 bg-[#0E1524] hover:bg-[#172138] border border-[#222F4C] text-gray-300 text-xs px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
        </div>
      </div>

      {/* 扫描信息条 */}
      <div className="text-xs text-gray-500 mb-4">
        {scanData.meta?.scan_date && (
          <>扫描日期: <span className="font-mono text-gray-300">{scanData.meta.scan_date}</span></>
        )}
        {scanData.meta?.total_scanned != null && (
          <> · 扫描范围: <span className="font-mono text-gray-300">{scanData.meta.total_scanned.toLocaleString()}</span> 只</>
        )}
        {scanData.meta?.pool && (
          <> · 股票池: <span className="font-mono text-gray-300">{POOL_OPTIONS.find(p => p.value === scanData.meta.pool)?.label || scanData.meta.pool}</span></>
        )}
      </div>

      {/* 共振概览卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {[
          { key: 'strong', label: '强共振', icon: Zap, levelConf: RESONANCE_LEVELS.strong },
          { key: 'medium', label: '中共振', icon: Activity, levelConf: RESONANCE_LEVELS.medium },
          { key: 'weak',   label: '弱共振', icon: Target, levelConf: RESONANCE_LEVELS.weak },
          { key: 'none',   label: '无共振', icon: Shield, levelConf: RESONANCE_LEVELS.none },
        ].map(item => {
          const count = levelCounts[item.key] || 0
          const pct = total > 0 ? (count / total * 100) : 0
          const Icon = item.icon
          return (
            <div key={item.key} className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className={`w-7 h-7 rounded-lg ${item.levelConf.bg} flex items-center justify-center`}>
                    <Icon size={14} style={{ color: item.levelConf.color }} />
                  </div>
                  <span className="text-xs text-gray-400">{item.label}</span>
                </div>
                <span className={`text-lg font-bold font-mono ${item.levelConf.text}`}>{count}</span>
              </div>
              <div className="h-1.5 bg-[#070c18] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${pct}%`, backgroundColor: item.levelConf.color }}
                />
              </div>
              <div className="text-[10px] text-gray-600 mt-1 text-right">{pct.toFixed(1)}%</div>
            </div>
          )
        })}
      </div>

      {/* Tab 导航 */}
      <div className="flex gap-1 mb-5 bg-[#0E1524] border border-[#222F4C] rounded-xl p-1">
        {TABS.map(tab => {
          const Icon = tab.icon
          const isActive = activeTab === tab.key
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-2 rounded-lg text-xs font-medium transition-colors ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-500/20 to-cyan-500/20 text-emerald-400 border border-emerald-500/30'
                  : 'text-gray-500 hover:text-gray-300 hover:bg-[#172138]'
              }`}
            >
              <Icon size={14} />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          )
        })}
      </div>

      {/* Tab 内容 */}
      <div className="min-h-[400px]">
        {activeTab === 'scan' && (
          <ScanTab
            data={scanData}
            loading={loading}
            error={error}
            onRefresh={() => loadScan(pool, topN)}
          />
        )}
        {activeTab === 'signals' && (
          <SellSignalsTab
            stocks={scanData.stocks || []}
            loading={loading}
            error={error}
            filter={signalFilter}
            onFilterChange={setSignalFilter}
          />
        )}
        {activeTab === 'ic' && <DimensionICTab />}
      </div>
    </div>
  )
}

/* ================================================================
 * Tab 1: 共振排行
 * ============================================================== */
function ScanTab({ data, loading, error, onRefresh }) {
  const [expandedRow, setExpandedRow] = useState(null)
  const [detailCache, setDetailCache] = useState({})
  const [loadingDetail, setLoadingDetail] = useState(null)

  const toggleRow = async (tsCode) => {
    if (expandedRow === tsCode) {
      setExpandedRow(null)
      return
    }
    setExpandedRow(tsCode)
    if (!detailCache[tsCode]) {
      setLoadingDetail(tsCode)
      try {
        const d = await fetchJSON(`${API_BASE}/stock/${tsCode}`)
        setDetailCache(prev => ({ ...prev, [tsCode]: d }))
      } catch (e) {
        console.error('加载股票详情失败:', e)
      }
      setLoadingDetail(null)
    }
  }

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={onRefresh} />

  return (
    <div>
      {data.stocks?.length > 0 ? (
        <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl overflow-hidden">
          {/* 表头 */}
          <div className="hidden md:grid grid-cols-12 gap-2 px-4 py-2.5 text-xs text-gray-500 border-b border-[#222F4C] items-center">
            <div className="col-span-1 font-medium">#</div>
            <div className="col-span-3 font-medium">股票</div>
            <div className="col-span-2 font-medium">共振分数</div>
            <div className="col-span-1 font-medium text-center">等级</div>
            <div className="col-span-3 font-medium">四维分数</div>
            <div className="col-span-1 font-medium text-right">建议仓位</div>
            <div className="col-span-1 font-medium text-right w-8"></div>
          </div>

          {/* 行 */}
          {data.stocks.map((stock, idx) => {
            const isExp = expandedRow === stock.ts_code
            const detail = detailCache[stock.ts_code]
            return (
              <React.Fragment key={stock.ts_code}>
                {/* 主行 */}
                <div
                  className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-[#172138] hover:bg-[#131d35] cursor-pointer transition-colors items-center"
                  onClick={() => toggleRow(stock.ts_code)}
                >
                  {/* 排名 */}
                  <div className="col-span-1">
                    <RankBadge rank={stock.rank} />
                  </div>

                  {/* 股票信息 */}
                  <div className="col-span-3 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-xs text-cyan-400">{stock.ts_code}</span>
                      <a
                        href={emStockUrl(stock.ts_code)}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        title={`${stock.name} · 在东方财富网查看行情`}
                        className="text-gray-500 hover:text-emerald-400 transition-colors"
                      >
                        <ExternalLink size={11} />
                      </a>
                    </div>
                    <div className="text-sm text-gray-200 font-medium truncate">{stock.name}</div>
                    <div className="text-xs text-gray-500 hidden md:block truncate">{stock.industry}</div>
                  </div>

                  {/* 共振分数 + 进度条 */}
                  <div className="col-span-2">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-gray-500">共振分</span>
                      <span className="font-mono font-bold text-emerald-400 text-sm">
                        {(stock.resonance_score * 100).toFixed(1)}
                      </span>
                    </div>
                    <div className="h-1.5 bg-[#070c18] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-emerald-500 to-cyan-500 rounded-full"
                        style={{ width: `${Math.min(100, stock.resonance_score * 100)}%` }}
                      />
                    </div>
                  </div>

                  {/* 共振等级 */}
                  <div className="col-span-1 text-center">
                    <ResonanceBadge level={stock.resonance_level} />
                  </div>

                  {/* 四维分数（桌面端） */}
                  <div className="col-span-3 hidden md:block">
                    <div className="grid grid-cols-2 gap-1">
                      {DIM_KEYS.map(key => {
                        const score = stock.dimension_scores?.[key] ?? 0
                        const dim = DIM_COLORS[key]
                        return (
                          <div key={key} className="flex items-center gap-1">
                            <div
                              className="w-1.5 h-1.5 rounded-full"
                              style={{ backgroundColor: dim.color }}
                            />
                            <span className="text-[10px] text-gray-500 w-6">{dim.name}</span>
                            <span className="text-[10px] font-mono text-gray-300">
                              {(score * 100).toFixed(0)}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  </div>

                  {/* 建议仓位 */}
                  <div className="col-span-1 text-right">
                    <div className="text-xs text-gray-500">仓位</div>
                    <div className="font-mono font-bold text-sm text-gray-200">
                      {stock.position_min != null ? `${(stock.position_min * 100).toFixed(0)}%` : '—'}
                      <span className="text-gray-600 mx-0.5">~</span>
                      {stock.position_max != null ? `${(stock.position_max * 100).toFixed(0)}%` : '—'}
                    </div>
                  </div>

                  {/* 展开箭头 */}
                  <div className="col-span-1 text-right">
                    <ChevronRight
                      size={16}
                      className={`text-gray-500 transition-transform inline-block ${isExp ? 'rotate-90' : ''}`}
                    />
                  </div>
                </div>

                {/* 展开详情 */}
                {isExp && (
                  <div className="bg-[#070c18] border-b border-[#172138] px-4 py-4">
                    {loadingDetail === stock.ts_code && (
                      <div className="text-center py-6 text-gray-500 text-sm">
                        <RefreshCw size={18} className="animate-spin mx-auto mb-2 text-emerald-400" />
                        加载四维详情...
                      </div>
                    )}
                    {!loadingDetail && detail && (
                      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
                        {/* 雷达图 */}
                        <div className="bg-[#0E1524] border border-[#1a2540] rounded-lg p-4">
                          <div className="text-xs font-semibold text-gray-300 mb-3">四维雷达图</div>
                          <RadarChart
                            scores={{
                              chip: stock.dimension_scores?.chip ?? 0,
                              capital: stock.dimension_scores?.capital ?? 0,
                              sector: stock.dimension_scores?.sector ?? 0,
                              sentiment: stock.dimension_scores?.sentiment ?? 0,
                            }}
                            size={220}
                          />
                          <div className="mt-3 text-center">
                            <span className="text-xs text-gray-500">共振总分: </span>
                            <span className="font-mono font-bold text-emerald-400">
                              {(stock.resonance_score * 100).toFixed(2)}
                            </span>
                          </div>
                        </div>

                        {/* 四维因子明细 */}
                        <div className="space-y-3">
                          {DIM_KEYS.map(key => {
                            const dim = DIM_COLORS[key]
                            const dimData = detail.dimensions?.[key] || {}
                            const factors = dimData.factors || []
                            return (
                              <div
                                key={key}
                                className="bg-[#0E1524] border border-[#1a2540] rounded-lg p-3"
                              >
                                <div className="flex items-center justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    <div
                                      className="w-3 h-3 rounded-full"
                                      style={{ backgroundColor: dim.color }}
                                    />
                                    <span className="text-sm font-semibold text-gray-200">{dim.name}维度</span>
                                  </div>
                                  <span
                                    className="font-mono font-bold text-sm"
                                    style={{ color: dim.color }}
                                  >
                                    {((dimData.score ?? stock.dimension_scores?.[key] ?? 0) * 100).toFixed(1)} 分
                                  </span>
                                </div>
                                {factors.length > 0 ? (
                                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                                    {factors.map((f, fi) => (
                                      <div
                                        key={fi}
                                        className="bg-[#070c18] border border-[#1a2540] rounded px-2 py-1.5"
                                      >
                                        <div className="text-[10px] text-gray-500 truncate">{f.name || `因子${fi + 1}`}</div>
                                        <div className="flex items-center justify-between mt-0.5">
                                          <span className="text-xs font-mono text-gray-300">
                                            {f.value != null ? Number(f.value).toFixed(3) : '—'}
                                          </span>
                                          {f.contribution != null && (
                                            <span
                                              className="text-[10px] font-mono"
                                              style={{ color: dim.color }}
                                            >
                                              {(f.contribution * 100).toFixed(0)}%
                                            </span>
                                          )}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <div className="text-xs text-gray-600">暂无因子明细</div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                    {!loadingDetail && !detail && (
                      <div className="text-center py-4 text-gray-500 text-sm">详情加载失败</div>
                    )}
                  </div>
                )}
              </React.Fragment>
            )
          })}
        </div>
      ) : (
        <EmptyState icon={TrendingUp} text="暂无共振股票数据" />
      )}
    </div>
  )
}

/* ================================================================
 * Tab 2: 卖出信号监控
 * ============================================================== */
function SellSignalsTab({ stocks, loading, error, filter, onFilterChange }) {
  const [signalsMap, setSignalsMap] = useState({})
  const [loadingSignals, setLoadingSignals] = useState(false)
  const [signalsError, setSignalsError] = useState(null)

  // 为每只股票拉取卖出信号（实际场景建议后端批量接口，这里做渐进加载）
  useEffect(() => {
    if (!stocks || stocks.length === 0) return
    // 只加载前 20 只的信号，避免请求过多
    const topStocks = stocks.slice(0, 20)
    const missing = topStocks.filter(s => !signalsMap[s.ts_code])
    if (missing.length === 0) return

    setLoadingSignals(true)
    setSignalsError(null)

    // 串行请求，避免并发过多
    const loadAll = async () => {
      const results = {}
      for (const s of missing) {
        try {
          const d = await fetchJSON(`${API_BASE}/sell-signals/${s.ts_code}`)
          results[s.ts_code] = d
        } catch (e) {
          // 单只失败不影响整体
          console.warn(`加载 ${s.ts_code} 卖出信号失败:`, e.message)
        }
      }
      setSignalsMap(prev => ({ ...prev, ...results }))
      setLoadingSignals(false)
    }
    loadAll()
  }, [stocks])

  // 分类股票
  const categorized = {
    exit: [],         // 清仓信号 (overall_level: exit)
    reduce: [],       // 降仓信号 (overall_level: reduce)
    take_profit: [],  // 止盈信号 (overall_level: take_profit)
  }

  Object.entries(signalsMap).forEach(([tsCode, data]) => {
    const stock = stocks.find(s => s.ts_code === tsCode)
    if (!stock) return
    const level = data.overall_level
    if (level === 'exit') categorized.exit.push({ stock, signals: data.signals })
    else if (level === 'reduce') categorized.reduce.push({ stock, signals: data.signals })
    else if (level === 'take_profit') categorized.take_profit.push({ stock, signals: data.signals })
  })

  const filterOptions = [
    { value: 'all',         label: '全部信号' },
    { value: 'exit',        label: '清仓信号' },
    { value: 'reduce',      label: '降仓信号' },
    { value: 'take_profit', label: '止盈信号' },
  ]

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} />

  const showSection = (key) => filter === 'all' || filter === key

  return (
    <div className="space-y-4">
      {/* 筛选器 */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-400">
          三重铁律卖出信号监控 · 已检查 <span className="font-mono text-gray-200">{Object.keys(signalsMap).length}</span> 只
          {loadingSignals && <span className="ml-2 text-emerald-400 text-xs">加载中...</span>}
        </div>
        <select
          value={filter}
          onChange={(e) => onFilterChange(e.target.value)}
          className="bg-[#0E1524] border border-[#222F4C] text-gray-300 text-xs px-3 py-1.5 rounded-lg focus:outline-none focus:border-emerald-500/50"
        >
          {filterOptions.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* 清仓信号 */}
      {showSection('exit') && (
        <SignalSection
          title="🔴 清仓信号（铁律③）"
          subtitle="个股破位 + 共振消失 — 无条件清仓离场"
          accent="red"
          items={categorized.exit}
          emptyText="暂无清仓信号"
        />
      )}

      {/* 降仓信号 */}
      {showSection('reduce') && (
        <SignalSection
          title="🟡 降仓信号（铁律②）"
          subtitle="板块弱化 + 资金流出 — 降低仓位至安全线"
          accent="yellow"
          items={categorized.reduce}
          emptyText="暂无降仓信号"
        />
      )}

      {/* 止盈信号 */}
      {showSection('take_profit') && (
        <SignalSection
          title="🟢 止盈信号（铁律①）"
          subtitle="预期兑现 + 情绪高潮 — 分批止盈锁定利润"
          accent="green"
          items={categorized.take_profit}
          emptyText="暂无止盈信号"
        />
      )}

      {signalsError && (
        <div className="text-xs text-red-400 text-center py-4">{signalsError}</div>
      )}
    </div>
  )
}

function SignalSection({ title, subtitle, accent, items, emptyText }) {
  const accentMap = {
    red:    { border: 'border-red-500/30',   text: 'text-red-400',   bg: 'bg-red-500/10' },
    yellow: { border: 'border-yellow-500/30',text: 'text-yellow-400',bg: 'bg-yellow-500/10' },
    green:  { border: 'border-emerald-500/30',text: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  }
  const a = accentMap[accent] || accentMap.red

  return (
    <div className={`bg-[#0E1524] border ${a.border} rounded-xl overflow-hidden`}>
      <div className={`px-4 py-3 border-b ${a.border} ${a.bg}`}>
        <div className={`text-sm font-semibold ${a.text}`}>{title}</div>
        <div className="text-xs text-gray-500 mt-0.5">{subtitle}</div>
      </div>
      {items.length > 0 ? (
        <div className="divide-y divide-[#172138]">
          {items.map(({ stock, signals }) => (
            <SignalRow key={stock.ts_code} stock={stock} signals={signals} accent={accent} />
          ))}
        </div>
      ) : (
        <div className="px-4 py-6 text-center text-xs text-gray-600">{emptyText}</div>
      )}
    </div>
  )
}

function SignalRow({ stock, signals, accent }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div>
      <div
        className="px-4 py-3 flex items-center justify-between hover:bg-[#131d35] cursor-pointer transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs text-cyan-400">{stock.ts_code}</span>
              <span className="text-sm text-gray-200 font-medium">{stock.name}</span>
            </div>
            <div className="text-xs text-gray-500">{stock.industry}</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right hidden sm:block">
            <div className="text-xs text-gray-500">共振分</div>
            <div className="font-mono font-bold text-emerald-400 text-sm">
              {(stock.resonance_score * 100).toFixed(1)}
            </div>
          </div>
          <ChevronRight
            size={16}
            className={`text-gray-500 transition-transform ${expanded ? 'rotate-90' : ''}`}
          />
        </div>
      </div>
      {expanded && (
        <div className="px-4 pb-3 pt-1 bg-[#070c18] space-y-2">
          {signals?.map(sig => (
            <div
              key={sig.id}
              className={`flex items-start gap-2 p-2 rounded-lg border ${
                sig.triggered
                  ? 'bg-red-950/20 border-red-900/30'
                  : 'bg-[#0E1524] border-[#1a2540]'
              }`}
            >
              <div className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${
                sig.triggered
                  ? sig.level === 'strong' ? 'bg-red-500'
                    : sig.level === 'medium' ? 'bg-yellow-500'
                    : 'bg-emerald-500'
                  : 'bg-gray-600'
              }`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-medium ${sig.triggered ? 'text-red-300' : 'text-gray-400'}`}>
                    {sig.name}
                  </span>
                  {sig.triggered && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      sig.level === 'strong' ? 'bg-red-500/20 text-red-400'
                        : sig.level === 'medium' ? 'bg-yellow-500/20 text-yellow-400'
                        : 'bg-emerald-500/20 text-emerald-400'
                    }`}>
                      {sig.level === 'strong' ? '强烈' : sig.level === 'medium' ? '中等' : '微弱'}
                    </span>
                  )}
                  {!sig.triggered && (
                    <span className="text-[10px] text-gray-600">未触发</span>
                  )}
                </div>
                {sig.reason && (
                  <div className="text-[11px] text-gray-500 mt-1 leading-relaxed">{sig.reason}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ================================================================
 * Tab 3: 四维 IC 表现
 * ============================================================== */
function DimensionICTab() {
  const [data, setData] = useState({ dimensions: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadData = () => {
    setLoading(true)
    setError(null)
    fetchJSON(`${API_BASE}/dimension-ic`)
      .then(d => { setData(d); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }

  useEffect(() => { loadData() }, [])

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={loadData} />

  const dims = data.dimensions || []
  const maxIC = Math.max(...dims.map(d => Math.abs(d.ic_mean || 0)), 0.01)
  const maxICIR = Math.max(...dims.map(d => Math.abs(d.icir || 0)), 0.1)

  return (
    <div className="space-y-4">
      {/* IC 均值对比 */}
      <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-4 flex items-center gap-2">
          <BarChart2 size={15} className="text-emerald-400" />
          IC 均值对比
        </h3>
        <div className="space-y-3">
          {dims.length > 0 ? dims.map(dim => {
            const dimInfo = DIM_COLORS[dim.name?.toLowerCase()] || { name: dim.name, color: '#64748b' }
            const pct = Math.abs(dim.ic_mean || 0) / maxIC * 100
            return (
              <div key={dim.name}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-gray-300 font-medium">{dimInfo.name}</span>
                  <span className="font-mono text-gray-200">
                    IC: {(dim.ic_mean || 0).toFixed(4)}
                    <span className="text-gray-600 mx-2">|</span>
                    ICIR: {(dim.icir || 0).toFixed(2)}
                  </span>
                </div>
                <div className="h-6 bg-[#070c18] rounded-lg overflow-hidden relative">
                  <div
                    className="h-full rounded-lg transition-all duration-500"
                    style={{
                      width: `${pct}%`,
                      backgroundColor: dimInfo.color,
                      opacity: 0.8,
                    }}
                  />
                  {/* ICIR 标记线 */}
                  <div
                    className="absolute top-0 bottom-0 w-0.5 bg-white/40"
                    style={{ left: `${Math.abs(dim.icir || 0) / maxICIR * pct}%` }}
                    title={`ICIR: ${(dim.icir || 0).toFixed(2)}`}
                  />
                </div>
              </div>
            )
          }) : (
            <div className="text-center py-8 text-gray-500 text-sm">暂无 IC 数据</div>
          )}
        </div>
        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-[#1a2540]">
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 bg-emerald-500/50 rounded" />
            <span className="text-[10px] text-gray-500">IC 均值（条形宽度）</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-0.5 h-3 bg-white/40" />
            <span className="text-[10px] text-gray-500">ICIR（相对位置）</span>
          </div>
        </div>
      </div>

      {/* IC 衰减 */}
      <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-4 flex items-center gap-2">
          <Activity size={15} className="text-cyan-400" />
          IC 衰减曲线（未来 N 日）
        </h3>
        {dims.length > 0 ? (
          <div className="space-y-4">
            {dims.map(dim => {
              const dimInfo = DIM_COLORS[dim.name?.toLowerCase()] || { name: dim.name, color: '#64748b' }
              const decay = dim.ic_decay || []
              const maxVal = Math.max(...decay.map(Math.abs), 0.01)
              return (
                <div key={dim.name}>
                  <div className="flex items-center gap-2 mb-2">
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: dimInfo.color }}
                    />
                    <span className="text-xs font-medium text-gray-300">{dimInfo.name}</span>
                    <span className="text-[10px] text-gray-500 ml-auto">
                      {decay.length} 日衰减
                    </span>
                  </div>
                  <div className="flex items-end gap-1 h-16 bg-[#070c18] rounded-lg p-2">
                    {decay.length > 0 ? decay.map((val, i) => {
                      const height = Math.abs(val) / maxVal * 100
                      return (
                        <div
                          key={i}
                          className="flex-1 rounded-t transition-all duration-300"
                          style={{
                            height: `${Math.max(height, 2)}%`,
                            backgroundColor: dimInfo.color,
                            opacity: 0.3 + (0.7 * (decay.length - i) / decay.length),
                          }}
                          title={`Day ${i + 1}: ${val.toFixed(4)}`}
                        />
                      )
                    }) : (
                      <div className="w-full text-center text-xs text-gray-600 self-center">
                        暂无衰减数据
                      </div>
                    )}
                  </div>
                  <div className="flex justify-between text-[10px] text-gray-600 mt-1 px-2">
                    <span>T+1</span>
                    <span>T+{decay.length || 'N'}</span>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500 text-sm">暂无 IC 衰减数据</div>
        )}
      </div>

      {/* 四维评分卡 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {dims.length > 0 ? dims.map(dim => {
          const dimInfo = DIM_COLORS[dim.name?.toLowerCase()] || { name: dim.name, color: '#64748b' }
          return (
            <div
              key={dim.name}
              className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-4"
            >
              <div className="flex items-center gap-2 mb-3">
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{ backgroundColor: `${dimInfo.color}20` }}
                >
                  <Layers size={14} style={{ color: dimInfo.color }} />
                </div>
                <span className="text-sm font-semibold text-gray-200">{dimInfo.name}</span>
              </div>
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">IC 均值</span>
                  <span className="font-mono text-gray-200">{(dim.ic_mean || 0).toFixed(4)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">ICIR</span>
                  <span className="font-mono" style={{ color: dimInfo.color }}>
                    {(dim.icir || 0).toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">衰减半衰期</span>
                  <span className="font-mono text-gray-300">
                    {dim.half_life || '—'} 日
                  </span>
                </div>
              </div>
            </div>
          )
        }) : (
          <div className="col-span-full text-center py-8 text-gray-500 text-sm">暂无维度数据</div>
        )}
      </div>
    </div>
  )
}

/* ================================================================
 * SVG 四维雷达图（正方形 / 菱形 4 轴）
 * ============================================================== */
function RadarChart({ scores, size = 200 }) {
  const cx = size / 2
  const cy = size / 2
  const maxR = size * 0.38

  // 四个维度对应四个方向：上(筹码)、右(资金)、下(板块)、左(情绪)
  const axes = [
    { key: 'chip',      angle: -90, label: '筹码' },   // 上
    { key: 'capital',   angle: 0,   label: '资金' },   // 右
    { key: 'sector',    angle: 90,  label: '板块' },   // 下
    { key: 'sentiment', angle: 180, label: '情绪' },   // 左
  ]

  // 将角度转换为弧度
  const toRad = (deg) => (deg * Math.PI) / 180

  // 计算某维度某分数对应的坐标
  const pointFor = (angle, score) => {
    const r = Math.max(0, Math.min(1, score)) * maxR
    return {
      x: cx + r * Math.cos(toRad(angle)),
      y: cy + r * Math.sin(toRad(angle)),
    }
  }

  // 背景网格（3 层）
  const gridLevels = [0.33, 0.66, 1.0]

  // 数据点路径
  const dataPoints = axes.map(axis => pointFor(axis.angle, scores[axis.key] || 0))
  const pathD = dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z'

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      className="w-full max-w-[220px] mx-auto"
      style={{ display: 'block' }}
    >
      <defs>
        <radialGradient id="radarFill" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#10b981" stopOpacity="0.4" />
          <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.15" />
        </radialGradient>
      </defs>

      {/* 背景网格（菱形） */}
      {gridLevels.map((level, li) => {
        const gridPoints = axes.map(axis => pointFor(axis.angle, level))
        const gridD = gridPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z'
        return (
          <path
            key={li}
            d={gridD}
            fill="none"
            stroke="#1a2540"
            strokeWidth="1"
            strokeDasharray={level < 1 ? '2,2' : 'none'}
          />
        )
      })}

      {/* 轴线 */}
      {axes.map((axis, i) => {
        const end = pointFor(axis.angle, 1)
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={end.x}
            y2={end.y}
            stroke="#1a2540"
            strokeWidth="1"
          />
        )
      })}

      {/* 数据填充区域 */}
      <path
        d={pathD}
        fill="url(#radarFill)"
        stroke="#10b981"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />

      {/* 数据点 */}
      {dataPoints.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r="3"
          fill={DIM_COLORS[axes[i].key]?.color || '#10b981'}
          stroke="#070c18"
          strokeWidth="1.5"
        />
      ))}

      {/* 维度标签 */}
      {axes.map((axis, i) => {
        const labelPos = pointFor(axis.angle, 1.22)
        const dimColor = DIM_COLORS[axis.key]?.color || '#94a3b8'
        // 调整文字对齐
        let textAnchor = 'middle'
        if (axis.angle === 0) textAnchor = 'start'
        else if (axis.angle === 180) textAnchor = 'end'

        return (
          <g key={i}>
            <text
              x={labelPos.x}
              y={labelPos.y}
              textAnchor={textAnchor}
              dominantBaseline="middle"
              fill={dimColor}
              fontSize="11"
              fontWeight="600"
            >
              {axis.label}
            </text>
            <text
              x={labelPos.x}
              y={labelPos.y + 13}
              textAnchor={textAnchor}
              dominantBaseline="middle"
              fill="#64748b"
              fontSize="10"
              fontFamily="monospace"
            >
              {((scores[axis.key] || 0) * 100).toFixed(0)}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

/* ================================================================
 * 公共组件
 * ============================================================== */

function LoadingState() {
  return (
    <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-12 text-center">
      <RefreshCw size={24} className="animate-spin text-emerald-400 mx-auto mb-3" />
      <div className="text-sm text-gray-500">加载中...</div>
    </div>
  )
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="bg-red-950/30 border border-red-900/50 rounded-xl p-6">
      <div className="flex items-start gap-3">
        <Info size={20} className="text-red-400 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-red-300 mb-1">加载失败</div>
          <div className="text-xs text-red-400/80 whitespace-pre-wrap break-all leading-relaxed">
            {message}
          </div>
          {onRetry && (
            <button
              onClick={onRetry}
              className="mt-3 px-3 py-1.5 bg-red-900/40 hover:bg-red-900/60 border border-red-800/50 text-red-300 text-xs rounded-lg transition-colors"
            >
              重试
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function EmptyState({ icon: Icon, text }) {
  return (
    <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-12 text-center">
      <Icon size={28} className="text-gray-600 mx-auto mb-3" />
      <div className="text-sm text-gray-500">{text}</div>
    </div>
  )
}

function RankBadge({ rank }) {
  if (rank === 1) return <span className="inline-flex items-center justify-center w-6 h-6 text-xs rounded bg-amber-500/20 text-amber-400 font-bold">1</span>
  if (rank === 2) return <span className="inline-flex items-center justify-center w-6 h-6 text-xs rounded bg-gray-400/20 text-gray-300 font-bold">2</span>
  if (rank === 3) return <span className="inline-flex items-center justify-center w-6 h-6 text-xs rounded bg-orange-500/20 text-orange-400 font-bold">3</span>
  return <span className="inline-flex items-center justify-center w-6 h-6 text-xs rounded bg-[#172138] text-gray-500 font-medium">{rank}</span>
}

function ResonanceBadge({ level }) {
  const conf = RESONANCE_LEVELS[level] || RESONANCE_LEVELS.none
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${conf.bg} ${conf.text} ${conf.border}`}
    >
      {conf.label}
    </span>
  )
}

export default Resonance
