import { useState, useEffect, useCallback } from 'react'
import {
  Activity, TrendingUp, Target, Zap, RefreshCw,
  CheckCircle2, XCircle, AlertCircle, ChevronRight,
  Play, Square, RotateCcw, Terminal, ExternalLink, BookOpen,
  Dna, Microscope, BarChart3,
} from 'lucide-react'

const API_BASE = '/api/dashboard'
const AH_BASE = '/api/alpha-hunt'

const DIM_META = {
  chip:      { name: '筹码', color: '#10b981' },
  capital:   { name: '资金', color: '#06b6d4' },
  sector:    { name: '板块', color: '#f59e0b' },
  sentiment: { name: '情绪', color: '#8b5cf6' },
}
const DIM_KEYS = ['chip', 'capital', 'sector', 'sentiment']

function eastMoneyUrl(tsCode) {
  if (!tsCode) return '#'
  const parts = tsCode.split('.')
  if (parts.length !== 2) return '#'
  const code = parts[0]
  const mkt = parts[1]
  const prefix = mkt === 'SH' ? 'sh' : mkt === 'SZ' ? 'sz' : mkt === 'BJ' ? 'bj' : 'sh'
  return `https://quote.eastmoney.com/${prefix}${code}.html`
}

function StockLink({ name, tsCode, className }) {
  return (
    <a
      href={eastMoneyUrl(tsCode)}
      target="_blank"
      rel="noopener noreferrer"
      className={className || "font-medium text-gray-200 hover:text-cyan-400 transition inline-flex items-center gap-1"}
    >
      {name}
      <ExternalLink size={11} className="opacity-40 hover:opacity-80" />
    </a>
  )
}

function StatCard({ icon: Icon, label, value, sub, color }) {
  return (
    <div className="bg-[#0f1626] border border-[#1e293b] rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={16} style={{ color }} />
        <span className="text-xs text-gray-400">{label}</span>
      </div>
      <div className="text-2xl font-bold" style={{ color }}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  )
}

function HitBadge({ isHit }) {
  return isHit ? (
    <span className="inline-flex items-center gap-1 text-emerald-400 text-xs font-semibold">
      <CheckCircle2 size={14} /> 命中
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-red-400 text-xs font-semibold">
      <XCircle size={14} /> 未中
    </span>
  )
}

