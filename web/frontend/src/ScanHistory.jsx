// ScanHistory.jsx —— 建仓扫描历史累计视图
import React, { useState, useEffect, useCallback } from 'react'
import { BarChart3, Calendar, RefreshCw, Flame, ArrowUpRight, ArrowDownRight, Minus, ChevronDown, ChevronRight, Clock, ExternalLink, Bell, Zap, Shield, TrendingDown, Info } from 'lucide-react'

// 生成东方财富行情页链接
// ts_code 格式：603026.SH / 002969.SZ / 688717.SH
function eastMoneyUrl(ts_code) {
  if (!ts_code) return '#'
  const parts = ts_code.split('.')
  const code = parts[0]          // 数字部分
  const exch = (parts[1] || '').toLowerCase()  // sh / sz
  return `https://quote.eastmoney.com/${exch}${code}.html`
}

// 股票名称 + 东方财富跳转链接
function StockLink({ ts_code, name, className = '' }) {
  return (
    <a
      href={eastMoneyUrl(ts_code)}
      target="_blank"
      rel="noopener noreferrer"
      className={`group/link inline-flex items-center gap-1 hover:text-sky-300 transition-colors ${className}`}
    >
      {name}
      <ExternalLink className="h-3 w-3 opacity-0 group-hover/link:opacity-60 transition-opacity flex-shrink-0" />
    </a>
  )
}

