/**
 * EvoGraham.jsx —— Graham 7 项价值安全边际雷达页
 *  两栏：左 = 通过 ≥4 项的股票池；右 = 选中个股的 7 项雷达图
 */
import React, { useEffect, useMemo, useState } from 'react'
import { Shield, Search, CheckCircle2, XCircle } from 'lucide-react'
import * as EvoApi from './EvoApi'
import { emStockUrl } from './EvoApi'

// Graham 7 项中文名与说明（与 evo.yaml checks 一一对应）
const GRAHAM_DIMENSIONS = [
  { key: 'adequate_size',        name: '流通规模',       desc: '≥ 阈值亿元（适当流动性）' },
  { key: 'strong_liquidity',     name: '偿债能力',       desc: '流动比率 ≥ 阈值（短期安全）' },
  { key: 'reasonable_pe',        name: '合理 PE',        desc: 'PE(TTM) ≤ 阈值（不贵）' },
  { key: 'safe_valuation_product', name: 'PE×PB 安全边际', desc: 'PE × PB ≤ 阈值（综合估值底）' },
  { key: 'consistent_earnings',  name: '持续盈利',       desc: 'ROE 持续为正（穿越周期）' },
  { key: 'dividend_record',      name: '分红记录',       desc: '连续 N 年分红（真金白银）' },
  { key: 'long_term_growth',     name: '长期增长',       desc: '10 年盈利增长 ≥ 阈值' },
]

