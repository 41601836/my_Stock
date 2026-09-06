// ScanHistory.jsx —— 时机预警独立页（其余 Tab 已迁入 /scanner 下）
import React, { useState, useEffect, useCallback } from 'react'
import { Clock, RefreshCw, ChevronDown, ChevronRight, ExternalLink, Bell, Info } from 'lucide-react'
import { eastMoneyUrl } from './scanner/shared'

// ── 时机预警配置 ───────────────────────────────────────────
const LEVEL_CONFIG = {
  GOLDEN: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', badge: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40', dot: 'bg-emerald-400', label: '🟢 最佳建仓窗口', desc: '多重信号共振，当前为最优入场时机' },
  WATCH:  { bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   badge: 'bg-amber-500/20 text-amber-300 border-amber-500/40',   dot: 'bg-amber-400',   label: '🟡 跟踪观察期',   desc: '信号初步触发，持续观察确认' },
  NORMAL: { bg: 'bg-[#0D1B2E]',      border: 'border-[#1A2840]',      badge: 'bg-gray-700/50 text-gray-400 border-gray-600/30',       dot: 'bg-gray-500',   label: '⚪ 普通信号',     desc: '信号偏弱，暂时观望' },
}

const SIGNAL_COLORS = {
  FIRST_APPEAR:  'bg-sky-500/15 text-sky-300 border-sky-500/30',
  REENTRY:       'bg-purple-500/15 text-purple-300 border-purple-500/30',
  STREAK_3:      'bg-amber-500/15 text-amber-300 border-amber-500/30',
  RANK_SURGE:    'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  HIGH_SCORE:    'bg-blue-500/15 text-blue-300 border-blue-500/30',
  REGIME_MATCH:  'bg-rose-500/15 text-rose-300 border-rose-500/30',
  OVERHEATED:    'bg-red-900/20 text-red-400 border-red-800/30',
  CHASING_HIGH:  'bg-red-900/20 text-red-400 border-red-800/30',
  CHASE_RISK:    'bg-orange-900/20 text-orange-400 border-orange-800/30',
}