function ScoreBar({ value }) {
  const pct = Math.min((value || 0) / 100, 1)
  const color = pct >= 0.75 ? 'bg-emerald-500' : pct >= 0.55 ? 'bg-sky-500' : pct >= 0.40 ? 'bg-amber-500' : 'bg-rose-500'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 bg-[#0E1524] rounded-full overflow-hidden border border-[#222F4C]">
        <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${pct * 100}%` }} />
      </div>
      <span className="text-xs font-mono text-gray-300">{(value || 0).toFixed(1)}</span>
    </div>
  )
}

function StreakBadge({ days }) {
  if (days >= 5) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/40">🔥 {days}天</span>
  if (days >= 3) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40">⚡ {days}天</span>
  return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-sky-500/20 text-sky-400 border border-sky-500/40">✦ {days}天</span>
}

function AppearBadge({ count }) {
  if (count >= 10) return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-rose-500/25 text-rose-300">{count}次</span>
  if (count >= 5)  return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-amber-500/25 text-amber-300">{count}次</span>
  if (count >= 2)  return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-sky-500/25 text-sky-300">{count}次</span>
  return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-gray-700/50 text-gray-400">{count}次</span>
}

function RankCircle({ rank }) {
  const color = rank === 1 ? 'bg-amber-500/30 border-amber-500/60 text-amber-300'
    : rank === 2 ? 'bg-gray-400/20 border-gray-400/50 text-gray-300'
    : rank === 3 ? 'bg-orange-700/20 border-orange-600/50 text-orange-400'
    : 'bg-[#0E1524] border-[#222F4C] text-gray-500'
  return <div className={`w-7 h-7 rounded-full border flex items-center justify-center text-xs font-bold font-mono ${color}`}>{rank}</div>
}

function PctChg({ value }) {
  if (!value && value !== 0) return <span className="text-gray-500 text-xs">—</span>
  if (value > 0) return <span className="text-rose-400 font-mono text-xs flex items-center gap-0.5"><ArrowUpRight className="h-3 w-3" />+{value.toFixed(2)}%</span>
  if (value < 0) return <span className="text-emerald-400 font-mono text-xs flex items-center gap-0.5"><ArrowDownRight className="h-3 w-3" />{value.toFixed(2)}%</span>
  return <span className="text-gray-400 font-mono text-xs"><Minus className="h-3 w-3 inline" />0.00%</span>
}

function SummaryTab({ summary, loading }) {
  if (loading) return <div className="flex items-center justify-center h-48 text-gray-500 text-sm">加载中…</div>
  if (!summary.length) return (
    <div className="flex flex-col items-center justify-center h-48 text-gray-500 gap-2">
      <BarChart3 className="h-8 w-8 opacity-30" />
      <p className="text-sm">暂无历史数据，访问建仓扫描页面后开始累计</p>
    </div>
  )
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-[#1A2840]">
            <th className="text-left py-2 px-3 text-xs text-gray-500 font-medium w-8">#</th>
            <th className="text-left py-2 px-3 text-xs text-gray-500 font-medium">股票</th>
            <th className="text-center py-2 px-3 text-xs text-gray-500 font-medium">出现次数</th>
            <th className="text-center py-2 px-3 text-xs text-gray-500 font-medium">均排名</th>
            <th className="text-left py-2 px-3 text-xs text-gray-500 font-medium">均因子分</th>
            <th className="text-left py-2 px-3 text-xs text-gray-500 font-medium">均净流入</th>
            <th className="text-center py-2 px-3 text-xs text-gray-500 font-medium">最近上榜</th>
          </tr>
        </thead>
        <tbody>
          {summary.map((s, i) => (
            <tr key={s.ts_code} className="border-b border-[#1A2840]/50 hover:bg-[#0D1B2E]/60 transition-colors">
              <td className="py-2.5 px-3"><RankCircle rank={i + 1} /></td>
              <td className="py-2.5 px-3">
                <div className="font-semibold text-gray-100 text-sm">
                  <StockLink ts_code={s.ts_code} name={s.name} />
                </div>
                <div className="text-xs text-gray-500 font-mono mt-0.5">
                  <a href={eastMoneyUrl(s.ts_code)} target="_blank" rel="noopener noreferrer"
                    className="hover:text-sky-400 transition-colors">{s.ts_code}</a>
                  {' · '}<span className="text-gray-600">{s.industry?.split(' | ')[1] || s.industry}</span>
                </div>
              </td>
              <td className="py-2.5 px-3 text-center"><AppearBadge count={s.appear_count} /></td>
              <td className="py-2.5 px-3 text-center"><span className="text-gray-300 font-mono text-xs">第 {s.avg_rank?.toFixed(1)} 名</span></td>
              <td className="py-2.5 px-3"><ScoreBar value={s.avg_factor} /></td>
              <td className="py-2.5 px-3">
                <span className={`font-mono text-xs ${s.avg_inflow > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                  {s.avg_inflow > 0 ? '+' : ''}{s.avg_inflow?.toFixed(2)} 亿
                </span>
              </td>
              <td className="py-2.5 px-3 text-center">
                <span className="text-gray-500 text-xs font-mono">
                  {s.last_date ? `${s.last_date.slice(0,4)}-${s.last_date.slice(4,6)}-${s.last_date.slice(6)}` : '—'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StreakTab({ streak, loading }) {
  if (loading) return <div className="flex items-center justify-center h-48 text-gray-500 text-sm">加载中…</div>
  if (!streak.length) return (
    <div className="flex flex-col items-center justify-center h-48 text-gray-500 gap-2">
      <Flame className="h-8 w-8 opacity-30" />
      <p className="text-sm">暂无连续上榜记录（需积累 ≥ 2 天数据）</p>
    </div>
  )
  return (
    <div className="grid gap-3 p-3">
      {streak.map((s, i) => (
        <div key={s.ts_code} className="flex items-center gap-4 p-3 rounded-xl bg-[#0D1B2E] border border-[#1A2840] hover:border-[#2A3F60] transition-all">
          <div className="text-2xl font-black font-mono text-gray-600 w-8 text-center">{i + 1}</div>
          <div className="flex-shrink-0"><StreakBadge days={s.streak_days} /></div>
          <div className="flex-1 min-w-0">
            <div className="font-bold text-gray-100">
              <StockLink ts_code={s.ts_code} name={s.name} />
            </div>
            <div className="text-xs text-gray-500 font-mono mt-0.5">
              <a href={eastMoneyUrl(s.ts_code)} target="_blank" rel="noopener noreferrer"
                className="hover:text-sky-400 transition-colors">{s.ts_code}</a>
              {' · '}{s.industry?.split(' | ')[1] || s.industry}
            </div>
          </div>
          <div className="flex gap-1 flex-shrink-0">
            {Array.from({ length: Math.min(s.streak_days, 10) }).map((_, di) => (
              <div key={di}
                className={`w-2.5 h-6 rounded-sm ${s.streak_days >= 5 ? 'bg-rose-500/70' : s.streak_days >= 3 ? 'bg-amber-500/70' : 'bg-sky-500/70'}`}
                style={{ opacity: 0.4 + (di / Math.max(s.streak_days - 1, 1)) * 0.6 }}
              />
            ))}
            {s.streak_days > 10 && <span className="text-xs text-gray-500 self-center ml-1">+{s.streak_days - 10}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}

function DailyTab({ daily, loading }) {
  const dates = Object.keys(daily).sort((a, b) => b.localeCompare(a))
  const [expanded, setExpanded] = useState({})
  useEffect(() => { if (dates.length > 0) setExpanded({ [dates[0]]: true }) }, [Object.keys(daily).join()])

  if (loading) return <div className="flex items-center justify-center h-48 text-gray-500 text-sm">加载中…</div>
  if (!dates.length) return (
    <div className="flex flex-col items-center justify-center h-48 text-gray-500 gap-2">
      <Calendar className="h-8 w-8 opacity-30" />
      <p className="text-sm">暂无每日快照数据</p>
    </div>
  )
  const toggle = (d) => setExpanded(p => ({ ...p, [d]: !p[d] }))
  const fmt = (d) => `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}`
  const weekdays = ['周日','周一','周二','周三','周四','周五','周六']

  return (
    <div className="space-y-2 p-2">
      {dates.map(d => {
        const rows = daily[d] || []
        const isOpen = expanded[d]
        const weekday = weekdays[new Date(fmt(d)).getDay()]
        return (
          <div key={d} className="rounded-xl border border-[#1A2840] overflow-hidden">
            <button onClick={() => toggle(d)}
              className="w-full flex items-center gap-3 px-4 py-3 bg-[#0D1B2E] hover:bg-[#0A1525] transition-colors text-left">
              {isOpen ? <ChevronDown className="h-4 w-4 text-gray-500 flex-shrink-0" /> : <ChevronRight className="h-4 w-4 text-gray-500 flex-shrink-0" />}
              <Calendar className="h-3.5 w-3.5 text-sky-400 flex-shrink-0" />
              <span className="text-gray-200 font-semibold text-sm">{fmt(d)}</span>
              <span className="text-gray-600 text-xs">{weekday}</span>
              <span className="ml-auto text-xs text-gray-500 bg-[#1A2840] px-2 py-0.5 rounded-full">{rows.length} 只</span>
              <span className="text-xs text-gray-600 font-mono ml-2">{rows[0]?.regime || '—'}</span>
            </button>
            {isOpen && (
              <div className="overflow-x-auto border-t border-[#1A2840]">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="bg-[#080F1C]">
                      {['排名','股票','因子分','筹码胜率','当日涨跌','大单净流入'].map(h => (
                        <th key={h} className="text-left py-1.5 px-3 text-gray-600 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(r => (
                      <tr key={r.ts_code} className="border-t border-[#1A2840]/40 hover:bg-[#0D1B2E]/40 transition-colors">
                        <td className="py-2 px-3"><span className={`font-mono font-bold ${r.rank <= 3 ? 'text-amber-400' : 'text-gray-500'}`}>#{r.rank}</span></td>
                        <td className="py-2 px-3">
                          <div className="font-semibold text-gray-200">
                            <StockLink ts_code={r.ts_code} name={r.name} />
                          </div>
                          <div className="text-gray-600 font-mono">
                            <a href={eastMoneyUrl(r.ts_code)} target="_blank" rel="noopener noreferrer"
                              className="hover:text-sky-400 transition-colors">{r.ts_code}</a>
                          </div>
                        </td>
                        <td className="py-2 px-3"><ScoreBar value={r.factor_score} /></td>
                        <td className="py-2 px-3 text-center"><span className="text-sky-400 font-mono">{r.winner_rate?.toFixed(1)}%</span></td>
                        <td className="py-2 px-3 text-center"><PctChg value={r.pct_chg} /></td>
                        <td className="py-2 px-3 text-center">
                          <span className={`font-mono ${r.big_net_inflow > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                            {r.big_net_inflow > 0 ? '+' : ''}{r.big_net_inflow?.toFixed(2)}亿
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── 时机预警 Tab ───────────────────────────────────────────
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

const REGIME_LABELS = { BEAR: { label: 'BEAR 熊市', color: 'text-rose-400 bg-rose-500/10 border-rose-500/30' }, DARK: { label: 'DARK 暗市', color: 'text-orange-400 bg-orange-500/10 border-orange-500/30' }, RANGE: { label: 'RANGE 震荡', color: 'text-sky-400 bg-sky-500/10 border-sky-500/30' }, BULL: { label: 'BULL 牛市', color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' } }

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
  const [tab, setTab] = useState('timing')   // 默认打开时机预警
  const [data, setData]     = useState({ summary: [], daily: {}, streak: [], meta: {} })
  const [timing, setTiming] = useState(null)
  const [loading, setLoading]       = useState(true)
  const [loadingTiming, setLoadingTiming] = useState(false)
  const [days, setDays]       = useState(30)
  const [topN, setTopN]       = useState(0)
  const [minAppear, setMinAppear] = useState(1)
  const [lastUpdate, setLastUpdate] = useState(null)

  const fetchHistory = useCallback(() => {
    setLoading(true)
    fetch(`/api/scan-history?days=${days}&top_n_per_day=${topN}&min_appear=${minAppear}`)
      .then(r => r.json())
      .then(d => { setData(d); setLastUpdate(new Date()) })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [days, topN, minAppear])

  const fetchTiming = useCallback(() => {
    setLoadingTiming(true)
    fetch('/api/scan-history/timing')
      .then(r => r.json())
      .then(d => setTiming(d))
      .catch(console.error)
      .finally(() => setLoadingTiming(false))
  }, [])

  useEffect(() => { fetchHistory() }, [fetchHistory])
  useEffect(() => { fetchTiming()  }, [fetchTiming])

  const meta = data.meta || {}
  const TABS = [
    { id: 'timing',  label: '时机预警', icon: <Bell className="h-3.5 w-3.5" />, count: timing?.summary?.golden || 0, highlight: (timing?.summary?.golden || 0) > 0 },
    { id: 'summary', label: '频率排行', icon: <BarChart3 className="h-3.5 w-3.5" />, count: data.summary?.length || 0 },
    { id: 'streak',  label: '连续上榜', icon: <Flame className="h-3.5 w-3.5" />,    count: data.streak?.length || 0 },
    { id: 'daily',   label: '每日快照', icon: <Calendar className="h-3.5 w-3.5" />, count: Object.keys(data.daily || {}).length },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-bold text-gray-100 flex items-center gap-2">
            <Clock className="h-5 w-5 text-sky-400" />建仓扫描历史
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">累计追踪每次扫描上榜股票，挖掘连续强势标的</p>
        </div>
        <button onClick={fetchHistory} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0D1B2E] border border-[#1A2840] hover:border-sky-500/40 text-gray-400 hover:text-gray-200 text-xs transition-all">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新
        </button>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: '累计扫描天数', value: meta.scan_days     || 0, unit: '天', color: 'text-sky-400' },
          { label: '覆盖股票数',   value: meta.unique_stocks || 0, unit: '只', color: 'text-emerald-400' },
          { label: '累计记录',     value: meta.total_records || 0, unit: '条', color: 'text-amber-400' },
          { label: '最新快照',     value: meta.date_latest ? `${(meta.date_latest||'').slice(4,6)}/${(meta.date_latest||'').slice(6)}` : '—', unit: '', color: 'text-rose-400' },
        ].map(c => (
          <div key={c.label} className="bg-[#0D1B2E] border border-[#1A2840] rounded-xl p-3">
            <div className="text-xs text-gray-500">{c.label}</div>
            <div className={`text-xl font-bold font-mono mt-1 ${c.color}`}>{c.value}<span className="text-xs text-gray-500 font-normal ml-0.5">{c.unit}</span></div>
          </div>
        ))}
      </div>

      {/* 筛选条件 */}
      <div className="flex items-center gap-3 flex-wrap text-xs text-gray-400">
        <label className="flex items-center gap-1.5">近
          <select value={days} onChange={e => setDays(+e.target.value)} className="bg-[#0D1B2E] border border-[#1A2840] text-gray-200 text-xs rounded px-2 py-1 focus:outline-none">
            {[7,14,30,60,90,180].map(d => <option key={d} value={d}>{d}天</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1.5">只看 Top
          <select value={topN} onChange={e => setTopN(+e.target.value)} className="bg-[#0D1B2E] border border-[#1A2840] text-gray-200 text-xs rounded px-2 py-1 focus:outline-none">
            <option value={0}>全部</option>
            {[3,5,10,15].map(n => <option key={n} value={n}>前{n}名</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1.5">出现 ≥
          <select value={minAppear} onChange={e => setMinAppear(+e.target.value)} className="bg-[#0D1B2E] border border-[#1A2840] text-gray-200 text-xs rounded px-2 py-1 focus:outline-none">
            {[1,2,3,5,7,10].map(n => <option key={n} value={n}>{n}次</option>)}
          </select>
        </label>
        {lastUpdate && <span className="ml-auto text-gray-600">更新于 {lastUpdate.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span>}
      </div>

      {/* Tab */}
      <div className="flex gap-1 bg-[#080F1C] p-1 rounded-xl border border-[#1A2840]">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-xs font-medium transition-all ${
              tab === t.id
                ? t.id === 'timing'
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                  : 'bg-sky-500/20 text-sky-300 border border-sky-500/30'
                : 'text-gray-500 hover:text-gray-300'
            }`}>
            {t.icon}{t.label}
            {t.count > 0 && (
              <span className={`ml-0.5 text-xs px-1.5 rounded-full font-mono ${
                tab === t.id
                  ? t.id === 'timing' ? 'bg-emerald-500/30 text-emerald-300' : 'bg-sky-500/30 text-sky-300'
                  : t.highlight ? 'bg-emerald-500/20 text-emerald-400' : 'bg-[#1A2840] text-gray-500'
              }`}>{t.count}</span>
            )}
            {t.highlight && tab !== t.id && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse ml-0.5" />
            )}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div className="bg-[#0A1322] border border-[#1A2840] rounded-xl overflow-hidden">
        {tab === 'timing'  && <TimingTab timing={timing} loadingTiming={loadingTiming} fetchTiming={fetchTiming} />}
        {tab === 'summary' && <SummaryTab summary={data.summary || []} loading={loading} />}
        {tab === 'streak'  && <StreakTab  streak={data.streak   || []} loading={loading} />}
        {tab === 'daily'   && <DailyTab   daily={data.daily     || {}} loading={loading} />}
      </div>
    </div>
  )
}
