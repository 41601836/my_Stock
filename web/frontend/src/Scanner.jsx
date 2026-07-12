import React, { useState, useEffect, useCallback } from 'react'
import {
  Crosshair, TrendingUp, BarChart3, Zap, RefreshCw,
  ArrowUpRight, ArrowDownRight, Minus, Info,
  Building2, Target, Layers, DollarSign, Activity, Sparkles
} from 'lucide-react'

// 建仓信号强度色阶
function ScoreBar({ value, max = 100 }) {
  const pct = Math.min(value / max, 1)
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
      <span className={`text-xs font-bold font-mono ${textColor}`}>{value.toFixed(1)}</span>
    </div>
  )
}

// 涨跌幅显示
function PctChg({ value }) {
  if (value > 0) return <span className="text-rose-500 font-bold font-mono flex items-center gap-0.5"><ArrowUpRight className="h-3 w-3" />+{value.toFixed(2)}%</span>
  if (value < 0) return <span className="text-emerald-500 font-bold font-mono flex items-center gap-0.5"><ArrowDownRight className="h-3 w-3" />{value.toFixed(2)}%</span>
  return <span className="text-gray-400 font-mono flex items-center gap-0.5"><Minus className="h-3 w-3" />0.00%</span>
}

// 建仓等级标签
function BuildGrade({ score }) {
  if (score >= 75) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">强烈建仓</span>
  if (score >= 60) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-sky-500/15 text-sky-400 border border-sky-500/30">积极关注</span>
  if (score >= 45) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500/15 text-amber-400 border border-amber-500/30">谨慎建仓</span>
  return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-gray-500/15 text-gray-400 border border-gray-500/30">观望</span>
}

