/**
 * EvoFactors.jsx —— EVO 因子监控页（真实数据）
 * 布局：
 *   [统计条] 数据日期 / regime / 红·黄警报数 / disable·half·normal 数
 *   [衰减警报] [拥挤度排行]
 *   [动态权重] [交叉因子截面热力表]
 *   [选中因子三联曲线: RankIC / 拥挤度 / 动态权重]（点击左表因子切换）
 * 数据源：/decay/alerts /crowding/status /weights/dynamic /factors/cross
 *         + /decay/history /crowding/history /weights/history（选中因子）
 */
import React, { useEffect, useMemo, useState } from 'react'
import { Activity, TrendingDown, Users, Scale, Grid3X3, LineChart } from 'lucide-react'
import * as EvoApi from './EvoApi'

const fmtDate = (d) => (d && String(d).length === 8
  ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : (d || '—'))

function Spark({ vals, color = '#38bdf8', zeroLine = false, suffix = '' }) {
  const v = (vals || []).filter(x => typeof x === 'number' && isFinite(x))
  if (v.length < 2) return <div className="h-9 flex items-center justify-center text-[11px] text-slate-600">数据不足</div>
  const w = 100, h = 36, pad = 2
  const lo = Math.min(...v, zeroLine ? 0 : Infinity)
  const hi = Math.max(...v, zeroLine ? 0 : -Infinity)
  const span = (hi - lo) || 1
  const pts = v.map((x, i) =>
    `${(i / (v.length - 1)) * w},${h - ((x - lo) / span) * (h - 2 * pad) - pad}`)
  const zeroY = h - ((0 - lo) / span) * (h - 2 * pad) - pad
  const last = v[v.length - 1]
  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="w-full h-9">
        {zeroLine && lo < 0 && hi > 0 && (
          <line x1="0" x2={w} y1={zeroY} y2={zeroY} stroke="#475569" strokeWidth="0.4" strokeDasharray="2 2" />)}
        <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth="1" />
      </svg>
      <div className="text-[10px] font-mono text-slate-500 mt-0.5">
        最新 <span style={{ color }}>{last.toFixed(4)}{suffix}</span> · {v.length} 点
      </div>
    </div>
  )
}

