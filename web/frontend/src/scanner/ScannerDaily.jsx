import React, { useState, useEffect, useCallback } from 'react'
import { Calendar, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import {
  StockLink, eastMoneyUrl, ScoreBar, PctChg,
} from './shared'

const REGIME_LABELS = {
  BEAR:  { label: 'BEAR 熊市', color: 'text-rose-400 bg-rose-500/10 border-rose-500/30' },
  DARK:  { label: 'DARK 暗市', color: 'text-orange-400 bg-orange-500/10 border-orange-500/30' },
  RANGE: { label: 'RANGE 震荡', color: 'text-sky-400 bg-sky-500/10 border-sky-500/30' },
  BULL:  { label: 'BULL 牛市', color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
}

export default function ScannerDaily() {
  const [daily, setDaily]     = useState({})
  const [meta, setMeta]       = useState({})
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [days, setDays]       = useState(30)
  const [topN, setTopN]       = useState(0)
  const [minAppear, setMinAppear] = useState(1)
  const [expanded, setExpanded] = useState({})

  const fetchHistory = useCallback(() => {
    setLoading(true)
    fetch(`/api/scan-history?days=${days}&top_n_per_day=${topN}&min_appear=${minAppear}`)
      .then(r => r.json())
      .then(d => {
        setDaily(d.daily || {})
        setMeta(d.meta || {})
        setLastUpdate(new Date())
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [days, topN, minAppear])

  useEffect(() => { fetchHistory() }, [fetchHistory])

  // 日期变化时默认展开最新一天
  const dates = Object.keys(daily).sort((a, b) => b.localeCompare(a))
  useEffect(() => {
    if (dates.length > 0) {
      setExpanded(p => {
        const next = { ...p }
        dates.forEach(d => { next[d] = false })
        next[dates[0]] = true
        return next
      })
    }
  }, [dates.join()])

  const toggle = (d) => setExpanded(p => ({ ...p, [d]: !p[d] }))
  const fmt = (d) => `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}`
  const weekdays = ['周日','周一','周二','周三','周四','周五','周六']

  return (
    <div className="space-y-4">

      {/* ── 统计卡片 ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: '快照天数',     value: dates.length || 0, unit: '天', color: 'text-sky-400' },
          { label: '累计扫描天数', value: meta.scan_days || 0, unit: '天', color: 'text-emerald-400' },
          { label: '覆盖股票数',   value: meta.unique_stocks || 0, unit: '只', color: 'text-amber-400' },
          { label: '累计记录',     value: meta.total_records || 0, unit: '条', color: 'text-rose-400' },
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

      {/* ── 每日快照列表 ── */}
      {loading ? (
        <div className="flex items-center justify-center h-48 text-gray-500 text-sm">加载中…</div>
      ) : !dates.length ? (
        <div className="flex flex-col items-center justify-center h-48 text-gray-500 gap-2">
          <Calendar className="h-8 w-8 opacity-30" />
          <p className="text-sm">暂无每日快照数据</p>
        </div>
      ) : (
        <div className="bg-[#0A1322] border border-[#1A2840] rounded-xl overflow-hidden">
          <div className="space-y-2 p-2">
            {dates.map(d => {
              const rows = daily[d] || []
              const isOpen = expanded[d]
              const weekday = weekdays[new Date(fmt(d)).getDay()]
              const regimeCfg = REGIME_LABELS[rows[0]?.regime]

              return (
                <div key={d} className="rounded-xl border border-[#1A2840] overflow-hidden">
                  <button onClick={() => toggle(d)}
                    className="w-full flex items-center gap-3 px-4 py-3 bg-[#0D1B2E] hover:bg-[#0A1525] transition-colors text-left">
                    {isOpen ? <ChevronDown className="h-4 w-4 text-gray-500 flex-shrink-0" /> : <ChevronRight className="h-4 w-4 text-gray-500 flex-shrink-0" />}
                    <Calendar className="h-3.5 w-3.5 text-sky-400 flex-shrink-0" />
                    <span className="text-gray-200 font-semibold text-sm">{fmt(d)}</span>
                    <span className="text-gray-600 text-xs">{weekday}</span>
                    {regimeCfg && (
                      <span className={`ml-auto text-xs px-2 py-0.5 rounded border ${regimeCfg.color}`}>{regimeCfg.label}</span>
                    )}
                    <span className="text-xs text-gray-500 bg-[#1A2840] px-2 py-0.5 rounded-full ml-2">{rows.length} 只</span>
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
        </div>
      )}
    </div>
  )
}