function Scanner() {
  const [stocks, setStocks]     = useState([])
  const [meta, setMeta]         = useState({})
  const [loading, setLoading]   = useState(true)
  const [selected, setSelected] = useState(null)
  const [lastUpdate, setLastUpdate] = useState(null)

  const fetchOpportunities = useCallback(() => {
    setLoading(true)
    fetch('/api/scan-opportunities')
      .then(res => res.json())
      .then(data => {
        setStocks(data.stocks || [])
        setMeta(data.meta || {})
        setLastUpdate(new Date())
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  // 首次加载 + 每5分钟自动刷新
  useEffect(() => {
    fetchOpportunities()
    const timer = setInterval(fetchOpportunities, 5 * 60 * 1000)
    return () => clearInterval(timer)
  }, [fetchOpportunities])

  const formatDate = (d) => {
    if (!d) return '—'
    const s = String(d)
    return `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}`
  }

  const selectedStock = selected !== null ? stocks.find(s => s.rank === selected) : null

  return (
    <div className="space-y-6" id="scanner-view">

      {/* ── 标题栏 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-purple-500/15 border border-purple-500/30">
            <Crosshair className="h-6 w-6 text-purple-400 animate-pulse" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-100">建仓机会实时扫描</h2>
            <p className="text-xs text-gray-500 font-mono">
              5维融合 · 因子+筹码+主力资金+涨幅过滤
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdate && (
            <span className="text-xs text-gray-500 font-mono">
              {lastUpdate.toLocaleTimeString('zh-CN', { hour12: false })} 刷新
            </span>
          )}
          <button
            onClick={fetchOpportunities}
            disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-purple-600/20 text-purple-400 border border-purple-600/30 hover:bg-purple-600/30 hover:text-purple-200 active:scale-95 transition-all disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>{loading ? '刷新列表...' : '刷新列表'}</span>
          </button>
        </div>
      </div>

      {/* ── 数据血统状态跟踪 (Data Lineage Tracker) */}
      <div className="grid grid-cols-4 gap-4 p-4 rounded-xl bg-[#151d32] border border-[#1e2a44]">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-gray-500 font-bold tracking-wider">行情基准日 (Price)</span>
          <span className="text-sm font-mono text-gray-300 flex items-center gap-2">
            {formatDate(meta.scan_date)}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-gray-500 font-bold tracking-wider">底层因子引擎 (Factors)</span>
          <span className={`text-sm font-mono flex items-center gap-2 ${meta.factor_date < meta.scan_date ? 'text-amber-400' : 'text-emerald-400'}`}>
            {formatDate(meta.factor_date)}
            {meta.factor_date < meta.scan_date && (
              <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/20 border border-amber-500/30 text-amber-500 ml-1">需重扫</span>
            )}
            {meta.factor_date >= meta.scan_date && meta.factor_date && (
              <span className="px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/20 border border-emerald-500/30 text-emerald-500 ml-1">LATEST</span>
            )}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-gray-500 font-bold tracking-wider">筹码分布 (CYQ)</span>
          <span className={`text-sm font-mono flex items-center gap-2 ${meta.cyq_date < meta.scan_date ? 'text-rose-400' : 'text-gray-300'}`}>
            {formatDate(meta.cyq_date)}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-gray-500 font-bold tracking-wider">大单资金 (Money Flow)</span>
          <span className={`text-sm font-mono flex items-center gap-2 ${meta.mf_date < meta.scan_date ? 'text-rose-400' : 'text-gray-300'}`}>
            {formatDate(meta.mf_date)}
          </span>
        </div>
      </div>

      {meta.factor_date < meta.scan_date && (
        <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 flex items-center gap-3">
          <Info className="h-5 w-5 text-amber-400 shrink-0" />
          <p className="text-xs text-amber-200">
            <strong>状态警告：</strong> 底层因子数据 ({formatDate(meta.factor_date)}) 落后于行情基准日 ({formatDate(meta.scan_date)})。
            当前榜单仍在使用旧因子排序。请点击网页顶部的 <strong>「扫描因子」</strong> 按钮来同步最新大脑。
          </p>
        </div>
      )}

      {/* ── 统计卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { icon: <BarChart3 className="h-5 w-5 text-sky-400" />, label: '全量扫描', value: meta.total_scanned?.toLocaleString() ?? '—', sub: '只股票参与因子打分', color: 'border-sky-500/20' },
          { icon: <Target className="h-5 w-5 text-emerald-400" />, label: '筛选通过', value: meta.after_filter ?? '—', sub: '满足建仓基础条件', color: 'border-emerald-500/20' },
          { icon: <Zap className="h-5 w-5 text-purple-400" />, label: '精选推荐', value: meta.final_count ?? '—', sub: '综合评分最优', color: 'border-purple-500/20' },
          { icon: <Activity className="h-5 w-5 text-amber-400" />, label: '因子截止', value: formatDate(meta.factor_date), sub: `资金: ${formatDate(meta.mf_date)}`, color: 'border-amber-500/20' },
        ].map((c, i) => (
          <div key={i} className={`p-5 bg-[#151D30]/80 rounded-2xl border ${c.color} border-[#222F4C] space-y-1`}>
            <div className="flex items-center gap-2">
              {c.icon}
              <span className="text-xs text-gray-400 font-mono">{c.label}</span>
            </div>
            <div className="text-2xl font-bold font-mono text-gray-100">{c.value}</div>
            <div className="text-xs text-gray-500">{c.sub}</div>
          </div>
        ))}
      </div>

      {/* ── 打分维度说明 */}
      <div className="p-4 rounded-xl bg-[#0B1220]/60 border border-[#1A253D] flex flex-wrap gap-4 text-xs text-gray-400">
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-purple-500 inline-block" />因子信号 35%（Range 策略权重）</div>
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-sky-500 inline-block" />筹码控盘 25%（胜率≥40% 机构锁仓）</div>
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />大资金净流入 25%（大单+超大单净额）</div>
        <div className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />低追高风险 15%（涨幅过滤 -8%~+5%）</div>
      </div>

      {/* ── 主表格 + 详情面板 */}
      <div className="flex gap-4">
        {/* 股票列表 */}
        <div className={`${selected ? 'w-3/5' : 'w-full'} transition-all duration-300`}>
          {loading ? (
            <div className="p-16 flex flex-col items-center gap-4 text-gray-500">
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-purple-500" />
              <span className="font-mono text-sm">正在扫描全市场 5500+ 只股票...</span>
            </div>
          ) : stocks.length === 0 ? (
            <div className="p-16 text-center text-gray-500 font-mono">
              <Target className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>当前无满足条件的建仓机会</p>
              <p className="text-xs mt-1">请等待数据更新后重新扫描</p>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-2xl border border-[#222F4C] bg-[#151D30]/60">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="bg-[#0E1524] text-gray-400 font-mono text-xs border-b border-[#222F4C]">
                    <th className="p-3 pl-5 text-left">排名</th>
                    <th className="p-3 text-left">代码 / 名称</th>
                    <th className="p-3 text-left">行业</th>
                    <th className="p-3 text-right">今日涨跌</th>
                    <th className="p-3">
                      <span title="5维综合建仓评分，满分100">建仓评分 ⓘ</span>
                    </th>
                    <th className="p-3 text-right">MVO 权重</th>
                    <th className="p-3 text-right">收盘价</th>
                    <th className="p-3 text-right pr-5">主力净流入</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#222F4C]/40 font-mono">
                  {stocks.map(s => (
                    <tr
                      key={s.ts_code}
                      onClick={() => setSelected(selected === s.rank ? null : s.rank)}
                      className={`cursor-pointer transition-colors ${selected === s.rank ? 'bg-purple-900/20 border-l-2 border-purple-500' : 'hover:bg-[#1A253D]/40'}`}
                    >
                      <td className="p-3 pl-5">
                        <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                          s.rank <= 3 ? 'bg-purple-500/25 text-purple-300 border border-purple-500/40' : 'text-gray-500'
                        }`}>{s.rank}</span>
                      </td>
                      <td className="p-3">
                        <a
                          href={`http://stockpage.10jqka.com.cn/${s.ts_code.substring(0, 6)}/`}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="hover:underline cursor-pointer flex flex-col"
                          title="在同花顺查看该股票详情"
                        >
                          <div className="font-bold text-gray-200 text-xs hover:text-indigo-300">{s.ts_code}</div>
                          <div className="text-gray-100 font-sans font-semibold hover:text-indigo-400">{s.name}</div>
                        </a>
                      </td>
                      <td className="p-3 text-gray-400 font-sans text-xs">{s.industry}</td>
                      <td className="p-3 text-right"><PctChg value={s.pct_chg} /></td>
                      <td className="p-3">
                        <div className="flex flex-col gap-1">
                          <ScoreBar value={s.build_score} />
                          <BuildGrade score={s.build_score} />
                        </div>
                      </td>
                      <td className="p-3 text-right font-bold text-sky-400">{s.mvo_weight !== undefined ? `${s.mvo_weight}%` : '均权'}</td>
                      <td className="p-3 text-right text-gray-300">{s.close.toFixed(2)} 元</td>
                      <td className="p-3 pr-5 text-right">
                        <span className={`font-bold text-xs ${s.big_net_inflow > 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
                          {s.big_net_inflow > 0 ? '+' : ''}{s.big_net_inflow.toFixed(2)} 亿
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* 详情面板 */}
        {selectedStock && (
          <div className="w-2/5 space-y-4">
            <div className="p-5 bg-[#151D30]/90 rounded-2xl border border-purple-500/30 space-y-4">
              {/* 股票标题 */}
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-lg font-bold text-gray-100">{selectedStock.name}</div>
                  <div className="text-xs text-gray-400 font-mono">{selectedStock.ts_code} · {selectedStock.industry}</div>
                </div>
                <BuildGrade score={selectedStock.build_score} />
              </div>

              {/* 5维指标详情 */}
              <div className="space-y-3">
                <div className="text-xs text-gray-500 font-mono uppercase tracking-widest">信号详情</div>

                {[
                  { label: '因子信号强度', value: selectedStock.factor_score, icon: <BarChart3 className="h-4 w-4 text-purple-400" />, suffix: '%', tip: '综合因子横截面得分（策略模型打分）' },
                  { label: '筹码胜率', value: selectedStock.winner_rate, icon: <Target className="h-4 w-4 text-sky-400" />, suffix: '%', tip: '持股盈利比例，越高说明机构锁仓越深' },
                  { label: '筹码集中度', value: selectedStock.chips_peak_pct, icon: <Layers className="h-4 w-4 text-sky-300" />, suffix: '%', tip: '主峰筹码占比，越高说明成本越集中' },
                  { label: '主力净流入', value: Math.abs(selectedStock.big_net_inflow), icon: <DollarSign className="h-4 w-4 text-rose-500" />, suffix: ' 亿', tip: '大单+超大单净买入金额（正值=主力吸筹）', prefix: selectedStock.big_net_inflow >= 0 ? '+' : '-' },
                  { label: '20日换手率', value: selectedStock.turnover_rate, icon: <Activity className="h-4 w-4 text-amber-400" />, suffix: '%', tip: '20日均换手率，0.5%~15% 为流动性合理区间' },
                  { label: 'MVO 建议权重', value: selectedStock.mvo_weight, icon: <Sparkles className="h-4 w-4 text-emerald-400" />, suffix: '%', tip: '经 Ledoit-Wolf 风险协方差矩阵和行业暴露控制计算的最优持仓权重，防范集中暴跌' },
                ].map((item, i) => (
                  <div key={i} className="flex items-center justify-between py-2 border-b border-[#1A253D]">
                    <div className="flex items-center gap-2">
                      {item.icon}
                      <span className="text-xs text-gray-400" title={item.tip}>{item.label}</span>
                    </div>
                    <span className="text-sm font-bold font-mono text-gray-100">
                      {item.prefix || ''}{item.value.toFixed(item.suffix === ' 亿' ? 2 : 1)}{item.suffix}
                    </span>
                  </div>
                ))}
              </div>

              {/* 建仓理由 */}
              <div className="p-3 bg-[#0B1220]/80 rounded-xl border border-[#1A253D]">
                <div className="text-xs text-gray-500 font-mono mb-1.5 flex items-center gap-1">
                  <Info className="h-3 w-3" /> 建仓依据
                </div>
                <div className="text-xs text-gray-300 leading-relaxed font-sans">
                  {selectedStock.reason}
                </div>
              </div>

              {/* 操作提示 */}
              <div className="p-3 rounded-xl bg-amber-900/10 border border-amber-700/20">
                <p className="text-xs text-amber-400/80 font-sans leading-relaxed">
                  ⚠️ 以上分析基于量化因子模型，仅供参考，不构成投资建议。建仓时请结合市场状态（当前 DARK 避险期建议降低仓位比例）。
                </p>
              </div>
            </div>

            {/* 综合评分雷达（文字版） */}
            <div className="p-4 bg-[#151D30]/60 rounded-2xl border border-[#222F4C]">
              <div className="text-xs text-gray-500 font-mono mb-3">综合评分构成</div>
              {[
                { label: '因子信号', score: selectedStock.factor_score, weight: 35 },
                { label: '筹码胜率', score: Math.min(selectedStock.winner_rate, 100), weight: 25 },
                { label: '主力吸筹', score: selectedStock.build_score > 0 ? 60 : 30, weight: 25 },
                { label: '低追高险', score: Math.max(0, 100 - Math.abs(selectedStock.pct_chg) * 10), weight: 15 },
              ].map((item, i) => (
                <div key={i} className="flex items-center gap-3 mb-2">
                  <div className="text-xs text-gray-500 w-16 shrink-0">{item.label}</div>
                  <div className="flex-1 h-1.5 bg-[#0E1524] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-purple-500/70 rounded-full transition-all duration-700"
                      style={{ width: `${Math.min(item.score, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-400 font-mono w-10 text-right">{item.weight}%权</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── 底部说明 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
        {[
          { icon: <Target className="h-4 w-4 text-emerald-400" />, title: '筹码胜率 ≥ 40%', desc: '机构在低位锁仓，散户解套压力小，上方阻力有限' },
          { icon: <TrendingUp className="h-4 w-4 text-sky-400" />, title: '大单净流入 > 0', desc: '主力资金当日正在吸筹（大单+超大单），而非撤退' },
          { icon: <Building2 className="h-4 w-4 text-purple-400" />, title: '涨幅在 -8%~+5%', desc: '排除当日追高（涨停板）和踩雷（跌停），建仓成本合理' },
        ].map((c, i) => (
          <div key={i} className="p-4 bg-[#0B1220]/40 rounded-xl border border-[#1A253D] flex gap-3">
            <div className="mt-0.5 shrink-0">{c.icon}</div>
            <div>
              <div className="font-bold text-gray-200 mb-1">{c.title}</div>
              <div className="text-gray-500 leading-relaxed">{c.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default Scanner
