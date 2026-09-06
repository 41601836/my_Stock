import React, { useState, useEffect, useCallback } from 'react'
import { BarChart3, RefreshCw } from 'lucide-react'
import {
  StockLink, eastMoneyUrl, ScoreBar, RankCircle, AppearBadge, PctChg,
} from '../scanner/shared'

export default function RecoSummary() {
  const [summary, setSummary] = useState([])
  const [meta, setMeta]       = useState({})
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [days, setDays]       = useState(30)
  const [minAppear, setMinAppear] = useState(1)

  const fetchHistory = useCallback(() => {
    setLoading(true)
    fetch(`/api/reco-history?days=${days}&min_appear=${minAppear}`)
      .then(r => r.json())
      .then(d => {
        setSummary(d.summary || [])
        setMeta(d.meta || {})
        setLastUpdate(new Date())
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [days, minAppear])

  useEffect(() => { fetchHistory() }, [fetchHistory])

  // 5 日超额胜率配色（≥50 强 / 30-50 中 / <30 弱；无样本不评色）
  const winRateCls = (v) => {
    if (v === null || v === undefined) return 'text-gray-500'
    if (v >= 50) return 'text-emerald-400'
    if (v >= 30) return 'text-amber-400'
    return 'text-rose-400'
  }

  return (
    <div className="space-y-4">

      {/* ── 统计卡片 ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: '累计推荐天数', value: meta.reco_days     || 0, unit: '天', color: 'text-amber-400' },
          { label: '覆盖股票数',   value: meta.unique_stocks || 0, unit: '只', color: 'text-emerald-400' },
          { label: '累计记录',     value: meta.total_records || 0, unit: '条', color: 'text-sky-400' },
          { label: '最新推荐',     value: meta.date_latest ? `${(meta.date_latest||'').slice(4,6)}/${(meta.date_latest||'').slice(6)}` : '—', unit: '', color: 'text-rose-400' },
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
        <label className="flex items-center gap-1.5">出现 ≥
          <select value={minAppear} onChange={e => setMinAppear(+e.target.value)} className="bg-[#0D1B2E] border border-[#1A2840] text-gray-200 text-xs rounded px-2 py-1 focus:outline-none">
            {[1,2,3,5,7,10].map(n => <option key={n} value={n}>{n}次</option>)}
          </select>
        </label>
        <span className="text-gray-600">5 日超额 = 上榜后 5 交易日相对基准超额收益（仅统计已回填样本）</span>
        {lastUpdate && <span className="ml-auto text-gray-600">更新于 {lastUpdate.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}</span>}
        <button onClick={fetchHistory} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0D1B2E] border border-[#1A2840] hover:border-amber-500/40 text-gray-400 hover:text-gray-200 text-xs transition-all">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />刷新
        </button>
      </div>

      {/* ── 主表格 ── */}
      {loading ? (
        <div className="flex items-center justify-center h-48 text-gray-500 text-sm">加载中…</div>
      ) : !summary.length ? (
        <div className="flex flex-col items-center justify-center h-48 text-gray-500 gap-2">
          <BarChart3 className="h-8 w-8 opacity-30" />
          <p className="text-sm">暂无推荐统计数据（访问仪表盘今日推荐列表后开始累计）</p>
        </div>
      ) : (
        <div className="bg-[#0A1322] border border-[#1A2840] rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-[#1A2840] bg-[#080F1C]">
                  <th className="text-left py-2 px-3 text-xs text-gray-500 font-medium w-8">#</th>
                  <th className="text-left py-2 px-3 text-xs text-gray-500 font-medium">股票</th>
                  <th className="text-center py-2 px-3 text-xs text-gray-500 font-medium">推荐次数</th>
                  <th className="text-center py-2 px-3 text-xs text-gray-500 font-medium">均排名</th>
                  <th className="text-left py-2 px-3 text-xs text-gray-500 font-medium">均因子分</th>
                  <th className="text-center py-2 px-3 text-xs text-gray-500 font-medium">5日超额胜率</th>
                  <th className="text-left py-2 px-3 text-xs text-gray-500 font-medium">均5日超额</th>
                  <th className="text-center py-2 px-3 text-xs text-gray-500 font-medium">最近推荐</th>
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
                    <td className="py-2.5 px-3 text-center">
                      {s.win_rate_5d === null || s.win_rate_5d === undefined ? (
                        <span className="text-gray-600 font-mono text-xs">样本{Math.round(s.alpha_5d_samples || 0)}</span>
                      ) : (
                        <span className={`font-mono text-xs font-bold ${winRateCls(s.win_rate_5d)}`}>
                          {s.win_rate_5d.toFixed(1)}%
                          <span className="text-gray-600 font-normal ml-1">({s.alpha_5d_samples})</span>
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 px-3"><PctChg value={s.avg_alpha_5d} /></td>
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
