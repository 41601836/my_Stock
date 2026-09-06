import React, { useState, useEffect } from 'react'
import {
  Layers, RefreshCw, Info, ChevronRight,
  Calendar, Flame, BarChart2, PieChart, TrendingUp, ExternalLink
} from 'lucide-react'

/**
 * MultiFactor202609 —— 202609 多因子分析页面
 * ============================================
 * 零侵入平行层：独立路由 /mf202609，独立组件，删除即回滚。
 *
 * 5 个 Tab：
 * - 扫描结果：最新截面 Top-N + 因子明细展开
 * - 每日快照：按日期分组的上榜列表
 * - 连续上榜：连续上榜天数排行
 * - 上榜频率：上榜次数频率排行
 * - 累计统计：整体数据汇总
 */

const API_BASE = '/api/mf202609'

// 生成东方财富行情链接（SH/SZ 市场前缀，北交所为 bj/ 带斜杠格式）
const emStockUrl = (tsCode) => {
  if (!tsCode) return '#'
  const [code, exch] = String(tsCode).split('.')
  if (exch === 'BJ') return `https://quote.eastmoney.com/bj/${code}.html`
  const p = exch === 'SH' ? 'sh' : 'sz'
  return `https://quote.eastmoney.com/${p}${code}.html`
}

/**
 * 统一 fetch 封装：优雅处理非 JSON 响应（如 SPA 返回的 HTML）、网络错误等
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
    // 非 JSON 响应 —— 通常是 SPA fallback 返回了 HTML
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

const TABS = [
  { key: 'scan',      label: '扫描结果', icon: TrendingUp },
  { key: 'daily',     label: '每日快照', icon: Calendar },
  { key: 'streak',    label: '连续上榜', icon: Flame },
  { key: 'frequency', label: '上榜频率', icon: BarChart2 },
  { key: 'cumulative',label: '累计统计', icon: PieChart },
]

function MultiFactor202609() {
  const [activeTab, setActiveTab] = useState('scan')
  const [config, setConfig] = useState(null)
  const [days, setDays] = useState(30)

  // 配置
  useEffect(() => {
    fetch(`${API_BASE}/config`)
      .then(res => res.json())
      .then(data => { if (data.success) setConfig(data) })
      .catch(err => console.error('加载配置失败:', err))
  }, [])

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* 页头 */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
            <Layers size={22} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-100">202609 多因子分析</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              5 独立因子 · 排名平均法 · 截面扫描
            </p>
          </div>
        </div>
        {config && (
          <div className="flex items-center gap-2">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="bg-[#0E1524] border border-[#222F4C] text-gray-300 text-xs px-3 py-1.5 rounded-lg focus:outline-none focus:border-amber-500/50"
            >
              <option value={7}>近 7 天</option>
              <option value={14}>近 14 天</option>
              <option value={30}>近 30 天</option>
              <option value={60}>近 60 天</option>
              <option value={90}>近 90 天</option>
            </select>
          </div>
        )}
      </div>

      {/* 模型配置概览 */}
      {config && (
        <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-4 mb-5">
          <div className="flex items-center gap-2 mb-3">
            <Info size={14} className="text-amber-400" />
            <span className="text-sm font-semibold text-gray-200">模型配置</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
            <div className="bg-[#070c18] rounded-lg p-2.5 border border-[#1a2540]">
              <div className="text-xs text-gray-500 mb-0.5">合成方法</div>
              <div className="text-base font-bold text-amber-400 font-mono">
                {config.method === 'rank_average' ? '排名平均' : config.method}
              </div>
            </div>
            <div className="bg-[#070c18] rounded-lg p-2.5 border border-[#1a2540]">
              <div className="text-xs text-gray-500 mb-0.5">因子数量</div>
              <div className="text-base font-bold text-cyan-400 font-mono">{config.factor_count}</div>
            </div>
            <div className="bg-[#070c18] rounded-lg p-2.5 border border-[#1a2540]">
              <div className="text-xs text-gray-500 mb-0.5">Top-N</div>
              <div className="text-base font-bold text-gray-300 font-mono">{config.top_n}</div>
            </div>
            <div className="bg-[#070c18] rounded-lg p-2.5 border border-[#1a2540]">
              <div className="text-xs text-gray-500 mb-0.5">版本</div>
              <div className="text-base font-bold text-gray-300 font-mono">{config.model_version}</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {config.factors?.map((f, i) => (
              <div
                key={f.name}
                className="inline-flex items-center gap-1.5 bg-[#070c18] border border-[#1a2540] rounded-full px-2.5 py-0.5"
              >
                <span className="w-4 h-4 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-[9px] font-bold text-white">
                  {i + 1}
                </span>
                <span className="text-xs font-mono text-gray-300">{f.name}</span>
                <span className="text-[10px] text-gray-600">·</span>
                <span className="text-[10px] text-gray-500">{f.category}</span>
              </div>
            ))}
          </div>
        </div>
      )}

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
                  ? 'bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-400 border border-amber-500/30'
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
        {activeTab === 'scan' && <ScanTab config={config} />}
        {activeTab === 'daily' && <DailyTab days={days} />}
        {activeTab === 'streak' && <StreakTab days={days} />}
        {activeTab === 'frequency' && <FrequencyTab days={days} />}
        {activeTab === 'cumulative' && <CumulativeTab days={days} />}
      </div>
    </div>
  )
}

