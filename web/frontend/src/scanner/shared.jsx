// scanner/shared.jsx —— 扫描系列页面共享工具组件
// ScannerLayout / ScannerRealtime / ScannerSector / ScannerSummary / ScannerStreak / ScannerDaily 共同消费
import React from 'react'
import { ArrowUpRight, ArrowDownRight, Minus, ExternalLink } from 'lucide-react'

// ts_code: 603026.SH / 002969.SZ / 688717.SH → 东方财富行情页链接
export function eastMoneyUrl(ts_code) {
  if (!ts_code) return '#'
  const parts = ts_code.split('.')
  return `https://quote.eastmoney.com/${(parts[1] || '').toLowerCase()}${parts[0]}.html`
}

export function StockLink({ ts_code, name, className = '' }) {
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

// ── 数值安全处理 ──
export function safeValue(value, decimals = 1, fallback = '—') {
  if (value === null || value === undefined || typeof value !== 'number' || isNaN(value) || !isFinite(value)) {
    return fallback
  }
  return value.toFixed(decimals)
}

export function isValidNum(v) {
  return v !== null && v !== undefined && typeof v === 'number' && !isNaN(v) && isFinite(v)
}

// ── 涨跌幅显示（红涨绿跌） ──
export function PctChg({ value }) {
  if (!isValidNum(value)) return <span className="text-gray-500 font-mono flex items-center gap-0.5"><Minus className="h-3 w-3" />—</span>
  if (value > 0) return <span className="text-rose-500 font-bold font-mono flex items-center gap-0.5"><ArrowUpRight className="h-3 w-3" />+{value.toFixed(2)}%</span>
  if (value < 0) return <span className="text-emerald-500 font-bold font-mono flex items-center gap-0.5"><ArrowDownRight className="h-3 w-3" />{value.toFixed(2)}%</span>
  return <span className="text-gray-400 font-mono flex items-center gap-0.5"><Minus className="h-3 w-3" />0.00%</span>
}

// ── 建仓等级标签 ──
export function BuildGrade({ score }) {
  const s = Number(score)
  if (!isValidNum(s)) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-gray-500/15 text-gray-400 border border-gray-500/30">—</span>
  if (s >= 75) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">强烈建仓</span>
  if (s >= 60) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-sky-500/15 text-sky-400 border border-sky-500/30">积极关注</span>
  if (s >= 45) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500/15 text-amber-400 border border-amber-500/30">谨慎建仓</span>
  return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-gray-500/15 text-gray-400 border border-gray-500/30">观望</span>
}

// ── 信号强度色阶条 ──
export function ScoreBar({ value, max = 100 }) {
  const v = isValidNum(value) ? Number(value) : 0
  const pct = Math.min(v / max, 1)
  const color =
    pct >= 0.75 ? 'bg-emerald-500' :
    pct >= 0.55 ? 'bg-sky-500' :
    pct >= 0.40 ? 'bg-amber-500' : 'bg-rose-500'
  const textColor =
    pct >= 0.75 ? 'text-emerald-400' :
    pct >= 0.55 ? 'text-sky-400' :
    pct >= 0.40 ? 'text-amber-400' : 'text-rose-400'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 bg-[#0E1524] rounded-full overflow-hidden border border-[#222F4C]">
        <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${pct * 100}%` }} />
      </div>
      <span className={`text-xs font-mono ${textColor}`}>{v.toFixed(1)}</span>
    </div>
  )
}

// ── 大号 ScoreBar（ScannerRealtime 详情面板用） ──
export function ScoreBarWide({ value, max = 100 }) {
  const v = isValidNum(value) ? Number(value) : 0
  const pct = Math.min(v / max, 1)
  const color =
    pct >= 0.75 ? 'bg-emerald-500' :
    pct >= 0.55 ? 'bg-sky-500' :
    pct >= 0.40 ? 'bg-amber-500' : 'bg-rose-500'
  const textColor =
    pct >= 0.75 ? 'text-emerald-400' :
    pct >= 0.55 ? 'text-sky-400' :
    pct >= 0.40 ? 'text-amber-400' : 'text-rose-400'
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-2 bg-[#0E1524] rounded-full overflow-hidden border border-[#222F4C]">
        <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${pct * 100}%` }} />
      </div>
      <span className={`text-xs font-bold font-mono ${textColor}`}>{v.toFixed(1)}</span>
    </div>
  )
}

// ── 排名圆圈 ──
export function RankCircle({ rank }) {
  const color = rank === 1 ? 'bg-amber-500/30 border-amber-500/60 text-amber-300'
    : rank === 2 ? 'bg-gray-400/20 border-gray-400/50 text-gray-300'
    : rank === 3 ? 'bg-orange-700/20 border-orange-600/50 text-orange-400'
    : 'bg-[#0E1524] border-[#222F4C] text-gray-500'
  return <div className={`w-7 h-7 rounded-full border flex items-center justify-center text-xs font-bold font-mono ${color}`}>{rank}</div>
}

// ── 连续上榜徽章 ──
export function StreakBadge({ days }) {
  if (days >= 5) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/40">🔥 {days}天</span>
  if (days >= 3) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40">⚡ {days}天</span>
  return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-sky-500/20 text-sky-400 border border-sky-500/40">✦ {days}天</span>
}

// ── 出现次数徽章 ──
export function AppearBadge({ count }) {
  if (count >= 10) return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-rose-500/25 text-rose-300">{count}次</span>
  if (count >= 5)  return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-amber-500/25 text-amber-300">{count}次</span>
  if (count >= 2)  return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-sky-500/25 text-sky-300">{count}次</span>
  return <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-gray-700/50 text-gray-400">{count}次</span>
}
