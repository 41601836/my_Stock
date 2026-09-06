/**
 * EvoML.jsx —— LambdaRank ML 排序页（真实数据）
 * 左：/ml/portfolio TopN 表（rank_score 条）+ 点行选股
 * 右：/ml/shap/{ts} SHAP 水平条形（正=推高排序 emerald / 负=拉低 rose）
 * 数据来源：每晚 21:30 管线第 4 步写入 evo_ml_predictions
 */
import React, { useEffect, useMemo, useState } from 'react'
import { Brain, MousePointerClick } from 'lucide-react'
import * as EvoApi from './EvoApi'

const fmtDate = (d) => (d && String(d).length === 8
  ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : (d || '—'))

// 因子展示名（与 EvoApi.MODULE_META 风格一致的紧凑映射）
const F_LABEL = {
  inter_quality_momentum: '质量×动量', inter_value_excess: '价值×超额',
  inter_chip_volume: '筹码×放量', inter_smart_defense: '智能防御',
  inter_overshoot_reversal: '超跌反转', inter_turnover_reversal: '换手反转',
  triple_value_mom_quality: '³价值质量动量', inter_mom_skew_neg: '动量×负偏度',
  inter_lowvol_profit: '低波×盈利', inter_chip_break_right: '筹码×右突破',
  surprise_price_vote: '价量共振预期差', surprise_earnings_gap: '跳空预期差',
  surprise_roe_qoq: 'ROE 预期差', text_sentiment_score: '文本情绪',
  graham_score: 'Graham 分', mkt_breadth_ma20: '市场宽度', mkt_vol_expansion: '波动扩张',
}

export default function EvoML() {
  const [data, setData] = useState(null)
  const [sel, setSel] = useState('')
  const [shap, setShap] = useState(null)

  useEffect(() => {
    EvoApi.mlPortfolio(30).then(d => {
      if (!d.error) {
        setData(d)
        const first = (d.stocks || [])[0]?.ts_code
        if (first) setSel(first)
      }
    })
  }, [])

  useEffect(() => {
    if (!sel) return
    let alive = true
    setShap(null)
    EvoApi.mlShap(sel).then(d => { if (alive && !d.error) setShap(d) })
    return () => { alive = false }
  }, [sel])

  const stocks = data?.stocks || []
  const maxScore = useMemo(() =>
    Math.max(...stocks.map(s => Number(s.rank_score) || 0), 0.0001), [stocks])

  const shapEntries = useMemo(() => Object.entries(shap?.shap || {})
    .map(([k, v]) => ({ k, v: Number(v) || 0 }))
    .sort((a, b) => Math.abs(b.v) - Math.abs(a.v)), [shap])
  const shapMax = useMemo(() =>
    Math.max(...shapEntries.map(e => Math.abs(e.v)), 0.0001), [shapEntries])

  return (
    <div className="flex flex-col gap-4">
      {/* 头部 */}
      <div className="rounded-xl bg-[#111827] border border-[#1F2937] px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
        <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
          <Brain className="h-4 w-4 text-emerald-300" />LambdaRank 排序
        </span>
        <span className="text-slate-500">推理日期 <span className="text-slate-200 font-mono">{fmtDate(data?.trade_date)}</span></span>
        <span className="text-slate-500">覆盖 <span className="text-slate-200 font-mono">{data?.count ?? '—'} 只</span></span>
        <span className="text-slate-500">组合 β <span className="text-emerald-300 font-mono">0.10</span>（灰度中）</span>
        <span className="text-slate-500">测试段 NDCG@10 <span className="text-emerald-300 font-mono">相对 IC 基线 +98.7%</span></span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 左：TopN 表 */}
        <div className="rounded-xl bg-[#111827] border border-[#1F2937] p-4 flex flex-col gap-2">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <MousePointerClick className="h-3.5 w-3.5 text-emerald-300" />
            点击任意行查看 SHAP 归因（右）
          </div>
          <div className="flex flex-col gap-1 overflow-y-auto max-h-[480px] pr-1">
            {stocks.map((s, i) => {
              const v = Number(s.rank_score) || 0
              const on = sel === s.ts_code
              return (
                <button key={s.ts_code} onClick={() => setSel(s.ts_code)}
                  className={`w-full text-left rounded-lg border px-2.5 py-1.5 text-xs flex items-center gap-2 transition-colors
                    ${on ? 'bg-slate-800 border-emerald-500/40' : 'bg-slate-900/30 border-slate-800 hover:border-slate-700'}`}>
                  <span className="w-6 text-slate-500 font-mono text-right">{i + 1}</span>
                  <a href={EvoApi.emStockUrl(s.ts_code)} target="_blank" rel="noopener noreferrer"
                    onClick={e => e.stopPropagation()}
                    className="font-mono text-slate-200 hover:text-sky-300">{s.ts_code}</a>
                  <div className="ml-auto flex items-center gap-2 w-36 shrink-0">
                    <div className="flex-1 h-1.5 rounded bg-slate-800">
                      <div className="h-full rounded bg-emerald-500" style={{ width: `${(v / maxScore) * 100}%` }} />
                    </div>
                    <span className="font-mono text-emerald-300 w-14 text-right">{v.toFixed(4)}</span>
                  </div>
                </button>
              )
            })}
            {!stocks.length && (
              <div className="text-xs text-slate-600 py-6 text-center">
                暂无推理数据（lambdarank 启用 + 管线运行后自动出现）
              </div>
            )}
          </div>
        </div>

        {/* 右：SHAP 归因 */}
        <div className="rounded-xl bg-[#111827] border border-[#1F2937] p-4 flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="text-slate-400">
              SHAP 贡献 · <span className="font-mono text-amber-300">{sel || '—'}</span>
            </span>
            {shap && <span className="text-slate-500 font-mono text-[10px]">{fmtDate(shap.trade_date)}</span>}
          </div>
          <div className="flex flex-col gap-1.5 overflow-y-auto max-h-[480px] pr-1">
            {shapEntries.map(({ k, v }) => {
              const pos = v >= 0
              const wPct = (Math.abs(v) / shapMax) * 50
              return (
                <div key={k} className="text-[11px] flex items-center gap-2">
                  <span className="text-slate-400 truncate w-28 text-right" title={k}>{F_LABEL[k] || k}</span>
                  <div className="flex-1 relative h-3.5 bg-slate-900/50 rounded">
                    {/* 中线 */}
                    <div className="absolute top-0 bottom-0 left-1/2 w-px bg-slate-700" />
                    <div className={`absolute top-0 bottom-0 rounded ${pos ? 'bg-emerald-500/70' : 'bg-rose-500/70'}`}
                      style={pos ? { left: '50%', width: `${wPct}%` } : { right: '50%', width: `${wPct}%` }} />
                  </div>
                  <span className={`font-mono w-16 ${pos ? 'text-emerald-400' : 'text-rose-400'}`}>{v >= 0 ? '+' : ''}{v.toFixed(4)}</span>
                </div>
              )
            })}
            {!shapEntries.length && (
              <div className="text-xs text-slate-600 py-6 text-center">
                {sel ? 'SHAP 加载中…' : '左侧选择股票后展示 17 项因子贡献'}
              </div>
            )}
          </div>
          {shapEntries.length > 0 && (
            <div className="text-[10px] text-slate-600 font-mono pt-1 border-t border-slate-800">
              正值 = 推高该股排序（emerald），负值 = 拉低（rose）；按绝对值排序，共 {shapEntries.length} 项
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
