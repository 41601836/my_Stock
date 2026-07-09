import React, { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { CheckCircle2, AlertTriangle, Play, RefreshCw, BarChart2, ShieldCheck, HelpCircle } from 'lucide-react'

export default function Diagnosis() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [adaptivePeriod, setAdaptivePeriod] = useState(20)

  const fetchAttribution = async () => {
    setLoading(true)
    try {
      const res = await fetch('http://localhost:8000/api/tracker/attribution')
      if (!res.ok) throw new Error('Failed to fetch attribution metrics')
      const json = await res.json()
      setData(json)
      
      const resPeriod = await fetch('http://localhost:8000/api/tracker/adaptive-period')
      if (resPeriod.ok) {
        const jsonPeriod = await resPeriod.json()
        setAdaptivePeriod(jsonPeriod.adaptive_period || 20)
      }
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAttribution()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <RefreshCw className="h-8 w-8 animate-spin text-purple-500" />
          <span className="text-sm font-mono">加载样本外归因诊断数据...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm font-mono">
        ❌ 错误: {error}
      </div>
    )
  }

  const formatPercent = (val) => {
    if (val === null || val === undefined) return '—'
    return `${val > 0 ? '+' : ''}${val.toFixed(2)}%`
  }

  // 格式化图表数据
  const chartData = data?.decay?.map(d => ({
    name: d.day,
    '全样本超额 (All)': parseFloat((d.alpha_all * 100).toFixed(3)),
    '高因子分超额 (High Score)': parseFloat((d.alpha_high_factor * 100).toFixed(3)),
    '低因子分超额 (Low Score)': parseFloat((d.alpha_low_factor * 100).toFixed(3)),
  })) || []

  return (
    <div className="space-y-6">
      
      {/* ── 动态自适应换仓决策卡 */}
      <div className="p-5 rounded-2xl bg-gradient-to-r from-emerald-500/10 to-teal-500/10 border border-emerald-500/30 flex items-center justify-between shadow-lg">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-emerald-500/20 rounded-xl border border-emerald-500/40 text-emerald-400">
            <CheckCircle2 className="h-6 w-6" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-gray-100">⏳ 策略前瞻自适应换仓决策反馈 (Adaptive Hold Period)</h3>
            <p className="text-xs text-gray-400 mt-1">系统正实时监控近 30 天样本外前瞻 IC 衰减。最新拟合结果显示当前因子 Alpha 在第 **{adaptivePeriod}** 个交易日见顶。</p>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-gray-500 font-mono">当前建议持有期</div>
          <div className="text-2xl font-bold font-mono text-emerald-400">{adaptivePeriod} 天</div>
        </div>
      </div>
      
      {/* ── 说明警告卡片 (防过拟合与幸存者偏差机制公示) */}
      {data?.is_mocked && (
        <div className="p-4 rounded-xl bg-purple-500/10 border border-purple-500/30 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-purple-400 shrink-0 mt-0.5" />
          <div className="text-xs space-y-1">
            <h4 className="font-bold text-purple-200">ℹ️ 仿真演示引导模式已开启</h4>
            <p className="text-purple-300">由于本地归因追踪表 (recommendation_tracker) 中已结算的数据量不足 (小于 5 日)，系统自动加载了由量化算法生成的 **前瞻对照组曲线**。</p>
            <p className="text-purple-400">系统数据将每日随着 Tushare 增量数据拉取和 scripts/tracker_updater.py 脚本的运行而逐步累积并自动切换为纯实盘数据。</p>
          </div>
        </div>
      )}

      {/* ── 核心图表与状态矩阵 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* 前瞻 IC 衰减线图 */}
        <div className="lg:col-span-2 p-6 rounded-xl bg-[#111827] border border-[#1F2937] space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-gray-100 flex items-center gap-2">
                📈 前瞻超额收益衰减曲线 (Forward Alpha Decay)
              </h3>
              <p className="text-xs text-gray-500 mt-1">展示个股推荐在建仓后第 1 至 20 个交易日的累计 Alpha 衰减，用以评估因子半衰期</p>
            </div>
            <span className="px-2.5 py-1 text-[10px] bg-slate-800 text-sky-400 font-bold border border-slate-700 rounded-full font-mono">
              滚动平滑: 30天 (防过拟合)
            </span>
          </div>

          <div className="h-[280px]">
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
                  <XAxis dataKey="name" stroke="#9CA3AF" fontSize={11} tickLine={false} />
                  <YAxis stroke="#9CA3AF" fontSize={11} tickLine={false} unit="%" />
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px' }} 
                    labelStyle={{ color: '#F3F4F6', fontWeight: 'bold', fontSize: 11 }}
                    itemStyle={{ fontSize: 11 }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11, paddingTop: 10 }} />
                  <Line type="monotone" dataKey="高因子分超额 (High Score)" stroke="#c084fc" strokeWidth={2.5} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                  <Line type="monotone" dataKey="全样本超额 (All)" stroke="#10b981" strokeWidth={2} strokeDasharray="5 5" dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="低因子分超额 (Low Score)" stroke="#ef4444" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-full text-gray-600 font-mono text-xs">暂无折线数据</div>
            )}
          </div>
        </div>

        {/* Regime 路由诊断矩阵 */}
        <div className="p-6 rounded-xl bg-[#111827] border border-[#1F2937] flex flex-col justify-between space-y-4">
          <div>
            <h3 className="text-sm font-bold text-gray-100 flex items-center gap-2">
              🧭 市场状态路由诊断矩阵 (Regime Diagnosis)
            </h3>
            <p className="text-xs text-gray-500 mt-1">评估策略大脑自适应路由机制在各阶段环境下的真实表现</p>
          </div>

          <div className="space-y-3 flex-1 justify-center flex flex-col">
            {data?.regime?.map((r, i) => {
              const colors = {
                BULL: { bg: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400', txt: 'text-emerald-300' },
                RANGE: { bg: 'bg-sky-500/10 border-sky-500/20 text-sky-400', txt: 'text-sky-300' },
                DARK: { bg: 'bg-rose-500/10 border-rose-500/20 text-rose-400', txt: 'text-rose-300' }
              }[r.regime] || { bg: 'bg-gray-800 border-gray-700 text-gray-400', txt: 'text-gray-400' }

              return (
                <div key={i} className={`p-4 rounded-xl border flex items-center justify-between ${colors.bg}`}>
                  <div className="space-y-1">
                    <span className="text-xs font-mono font-bold tracking-wider">{r.regime} 模式</span>
                    <div className="text-[10px] text-gray-500 font-mono">样本数: {r.count}</div>
                  </div>
                  <div className="text-right">
                    <div className={`text-sm font-mono font-bold ${colors.txt}`}>
                      Alpha-5D: {formatPercent(r.avg_alpha * 100)}
                    </div>
                    <div className="text-[10px] text-gray-500 font-mono">胜率: {(r.win_rate * 100).toFixed(1)}%</div>
                  </div>
                </div>
              )
            })}
          </div>

          <div className="p-3 rounded-lg bg-[#151d32] border border-slate-700/50 flex items-start gap-2">
            <ShieldCheck className="h-4 w-4 text-sky-400 shrink-0 mt-0.5" />
            <p className="text-[10px] text-gray-400 leading-relaxed">
              **防偏机制**：已强制启用退市惩罚（归零结算）与停牌冻结对齐。
            </p>
          </div>
        </div>

      </div>

      {/* ── 推荐明细列表表 */}
      <div className="p-6 rounded-xl bg-[#111827] border border-[#1F2937] space-y-4">
        <div>
          <h3 className="text-sm font-bold text-gray-100 flex items-center gap-2">
            📋 历史推荐建仓与样本外表现追踪 ( Attributed Tracking Details )
          </h3>
          <p className="text-xs text-gray-500 mt-1">展示最近 100 条历史推荐股在推荐发生那一刻的因子截面分与 5 日后真实表现对照</p>
        </div>

        <div className="overflow-x-auto max-h-[400px]">
          <table className="w-full text-left border-collapse font-mono text-xs">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 font-bold bg-slate-900/50">
                <th className="py-2.5 px-3">推荐日期</th>
                <th className="py-2.5 px-3">代码/名称</th>
                <th className="py-2.5 px-3">基准价(开盘)</th>
                <th className="py-2.5 px-3 text-center">状态</th>
                <th className="py-2.5 px-3 text-right">因子打分</th>
                <th className="py-2.5 px-3 text-right">筹码胜率</th>
                <th className="py-2.5 px-3 text-right">筹码集中</th>
                <th className="py-2.5 px-3 text-right">主力流入</th>
                <th className="py-2.5 px-3 text-right text-emerald-400">5D 绝对</th>
                <th className="py-2.5 px-3 text-right text-purple-400 font-bold">5D 超额 (Alpha)</th>
              </tr>
            </thead>
            <tbody>
              {data?.details?.length > 0 ? (
                data.details.map((d, i) => (
                  <tr key={i} className="border-b border-gray-900 hover:bg-[#1c2336]/40 transition-colors text-gray-300">
                    <td className="py-2.5 px-3 text-gray-500">{d.recommend_date}</td>
                    <td className="py-2.5 px-3 font-semibold text-gray-200">
                      <div>{d.ts_code}</div>
                      <div className="text-[10px] text-gray-500">{d.name} | {d.industry.split(' | ')[1] || d.industry}</div>
                    </td>
                    <td className="py-2.5 px-3 text-gray-400">{d.base_price !== null ? `${d.base_price.toFixed(2)}元` : '未结算'}</td>
                    <td className="py-2.5 px-3 text-center">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        d.regime === 'BULL' ? 'bg-emerald-500/10 text-emerald-400' :
                        d.regime === 'RANGE' ? 'bg-sky-500/10 text-sky-400' : 'bg-rose-500/10 text-rose-400'
                      }`}>{d.regime}</span>
                    </td>
                    <td className="py-2.5 px-3 text-right">{d.factor_score}%</td>
                    <td className="py-2.5 px-3 text-right">{d.winner_rate}%</td>
                    <td className="py-2.5 px-3 text-right">{d.chips_concentration}%</td>
                    <td className="py-2.5 px-3 text-right text-gray-400">{d.net_mf_amount > 0 ? `+${d.net_mf_amount}` : d.net_mf_amount}万</td>
                    <td className="py-2.5 px-3 text-right text-emerald-500">{formatPercent(d.ret_5d)}</td>
                    <td className="py-2.5 px-3 text-right text-purple-400 font-bold">{formatPercent(d.alpha_5d)}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan="10" className="py-8 text-center text-gray-600">暂无追踪记录，推荐生成并日终结算后在此展现。</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  )
}
