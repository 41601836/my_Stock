import React, { useState, useEffect, useCallback } from 'react'
import { BarChart3, RefreshCw } from 'lucide-react'
import {
  StockLink, eastMoneyUrl, ScoreBar, RankCircle, AppearBadge,
} from './shared'

export default function ScannerSummary() {
  const [summary, setSummary] = useState([])
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
        setSummary(d.summary || [])
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

      {/* ── 主表格 ── */}
      {loading ? (
        <div className="flex items-center justify-center h-48 text-gray-500 text-sm">加载中…</div>
      ) : !summary.length ? (
        <div className="flex flex-col items-center justify-center h-48 text-gray-500 gap-2">
          <BarChart3 className="h-8 w-8 opacity-30" />
          <p className="text-sm">暂无历史数据，访问实时扫描页面后开始累计</p>
        </div>
      ) : (
        <div className="bg-[#0A1322] border border-[#1A2840] rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-[#1A2840] bg-[#080F1C]">
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
        </div>
      )}
    </div>
  )
}