/* ========== Tab 1: 扫描结果 ========== */
function ScanTab({ config }) {
  const [data, setData] = useState({ stocks: [], meta: {} })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [topN, setTopN] = useState(20)
  const [expandedRow, setExpandedRow] = useState(null)

  const loadData = (n = topN) => {
    setLoading(true)
    setError(null)
    fetchJSON(`${API_BASE}/scan?top_n=${n}`)
      .then(d => { setData(d); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }

  useEffect(() => { loadData(topN) }, [topN])

  const toggleRow = (code) => setExpandedRow(expandedRow === code ? null : code)
  const directionLabel = (dir) => dir > 0
    ? <span className="text-emerald-400 text-xs font-mono">正向↑</span>
    : <span className="text-indigo-400 text-xs font-mono">反向↓</span>

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm text-gray-400">
          {data.meta?.scan_date && (
            <>扫描日期: <span className="font-mono text-gray-200">{data.meta.scan_date}</span></>
          )}
          {data.meta?.total_scanned && (
            <> · 范围: <span className="font-mono text-gray-200">{data.meta.total_scanned.toLocaleString()}</span> 只</>
          )}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            className="bg-[#0E1524] border border-[#222F4C] text-gray-300 text-xs px-2.5 py-1 rounded-lg focus:outline-none focus:border-amber-500/50"
          >
            <option value={10}>Top 10</option>
            <option value={20}>Top 20</option>
            <option value={30}>Top 30</option>
            <option value={50}>Top 50</option>
          </select>
          <button
            onClick={() => loadData(topN)}
            disabled={loading}
            className="flex items-center gap-1.5 bg-[#0E1524] hover:bg-[#172138] border border-[#222F4C] text-gray-300 text-xs px-2.5 py-1 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
        </div>
      </div>

      {loading && <LoadingState />}

      {!loading && error && <ErrorState message={error} onRetry={() => loadData(topN)} />}

      {!loading && !error && data.stocks?.length > 0 && (
        <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-[#222F4C]">
                <th className="px-4 py-2.5 font-medium w-14">#</th>
                <th className="px-3 py-2.5 font-medium">代码</th>
                <th className="px-3 py-2.5 font-medium">名称</th>
                <th className="px-3 py-2.5 font-medium hidden md:table-cell">行业</th>
                <th className="px-3 py-2.5 font-medium text-right">综合得分</th>
                <th className="px-4 py-2.5 font-medium w-10"></th>
              </tr>
            </thead>
            <tbody>
              {data.stocks.map((stock, idx) => {
                const isExp = expandedRow === stock.ts_code
                return (
                  <React.Fragment key={stock.ts_code}>
                    <tr
                      className="border-b border-[#172138] hover:bg-[#131d35] cursor-pointer transition-colors"
                      onClick={() => toggleRow(stock.ts_code)}
                    >
                      <td className="px-4 py-2.5">
                        <RankBadge rank={stock.rank} />
                      </td>
                      <td className="px-3 py-2.5 font-mono text-xs text-cyan-400">
                        {stock.ts_code}
                        <a
                          href={emStockUrl(stock.ts_code)}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          title={`${stock.name} · 在东方财富网查看行情`}
                          className="inline-flex items-center ml-1.5 text-gray-500 hover:text-amber-400 transition-colors align-middle"
                        >
                          <ExternalLink size={12} />
                        </a>
                      </td>
                      <td className="px-3 py-2.5 text-gray-200 font-medium">{stock.name}</td>
                      <td className="px-3 py-2.5 text-gray-500 text-xs hidden md:table-cell">{stock.industry}</td>
                      <td className="px-3 py-2.5 text-right font-mono font-bold text-amber-400">
                        {(stock.composite_score * 100).toFixed(2)}
                        <span className="text-gray-600 text-xs ml-0.5">分</span>
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <ChevronRight size={16} className={`text-gray-500 transition-transform inline-block ${isExp ? 'rotate-90' : ''}`} />
                      </td>
                    </tr>
                    {isExp && (
                      <tr className="bg-[#070c18]">
                        <td colSpan={6} className="px-4 py-3">
                          <div className="grid grid-cols-2 lg:grid-cols-5 gap-2.5">
                            {Object.entries(stock.factor_details).map(([fname, fdet], fi) => {
                              const fInfo = config?.factors?.find(f => f.name === fname)
                              return (
                                <div key={fname} className="bg-[#0E1524] border border-[#1a2540] rounded-lg p-2.5">
                                  <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-xs font-mono text-gray-300 font-semibold truncate">{fname}</span>
                                    <span className="w-4 h-4 rounded-full bg-amber-500/20 flex items-center justify-center text-[9px] font-bold text-amber-400">
                                      {fi + 1}
                                    </span>
                                  </div>
                                  <div className="text-base font-bold text-white font-mono mb-0.5">
                                    {fdet.raw != null ? Number(fdet.raw).toFixed(4) : '—'}
                                  </div>
                                  <div className="flex items-center justify-between text-[10px]">
                                    <span className="text-gray-500">{fInfo?.category || '—'}</span>
                                    {directionLabel(fdet.direction)}
                                  </div>
                                  <div className="mt-1.5 flex items-center justify-between text-[10px]">
                                    <span className="text-gray-500">权重</span>
                                    <span className="font-mono text-amber-400">{(fdet.weight * 100).toFixed(0)}%</span>
                                  </div>
                                  {fdet.raw != null && (
                                    <div className="mt-1.5 h-1 w-full bg-[#1a2540] rounded-full overflow-hidden">
                                      <div
                                        className="h-full bg-gradient-to-r from-amber-500 to-orange-500 rounded-full"
                                        style={{ width: `${Math.min(100, Math.abs(Number(fdet.raw)) * 100)}%` }}
                                      />
                                    </div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && (!data.stocks || data.stocks.length === 0) && (
        <EmptyState icon={TrendingUp} text="暂无扫描结果" />
      )}
    </div>
  )
}

/* ========== Tab 2: 每日快照 ========== */
function DailyTab({ days }) {
  const [data, setData] = useState({ daily: {}, dates: [], meta: {} })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeDate, setActiveDate] = useState('')
  const [topN, setTopN] = useState(0)

  const loadData = () => {
    setLoading(true)
    setError(null)
    fetchJSON(`${API_BASE}/history/daily?days=${days}&top_n_per_day=${topN}`)
      .then(d => {
        setData(d)
        if (d.dates?.length > 0 && !activeDate) setActiveDate(d.dates[0])
        setLoading(false)
      })
      .catch(err => { setError(err.message); setLoading(false) })
  }

  useEffect(() => { loadData() }, [days, topN])

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={loadData} />

  const stocks = data.daily?.[activeDate] || []

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm text-gray-400">
          共 <span className="font-mono text-gray-200">{data.meta?.scan_days || 0}</span> 个交易日 ·
          <span className="font-mono text-gray-200"> {data.meta?.total_records || 0}</span> 条记录
        </div>
        <select
          value={topN}
          onChange={(e) => setTopN(Number(e.target.value))}
          className="bg-[#0E1524] border border-[#222F4C] text-gray-300 text-xs px-2.5 py-1 rounded-lg focus:outline-none focus:border-amber-500/50"
        >
          <option value={0}>全部排名</option>
          <option value={5}>Top 5</option>
          <option value={10}>Top 10</option>
          <option value={20}>Top 20</option>
        </select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[180px_1fr] gap-4">
        {/* 日期选择器 */}
        <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-2 max-h-[500px] overflow-y-auto">
          {data.dates?.map(d => (
            <button
              key={d}
              onClick={() => setActiveDate(d)}
              className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-mono transition-colors ${
                activeDate === d
                  ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                  : 'text-gray-400 hover:bg-[#172138]'
              }`}
            >
              {d}
              <span className="text-gray-600 ml-2">({data.daily[d]?.length || 0})</span>
            </button>
          ))}
          {(!data.dates || data.dates.length === 0) && (
            <div className="text-xs text-gray-500 text-center py-4">暂无历史数据</div>
          )}
        </div>

        {/* 当日列表 */}
        <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-[#222F4C] flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-200">{activeDate || '—'}</span>
            <span className="text-xs text-gray-500">{stocks.length} 只股票</span>
          </div>
          {stocks.length > 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 border-b border-[#172138]">
                  <th className="px-4 py-2 font-medium w-12">#</th>
                  <th className="px-3 py-2 font-medium">代码</th>
                  <th className="px-3 py-2 font-medium">名称</th>
                  <th className="px-3 py-2 font-medium hidden sm:table-cell">行业</th>
                  <th className="px-4 py-2 font-medium text-right">得分</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map(s => (
                  <tr key={s.ts_code} className="border-b border-[#172138] hover:bg-[#131d35]">
                    <td className="px-4 py-2">
                      <RankBadge rank={s.rank} small />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-cyan-400">
                      {s.ts_code}
                      <a
                        href={emStockUrl(s.ts_code)}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`${s.name} · 在东方财富网查看行情`}
                        className="inline-flex items-center ml-1.5 text-gray-500 hover:text-amber-400 transition-colors align-middle"
                      >
                        <ExternalLink size={11} />
                      </a>
                    </td>
                    <td className="px-3 py-2 text-gray-200">{s.name}</td>
                    <td className="px-3 py-2 text-gray-500 text-xs hidden sm:table-cell">{s.industry}</td>
                    <td className="px-4 py-2 text-right font-mono font-bold text-amber-400">
                      {(s.composite_score * 100).toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="text-center py-8 text-gray-500 text-sm">选择日期查看详情</div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ========== Tab 3: 连续上榜 ========== */
function StreakTab({ days }) {
  const [data, setData] = useState({ stocks: [], meta: {} })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [minStreak, setMinStreak] = useState(2)

  const loadData = () => {
    setLoading(true)
    setError(null)
    fetchJSON(`${API_BASE}/history/streak?days=${days}&min_streak=${minStreak}`)
      .then(d => { setData(d); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }

  useEffect(() => { loadData() }, [days, minStreak])

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={loadData} />

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm text-gray-400">
          近 <span className="font-mono text-gray-200">{days}</span> 天 ·
          连续上榜 ≥ <span className="font-mono text-gray-200">{minStreak}</span> 天 ·
          共 <span className="font-mono text-gray-200">{data.meta?.total || 0}</span> 只
        </div>
        <select
          value={minStreak}
          onChange={(e) => setMinStreak(Number(e.target.value))}
          className="bg-[#0E1524] border border-[#222F4C] text-gray-300 text-xs px-2.5 py-1 rounded-lg focus:outline-none focus:border-amber-500/50"
        >
          <option value={1}>≥ 1 天</option>
          <option value={2}>≥ 2 天</option>
          <option value={3}>≥ 3 天</option>
          <option value={5}>≥ 5 天</option>
          <option value={7}>≥ 7 天</option>
        </select>
      </div>

      {data.stocks?.length > 0 ? (
        <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-[#222F4C]">
                <th className="px-4 py-2.5 font-medium w-12">#</th>
                <th className="px-3 py-2.5 font-medium">股票</th>
                <th className="px-3 py-2.5 font-medium hidden sm:table-cell">行业</th>
                <th className="px-3 py-2.5 font-medium text-center">连续天数</th>
                <th className="px-3 py-2.5 font-medium text-right hidden md:table-cell">最新排名</th>
                <th className="px-4 py-2.5 font-medium text-right">最新得分</th>
              </tr>
            </thead>
            <tbody>
              {data.stocks.map((s, i) => (
                <tr key={s.ts_code} className="border-b border-[#172138] hover:bg-[#131d35]">
                  <td className="px-4 py-2.5 text-gray-500 text-xs">{i + 1}</td>
                  <td className="px-3 py-2.5">
                    <div className="font-mono text-xs text-cyan-400">
                      {s.ts_code}
                      <a
                        href={emStockUrl(s.ts_code)}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`${s.name} · 在东方财富网查看行情`}
                        className="inline-flex items-center ml-1.5 text-gray-500 hover:text-amber-400 transition-colors align-middle"
                      >
                        <ExternalLink size={11} />
                      </a>
                    </div>
                    <div className="text-gray-200 text-xs">{s.name}</div>
                  </td>
                  <td className="px-3 py-2.5 text-gray-500 text-xs hidden sm:table-cell">{s.industry}</td>
                  <td className="px-3 py-2.5 text-center">
                    <div className="inline-flex items-center gap-1 bg-orange-500/20 text-orange-400 px-2.5 py-1 rounded-full text-xs font-bold font-mono">
                      <Flame size={12} />
                      {s.streak_days} 天
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-gray-300 hidden md:table-cell">
                    #{s.latest_rank || '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono font-bold text-amber-400">
                    {s.latest_score != null ? (s.latest_score * 100).toFixed(1) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState icon={Flame} text="暂无连续上榜股票" />
      )}
    </div>
  )
}

/* ========== Tab 4: 上榜频率 ========== */
function FrequencyTab({ days }) {
  const [data, setData] = useState({ stocks: [], meta: {} })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [minAppear, setMinAppear] = useState(1)

  const loadData = () => {
    setLoading(true)
    setError(null)
    fetchJSON(`${API_BASE}/history/frequency?days=${days}&min_appear=${minAppear}`)
      .then(d => { setData(d); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }

  useEffect(() => { loadData() }, [days, minAppear])

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={loadData} />

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm text-gray-400">
          近 <span className="font-mono text-gray-200">{days}</span> 天 ·
          上榜 ≥ <span className="font-mono text-gray-200">{minAppear}</span> 次 ·
          共 <span className="font-mono text-gray-200">{data.meta?.total || 0}</span> 只
        </div>
        <select
          value={minAppear}
          onChange={(e) => setMinAppear(Number(e.target.value))}
          className="bg-[#0E1524] border border-[#222F4C] text-gray-300 text-xs px-2.5 py-1 rounded-lg focus:outline-none focus:border-amber-500/50"
        >
          <option value={1}>≥ 1 次</option>
          <option value={2}>≥ 2 次</option>
          <option value={3}>≥ 3 次</option>
          <option value={5}>≥ 5 次</option>
          <option value={10}>≥ 10 次</option>
        </select>
      </div>

      {data.stocks?.length > 0 ? (
        <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-[#222F4C]">
                <th className="px-4 py-2.5 font-medium w-12">#</th>
                <th className="px-3 py-2.5 font-medium">股票</th>
                <th className="px-3 py-2.5 font-medium hidden sm:table-cell">行业</th>
                <th className="px-3 py-2.5 font-medium text-center">上榜次数</th>
                <th className="px-3 py-2.5 font-medium text-right hidden md:table-cell">平均排名</th>
                <th className="px-3 py-2.5 font-medium text-right hidden sm:table-cell">最佳排名</th>
                <th className="px-4 py-2.5 font-medium text-right">最新排名</th>
              </tr>
            </thead>
            <tbody>
              {data.stocks.map((s, i) => (
                <tr key={s.ts_code} className="border-b border-[#172138] hover:bg-[#131d35]">
                  <td className="px-4 py-2.5 text-gray-500 text-xs">{i + 1}</td>
                  <td className="px-3 py-2.5">
                    <div className="font-mono text-xs text-cyan-400">
                      {s.ts_code}
                      <a
                        href={emStockUrl(s.ts_code)}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`${s.name} · 在东方财富网查看行情`}
                        className="inline-flex items-center ml-1.5 text-gray-500 hover:text-amber-400 transition-colors align-middle"
                      >
                        <ExternalLink size={11} />
                      </a>
                    </div>
                    <div className="text-gray-200 text-xs">{s.name}</div>
                  </td>
                  <td className="px-3 py-2.5 text-gray-500 text-xs hidden sm:table-cell">{s.industry}</td>
                  <td className="px-3 py-2.5 text-center">
                    <span className="inline-block bg-cyan-500/20 text-cyan-400 px-2.5 py-0.5 rounded-full text-xs font-bold font-mono min-w-[40px]">
                      {s.appear_count} 次
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-gray-300 hidden md:table-cell">
                    {s.avg_rank}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-emerald-400 hidden sm:table-cell">
                    #{s.best_rank}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-gray-300">
                    #{s.latest_rank || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState icon={BarChart2} text="暂无频率数据" />
      )}
    </div>
  )
}

/* ========== Tab 5: 累计统计 ========== */
function CumulativeTab({ days }) {
  const [data, setData] = useState({ stats: {}, rank_distribution: {}, industry_top: [], meta: {} })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadData = () => {
    setLoading(true)
    setError(null)
    fetchJSON(`${API_BASE}/history/cumulative?days=${days}`)
      .then(d => { setData(d); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }

  useEffect(() => { loadData() }, [days])

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={loadData} />

  const s = data.stats || {}
  const rd = data.rank_distribution || {}

  return (
    <div className="space-y-4">
      {/* 核心指标 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="总记录数" value={s.total_records?.toLocaleString() || 0} accent="cyan" />
        <StatCard label="扫描天数" value={s.scan_days || 0} suffix="天" accent="amber" />
        <StatCard label="覆盖个股" value={s.unique_stocks?.toLocaleString() || 0} accent="emerald" />
        <StatCard label="最长连续" value={s.top_streak || 0} suffix="天" accent="orange" />
      </div>

      {/* 排名分布 + 行业上榜 TOP */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 排名分布 */}
        <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-4">
          <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
            <PieChart size={15} className="text-amber-400" />
            排名分布
          </h3>
          <div className="space-y-2.5">
            {[
              { label: 'Top 1', key: 'top1', color: 'from-amber-400 to-amber-600' },
              { label: 'Top 3', key: 'top3', color: 'from-orange-400 to-orange-600' },
              { label: 'Top 5', key: 'top5', color: 'from-cyan-400 to-cyan-600' },
              { label: 'Top 10', key: 'top10', color: 'from-emerald-400 to-emerald-600' },
              { label: 'Top 20', key: 'top20', color: 'from-indigo-400 to-indigo-600' },
            ].map(item => {
              const val = rd[item.key] || 0
              const pct = s.total_records > 0 ? (val / s.total_records * 100) : 0
              return (
                <div key={item.key}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-400">{item.label}</span>
                    <span className="font-mono text-gray-200">{val} 次 ({pct.toFixed(1)}%)</span>
                  </div>
                  <div className="h-2 bg-[#070c18] rounded-full overflow-hidden">
                    <div
                      className={`h-full bg-gradient-to-r ${item.color} rounded-full`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* 行业上榜 TOP10 */}
        <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-4">
          <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
            <BarChart2 size={15} className="text-cyan-400" />
            行业上榜 TOP 10
          </h3>
          {data.industry_top?.length > 0 ? (
            <div className="space-y-2">
              {data.industry_top.slice(0, 10).map((ind, i) => {
                const maxCnt = data.industry_top[0]?.appear_count || 1
                const pct = (ind.appear_count / maxCnt) * 100
                return (
                  <div key={ind.industry} className="flex items-center gap-2">
                    <span className="text-xs text-gray-500 w-5 text-right">{i + 1}</span>
                    <span className="text-xs text-gray-300 w-24 truncate flex-shrink-0">{ind.industry}</span>
                    <div className="flex-1 h-2 bg-[#070c18] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-cyan-500/80 to-cyan-400 rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono text-gray-400 w-12 text-right">
                      {ind.appear_count}次
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-center py-6 text-gray-500 text-sm">暂无行业数据</div>
          )}
        </div>
      </div>

      {/* 时间范围 */}
      <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-4">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Calendar size={14} />
          <span>统计区间:</span>
          <span className="font-mono text-gray-300">{s.date_from || '—'}</span>
          <span className="text-gray-600">~</span>
          <span className="font-mono text-gray-300">{s.date_latest || '—'}</span>
          <span className="text-gray-600 ml-2">日均上榜 {s.avg_per_day || 0} 只</span>
        </div>
      </div>
    </div>
  )
}

/* ========== 公共组件 ========== */

function LoadingState() {
  return (
    <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-12 text-center">
      <RefreshCw size={24} className="animate-spin text-amber-400 mx-auto mb-3" />
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

function StatCard({ label, value, suffix, accent }) {
  const colorMap = {
    cyan: 'text-cyan-400',
    amber: 'text-amber-400',
    emerald: 'text-emerald-400',
    orange: 'text-orange-400',
  }
  return (
    <div className="bg-[#0E1524] border border-[#222F4C] rounded-xl p-4">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold font-mono ${colorMap[accent] || 'text-gray-200'}`}>
        {value}
        {suffix && <span className="text-sm font-normal text-gray-500 ml-1">{suffix}</span>}
      </div>
    </div>
  )
}

function RankBadge({ rank, small }) {
  const size = small ? 'w-5 h-5 text-[10px]' : 'w-6 h-6 text-xs'
  if (rank === 1) return <span className={`inline-flex items-center justify-center ${size} rounded bg-amber-500/20 text-amber-400 font-bold`}>1</span>
  if (rank === 2) return <span className={`inline-flex items-center justify-center ${size} rounded bg-gray-400/20 text-gray-300 font-bold`}>2</span>
  if (rank === 3) return <span className={`inline-flex items-center justify-center ${size} rounded bg-orange-500/20 text-orange-400 font-bold`}>3</span>
  return <span className={`inline-flex items-center justify-center ${size} rounded bg-[#172138] text-gray-500 font-medium`}>{rank}</span>
}

export default MultiFactor202609
