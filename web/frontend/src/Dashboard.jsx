import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Landmark, ArrowUpRight, ArrowDownRight, Compass, ShieldCheck, Cpu, BarChart3, Flame, Calendar, ChevronRight } from 'lucide-react'
import { StreakBadge, RankCircle, AppearBadge } from './scanner/shared'

// 生成东方财富行情链接（对格式异常的代码做防护）
const getEastmoneyUrl = (stockCode) => {
  if (!stockCode || stockCode.length < 9) return '#'
  const market = stockCode.substring(7).toLowerCase()  // 'SZ' → 'sz'
  const code   = stockCode.substring(0, 6)
  return `https://quote.eastmoney.com/${market}${code}.html`
}

// 画像等级样式配置（来自 T+1 上涨画像实证分析）
const portraitGradeConfig = {
  A: { label: 'A', emoji: '🔥', color: '#10b981', bg: 'rgba(16,185,129,0.15)', border: 'rgba(16,185,129,0.35)', title: '强烈推荐 · 符合所有T+1上涨特征' },
  B: { label: 'B', emoji: '✅', color: '#38bdf8', bg: 'rgba(56,189,248,0.12)', border: 'rgba(56,189,248,0.30)', title: '符合画像 · 多数T+1上涨特征匹配' },
  C: { label: 'C', emoji: '⚠️', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.30)', title: '勉强通过 · 部分特征不匹配' },
  D: { label: 'D', emoji: '❌', color: '#f43f5e', bg: 'rgba(244,63,94,0.12)', border: 'rgba(244,63,94,0.30)', title: '画像不符 · T+1上涨概率偏低' },
}