function MiniBar({ value, max, color }) {
  const pct = max > 0 ? Math.min(100, Math.abs(value) / max * 100) : 0
  return (
    <div className="w-16 h-1.5 bg-[#1e293b] rounded-full overflow-hidden">
      <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  )
}

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [agentBusy, setAgentBusy] = useState(false)

  // ── Alpha 搜索状态（Hook 必须在所有 early return 之前无条件调用）──
  const [ahStatus, setAhStatus] = useState({ running: false, stage: 'idle', progress: '', elapsed_seconds: 0 })
  const [ahResult, setAhResult] = useState(null)
  const [ahIcReport, setAhIcReport] = useState([])
  const [ahShowIC, setAhShowShowIC] = useState(false)
  const [ahShowResult, setAhShowResult] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}`)
      const d = await r.json()
      if (d.success) {
        setData(d.data)
        setError(null)
      } else {
        setError(d.error || '加载失败')
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  // Agent 运行中时每 10s 轮询状态
  useEffect(() => {
    if (data?.agent_status !== 'RUNNING') return
    const timer = setInterval(fetchData, 10000)
    return () => clearInterval(timer)
  }, [data?.agent_status, fetchData])

  const fetchAhStatus = useCallback(async () => {
    try {
      const r = await fetch(`${AH_BASE}/status`)
      if (r.ok) setAhStatus(await r.json())
    } catch {}
  }, [])

  useEffect(() => {
    fetchAhStatus()
    const t = setInterval(fetchAhStatus, 5000)
    return () => clearInterval(t)
  }, [fetchAhStatus])

  const fetchAhResult = useCallback(async () => {
    try {
      const r = await fetch(`${AH_BASE}/result`)
      if (r.ok) setAhResult(await r.json())
    } catch {}
  }, [])

  const fetchIcReport = useCallback(async () => {
    try {
      const r = await fetch(`${AH_BASE}/ic-report`)
      if (r.ok) {
        const d = await r.json()
        setAhIcReport(d.factors || [])
      }
    } catch {}
  }, [])

  const runDaily = async () => {
    setRunning(true)
    try {
      await fetch(`${API_BASE}/run`, { method: 'POST' })
      await fetchData()
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const startAgent = async () => {
    setAgentBusy(true)
    try {
      const r = await fetch('/api/agent/cruise/start', { method: 'POST' })
      const d = await r.json()
      if (d.status === 'error' || d.status === 'busy') {
        setError(d.message)
      }
      await fetchData()
    } catch (e) {
      setError(e.message)
    } finally {
      setAgentBusy(false)
    }
  }

  const stopAgent = async () => {
    setAgentBusy(true)
    try {
      await fetch('/api/agent/cruise/stop', { method: 'POST' })
      await new Promise(r => setTimeout(r, 2000))
      await fetchData()
    } catch (e) {
      setError(e.message)
    } finally {
      setAgentBusy(false)
    }
  }

  const resetAgent = async () => {
    setAgentBusy(true)
    try {
      await fetch('/api/agent/cruise/reset', { method: 'POST' })
      await fetchData()
    } catch (e) {
      setError(e.message)
    } finally {
      setAgentBusy(false)
    }
  }

  const startHunt = async () => {
    try {
      await fetch(`${AH_BASE}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ weeks: 104, population_size: 30, max_generations: 5 }),
      })
      fetchAhStatus()
    } catch {}
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh] text-gray-400">
        <RefreshCw size={24} className="animate-spin mr-2" />
        加载指挥中心...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-center">
          <AlertCircle size={32} className="text-amber-400 mx-auto mb-3" />
          <p className="text-gray-400 mb-2">{error}</p>
          <button onClick={fetchData} className="text-cyan-400 text-sm hover:underline">重试</button>
        </div>
      </div>
    )
  }

  const stats = data?.stats || {}
  const todaySel = data?.today_selections || []
  const perf = data?.latest_performance || []
  const trend = data?.trend || []
  const dimAnalysis = data?.dimension_analysis || {}
  const agentStatus = data?.agent_status || 'IDLE'
  const selDate = data?.latest_selection_date || '—'

  return (
    <div className="space-y-6">
      {/* ── 头部 ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Activity size={20} className="text-cyan-400" />
            指挥中心
          </h1>
          <p className="text-xs text-gray-500 mt-1">
            选股 → 验证 → 归因 → 调参 · 良性闭环系统
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Agent 状态 + 控制 */}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-[#0f1626] border border-[#1e293b]">
            <Terminal size={14} className={
              agentStatus === 'RUNNING' ? 'text-emerald-400' : 'text-slate-500'
            } />
            <span className={`text-xs font-semibold ${
              agentStatus === 'RUNNING' ? 'text-emerald-400' : 'text-slate-400'
            }`}>
              Agent {agentStatus}
            </span>
            <div className="w-px h-4 bg-[#1e293b] mx-1" />
            {agentStatus === 'RUNNING' ? (
              <button
                onClick={stopAgent}
                disabled={agentBusy}
                title="停止巡航"
                className="flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-500/15 text-red-400 hover:bg-red-500/25 border border-red-500/20 transition disabled:opacity-40"
              >
                <Square size={11} />
                {agentBusy ? '停止中...' : '停止'}
              </button>
            ) : (
              <button
                onClick={startAgent}
                disabled={agentBusy}
                title="启动巡航"
                className="flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/20 transition disabled:opacity-40"
              >
                <Play size={11} />
                {agentBusy ? '启动中...' : '启动'}
              </button>
            )}
            <button
              onClick={resetAgent}
              disabled={agentBusy}
              title="重置巡航"
              className="flex items-center justify-center w-6 h-5 rounded text-xs bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 border border-amber-500/20 transition disabled:opacity-40"
            >
              <RotateCcw size={10} />
            </button>
          </div>
          {/* 每日闭环 */}
          <button
            onClick={runDaily}
            disabled={running}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/30 transition text-sm font-semibold disabled:opacity-50"
          >
            <Zap size={14} />
            {running ? '执行中...' : '执行每日闭环'}
          </button>
        </div>
      </div>

      {/* ── 状态卡片 ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          icon={Target} label="今日选股" color="#3b82f6"
          value={todaySel.length}
          sub={selDate}
        />
        <StatCard
          icon={CheckCircle2} label="累计命中率" color="#10b981"
          value={stats.total_verified ? `${(stats.hit_rate * 100).toFixed(1)}%` : '—'}
          sub={stats.total_verified ? `${stats.total_hits}/${stats.total_verified}` : '未验证'}
        />
        <StatCard
          icon={TrendingUp} label="平均超额" color="#06b6d4"
          value={stats.avg_excess != null ? `${stats.avg_excess.toFixed(2)}%` : '—'}
          sub={stats.avg_pct_chg != null ? `绝对 ${stats.avg_pct_chg.toFixed(2)}%` : ''}
        />
        <StatCard
          icon={Activity} label="趋势天数" color="#8b5cf6"
          value={trend.length}
          sub={trend.length > 0 ? `${trend[0].selection_date} 最新` : '无数据'}
        />
      </div>

      {/* ── 主体内容 ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 左：今日选股 */}
        <div className="bg-[#0f1626] border border-[#1e293b] rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#1e293b]">
            <span className="text-sm font-semibold text-gray-200">今日选股 Top-{todaySel.length}</span>
            <span className="text-xs text-gray-500">{selDate}</span>
          </div>
          <div className="max-h-[400px] overflow-y-auto">
            {todaySel.length === 0 ? (
              <div className="p-8 text-center text-gray-500 text-sm">
                <Target size={24} className="mx-auto mb-2 opacity-30" />
                尚未执行选股
                <button onClick={runDaily} className="block mx-auto mt-3 text-cyan-400 text-xs hover:underline">
                  执行每日闭环
                </button>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-[#1e293b]">
                    <th className="px-3 py-2 text-left">#</th>
                    <th className="px-3 py-2 text-left">股票</th>
                    <th className="px-3 py-2 text-right">共振分</th>
                    <th className="px-3 py-2 text-center hidden sm:table-cell">维度</th>
                  </tr>
                </thead>
                <tbody>
                  {todaySel.map((s, i) => (
                    <tr key={i} className="border-b border-[#1e293b]/50 hover:bg-[#131c2f]">
                      <td className="px-3 py-2 text-gray-500">{s.rank || i + 1}</td>
                      <td className="px-3 py-2">
                        <StockLink name={s.name} tsCode={s.ts_code} />
                        <div className="text-xs text-gray-500">{s.ts_code}</div>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className="font-mono text-emerald-400">{(s.resonance_score * 100).toFixed(1)}</span>
                        <span className="text-xs text-gray-500 ml-1">{s.resonance_level}</span>
                      </td>
                      <td className="px-3 py-2 hidden sm:table-cell">
                        <div className="flex items-center gap-1 justify-center">
                          {DIM_KEYS.map(k => {
                            const v = s[`${k}_score`]
                            return (
                              <div
                                key={k}
                                className="w-1.5 h-1.5 rounded-full"
                                style={{
                                  backgroundColor: DIM_META[k].color,
                                  opacity: v != null ? 0.3 + (v || 0) * 0.7 : 0.15
                                }}
                                title={`${DIM_META[k].name}: ${v != null ? (v * 100).toFixed(0) : '—'}`}
                              />
                            )
                          })}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* 右：昨日表现 */}
        <div className="bg-[#0f1626] border border-[#1e293b] rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#1e293b]">
            <span className="text-sm font-semibold text-gray-200">次日验证</span>
            <span className="text-xs text-gray-500">
              {perf.length > 0 ? `${perf[0].selection_date} → ${perf[0].next_trade_date}` : '—'}
            </span>
          </div>
          <div className="max-h-[400px] overflow-y-auto">
            {perf.length === 0 ? (
              <div className="p-8 text-center text-gray-500 text-sm">
                <CheckCircle2 size={24} className="mx-auto mb-2 opacity-30" />
                尚无验证记录
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b border-[#1e293b]">
                    <th className="px-3 py-2 text-left">股票</th>
                    <th className="px-3 py-2 text-right">涨跌</th>
                    <th className="px-3 py-2 text-right">超额</th>
                    <th className="px-3 py-2 text-center">命中</th>
                  </tr>
                </thead>
                <tbody>
                  {perf.map((p, i) => (
                    <tr key={i} className="border-b border-[#1e293b]/50 hover:bg-[#131c2f]">
                      <td className="px-3 py-2">
                        <StockLink name={p.name} tsCode={p.ts_code} className="font-medium text-gray-200 text-xs hover:text-cyan-400 transition inline-flex items-center gap-1" />
                        <div className="text-[10px] text-gray-500">#{p.rank} {(p.resonance_score * 100).toFixed(0)}分</div>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs">
                        <span className={p.pct_chg >= 0 ? 'text-red-400' : 'text-green-400'}>
                          {p.pct_chg.toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs">
                        <span className={p.excess_return >= 0 ? 'text-red-400' : 'text-green-400'}>
                          {p.excess_return.toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <HitBadge isHit={p.is_hit} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* ── 底部：维度贡献 + 趋势 ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 维度贡献分析 */}
        <div className="bg-[#0f1626] border border-[#1e293b] rounded-xl p-4">
          <div className="text-sm font-semibold text-gray-200 mb-3">维度贡献分析</div>
          {Object.keys(dimAnalysis).length === 0 ? (
            <div className="text-gray-500 text-sm text-center py-4">需要验证数据才能分析</div>
          ) : (
            <div className="space-y-3">
              {DIM_KEYS.map(k => {
                const d = dimAnalysis[k]
                if (!d) return null
                const meta = DIM_META[k]
                const edge = d.edge || 0
                const maxEdge = 0.3
                return (
                  <div key={k} className="flex items-center gap-3">
                    <div className="w-12 flex items-center gap-1.5">
                      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: meta.color }} />
                      <span className="text-xs text-gray-300">{meta.name}</span>
                    </div>
                    <div className="flex-1 text-xs">
                      <span className="text-gray-500">命中 {d.hit_avg_score.toFixed(2)}</span>
                      <span className="text-gray-600 mx-2">vs</span>
                      <span className="text-gray-500">未中 {d.miss_avg_score.toFixed(2)}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <MiniBar value={edge} max={maxEdge} color={meta.color} />
                      <span className="text-xs font-mono" style={{ color: edge > 0 ? '#10b981' : '#ef4444' }}>
                        {edge >= 0 ? '+' : ''}{edge.toFixed(3)}
                      </span>
                    </div>
                  </div>
                )
              })}
              <div className="text-xs text-gray-500 mt-2 pt-2 border-t border-[#1e293b]">
                  edge {'>'} 0 表示该维度高分时命中率高，维度有效
                </div>
            </div>
          )}
        </div>

        {/* 命中率趋势 */}
        <div className="bg-[#0f1626] border border-[#1e293b] rounded-xl p-4">
          <div className="text-sm font-semibold text-gray-200 mb-3">命中率趋势</div>
          {trend.length === 0 ? (
            <div className="text-gray-500 text-sm text-center py-4">尚无趋势数据</div>
          ) : (
            <div className="space-y-1">
              {trend.slice(0, 10).map((t, i) => {
                const hr = t.total > 0 ? t.hits / t.total : 0
                const avgExc = t.avg_excess || 0
                return (
                  <div key={i} className="flex items-center gap-3 text-xs">
                    <span className="text-gray-500 w-20">{t.selection_date}</span>
                    <div className="flex-1 h-2 bg-[#1e293b] rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${hr * 100}%`,
                          backgroundColor: hr >= 0.5 ? '#10b981' : '#ef4444'
                        }}
                      />
                    </div>
                    <span className={`w-12 text-right font-mono ${hr >= 0.5 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {(hr * 100).toFixed(0)}%
                    </span>
                    <span className={`w-14 text-right font-mono ${avgExc >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                      {avgExc.toFixed(2)}%
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── Alpha 搜索流水线 ── */}
      <div className="bg-[#0a0e17] border border-[#1e293b] rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-bold text-gray-200 flex items-center gap-2">
            <Dna size={16} className="text-cyan-400" />
            Alpha 搜索流水线
          </h3>
          <div className="flex items-center gap-2">
            <button
              onClick={startHunt}
              disabled={ahStatus.running}
              className={`px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 ${
                ahStatus.running
                  ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                  : 'bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 border border-emerald-500/30'
              }`}
            >
              <Play size={12} /> 启动搜索
            </button>
            <button
              onClick={() => { fetchIcReport(); setAhShowShowIC(!ahShowIC) }}
              className="px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 border border-cyan-500/30"
            >
              <Microscope size={12} /> 因子体检
            </button>
            <button
              onClick={() => { fetchAhResult(); setAhShowResult(!ahShowResult) }}
              className="px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 border border-purple-500/30"
            >
              <BarChart3 size={12} /> 搜索结果
            </button>
          </div>
        </div>

        {/* 状态条 */}
        {ahStatus.running && (
          <div className="mb-3 bg-[#0d1117] border border-[#1e293b] rounded-lg p-3">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs text-emerald-400 font-semibold">{ahStatus.stage}</span>
              <span className="text-xs text-gray-500 ml-auto">{ahStatus.elapsed_seconds}s</span>
            </div>
            <p className="text-xs text-gray-400">{ahStatus.progress}</p>
          </div>
        )}

        {/* 因子体检报告 */}
        {ahShowIC && ahIcReport.length > 0 && (
          <div className="mb-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-[#1e293b]">
                  <th className="text-left py-1.5 px-2">因子</th>
                  <th className="text-right py-1.5 px-2">IC均值</th>
                  <th className="text-right py-1.5 px-2">t值</th>
                  <th className="text-right py-1.5 px-2">半衰期</th>
                  <th className="text-right py-1.5 px-2">胜率</th>
                  <th className="text-center py-1.5 px-2">状态</th>
                </tr>
              </thead>
              <tbody>
                {ahIcReport.map(r => (
                  <tr key={r.factor} className="border-b border-[#1e293b]/50 hover:bg-[#1e293b]/30">
                    <td className="py-1.5 px-2"><code className="text-cyan-300">{r.factor}</code></td>
                    <td className={`text-right py-1.5 px-2 ${r.ic_mean > 0 ? 'text-emerald-400' : 'text-red-400'}`}>{r.ic_mean > 0 ? '+' : ''}{r.ic_mean?.toFixed(4)}</td>
                    <td className="text-right py-1.5 px-2 text-gray-300">{r.t_stat?.toFixed(1)}</td>
                    <td className="text-right py-1.5 px-2 text-gray-300">{r.halflife_weeks ? `${r.halflife_weeks}w` : '—'}</td>
                    <td className="text-right py-1.5 px-2 text-gray-300">{r.winrate?.toFixed(3)}</td>
                    <td className="text-center py-1.5 px-2">
                      {r.status === 'PASS' ? <CheckCircle2 size={14} className="text-emerald-400 inline" /> : <XCircle size={14} className="text-red-400 inline" />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* 搜索结果 */}
        {ahShowResult && ahResult && (
          <div className="mb-3 bg-[#0d1117] border border-[#1e293b] rounded-lg p-3 space-y-2">
            {ahResult.error ? (
              <p className="text-xs text-red-400">{ahResult.error}</p>
            ) : ahResult.best_combo ? (
              <>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500">最优组合:</span>
                  <div className="flex flex-wrap gap-1">
                    {ahResult.best_combo.map(f => (
                      <code key={f} className="text-xs text-cyan-300 bg-[#1e293b] px-1.5 py-0.5 rounded">{f}</code>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-4 text-xs">
                  <span className="text-gray-500">适应度: <strong className="text-emerald-400">{ahResult.best_fitness}</strong></span>
                  <span className="text-gray-500">评估组合数: {ahResult.n_evaluated}</span>
                  <span className="text-gray-500">回测周数: {ahResult.n_weeks}</span>
                </div>
                {ahResult.passed_factors && (
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">通过IC筛选:</span>
                    <span className="text-xs text-gray-400">{ahResult.passed_factors.length} 个因子</span>
                  </div>
                )}
              </>
            ) : (
              <p className="text-xs text-gray-500">尚无搜索结果，请先启动搜索</p>
            )}
          </div>
        )}

        {/* 搜索方法论说明 */}
        <div className="text-[11px] text-gray-500 leading-relaxed mt-2 pt-2 border-t border-[#1e293b]/50">
          <span className="text-gray-400 font-semibold">流水线:</span>
          IC 预筛选(半衰期≥1.5w) → 中性化预计算缓存 → 遗传搜索(50种群×10代) → 复合适应度(ER/max(MDD,4%)×ICIR/0.4) → Buffer Zone(Top20/Top35) → 四关验证
        </div>
      </div>

      {/* ── 策略说明 + 因子释义 ── */}
      <StrategyExplanation />
    </div>
  )
}

// ═════════════════════════════════════════
//  策略说明 + 因子释义组件
// ═════════════════════════════════════════

const STRATEGY_TEXT = {
  summary: '四重共振策略通过筹码、资金、板块、情绪四个维度对全市场股票进行截面评分，四维加权合成共振总分，按总分排名选股。共振等级分为 strong（>75分）、medium（>55分）、weak（>35分）、none（≤35分）。每日收盘后运行选股，次日验证表现，形成"选股→验证→归因→调权"的良性闭环。',
}

const DIM_EXPLANATIONS = [
  {
    key: 'chip', name: '筹码维度', color: '#10b981',
    desc: '衡量股票的持仓成本分布和筹码集中度，反映主力建仓行为和获利盘压力。',
    factors: [
      { name: 'cyq_chip_concentration_60d', desc: 'CYQ 筹码集中度：基于指数衰减换手率加权的持仓成本分布直方图，计算 60 日内筹码集中程度。值越高表示筹码越集中在某价格区间，主力控盘力度越强。' },
      { name: 'chip_concentration', desc: '均线偏离筹码集中度（回退因子）：基于收盘价与各均线的偏离度合成，作为 CYQ 不可用时的兜底指标。' },
    ],
  },
  {
    key: 'capital', name: '资金维度', color: '#06b6d4',
    desc: '衡量股票的流动性特征和资金流向，反映市场参与度和机构资金态度。',
    factors: [
      { name: 'amihud_illiq_20d', desc: 'Amihud 非流动性指标：|日收益率| / 成交额 的 20 日均值。值越高表示股票越不流动，单位资金对价格冲击越大，适合捕捉流动性溢价。' },
      { name: 'vol_ratio', desc: '量比：当日成交量与过去 5 日平均成交量之比，反映成交活跃度的突变。量比 > 1 表示放量，< 1 表示缩量。' },
      { name: 'north_net_inflow_ratio', desc: '北向资金净流入占比：沪/深股通净买入额占流通市值的比例，反映外资对该股票的态度。正值表示外资净流入。' },
    ],
  },
  {
    key: 'sector', name: '板块维度', color: '#f59e0b',
    desc: '衡量股票所属行业的整体强弱，反映板块轮动效应和行业资金流向。',
    factors: [
      { name: 'sector_strength', desc: '板块强度因子：按行业分组计算三个子指标加权合成——① 行业收益中位数（板块涨跌幅度）② 板块宽度（上涨家数/总家数）③ 行业成交额排名分位。三者加权后截面 rank 归一化到 [0,1]。值越高表示该行业当前越强。' },
    ],
  },
  {
    key: 'sentiment', name: '情绪维度', color: '#8b5cf6',
    desc: '衡量市场参与者的情绪倾向和交易热度，反映散户跟风意愿和短期博弈氛围。',
    factors: [
      { name: 'sentiment_composite', desc: '情绪复合因子：综合换手率偏离度、成交额波动率、量价背离程度三个子指标，归一化到 [0,1]。值越高表示市场情绪越亢奋。' },
      { name: 'turnover_rate', desc: '换手率（回退因子）：当日成交量与流通股本之比，直接反映交易活跃度。高换手通常伴随情绪高潮。' },
    ],
  },
]

const OTHER_FACTORS = [
  { name: 'overnight_return_5d', desc: '隔夜收益 5 日均值：开盘价相对前日收盘价的变动率，反映隔夜消息面和散户情绪。A股隔夜收益主要由散户行为驱动。' },
  { name: 'intraday_return_5d', desc: '日内收益 5 日均值：收盘价相对当日开盘价的变动率，反映日内机构博弈方向。A股日内收益主要由机构行为驱动。' },
  { name: 'gk_volatility_20d', desc: 'Garman-Klass 波动率：基于 OHLC 四价的高效波动率估计器，比传统收盘价波动率更精确。利用日内极值信息，捕捉真实波动。' },
  { name: 'parkinson_volatility_20d', desc: 'Parkinson 波动率：仅用最高价/最低价计算的波动率，计算简单但效率较高。' },
  { name: 'turnover_volatility_20d', desc: '换手率波动率：20 日换手率标准差，衡量交易活跃度的稳定性。高波动表示资金进出频繁。' },
  { name: 'volume_skewness_20d', desc: '成交量偏度：20 日成交量分布的偏斜度。正偏表示偶发放量，负偏表示偶发缩量。' },
  { name: 'return_5d / return_20d / return_60d', desc: '不同周期的动量因子：过去 N 日累计收益率，衡量价格趋势的持续性。短期动量反映近期资金态度，长期动量反映基本面变化。' },
  { name: 'volatility_10d / 20d / 60d / 120d', desc: '不同周期的波动率：基于收盘价的标准差年化，衡量价格波动程度。低波动股票通常风险调整后收益更优。' },
  { name: 'max_drawdown_20d / 60d', desc: '最大回撤：过去 N 日内从最高点到最低点的最大跌幅，衡量下行风险。' },
  { name: 'skewness_20d', desc: '收益偏度：20 日收益率分布的偏斜度。负偏表示左尾风险大（偶发大跌），正偏表示右尾机会多（偶发大涨）。' },
  { name: 'pb / pe_ttm / roe', desc: '估值因子：PB（市净率）衡量股价相对净资产溢价；PE_TTM（滚动市盈率）衡量回本年限；ROE（净资产收益率）衡量盈利能力。低 PB + 高 ROE 是价值投资核心。' },
  { name: 'north_net_inflow_ratio', desc: '北向资金净流入占比：外资通过沪/深股通净买入额占流通市值比，正值表示外资看好。' },
  { name: 'profit_ratio_estimate', desc: '获利盘比例估算：基于均线偏离度估算当前持股者的盈利比例，高获利盘意味着获利回吐压力。' },
  { name: 'chip_concentration', desc: '筹码集中度（均线偏离法）：收盘价与多条均线偏离程度的合成指标，作为 CYQ 的回退方案。' },
]

function StrategyExplanation() {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-[#0f1626] border border-[#1e293b] rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-[#131c2f] transition"
      >
        <div className="flex items-center gap-2">
          <BookOpen size={16} className="text-cyan-400" />
          <span className="text-sm font-semibold text-gray-200">策略说明 · 因子释义</span>
        </div>
        <ChevronRight
          size={16}
          className={`text-gray-500 transition-transform ${expanded ? 'rotate-90' : ''}`}
        />
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-4">
          {/* 策略概述 */}
          <div className="bg-[#0d1117] border border-[#1e293b] rounded-lg p-3">
            <div className="text-xs font-semibold text-cyan-400 mb-2">策略概述</div>
            <p className="text-xs text-gray-400 leading-relaxed">{STRATEGY_TEXT.summary}</p>
          </div>

          {/* 四维详解 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {DIM_EXPLANATIONS.map(dim => (
              <div key={dim.key} className="bg-[#0d1117] border border-[#1e293b] rounded-lg p-3">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: dim.color }} />
                  <span className="text-xs font-semibold" style={{ color: dim.color }}>{dim.name}</span>
                </div>
                <p className="text-[11px] text-gray-500 mb-2">{dim.desc}</p>
                <div className="space-y-1.5">
                  {dim.factors.map(f => (
                    <div key={f.name} className="text-[11px]">
                      <code className="text-cyan-300 bg-[#1e293b] px-1.5 py-0.5 rounded">{f.name}</code>
                      <p className="text-gray-500 mt-0.5 leading-relaxed">{f.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* 其他候选因子 */}
          <div className="bg-[#0d1117] border border-[#1e293b] rounded-lg p-3">
            <div className="text-xs font-semibold text-gray-300 mb-2">其他候选因子释义</div>
            <div className="space-y-1.5">
              {OTHER_FACTORS.map(f => (
                <div key={f.name} className="text-[11px] flex gap-2">
                  <code className="text-cyan-300 bg-[#1e293b] px-1.5 py-0.5 rounded shrink-0">{f.name}</code>
                  <span className="text-gray-500 leading-relaxed">{f.desc}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 闭环说明 */}
          <div className="bg-[#0d1117] border border-[#1e293b] rounded-lg p-3">
            <div className="text-xs font-semibold text-emerald-400 mb-2">闭环系统</div>
            <div className="text-[11px] text-gray-400 leading-relaxed space-y-1">
              <p>1. <strong className="text-gray-300">选股</strong>：每日收盘后运行共振引擎，选出 Top-20 写入 selection_log</p>
              <p>2. <strong className="text-gray-300">验证</strong>：次日对比选股实际涨跌 vs 基准，计算超额收益和命中率，写入 performance_log</p>
              <p>3. <strong className="text-gray-300">归因</strong>：分析各维度高分时命中率差异（edge），判断哪个维度当前最有效</p>
              <p>4. <strong className="text-gray-300">调权</strong>：edge {'>'} 0 的维度增加权重，edge {'<'} 0 的降低权重，实现自动学习</p>
              <p>5. <strong className="text-gray-300">Agent 巡航</strong>：后台搜索最优因子组合，达标（超额卡玛 ≥ 0.50）后部署权重</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
