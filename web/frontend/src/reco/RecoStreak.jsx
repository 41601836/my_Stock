import React, { useState, useEffect, useCallback } from 'react'
import { Flame, RefreshCw } from 'lucide-react'
import {
  StockLink, eastMoneyUrl, StreakBadge,
} from '../scanner/shared'

export default function RecoStreak() {
  const [streak, setStreak]   = useState([])
  const [meta, setMeta]       = useState({})
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [days, setDays]       = useState(30)

  const fetchHistory = useCallback(() => {
    setLoading(true)
    fetch(`/api/reco-history?days=${days}&min_appear=1`)
      .then(r => r.json())
      .then(d => {
        setStreak(d.streak || [])
        setMeta(d.meta || {})
        setLastUpdate(new Date())
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [days])

  useEffect(() => { fetchHistory() }, [fetchHistory])

  const maxStreak = streak[0]?.max_streak_days || 0
  const currentCnt = streak.filter(s => s.streak_days >= 2).length

  return (
    <div className="space-y-4">

      {/* ── 统计卡片 ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: '期内连续推荐标的', value: streak.length, unit: '只', color: 'text-rose-400' },
          { label: '当前仍连续在榜',   value: currentCnt,    unit: '只', color: 'text-amber-400' },
          { label: '期内最长连续',     value: maxStreak,     unit: '天', color: 'text-emerald-400' },
          { label: '累计推荐天数',     value: meta.reco_days || 0, unit: '天', color: 'text-sky-400' },
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
        <span className="text-gray-600">徽章 = 期内最长连续推荐天数；推荐名单日度轮换较快，最长连续更具统计意义</span>
        {lastUpdate && <span className="ml-auto text-gray-600">更新于 {lastUpdate.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span>}
        <button onClick={fetchHistory} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0D1B2E] border border-[#1A2840] hover:border-amber-500/40 text-gray-400 hover:text-gray-200 text-xs transition-all">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新
        </button>
      </div>

      {/* ── 列表 ── */}
      {loading ? (
        <div className="flex items-center justify-center h-48 text-gray-500 text-sm">加载中…</div>
      ) : !streak.length ? (
        <div className="flex flex-col items-center justify-center h-48 text-gray-500 gap-2">
          <Flame className="h-8 w-8 opacity-30" />
          <p className="text-sm">暂无连续推荐记录（需 ≥ 2 个连续推荐日数据）</p>
        </div>
      ) : (
        <div className="bg-[#0A1322] border border-[#1A2840] rounded-xl overflow-hidden">
          <div className="grid gap-2 p-3">
            {streak.map((s, i) => (
              <div key={s.ts_code} className="flex items-center gap-4 p-3 rounded-xl bg-[#0D1B2E] border border-[#1A2840] hover:border-[#2A3F60] transition-all">
                <div className="text-2xl font-black font-mono text-gray-600 w-8 text-center">{i + 1}</div>
                <div className="flex-shrink-0 flex flex-col items-center gap-1">
                  <StreakBadge days={s.max_streak_days} />
                  <span className="text-[10px] text-gray-500 font-mono">当前连续 {s.streak_days} 天</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-bold text-gray-100">
                    <StockLink ts_code={s.ts_code} name={s.name} />
                  </div>
                  <div className="text-xs text-gray-500 font-mono mt-0.5">
                    <a href={eastMoneyUrl(s.ts_code)} target="_blank" rel="noopener noreferrer"
                      className="hover:text-sky-400 transition-colors">{s.ts_code}</a>
                    {' · '}{s.industry?.split(' | ')[1] || s.industry}
                    {' · '}共 <span className="text-gray-400">{s.appear_count}</span> 次
                  </div>
                </div>
                <div className="flex gap-1 flex-shrink-0">
                  {Array.from({ length: Math.min(s.max_streak_days, 10) }).map((_, di) => (
                    <div key={di}
                      className={`w-2.5 h-6 rounded-sm ${s.streak_days >= 2 ? 'bg-rose-500/70' : s.max_streak_days >= 5 ? 'bg-amber-500/70' : 'bg-sky-500/70'}`}
                      style={{ opacity: 0.4 + (di / Math.max(s.max_streak_days - 1, 1)) * 0.6 }}
                    />
                  ))}
                  {s.max_streak_days > 10 && <span className="text-xs text-gray-500 self-center ml-1">+{s.max_streak_days - 10}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