export default function EvoGraham() {
  const [data, setData] = useState(null)
  const [minChecks, setMinChecks] = useState(4)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    EvoApi.grahamScreen(minChecks, 50).then(d => !d.error && setData(d))
  }, [minChecks])

  useEffect(() => {
    if (!selected) { setDetail(null); return }
    EvoApi.grahamScore(selected).then(d => !d.error && setDetail(d))
  }, [selected])

  const list = useMemo(() => {
    // ⚠️ /graham/screen 的列表在 `data` 键（非 stocks），两者兜底
    const arr = data?.stocks || data?.data || []
    if (!keyword.trim()) return arr
    const kw = keyword.trim().toLowerCase()
    return arr.filter(s => (s.ts_code || '').toLowerCase().includes(kw))
  }, [data, keyword])

  const detailObj = useMemo(() => {
    let d = detail?.detail
    if (typeof d === 'string') { try { d = JSON.parse(d) } catch (_) { d = null } }
    return d || {}
  }, [detail])

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr,420px] gap-4 min-h-0 h-full">
      {/* 左栏：股票池 */}
      <div className="rounded-xl bg-[#111827] border border-[#1F2937] flex flex-col min-h-0">
        <div className="px-4 py-3 border-b border-[#1F2937] flex flex-col md:flex-row md:items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-rose-500/15 text-rose-300 border border-rose-500/30">
              <Shield className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-100">Graham 价值防御池</h3>
              <p className="text-[11px] text-slate-500">
                通过 ≥ N 项的股票池，数据日期：<span className="font-mono text-slate-300">{data?.trade_date || '—'}</span>
                ，共 <span className="text-rose-300 font-bold">{data?.count ?? list.length}</span> 只
              </p>
            </div>
          </div>
          <div className="md:ml-auto flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <label>最少通过</label>
              <select
                value={minChecks}
                onChange={e => setMinChecks(Number(e.target.value))}
                className="bg-slate-900/60 border border-slate-700/40 rounded px-2 py-1 text-slate-200 text-xs"
              >
                {[0,1,2,3,4,5,6,7].map(n => <option key={n} value={n}>{n} 项</option>)}
              </select>
            </div>
            <div className="relative">
              <Search className="h-3 w-3 absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={keyword}
                onChange={e => setKeyword(e.target.value)}
                placeholder="搜代码"
                className="w-36 pl-6 pr-2 py-1 text-xs bg-slate-900/60 border border-slate-700/40 rounded text-slate-200 placeholder:text-slate-600"
              />
            </div>
          </div>
        </div>
        <div className="overflow-auto flex-1">
          {list.length ? (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-[#0E1321] z-10">
                <tr className="text-[10px] text-slate-500 uppercase tracking-wider">
                  <th className="text-left px-3 py-2">代码</th>
                  <th className="text-right px-3 py-2">得分</th>
                  <th className="text-left px-3 py-2">明细（7 项 bool）</th>
                </tr>
              </thead>
              <tbody>
                {list.map((s, i) => {
                  let det = s.graham_detail_json
                  if (typeof det === 'string') { try { det = JSON.parse(det) } catch(_) { det = {} } }
                  const score = s.graham_score ?? 0
                  return (
                    <tr
                      key={s.ts_code || i}
                      onClick={() => setSelected(s.ts_code)}
                      className={`border-t border-[#1F2937] cursor-pointer transition-colors
                        ${selected === s.ts_code ? 'bg-rose-500/10' : 'hover:bg-[#151d32]'}`}
                    >
                      <td className="px-3 py-2 font-mono">
                        <a href={emStockUrl(s.ts_code)} target="_blank" rel="noopener noreferrer"
                           onClick={e => e.stopPropagation()}
                           className="text-slate-200 hover:text-sky-300 hover:underline transition-colors"
                           title="在东方财富查看行情">
                          {s.ts_code}
                        </a>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className={`font-bold font-mono text-sm
                          ${score >= 6 ? 'text-emerald-300' : score >= 4 ? 'text-sky-300' : score >= 2 ? 'text-amber-300' : 'text-rose-300'}`}>
                          {score}<span className="text-[10px] text-slate-500">/7</span>
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-0.5 max-w-[460px]">
                          {GRAHAM_DIMENSIONS.map(dim => {
                            const ok = !!det[dim.key]
                            return ok ? (
                              <CheckCircle2 key={dim.key} title={dim.name + ' ✓'} className="h-3 w-3 text-emerald-400" />
                            ) : (
                              <XCircle     key={dim.key} title={dim.name + ' ✗'} className="h-3 w-3 text-slate-600" />
                            )
                          })}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <div className="p-10 text-center text-xs text-slate-500">
              <Shield className="h-6 w-6 mx-auto mb-2 text-slate-600" />
              <div>暂无 Graham 评分数据。</div>
              <div className="mt-1 opacity-70">
                待 src/feature_engineering_evo.py 产出数据后，此处自动填充。
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 右栏：个股 7 维雷达 */}
      <div className="rounded-xl bg-[#111827] border border-[#1F2937] flex flex-col min-h-0">
        <div className="px-4 py-3 border-b border-[#1F2937]">
          <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
            <Shield className="h-4 w-4 text-rose-300" />
            个股价值雷达
            <span className="text-[10px] text-slate-500 font-mono ml-2">
              {detail?.ts_code || selected || '请点击左侧股票'}
            </span>
          </h3>
          <p className="text-[11px] text-slate-500 mt-0.5">
            {detail?.score != null
              ? `Graham 得分 ${detail.score} / 7（${detail.score >= 4 ? '画像分 +5' : detail.score <= 1 ? '画像分 -10' : '无加减分'}）`
              : '选择左侧代码查看 7 项明细'}
          </p>
        </div>
        <div className="flex-1 overflow-auto p-4">
          {detail ? (
            <ul className="space-y-2">
              {GRAHAM_DIMENSIONS.map(dim => {
                const ok = !!detailObj[dim.key]
                return (
                  <li key={dim.key}
                    className={`flex items-start gap-3 p-3 rounded-lg border
                      ${ok ? 'bg-emerald-500/5 border-emerald-500/30' : 'bg-slate-900/40 border-slate-700/40'}`}>
                    <div className={`p-1 rounded shrink-0 ${ok ? 'text-emerald-400' : 'text-slate-500'}`}>
                      {ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                    </div>
                    <div className="min-w-0">
                      <div className={`text-xs font-semibold ${ok ? 'text-emerald-200' : 'text-slate-300'}`}>
                        {dim.name}
                      </div>
                      <div className="text-[10px] text-slate-500 mt-0.5">{dim.desc}</div>
                    </div>
                  </li>
                )
              })}
            </ul>
          ) : (
            <div className="h-full flex items-center justify-center text-xs text-slate-500 text-center p-6">
              <div>
                <Shield className="h-6 w-6 mx-auto mb-2 text-slate-600" />
                点击左侧任意股票查看 Graham 七维画像
              </div>
            </div>
          )}
        </div>
        <div className="px-4 py-2 border-t border-[#1F2937] text-[10px] text-slate-500 font-mono">
          PE×PB 上限=30，PE 上限=25，规模≥50 亿（A 股宽松版）
        </div>
      </div>
    </div>
  )
}