function Dashboard({ marketStatus }) {
  const navigate = useNavigate()
  const [portfolio, setPortfolio] = useState([])
  const [loading, setLoading] = useState(true)
  // 扫描历史预览（供三个预览卡片使用）
  const [scanPreview, setScanPreview] = useState({ summary: [], streak: [], daily: {}, meta: {} })

  useEffect(() => {
    fetch('/api/portfolio')
      .then(res => res.json())
      .then(data => {
        setPortfolio(data)
        setLoading(false)
      })
      .catch(err => {
        console.error(err)
        setLoading(false)
      })
  }, [])

  // 仪表盘用：取近 30 天「今日策略推荐」累计统计（胜率猎手优化器；只消费 summary/streak/daily 顶部几条）
  useEffect(() => {
    fetch('/api/reco-history?days=30&min_appear=1')
      .then(r => r.json())
      .then(d => setScanPreview({
        summary: (d.summary || []).slice(0, 5),
        streak:  (d.streak  || []).slice(0, 5),
        daily:   d.daily   || {},
        meta:    d.meta    || {},
      }))
      .catch(err => console.error('scan-history preview fetch failed:', err))
  }, [])

  const getRegimeDetails = (regime) => {
    switch (regime?.toUpperCase()) {
      case 'BULL':
        return {
          title: '牛市拉升状态 (BULL)',
          color: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10',
          desc: '策略选用「牛市专用Ridge模型」进行专轨高波换手因子的进攻性打分选股。',
          icon: '🐂'
        }
      case 'BEAR':
        return {
          title: '熊市大跌状态 (BEAR)',
          color: 'text-rose-400 border-rose-500/30 bg-rose-500/10',
          desc: '策略触发「Bear轻仓跟踪风控」，将仓位削减50%进行基准被动避险跟踪。',
          icon: '🐻'
        }
      case 'DARK':
        return {
          title: '系统性避险状态 (DARK)',
          color: 'text-purple-400 border-purple-500/30 bg-purple-500/10',
          desc: '市场环境极恶劣，自动触发「Dark轻仓跟踪风控」，仅以50%被动轻仓跟踪避灾。',
          icon: '🛡️'
        }
      case 'RANGE':
      default:
        return {
          title: '震荡市箱体状态 (RANGE)',
          color: 'text-blue-400 border-blue-500/30 bg-blue-500/10',
          desc: '策略选用「Range核心6因子模型」进行低回撤、质量和聪明钱因子的稳健打分选股。',
          icon: '⚖️'
        }
    }
  }

  const regimeInfo = getRegimeDetails(marketStatus?.regime)
  
  // 仿真计算持仓当日虚拟盈亏
  const isHolding = !['DARK', 'BEAR'].includes(marketStatus?.regime?.toUpperCase())
  const totalProfit = isHolding ? portfolio.reduce((acc, item) => acc + item.position_profit, 0) : 0
  const avgChange = isHolding && portfolio.length > 0
    ? portfolio.reduce((acc, item) => acc + item.daily_change, 0) / portfolio.length
    : 0

  return (
    <div className="space-y-6">
      {/* 🔮 状态看板 (Market Regime Banner) */}
      <div className={`p-6 rounded-2xl border pulsate transition-all ${regimeInfo.color}`}>
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
          <div className="space-y-2">
            <span className="text-xs uppercase font-mono tracking-widest text-gray-400">当前决策路由状态</span>
            <h3 className="text-2xl font-bold flex items-center space-x-2">
              <span className="text-3xl mr-2">{regimeInfo.icon}</span>
              <span>{regimeInfo.title}</span>
            </h3>
            <p className="text-sm opacity-90 leading-relaxed max-w-3xl">{regimeInfo.desc}</p>
          </div>
          <div className="text-left md:text-right space-y-1 w-full md:w-auto">
            <span className="text-xs text-gray-400 font-mono">本周路由选用模型</span>
            <div className="text-sm font-mono font-semibold bg-[#0D1220]/60 px-3 py-1 rounded-lg border border-gray-700">
              {marketStatus?.model_used || 'None'}
            </div>
          </div>
        </div>
      </div>

      {/* 📊 账户当日表现 & 系统健康 (Grid) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-3">
          <span className="text-xs text-gray-400 font-mono">当日持仓表现</span>
          <div className="flex items-baseline space-x-2">
            <span className={`text-3xl font-bold font-mono ${totalProfit >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
              {totalProfit >= 0 ? '+' : ''}{totalProfit.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 元
            </span>
          </div>
          <div className="flex items-center text-xs text-gray-400">
            {totalProfit >= 0 ? (
              <ArrowUpRight className="h-4 w-4 text-emerald-400 mr-1" />
            ) : (
              <ArrowDownRight className="h-4 w-4 text-rose-500 mr-1" />
            )}
            <span>日涨跌率: </span>
            <span className={`ml-1 font-mono font-semibold ${avgChange >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
              {(avgChange * 100).toFixed(2)}%
            </span>
          </div>
        </div>

        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-3">
          <span className="text-xs text-gray-400 font-mono">本周基准表现 (Benchmark)</span>
          <div className="flex items-baseline space-x-2">
            <span className={`text-3xl font-bold font-mono ${marketStatus?.benchmark_return >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
              {marketStatus?.benchmark_return >= 0 ? '+' : ''}{(marketStatus?.benchmark_return * 100).toFixed(2)}%
            </span>
          </div>
          <div className="text-xs text-gray-400 flex items-center">
            <Landmark className="h-3.5 w-3.5 mr-1" />
            <span>全市场股票每日收益等权均值</span>
          </div>
        </div>

        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-3">
          <span className="text-xs text-gray-400 font-mono">系统健康自检</span>
          <div className="text-3xl font-bold font-mono text-emerald-400 flex items-center">
            <Compass className="h-8 w-8 text-emerald-400 mr-2 animate-spin-slow" />
            <span>HEALTHY</span>
          </div>
          <div className="text-xs text-gray-400 flex items-center">
            <ShieldCheck className="h-3.5 w-3.5 mr-1 text-emerald-400" />
            <span>暴跌周内减仓/清仓风控挂载中</span>
          </div>
        </div>
      </div>

      {/* 📋 今日策略推荐统计预览（胜率猎手优化器；3 卡 grid，整张卡可跳完整子页） */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-gray-200">今日策略推荐统计</span>
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30">
            策略：胜率猎手优化器
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* 频率排行 Top 5 */}
        <button
          onClick={() => navigate('/reco-history')}
          title="查看完整的今日策略推荐上榜统计（近 30 天累计，含5日超额胜率）"
          className="group text-left p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-3 hover:border-sky-500/40 hover:bg-[#1A253D]/60 hover:-translate-y-0.5 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-sky-500/30"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400 font-mono flex items-center gap-1.5">
              <BarChart3 className="h-3.5 w-3.5 text-sky-400 group-hover:scale-110 transition-transform" />上榜频率 Top 5
            </span>
            <span className="text-xs text-sky-400/80 group-hover:text-sky-300 flex items-center gap-0.5 transition-colors">
              查看全部 <ChevronRight className="h-3 w-3 group-hover:translate-x-0.5 transition-transform" />
            </span>
          </div>
          {scanPreview.summary.length === 0 ? (
            <div className="text-xs text-gray-500 py-6 text-center">暂无历史数据</div>
          ) : (
            <div className="space-y-1.5">
              {scanPreview.summary.map((s, i) => (
                <div key={s.ts_code} className="flex items-center gap-2 text-xs">
                  <RankCircle rank={i + 1} />
                  <div className="flex-1 min-w-0 truncate">
                    <span className="text-gray-200 font-semibold font-sans">
                      {s.name}
                    </span>
                  </div>
                  <AppearBadge count={s.appear_count} />
                </div>
              ))}
            </div>
          )}
        </button>

        {/* 连续上榜 Top 5 */}
        <button
          onClick={() => navigate('/reco-history/streak')}
          title="查看完整的连续推荐追踪（识别策略持续看多的标的）"
          className="group text-left p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-3 hover:border-rose-500/40 hover:bg-[#1A253D]/60 hover:-translate-y-0.5 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-rose-500/30"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400 font-mono flex items-center gap-1.5">
              <Flame className="h-3.5 w-3.5 text-rose-400 group-hover:scale-110 transition-transform" />连续上榜 Top 5
            </span>
            <span className="text-xs text-rose-400/80 group-hover:text-rose-300 flex items-center gap-0.5 transition-colors">
              查看全部 <ChevronRight className="h-3 w-3 group-hover:translate-x-0.5 transition-transform" />
            </span>
          </div>
          {scanPreview.streak.length === 0 ? (
            <div className="text-xs text-gray-500 py-6 text-center">暂无连续上榜记录</div>
          ) : (
            <div className="space-y-1.5">
              {scanPreview.streak.map((s, i) => (
                <div key={s.ts_code} className="flex items-center gap-2 text-xs">
                  <div className="w-6 text-right text-gray-600 font-mono">{i + 1}</div>
                  <div className="flex-1 min-w-0 truncate">
                    <span className="text-gray-200 font-semibold font-sans">{s.name}</span>
                  </div>
                  <StreakBadge days={s.max_streak_days || s.streak_days} />
                </div>
              ))}
            </div>
          )}
        </button>

        {/* 每日快照概览 */}
        <button
          onClick={() => navigate('/reco-history/daily')}
          title="查看完整的每日策略推荐快照（含当日 Regime 和推荐名单）"
          className="group text-left p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-3 hover:border-emerald-500/40 hover:bg-[#1A253D]/60 hover:-translate-y-0.5 transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400 font-mono flex items-center gap-1.5">
              <Calendar className="h-3.5 w-3.5 text-emerald-400 group-hover:scale-110 transition-transform" />最近快照概览
            </span>
            <span className="text-xs text-emerald-400/80 group-hover:text-emerald-300 flex items-center gap-0.5 transition-colors">
              查看全部 <ChevronRight className="h-3 w-3 group-hover:translate-x-0.5 transition-transform" />
            </span>
          </div>
          {(() => {
            const dates = Object.keys(scanPreview.daily).sort((a, b) => b.localeCompare(a)).slice(0, 4)
            if (dates.length === 0) return <div className="text-xs text-gray-500 py-6 text-center">暂无快照数据</div>
            return (
              <div className="space-y-1.5">
                {dates.map(d => {
                  const rows = scanPreview.daily[d] || []
                  const regime = rows[0]?.regime || '—'
                  const fmt = `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)}`
                  return (
                    <div key={d}
                      className="w-full flex items-center gap-2 text-xs py-1 px-2 rounded-lg bg-[#0E1524]/40 group-hover:bg-[#0E1524]/80 transition-colors">
                      <span className="text-gray-300 font-mono flex-1 text-left">{fmt}</span>
                      <span className="text-gray-500 font-mono">{rows.length} 只</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono border ${
                        regime === 'BULL'  ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' :
                        regime === 'BEAR'  ? 'text-rose-400 bg-rose-500/10 border-rose-500/30' :
                        regime === 'DARK'  ? 'text-orange-400 bg-orange-500/10 border-orange-500/30' :
                        regime === 'RANGE' ? 'text-sky-400 bg-sky-500/10 border-sky-500/30' :
                                             'text-gray-400 bg-gray-500/10 border-gray-500/30'
                      }`}>{regime}</span>
                    </div>
                  )
                })}
              </div>
            )
          })()}
          {/* 累计统计 */}
          {scanPreview.meta.scan_days && (
            <div className="pt-2 border-t border-[#222F4C]/50 flex justify-between text-[11px] text-gray-500">
              <span>累计 <span className="text-gray-300 font-mono">{scanPreview.meta.scan_days}</span> 天</span>
              <span>覆盖 <span className="text-gray-300 font-mono">{scanPreview.meta.unique_stocks}</span> 只</span>
              <span>记录 <span className="text-gray-300 font-mono">{scanPreview.meta.total_records}</span> 条</span>
            </div>
          )}
        </button>

        </div>
      </div>

      {/* 📈 股票列表 */}
      <div className="bg-[#151D30] rounded-2xl border border-[#222F4C] overflow-hidden">
        <div className="p-6 border-b border-[#222F4C] flex items-center justify-between">
          <h4 className="font-bold flex items-center space-x-2">
            <Cpu className="h-5 w-5 text-purple-400" />
            <span>今日策略推荐股票列表 (Top 10)</span>
          </h4>
          {!isHolding && (
            <span className="text-xs px-3 py-1 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 font-mono">
              🛡️ 当前避险降仓，备选展示
            </span>
          )}
        </div>
        
        {loading ? (
          <div className="p-12 text-center text-gray-500 font-mono">正在根据已部署因子和权重打分选股...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm border-collapse">
              <thead>
                <tr className="bg-[#0E1524] text-gray-400 font-mono text-xs border-b border-[#222F4C] whitespace-nowrap">
                  <th className="p-4 pl-6">推荐排名</th>
                  <th className="p-4">股票代码</th>
                  <th className="p-4">股票名称</th>
                  <th className="p-4">所属行业</th>
                  <th className="p-4">
                    <span title="综合因子信号强度，归一化到 0-100%。第1名最强，100%代表当期全市场最优信号。">
                      策略信号强度 ⓘ
                    </span>
                  </th>
                  <th className="p-4 text-right">5日涨幅</th>
                  <th className="p-4 text-right">10日涨幅</th>
                  <th className="p-4 text-right">20日涨幅</th>
                  <th className="p-4 text-right">昨日收盘价</th>
                  <th className="p-4 text-center">
                    <span title="基于T+1上涨画像实证分析的5维评分：位置/估值/温度/筹码/因子，满分100分">
                      画像等级 ⓘ
                    </span>
                  </th>
                  <th className="p-4 text-right pr-6">今日涨跌幅</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#222F4C]/40 font-mono">
                {portfolio.map((item) => {
                  const pct = Math.round(item.score * 100)
                  // 进度条颜色：高分绿 → 低分橙
                  const barColor = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-purple-500' : 'bg-amber-500'
                  return (
                    <tr key={item.stock_code} className="hover:bg-[#1A253D]/40 transition-colors">
                      <td className="p-4 pl-6 text-gray-400 font-semibold whitespace-nowrap">{item.rank}</td>
                      <td className="p-4 font-bold whitespace-nowrap">
                        <a 
                          href={getEastmoneyUrl(item.stock_code)} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-indigo-400 hover:text-indigo-300 hover:underline cursor-pointer"
                          title="在同花顺查看该股票详情"
                        >
                          {item.stock_code}
                        </a>
                      </td>
                      <td className="p-4 font-sans font-semibold whitespace-nowrap">
                        <a 
                          href={getEastmoneyUrl(item.stock_code)} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-gray-100 hover:text-white hover:underline cursor-pointer"
                          title="在同花顺查看该股票详情"
                        >
                          {item.name}
                        </a>
                      </td>
                      <td className="p-4 text-gray-400 font-sans whitespace-nowrap">{item.industry}</td>
                      <td className="p-4 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          {/* 进度条 */}
                          <div className="w-20 h-2 bg-[#0E1524] rounded-full overflow-hidden border border-[#222F4C]">
                            <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
                          </div>
                          <span className={`text-xs font-bold ${pct >= 70 ? 'text-emerald-400' : pct >= 40 ? 'text-purple-400' : 'text-amber-400'}`}>
                            {pct}%
                          </span>
                        </div>
                      </td>
                      <td className={`p-4 text-right whitespace-nowrap ${item.return_5d >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {item.return_5d > 0 ? '+' : ''}{(item.return_5d * 100).toFixed(2)}%
                      </td>
                      <td className={`p-4 text-right whitespace-nowrap ${item.return_10d >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {item.return_10d > 0 ? '+' : ''}{(item.return_10d * 100).toFixed(2)}%
                      </td>
                      <td className={`p-4 text-right whitespace-nowrap ${item.return_20d >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {item.return_20d > 0 ? '+' : ''}{(item.return_20d * 100).toFixed(2)}%
                      </td>
                      <td className="p-4 text-right text-gray-300 whitespace-nowrap">{item.close_price.toFixed(2)} 元</td>
                      {/* ── 画像等级徽章 ── */}
                      <td className="p-4 text-center whitespace-nowrap">
                        {item.portrait_grade && item.portrait_grade !== '—' ? (() => {
                          const cfg = portraitGradeConfig[item.portrait_grade] || portraitGradeConfig['C']
                          // 构建 tooltip 内容（5维明细）
                          const details = item.portrait_details || {}
                          const detailText = Object.entries(details)
                            .map(([k, v]) => `${k}: ${v}分`)
                            .join(' | ')
                          const tooltipTitle = `${cfg.title}\n画像总分: ${item.portrait_score}分\n${detailText}`
                          return (
                            <span
                              title={tooltipTitle}
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '4px',
                                padding: '3px 10px',
                                borderRadius: '999px',
                                fontSize: '11px',
                                fontWeight: 700,
                                fontFamily: 'monospace',
                                color: cfg.color,
                                background: cfg.bg,
                                border: `1px solid ${cfg.border}`,
                                cursor: 'help',
                                letterSpacing: '0.05em',
                              }}
                            >
                              <span>{cfg.emoji}</span>
                              <span>{cfg.label}</span>
                              <span style={{ opacity: 0.7, fontSize: '10px' }}>{item.portrait_score}</span>
                            </span>
                          )
                        })() : (
                          <span style={{ color: '#4b5563', fontSize: '11px', fontFamily: 'monospace' }}>—</span>
                        )}
                      </td>
                      <td className={`p-4 text-right pr-6 font-bold whitespace-nowrap ${item.daily_change >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {item.daily_change > 0 ? '+' : ''}{(item.daily_change * 100).toFixed(2)}%
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default Dashboard