const ACTION_STYLE = {
  disable:    { label: '禁用',   cls: 'bg-rose-500/15 text-rose-300 border-rose-500/40',   bar: 'bg-rose-500' },
  half_weight:{ label: '半权重', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40', bar: 'bg-amber-500' },
  normal:     { label: '正常',   cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30', bar: 'bg-emerald-500' },
}

export default function EvoFactors() {
  const [base, setBase] = useState({})
  const [selected, setSelected] = useState('')
  const [series, setSeries] = useState(null)

  useEffect(() => {
    Promise.all([
      EvoApi.decayAlerts(), EvoApi.crowdingStatus(),
      EvoApi.weightsDynamic(), EvoApi.factorsCross('', 20),
    ]).then(([a, c, w, x]) => {
      setBase({ a: a.error ? null : a, c: c.error ? null : c, w: w.error ? null : w, x: x.error ? null : x })
      const first = (a.error ? null : a)?.alerts?.[0]?.factor_name
        || (c.error ? null : c)?.factors?.[0]?.factor_name
      if (first) setSelected(first)
    })
  }, [])

  useEffect(() => {
    if (!selected) return
    let alive = true
    Promise.all([
      EvoApi.decayHistory(selected, 60),
      EvoApi.crowdingHistory(selected, 60),
      EvoApi.weightsHistory(30),
    ]).then(([d, cw, wh]) => {
      if (!alive) return
      const wSeries = (wh.error ? null : wh)?.series || []
      // series 为日期倒序快照 {trade_date, weights:{factor:w}} → 正序提取选中因子
      const weightVals = [...wSeries].reverse()
        .map(s => (s.weights || {})[selected])
        .filter(v => typeof v === 'number')
      setSeries({
        ic:  ((d.error ? null : d)?.series || []).slice().reverse().map(r => r.rank_ic),
        cw:  ((cw.error ? null : cw)?.series || []).slice().reverse().map(r => r.crowding_score),
        w:   weightVals,
      })
    })
    return () => { alive = false }
  }, [selected])

  const alerts = base.a?.alerts || []
  const cFactors = base.c?.factors || []
  const weights = useMemo(() => Object.entries(base.w?.weights || {})
    .sort((x, y) => y[1] - x[1]), [base.w])
  const activeW = weights.filter(([, v]) => v > 0)
  const zeroW = weights.length - activeW.length

  const crossRows = base.x?.data || []
  const crossCols = base.x?.enabled_factors || []
  const maxW = Math.max(...cFactors.map(f => f.crowding_score || 0), 0.01)

  return (
    <div className="flex flex-col gap-4">
      {/* 统计条 */}
      <div className="rounded-xl bg-[#111827] border border-[#1F2937] px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
        <span className="text-slate-500">数据日期 <span className="text-slate-200 font-mono">{fmtDate(base.c?.date || base.x?.trade_date)}</span></span>
        <span className="text-slate-500">市场状态 <span className="text-sky-300 font-mono">{base.w?.regime || '—'}</span></span>
        <span className="text-slate-500">衰减警报
          <span className="text-rose-400 font-mono"> 🔴{base.a?.n_red ?? '—'}</span>
          <span className="text-amber-400 font-mono"> 🟡{base.a?.n_yellow ?? '—'}</span>
        </span>
        <span className="text-slate-500">拥挤处置
          <span className="text-rose-400 font-mono"> 禁用 {base.c?.summary?.n_disable ?? '—'}</span>
          <span className="text-amber-400 font-mono"> 半权 {base.c?.summary?.n_half_weight ?? '—'}</span>
          <span className="text-emerald-400 font-mono"> 正常 {base.c?.summary?.n_normal ?? '—'}</span>
        </span>
        <span className="text-slate-500">有效权重 <span className="text-emerald-300 font-mono">{activeW.length}/{weights.length}</span></span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 衰减警报 */}
        <div className="rounded-xl bg-[#111827] border border-[#1F2937] p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <TrendingDown className="h-4 w-4 text-orange-300" />因子衰减警报
            <span className="text-[10px] text-slate-500 font-normal">滚动 20 日 RankIC；连续 {base.a?.red_neg_days ?? 5} 日为负→红</span>
          </div>
          <div className="flex flex-col gap-1 overflow-y-auto max-h-64">
            {alerts.map(al => (
              <button key={al.factor_name} onClick={() => setSelected(al.factor_name)}
                className={`w-full text-left px-2.5 py-1.5 rounded-lg border text-xs flex items-center gap-2 transition-colors
                  ${selected === al.factor_name ? 'bg-slate-800 border-slate-600' : 'bg-slate-900/30 border-slate-800 hover:border-slate-700'}`}>
                <span className={`px-1.5 py-0.5 rounded text-[10px] border shrink-0
                  ${al.level === 'red' ? 'bg-rose-500/15 text-rose-300 border-rose-500/40' : 'bg-amber-500/15 text-amber-300 border-amber-500/40'}`}>
                  {al.level === 'red' ? '🔴 红' : '🟡 黄'}
                </span>
                <span className="font-mono text-slate-200 truncate">{al.factor_name}</span>
                <span className={`ml-auto font-mono shrink-0 ${Number(al.rolling_ic) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  IC {Number(al.rolling_ic ?? 0).toFixed(3)}
                </span>
              </button>
            ))}
            {!alerts.length && <div className="text-xs text-slate-600 py-3 text-center">暂无警报（管线运行后自动出现）</div>}
          </div>
        </div>

        {/* 拥挤度排行 */}
        <div className="rounded-xl bg-[#111827] border border-[#1F2937] p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <Users className="h-4 w-4 text-amber-300" />拥挤度排行（截面自相关）
            <span className="text-[10px] text-slate-500 font-normal">阈值 {base.c?.thresholds?.half_weight ?? 0.70} / {base.c?.thresholds?.disable ?? 0.85}</span>
          </div>
          <div className="flex flex-col gap-1 overflow-y-auto max-h-64 pr-1">
            {cFactors.map(f => {
              const st = ACTION_STYLE[f.action] || ACTION_STYLE.normal
              const v = Number(f.crowding_score || 0)
              return (
                <button key={f.factor_name} onClick={() => setSelected(f.factor_name)}
                  className={`w-full text-left rounded-lg border px-2.5 py-1.5 transition-colors
                    ${selected === f.factor_name ? 'bg-slate-800 border-slate-600' : 'bg-slate-900/30 border-slate-800 hover:border-slate-700'}`}>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="font-mono text-slate-200 truncate">{f.factor_name}</span>
                    <span className={`ml-auto px-1.5 py-0.5 rounded text-[10px] border shrink-0 ${st.cls}`}>{st.label}</span>
                    <span className="font-mono text-slate-400 shrink-0 w-12 text-right">{v.toFixed(3)}</span>
                  </div>
                  <div className="mt-1 h-1 rounded bg-slate-800 relative overflow-hidden">
                    <div className={`h-full rounded ${st.bar}`} style={{ width: `${Math.min(100, (v / maxW) * 100)}%` }} />
                    <div className="absolute top-0 bottom-0 w-px bg-slate-500" style={{ left: `${(0.7 / maxW) * 100}%` }} />
                    <div className="absolute top-0 bottom-0 w-px bg-rose-400" style={{ left: `${(0.85 / maxW) * 100}%` }} />
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        {/* 动态权重 */}
        <div className="rounded-xl bg-[#111827] border border-[#1F2937] p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <Scale className="h-4 w-4 text-sky-300" />动态权重（ICMean/ICIR 加权，Σ=1）
            {zeroW > 0 && <span className="text-[10px] text-slate-500 font-normal">{zeroW} 个 IC 为负因子已自动置 0</span>}
          </div>
          <div className="flex flex-col gap-1 overflow-y-auto max-h-64 pr-1">
            {weights.map(([name, v]) => (
              <button key={name} onClick={() => setSelected(name)}
                className="w-full text-left rounded-lg px-2.5 py-1.5 bg-slate-900/30 border border-slate-800 hover:border-slate-700 text-xs flex items-center gap-2">
                <span className={`font-mono truncate ${v > 0 ? 'text-slate-200' : 'text-slate-600'}`}>{name}</span>
                <div className="ml-auto flex items-center gap-2 shrink-0 w-32">
                  <div className="flex-1 h-1 rounded bg-slate-800">
                    <div className="h-full rounded bg-sky-500" style={{ width: `${v * 100}%` }} />
                  </div>
                  <span className={`font-mono w-12 text-right ${v > 0 ? 'text-sky-300' : 'text-slate-600'}`}>{v.toFixed(3)}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* 交叉因子截面热力表 */}
        <div className="rounded-xl bg-[#111827] border border-[#1F2937] p-4 flex flex-col gap-2 min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <Grid3X3 className="h-4 w-4 text-purple-300" />交叉因子截面 · Top {crossRows.length}
            <span className="text-[10px] text-slate-500 font-normal">{fmtDate(base.x?.trade_date)}，值域 0~1</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] border-collapse">
              <thead>
                <tr className="text-slate-500">
                  <th className="text-left font-normal py-1 pr-2 sticky left-0 bg-[#111827]">代码</th>
                  {crossCols.map(c => (
                    <th key={c} className="text-center font-normal py-1 px-1 whitespace-nowrap" title={c}>
                      {c.replace(/^inter_/, '').replace(/^triple_/, '³').slice(0, 8)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {crossRows.map(r => (
                  <tr key={r.ts_code} className="border-t border-slate-800/60">
                    <td className="py-1 pr-2 sticky left-0 bg-[#111827]">
                      <a href={EvoApi.emStockUrl(r.ts_code)} target="_blank" rel="noopener noreferrer"
                        className="font-mono text-slate-300 hover:text-sky-300">{r.ts_code}</a>
                    </td>
                    {crossCols.map(c => {
                      const v = Number(r[c])
                      const ok = typeof r[c] === 'number' && isFinite(v)
                      return (
                        <td key={c} className="text-center py-0.5 px-0.5">
                          <span className="inline-block w-11 rounded font-mono"
                            style={ok ? { background: `rgba(217,119,6,${0.12 + v * 0.5})`, color: v > 0.66 ? '#fcd34d' : '#cbd5e1' } : { color: '#475569' }}>
                            {ok ? v.toFixed(2) : '—'}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            {!crossRows.length && <div className="text-xs text-slate-600 py-4 text-center">暂无截面数据</div>}
          </div>
        </div>
      </div>

      {/* 选中因子三联曲线 */}
      <div className="rounded-xl bg-[#111827] border border-[#1F2937] p-4 flex flex-col gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          <LineChart className="h-4 w-4 text-emerald-300" />
          因子追踪 · <span className="font-mono text-amber-300">{selected || '—'}</span>
          <span className="text-[10px] text-slate-500 font-normal">点击上方任一因子行切换</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div><div className="text-[11px] text-slate-400 mb-1 flex items-center gap-1"><Activity className="h-3 w-3 text-sky-400" />RankIC（60 日）</div>
            <Spark vals={series?.ic} color="#38bdf8" zeroLine /></div>
          <div><div className="text-[11px] text-slate-400 mb-1 flex items-center gap-1"><Users className="h-3 w-3 text-amber-400" />拥挤度（60 日）</div>
            <Spark vals={series?.cw} color="#fbbf24" /></div>
          <div><div className="text-[11px] text-slate-400 mb-1 flex items-center gap-1"><Scale className="h-3 w-3 text-emerald-400" />动态权重（30 快照）</div>
            <Spark vals={series?.w} color="#34d399" /></div>
        </div>
      </div>
    </div>
  )
}
