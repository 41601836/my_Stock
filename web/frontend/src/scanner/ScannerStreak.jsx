import React, { useState, useEffect, useCallback } from 'react'
import { Flame, RefreshCw } from 'lucide-react'
import {
  StockLink, eastMoneyUrl, StreakBadge,
} from './shared'

export default function ScannerStreak() {
  const [streak, setStreak]   = useState([])
  const [meta, setMeta]       = useState({})
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [days, setDays]       = useState(30)
  const [topN, setTopN]       = useState(0)
  const [minAppear, setMinAppear] = useState(1)

  const fetchHistory = useCallback(() => {
    setLoading(true)
    fetch(`/api/scan-history?days=${days}&top_n_per_day=${topN}&min_appear=${minAppear}`)
      .then(r => r.json())
      .then(d => {
        setStreak(d.streak || [])
        setMeta(d.meta || {})
        setLastUpdate(new Date())
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [days, topN, minAppear])

  useEffect(() => { fetchHistory() }, [fetchHistory])

  return (
    <div className="space-y-4">

      {/* ── 统计卡片 ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: '连续上榜标的', value: streak.length, unit: '只', color: 'text-rose-400' },
          { label: '最高连续天数', value: streak[0]?.streak_days || 0, unit: '天', color: 'text-amber-400' },
          { label: '累计扫描天数', value: meta.scan_days || 0, unit: '天', color: 'text-sky-400' },
          { label: '覆盖股票数',   value: meta.unique_stocks || 0, unit: '只', color: 'text-emerald-400' },
        ].map(c => (
          <div key={c.label} className="bg-[#0D1B2E] border border-[#1A2840] rounded-xl p-3">
            <div className="text-xs text-gray-500">{c.label}</div>
            <div className={`text-xl font-bold font-mono mt-1 ${c.color}`}>{c.value}<span className="text-xs text-gray-500 font-normal ml-0.5">{c.unit}</span></div>
          </div>
        ))}
      </div>

      {/* ── 筛选条件 ── */}
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
        <button onClick={fetchHistory} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0D1B2E] border border-[#1A2840] hover:border-sky-500/40 text-gray-400 hover:text-gray-200 text-xs transition-all">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新
        </button>
      </div>

      {/* ── 列表 ── */}
      {loading ? (
        <div className="flex items-center justify-center h-48 text-gray-500 text-sm">加载中…</div>
      ) : !streak.length ? (
        <div className="flex flex-col items-center justify-center h-48 text-gray-500 gap-2">
          <Flame className="h-8 w-8 opacity-30" />
          <p className="text-sm">暂无连续上榜记录（需积累 ≥ 2 天数据）</p>
        </div>
      ) : (
        <div className="bg-[#0A1322] border border-[#1A2840] rounded-xl overflow-hidden">
          <div className="grid gap-2 p-3">
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
        </div>
      )}
    </div>
  )
}