const REGIME_LABELS = {
  BEAR:  { label: 'BEAR 熊市', color: 'text-rose-400 bg-rose-500/10 border-rose-500/30' },
  DARK:  { label: 'DARK 暗市', color: 'text-orange-400 bg-orange-500/10 border-orange-500/30' },
  RANGE: { label: 'RANGE 震荡', color: 'text-sky-400 bg-sky-500/10 border-sky-500/30' },
  BULL:  { label: 'BULL 牛市', color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
}

function ScoreMeter({ score }) {
  const color = score >= 60 ? 'from-emerald-500 to-emerald-400'
    : score >= 35 ? 'from-amber-500 to-amber-400'
    : 'from-gray-600 to-gray-500'
  return (
    <div className="flex items-center gap-2">
      <div className="relative w-14 h-14 flex-shrink-0">
        <svg className="w-14 h-14 -rotate-90" viewBox="0 0 56 56">
          <circle cx="28" cy="28" r="22" fill="none" stroke="#1A2840" strokeWidth="5" />
          <circle cx="28" cy="28" r="22" fill="none"
            stroke="url(#sg)" strokeWidth="5" strokeLinecap="round"
            strokeDasharray={`${(score / 100) * 138.2} 138.2`}
          />
          <defs>
            <linearGradient id="sg" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" className={`stop-color-emerald-500`}
                stopColor={score >= 60 ? '#10b981' : score >= 35 ? '#f59e0b' : '#4b5563'} />
              <stop offset="100%"
                stopColor={score >= 60 ? '#34d399' : score >= 35 ? '#fbbf24' : '#6b7280'} />
            </linearGradient>
          </defs>
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={`text-sm font-bold font-mono ${
            score >= 60 ? 'text-emerald-400' : score >= 35 ? 'text-amber-400' : 'text-gray-500'
          }`}>{score}</span>
        </div>
      </div>
    </div>
  )
}

function AlertCard({ alert, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const cfg = LEVEL_CONFIG[alert.level] || LEVEL_CONFIG.NORMAL
  const posSignals = alert.signals.filter(s => s.points > 0)
  const negSignals = alert.signals.filter(s => s.points < 0)

  return (
    <div className={`rounded-xl border ${cfg.border} ${cfg.bg} overflow-hidden transition-all`}>
      {/* 卡片主行 */}
      <button className="w-full flex items-center gap-3 p-3 text-left" onClick={() => setOpen(o => !o)}>
        <ScoreMeter score={alert.score} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <a href={eastMoneyUrl(alert.ts_code)} target="_blank" rel="noopener noreferrer"
              onClick={e => e.stopPropagation()}
              className="font-bold text-gray-100 hover:text-sky-300 transition-colors inline-flex items-center gap-1 group/lk">
              {alert.name}
              <ExternalLink className="h-3 w-3 opacity-0 group-hover/lk:opacity-50 flex-shrink-0" />
            </a>
            <span className="text-xs text-gray-500 font-mono">{alert.ts_code}</span>
            <span className={`px-1.5 py-0.5 rounded text-xs border ${cfg.badge}`}>
              {alert.level === 'GOLDEN' ? '最佳建仓' : alert.level === 'WATCH' ? '跟踪观察' : '普通信号'}
            </span>
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            {alert.industry?.split(' | ')[1] || alert.industry}
            <span className="mx-1.5 text-gray-700">·</span>
            今日排名 <span className="text-gray-300">#{alert.rank}</span>
            <span className="mx-1.5 text-gray-700">·</span>
            连续 <span className="text-gray-300">{alert.streak}</span> 天
            {alert.yesterday_rank && (
              <><span className="mx-1.5 text-gray-700">·</span>
              昨排 <span className="text-gray-400">#{alert.yesterday_rank}</span></>
            )}
          </div>
          {/* 信号标签（折叠时展示正向信号） */}
          {!open && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {posSignals.slice(0, 3).map(s => (
                <span key={s.type} className={`px-1.5 py-0.5 rounded text-xs border ${SIGNAL_COLORS[s.type] || 'bg-gray-700/30 text-gray-400 border-gray-600/30'}`}>
                  {s.label}
                </span>
              ))}
              {negSignals.length > 0 && (
                <span className="px-1.5 py-0.5 rounded text-xs border bg-red-900/20 text-red-400 border-red-800/30">
                  {negSignals[0].label}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <div className="text-right">
            <div className={`text-xs font-mono ${alert.pct_chg > 0 ? 'text-rose-400' : alert.pct_chg < 0 ? 'text-emerald-400' : 'text-gray-500'}`}>
              {alert.pct_chg > 0 ? '+' : ''}{alert.pct_chg?.toFixed(2)}%
            </div>
            <div className="text-xs text-gray-600 font-mono">¥{alert.close}</div>
          </div>
          {open ? <ChevronDown className="h-4 w-4 text-gray-600" /> : <ChevronRight className="h-4 w-4 text-gray-600" />}
        </div>
      </button>

      {/* 展开：信号详情 */}
      {open && (
        <div className="border-t border-[#1A2840] px-4 py-3 space-y-2">
          <div className="text-xs text-gray-500 font-medium mb-2">信号拆解</div>
          {alert.signals.map(s => (
            <div key={s.type} className="flex items-start gap-2">
              <span className={`px-1.5 py-0.5 rounded text-xs border flex-shrink-0 ${SIGNAL_COLORS[s.type] || 'bg-gray-700/30 text-gray-400 border-gray-600/30'}`}>
                {s.label}
              </span>
              <span className="text-xs text-gray-400 flex-1">{s.desc}</span>
              <span className={`text-xs font-mono font-bold flex-shrink-0 ${s.points > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {s.points > 0 ? '+' : ''}{s.points}分
              </span>
            </div>
          ))}
          <div className="flex items-center gap-2 pt-2 border-t border-[#1A2840]">
            <span className="text-xs text-gray-500">因子分</span>
            <div className="flex-1 h-1 bg-[#0E1524] rounded-full overflow-hidden">
              <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${Math.min(alert.factor_score, 100)}%` }} />
            </div>
            <span className="text-xs font-mono text-gray-300">{alert.factor_score}%</span>
          </div>
        </div>
      )}
    </div>
  )
}

function TimingTab({ timing, loadingTiming, fetchTiming }) {
  if (loadingTiming) return (
    <div className="flex flex-col items-center justify-center h-48 gap-3">
      <div className="w-8 h-8 border-2 border-sky-500/30 border-t-sky-400 rounded-full animate-spin" />
      <p className="text-gray-500 text-sm">正在计算时机评分…</p>
    </div>
  )

  if (!timing || !timing.alerts?.length) return (
    <div className="flex flex-col items-center justify-center h-48 text-gray-500 gap-2">
      <Bell className="h-8 w-8 opacity-30" />
      <p className="text-sm">暂无今日在榜数据，请先访问建仓机会扫描页面</p>
    </div>
  )

  const { summary = {}, golden = [], watch = [], normal = [], regime, scan_date } = timing
  const regimeCfg = REGIME_LABELS[regime] || { label: regime, color: 'text-gray-400 bg-gray-700/20 border-gray-600/30' }
  const fmtDate = d => d ? `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}` : '—'

  return (
    <div className="space-y-4 p-3">
      {/* 顶部状态栏 */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className={`px-2 py-1 rounded-lg text-xs font-bold border ${regimeCfg.color}`}>{regimeCfg.label}</span>
        <span className="text-xs text-gray-500">基准日期：{fmtDate(scan_date)}</span>
        <div className="flex gap-3 ml-auto text-xs">
          <span className="text-emerald-400 font-bold">🟢 {summary.golden} 只最佳</span>
          <span className="text-amber-400 font-bold">🟡 {summary.watch} 只观察</span>
          <span className="text-gray-500">⚪ {summary.normal} 只普通</span>
        </div>
        <button onClick={fetchTiming} className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-500 hover:text-gray-300 border border-[#1A2840] hover:border-sky-500/40 transition-all">
          <RefreshCw className="h-3 w-3" />刷新
        </button>
      </div>

      {/* 评分说明 */}
      <div className="bg-[#080F1C] border border-[#1A2840] rounded-lg px-3 py-2 flex items-start gap-2">
        <Info className="h-3.5 w-3.5 text-gray-600 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-gray-500">
          评分维度：<span className="text-sky-400">初次入榜+25</span>、<span className="text-amber-400">连续第3天+15</span>、<span className="text-emerald-400">排名跃升+20</span>、<span className="text-purple-400">二次入榜+12</span>、<span className="text-blue-400">因子极强+10</span>、<span className="text-rose-400">Bear/Dark状态+18</span>；追涨/过热扣分
        </p>
      </div>

      {/* 最佳建仓窗口 */}
      {golden.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-sm font-bold text-emerald-400">最佳建仓窗口（{golden.length} 只）</span>
          </div>
          {golden.map(a => <AlertCard key={a.ts_code} alert={a} defaultOpen={true} />)}
        </div>
      )}

      {/* 跟踪观察期 */}
      {watch.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-amber-400" />
            <span className="text-sm font-bold text-amber-400">跟踪观察期（{watch.length} 只）</span>
          </div>
          {watch.map(a => <AlertCard key={a.ts_code} alert={a} defaultOpen={false} />)}
        </div>
      )}

      {/* 普通信号（折叠） */}
      {normal.length > 0 && (
        <details className="group">
          <summary className="flex items-center gap-2 cursor-pointer list-none py-1">
            <ChevronRight className="h-4 w-4 text-gray-600 group-open:rotate-90 transition-transform" />
            <span className="text-sm text-gray-500">普通信号（{normal.length} 只，点击展开）</span>
          </summary>
          <div className="space-y-2 mt-2">
            {normal.map(a => <AlertCard key={a.ts_code} alert={a} />)}
          </div>
        </details>
      )}
    </div>
  )
}

export default function ScanHistory() {
  const [timing, setTiming] = useState(null)
  const [loadingTiming, setLoadingTiming] = useState(false)

  const fetchTiming = useCallback(() => {
    setLoadingTiming(true)
    fetch('/api/scan-history/timing')
      .then(r => r.json())
      .then(d => setTiming(d))
      .catch(console.error)
      .finally(() => setLoadingTiming(false))
  }, [])

  useEffect(() => { fetchTiming() }, [fetchTiming])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-bold text-gray-100 flex items-center gap-2">
            <Clock className="h-5 w-5 text-sky-400" />建仓时机预警
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">多维度信号融合评分，识别最佳建仓窗口</p>
        </div>
        <button onClick={fetchTiming} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0D1B2E] border border-[#1A2840] hover:border-sky-500/40 text-gray-400 hover:text-gray-200 text-xs transition-all">
          <RefreshCw className={`h-3.5 w-3.5 ${loadingTiming ? 'animate-spin' : ''}`} />刷新
        </button>
      </div>

      <div className="bg-[#0A1322] border border-[#1A2840] rounded-xl overflow-hidden">
        <TimingTab timing={timing} loadingTiming={loadingTiming} fetchTiming={fetchTiming} />
      </div>

      <p className="text-xs text-gray-500 text-center">
        频率排行 / 连续上榜 / 每日快照 已迁入侧边栏「建仓机会扫描」下的独立子路由
      </p>
    </div>
  )
}
