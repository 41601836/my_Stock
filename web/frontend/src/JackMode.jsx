import React, { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { Flame, ShieldAlert, Award, Star, Activity, ArrowUpRight, ArrowDownRight, Calendar, User, MessageSquare } from 'lucide-react'



function JackMode() {
  const [data, setData] = useState([])
  const [metrics, setMetrics] = useState({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/jack-performance')
      .then(res => res.json())
      .then(res => {
        setData(res.chart_data)
        setMetrics(res.metrics)
        setLoading(false)
      })
      .catch(err => {
        console.error(err)
        setLoading(false)
      })
  }, [])

  return (
    <div className="space-y-8" id="jack-mode-view">
      {/* 🔮 游资自适应路由业绩看板 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        <div className="p-6 bg-[#151D30]/80 backdrop-blur-md rounded-2xl border border-[#222F4C] hover:border-purple-500/40 transition-all duration-300 space-y-1">
          <span className="text-xs text-gray-400 font-mono">年化绝对收益</span>
          <div className="text-2xl font-bold font-mono text-emerald-400 flex items-center">
            <Award className="h-5 w-5 mr-1.5 text-emerald-400 animate-pulse" />
            <span>{metrics.portfolio_ann_return || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono block">累计净收益: {metrics.portfolio_total_return || '0.00%'}</span>
        </div>

        <div className="p-6 bg-[#151D30]/80 backdrop-blur-md rounded-2xl border border-[#222F4C] hover:border-purple-500/40 transition-all duration-300 space-y-1">
          <span className="text-xs text-gray-400 font-mono">绝对最大回撤</span>
          <div className="text-2xl font-bold font-mono text-rose-400 flex items-center">
            <ShieldAlert className="h-5 w-5 mr-1.5 text-rose-400" />
            <span>{metrics.portfolio_max_drawdown || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono block">绝对卡玛比率: {metrics.portfolio_calmar || '0.00'}</span>
        </div>

        <div className="p-6 bg-[#151D30]/80 backdrop-blur-md rounded-2xl border border-[#222F4C] hover:border-purple-500/40 transition-all duration-300 space-y-1">
          <span className="text-xs text-gray-400 font-mono">年化超额收益 (Alpha)</span>
          <div className="text-2xl font-bold font-mono text-purple-400 flex items-center">
            <Star className="h-5 w-5 mr-1.5 text-purple-400" />
            <span>{metrics.excess_ann_return || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono block">超额总收益: {metrics.excess_total_return || '0.00%'}</span>
        </div>

        <div className="p-6 bg-[#151D30]/80 backdrop-blur-md rounded-2xl border border-[#222F4C] hover:border-purple-500/40 transition-all duration-300 space-y-1">
          <span className="text-xs text-gray-400 font-mono">超额最大回撤与卡玛</span>
          <div className="text-2xl font-bold font-mono text-purple-300 flex items-center">
            <Activity className="h-5 w-5 mr-1.5 text-purple-300" />
            <span>{metrics.excess_max_drawdown || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono block">超额卡玛比率: {metrics.excess_calmar || '0.00'}</span>
        </div>
      </div>

      {/* 📈 散户/游资风格模拟曲线 (Recharts) */}
      <div className="p-6 bg-[#151D30]/60 backdrop-blur-md rounded-2xl border border-[#222F4C] space-y-4">
        <div className="flex items-center justify-between">
          <h4 className="font-bold text-gray-100 font-sans flex items-center space-x-2">
            <Flame className="h-5 w-5 text-purple-400 animate-bounce" />
            <span>散户/游资风格自适应路由累计净值走势 (组合 vs 基准 vs 超额 Alpha)</span>
          </h4>
          <span className="text-xs text-gray-500 font-mono">回测周期: {metrics.total_weeks || 0} 周 (最近 52 周)</span>
        </div>

        {loading ? (
          <div className="h-96 flex items-center justify-center text-gray-500 font-mono">加载时序数据中...</div>
        ) : (
          <div className="h-96 w-full font-mono text-xs">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data}
                margin={{ top: 10, right: 20, left: 0, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#222F4C" />
                <XAxis dataKey="date" stroke="#9CA3AF" tickLine={false} />
                <YAxis stroke="#9CA3AF" tickLine={false} domain={['auto', 'auto']} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#151D30', borderColor: '#222F4C', color: '#fff' }}
                  labelStyle={{ fontWeight: 'bold' }}
                />
                <Legend verticalAlign="top" height={36} />
                <Line
                  name="游资组合绝对净值 (Portfolio)"
                  type="monotone"
                  dataKey="portfolio"
                  stroke="#10B981"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 6 }}
                />
                <Line
                  name="等权大盘基准净值 (Benchmark)"
                  type="monotone"
                  dataKey="benchmark"
                  stroke="#9CA3AF"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  dot={false}
                />
                <Line
                  name="游资组合超额净值 (Excess Alpha)"
                  type="monotone"
                  dataKey="excess"
                  stroke="#A855F7"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 6 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* 🛡️ 诊断与反思说明 */}
      <div className="p-6 bg-[#181127]/40 rounded-2xl border border-purple-900/30 grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
        <div className="space-y-2">
          <h4 className="font-bold text-gray-200 text-sm flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-purple-400" />
            <span>游资回测诊断：为何长期业绩跑输基准？</span>
          </h4>
          <p className="text-xs text-gray-400 leading-relaxed font-sans">
            该策略高度模拟散户在“牛市追强动量，震荡市抄底，熊市主观空仓”的习惯。
            数据表明，在缺乏基本面支撑和贝塔平滑控制下，<strong>“无脑开盘集合竞价梭哈”</strong>极易在牛市中买在日内最高点（追高闷杀），并在阴跌中不断“接飞刀式左侧抄底”被套，加之每周全仓轮动产生高达 <strong>15.6%</strong> 的交易摩擦成本，严重蚕食了本金。
          </p>
        </div>
        <div className="p-4 bg-[#0F1424] rounded-xl border border-[#222F4C] space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-gray-400 font-mono">周绝对胜率:</span>
            <span className="font-bold font-mono text-emerald-400">{metrics.win_rate || '0.0%'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400 font-mono">周超额胜率:</span>
            <span className="font-bold font-mono text-purple-400">{metrics.ex_win_rate || '0.0%'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400 font-mono">每周全仓换手摩擦:</span>
            <span className="font-bold font-mono text-rose-400">双边 0.30% / 周</span>
          </div>
        </div>
      </div>


    </div>
  )
}

export default JackMode
