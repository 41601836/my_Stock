import { useState, useEffect, useCallback } from 'react'
import {
  Activity, TrendingUp, Target, Zap, RefreshCw,
  CheckCircle2, XCircle, AlertCircle, ChevronRight,
  Play, Square, RotateCcw, Terminal,
} from 'lucide-react'

const API_BASE = '/api/dashboard'

const DIM_META = {
  chip:      { name: '筹码', color: '#10b981' },
  capital:   { name: '资金', color: '#06b6d4' },
  sector:    { name: '板块', color: '#f59e0b' },
  sentiment: { name: '情绪', color: '#8b5cf6' },
}
const DIM_KEYS = ['chip', 'capital', 'sector', 'sentiment']

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
  }, [data?.agent_status])

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
                        <div className="font-medium text-gray-200">{s.name}</div>
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
                        <div className="font-medium text-gray-200 text-xs">{p.name}</div>
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
    </div>
  )
}
