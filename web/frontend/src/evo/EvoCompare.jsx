/**
 * EvoCompare.jsx —— 经典 vs 进化 A/B 并排对比（最核心的价值验证页面）
 * ===============================================================
 * - 左栏：/api/portfolio 经典推荐（直接 fetch，不封装，保持 100% 原始）
 * - 右栏：/api/evo/portfolio 进化推荐（通过 EvoApi）
 * - 底部：共同 / 新增 / 剔除 三类股票清单 + 重合度百分比
 */
import React, { useEffect, useMemo, useState } from 'react'
import { GitCompare, CheckCircle, PlusCircle, MinusCircle, TrendingUp, Shield, Brain, Scale, AlertTriangle } from 'lucide-react'
import * as EvoApi from './EvoApi'
import { emStockUrl } from './EvoApi'

function StockTable({ title, subtitle, stocks, date, flags, tagColor, Icon, fallbackNote }) {
  const hasData = Array.isArray(stocks) && stocks.length > 0
  return (
    <div className="flex flex-col rounded-xl bg-[#111827] border border-[#1F2937] min-h-0">
      <div className="px-4 py-3 border-b border-[#1F2937] flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`p-1.5 rounded-lg shrink-0 ${tagColor}`}>
            {Icon ? <Icon className="h-4 w-4" /> : null}
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-100 truncate">{title}</h3>
            <p className="text-[11px] text-slate-500 truncate">{subtitle}</p>
          </div>
        </div>
        {date ? <span className="text-[10px] font-mono text-slate-500 shrink-0">{date}</span> : null}
      </div>

      {/* 模块徽章 */}
      {flags && Object.keys(flags).length > 0 ? (
        <div className="px-4 py-2 border-b border-[#1F2937] flex flex-wrap gap-1.5">
          {flags.dynamic_weight ? <Badge icon="⚖️" label="动态权重" /> : null}
          {flags.ml_rank        ? <Badge icon="🧠" label="ML 排序" /> : null}
          {flags.graham         ? <Badge icon="🛡️" label="Graham" /> : null}
          {flags.surprise       ? <Badge icon="🎯" label="预期差" /> : null}
          {flags.crowding_filter? <Badge icon="🧍" label="拥挤过滤" /> : null}
        </div>
      ) : null}

      <div className="overflow-auto max-h-[460px]">
        {hasData ? (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-[#0E1321] z-10">
              <tr className="text-[10px] text-slate-500 uppercase tracking-wider">
                <th className="text-left px-3 py-2">#</th>
                <th className="text-left px-3 py-2">股票</th>
                <th className="text-right px-3 py-2">因子分</th>
                <th className="text-right px-3 py-2">画像分</th>
                <th className="text-right px-3 py-2">等级</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s, i) => {
                const name = s.name || s.stock_name || '—'
                const code = s.ts_code || s.stock_code || s.code || ''
                const fScore = s.evo_score ?? s.composite_score ?? s.factor_score ?? s.score ?? null
                // 经典侧=portrait_score(0~100)；EVO 侧=graham_score(0~7)，量纲不同分列渲染
                const isGraham = s.portrait_score == null && s.graham_score != null
                const pScore = s.portrait_score ?? null
                const grade  = s.grade ?? s.level ?? s.portrait_grade ?? ''
                return (
                  <tr key={code || i} className="border-t border-[#1F2937] hover:bg-[#151d32] transition-colors">
                    <td className="px-3 py-1.5 font-mono text-slate-500">{i + 1}</td>
                    <td className="px-3 py-1.5 min-w-[180px]">
                      <div className="text-slate-100 font-medium">{name}</div>
                      <div className="text-[10px] font-mono">
                        <a href={emStockUrl(code)} target="_blank" rel="noopener noreferrer"
                           onClick={e => e.stopPropagation()}
                           className="text-slate-500 hover:text-sky-300 hover:underline transition-colors"
                           title="在东方财富查看行情">
                          {code}
                        </a>
                      </div>
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-sky-300">
                      {typeof fScore === 'number' ? fScore.toFixed(2) : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-purple-300">
                      {isGraham
                        ? `${s.graham_score}/7`
                        : typeof pScore === 'number' ? pScore.toFixed(1) : '—'}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {grade ? (
                        <span className={gradeBadgeClass(grade)}>{grade}</span>
                      ) : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <div className="p-8 text-center text-xs text-slate-500 space-y-2">
            <AlertTriangle className="h-6 w-6 mx-auto text-slate-600" />
            <div>{fallbackNote || '暂无数据'}</div>
          </div>
        )}
      </div>
    </div>
  )
}

function Badge({ icon, label }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border border-amber-500/30 bg-amber-500/10 text-amber-200">
      <span>{icon}</span><span>{label}</span>
    </span>
  )
}

function gradeBadgeClass(g) {
  const level = String(g || '').toUpperCase()
  const s = 'px-2 py-0.5 rounded text-[10px] border font-semibold '
  if (level.includes('S')) return s + 'bg-rose-500/15 text-rose-300 border-rose-500/40'
  if (level.includes('A')) return s + 'bg-amber-500/15 text-amber-300 border-amber-500/40'
  if (level.includes('B')) return s + 'bg-sky-500/15 text-sky-300 border-sky-500/40'
  if (level.includes('C')) return s + 'bg-slate-500/15 text-slate-300 border-slate-500/40'
  return s + 'bg-slate-700/40 text-slate-300 border-slate-600/40'
}

export default function EvoCompare() {
  const [classic, setClassic] = useState(null)
  const [evo, setEvo] = useState(null)

  useEffect(() => {
    // 左栏：经典层（直接 fetch，保持与现有页面 100% 一致的调用）
    // ⚠️ /api/portfolio 实际返回 list[stock]（非 {stocks}），此处归一化，不改经典层
    fetch('/api/portfolio?top_n=10').then(r => r.ok ? r.json() : { error: r.status })
      .then(raw => {
        if (Array.isArray(raw)) setClassic({ stocks: raw, date: null })
        else if (raw && Array.isArray(raw.stocks)) setClassic(raw)
        else setClassic({ error: raw?.error || 'unexpected_shape', stocks: raw?.stocks || [] })
      })
      .catch(e => setClassic({ error: String(e) }))
    // 右栏：进化层（统一走 EvoApi）
    EvoApi.comparePortfolio(10).then(d => setEvo(d.error ? null : d))
  }, [])

  const classicCodes = useMemo(
    () => new Set((classic?.stocks || []).map(s => s.ts_code || s.stock_code || s.code).filter(Boolean)),
    [classic]
  )
  const evoCodes = useMemo(
    () => new Set(((evo?.evo?.stocks) || (evo?.stocks) || []).map(s => s.ts_code || s.code).filter(Boolean)),
    [evo]
  )
  const overlap = useMemo(() => {
    const common = [...classicCodes].filter(c => evoCodes.has(c))
    const union = new Set([...classicCodes, ...evoCodes])
    const ratio = union.size ? common.length / union.size : 0
    return { common, ratio, onlyClassic: [...classicCodes].filter(c => !evoCodes.has(c)), onlyEvo: [...evoCodes].filter(c => !classicCodes.has(c)) }
  }, [classicCodes, evoCodes])

  const classicOk = (classic?.stocks || []).length > 0
  const overlapPct = Math.round(overlap.ratio * 100)
  // 严谨性：经典侧缺失时重合度无从计算，显示「—」而非 0%，也不触发熔断告警
  const overlapWarn = classicOk && overlap.ratio < 0.20

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* 重合度 & 熔断状态栏 */}
      <div className={`rounded-xl p-4 border flex items-center justify-between gap-4
        ${overlapWarn
          ? 'bg-rose-500/10 border-rose-500/40'
          : 'bg-emerald-500/10 border-emerald-500/30'}`}>
        <div className="flex items-center gap-3 min-w-0">
          <GitCompare className="h-5 w-5 shrink-0 text-slate-200" />
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-100">经典 vs EVO Top10 对比</h2>
            <p className="text-[11px] text-slate-400 truncate">
              共同 {overlap.common.length} 只 · EVO 新增 {overlap.onlyEvo.length} 只 · EVO 剔除 {overlap.onlyClassic.length} 只
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <div className="text-right">
            <div className="text-[10px] text-slate-500 font-mono">重合度</div>
            <div className={`text-2xl font-bold font-mono ${!classicOk ? 'text-slate-500' : overlapWarn ? 'text-rose-300' : 'text-emerald-300'}`}>
              {classicOk ? overlapPct : '—'}<span className="text-sm">%</span>
            </div>
          </div>
          {!classicOk ? (
            <div className="px-3 py-1.5 rounded border border-slate-600/40 bg-slate-700/30 text-slate-300 text-[10px] font-mono">
              经典数据缺失，重合度不可算
            </div>
          ) : overlapWarn ? (
            <div className="px-3 py-1.5 rounded border border-rose-500/40 bg-rose-500/20 text-rose-200 text-[10px] font-mono">
              ⚠️ 熔断阈值（20%）
            </div>
          ) : (
            <div className="px-3 py-1.5 rounded border border-emerald-500/40 bg-emerald-500/20 text-emerald-200 text-[10px] font-mono">
              ✓ 组合平稳
            </div>
          )}
        </div>
      </div>

      {/* 左右两栏并排 */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 min-h-0 flex-1">
        <StockTable
          title="经典策略"
          subtitle={`/api/portfolio (传统静态权重 + 画像漏斗)`}
          Icon={TrendingUp}
          tagColor="bg-purple-500/15 text-purple-300 border border-purple-500/30"
          stocks={classic?.stocks || []}
          date={classic?.date}
          flags={null}
          fallbackNote="经典接口暂不可用，请检查策略引擎状态"
        />
        <StockTable
          title="EVO 进化策略"
          subtitle={evo?.evo?.note || evo?.note || '/api/evo/portfolio（动态权重+交叉+Graham+预期差融合）'}
          Icon={Scale}
          tagColor="bg-amber-500/15 text-amber-300 border border-amber-500/30"
          stocks={evo?.evo?.stocks || evo?.stocks || []}
          date={evo?.date}
          flags={evo?.evo?.engine_flags || evo?.engine_flags}
          fallbackNote={evo?.evo?.note || "EVO 引擎：阶段 1+ 起开始填充交叉因子与真实排序"}
        />
      </div>

      {/* 差异分析 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <DiffPanel title="共同推荐" color="emerald" icon={CheckCircle} stocks={overlap.common} />
        <DiffPanel title="EVO 新增（经典没有）" color="sky" icon={PlusCircle} stocks={overlap.onlyEvo} />
        <DiffPanel title="EVO 剔除（经典有但 EVO 无）" color="rose" icon={MinusCircle} stocks={overlap.onlyClassic} />
      </div>
    </div>
  )
}

function DiffPanel({ title, color, icon: Icon, stocks }) {
  const palette = {
    emerald: { bd: 'border-emerald-500/30', bg: 'bg-emerald-500/10', text: 'text-emerald-300', count: 'text-emerald-200' },
    sky:     { bd: 'border-sky-500/30',     bg: 'bg-sky-500/10',     text: 'text-sky-300',     count: 'text-sky-200' },
    rose:    { bd: 'border-rose-500/30',    bg: 'bg-rose-500/10',    text: 'text-rose-300',    count: 'text-rose-200' },
  }[color] || { bd: 'border-slate-500/30', bg: 'bg-slate-500/10', text: 'text-slate-300', count: 'text-slate-200' }

  return (
    <div className={`rounded-xl border ${palette.bd} bg-[#111827] p-4 flex flex-col gap-3`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`p-1 rounded-lg shrink-0 ${palette.bg} ${palette.text} border ${palette.bd}`}>
            <Icon className="h-3.5 w-3.5" />
          </div>
          <h4 className={`text-xs font-semibold ${palette.text} truncate`}>{title}</h4>
        </div>
        <span className={`text-sm font-bold font-mono ${palette.count}`}>{stocks.length}</span>
      </div>
      <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
        {stocks.length ? stocks.map(c => (
          <a key={c} href={emStockUrl(c)} target="_blank" rel="noopener noreferrer"
             className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-900/50 text-slate-300 border border-slate-700/40 hover:text-sky-300 hover:border-sky-500/40 transition-colors"
             title="在东方财富查看行情">
            {c}
          </a>
        )) : <span className="text-[11px] text-slate-500">—</span>}
      </div>
    </div>
  )
}
