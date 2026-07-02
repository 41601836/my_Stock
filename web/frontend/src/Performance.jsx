import React, { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { Activity, ShieldAlert, Award, Star } from 'lucide-react'

function Performance() {
  const [data, setData] = useState([])
  const [metrics, setMetrics] = useState({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/performance')
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
    <div className="space-y-6">
      {/* 📊 指标卡片组 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-1">
          <span className="text-xs text-gray-400 font-mono">组合年化绝对收益</span>
          <div className="text-2xl font-bold font-mono text-emerald-400 flex items-center">
            <Award className="h-5 w-5 mr-1.5 text-emerald-400" />
            <span>{metrics.portfolio_ann_return || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono">累计收益: {metrics.portfolio_total_return || '0.00%'}</span>
        </div>

        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-1">
          <span className="text-xs text-gray-400 font-mono">组合绝对最大回撤</span>
          <div className="text-2xl font-bold font-mono text-rose-400 flex items-center">
            <ShieldAlert className="h-5 w-5 mr-1.5 text-rose-400" />
            <span>{metrics.portfolio_max_drawdown || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono">绝对卡玛: {metrics.portfolio_calmar || '0.00'}</span>
        </div>

        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-1">
          <span className="text-xs text-gray-400 font-mono">策略年化超额收益</span>
          <div className="text-2xl font-bold font-mono text-purple-400 flex items-center">
            <Star className="h-5 w-5 mr-1.5 text-purple-400" />
            <span>{metrics.excess_ann_return || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono">超额总收益: {metrics.excess_total_return || '0.00%'}</span>
        </div>

        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-1">
          <span className="text-xs text-gray-400 font-mono">超额最大回撤与卡玛</span>
          <div className="text-2xl font-bold font-mono text-purple-300 flex items-center">
            <Activity className="h-5 w-5 mr-1.5 text-purple-300" />
            <span>{metrics.excess_max_drawdown || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono">超额卡玛比率: {metrics.excess_calmar || '0.00'}</span>
        </div>
      </div>

      {/* 📈 三曲线图表 (Recharts) */}
      <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-4">
        <div className="flex items-center justify-between">
          <h4 className="font-bold text-gray-100 font-sans flex items-center space-x-2">
            <Activity className="h-5 w-5 text-purple-400" />
            <span>累计收益净值三曲线走势比对 (组合 vs 基准 vs 超额 Alpha)</span>
          </h4>
          <span className="text-xs text-gray-500 font-mono">回测周期: {metrics.total_weeks || 0} 周 (208周深度回测数据)</span>
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
                  name="组合绝对净值 (Portfolio)"
                  type="monotone"
                  dataKey="portfolio"
                  stroke="#10B981"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 6 }}
                />
                <Line
                  name="等权基准净值 (Benchmark)"
                  type="monotone"
                  dataKey="benchmark"
                  stroke="#9CA3AF"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  dot={false}
                />
                <Line
                  name="超额收益净值 (Excess Alpha)"
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

      {/* 🗺️ 三曲线状态占比与收益率辅助 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-3">
          <h4 className="font-bold font-sans text-sm text-gray-200">策略盈亏胜率指标</h4>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-[#0E1524] rounded-xl border border-[#222F4C] text-center">
              <span className="text-xs text-gray-400 font-mono">周绝对胜率</span>
              <div className="text-xl font-bold font-mono text-emerald-400 mt-1">{metrics.win_rate || '0.0%'}</div>
            </div>
            <div className="p-4 bg-[#0E1524] rounded-xl border border-[#222F4C] text-center">
              <span className="text-xs text-gray-400 font-mono">周超额胜率 (Alpha)</span>
              <div className="text-xl font-bold font-mono text-purple-400 mt-1">{metrics.ex_win_rate || '0.0%'}</div>
            </div>
          </div>
        </div>

        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-3">
          <h4 className="font-bold font-sans text-sm text-gray-200 font-sans">大跌止损风控效能</h4>
          <p className="text-xs text-gray-400 leading-relaxed font-sans">
            在回测时间轴内，策略对基准跌幅发生大震荡的交易周（基准跌超 5% 或 10%）施加了动态止损风控。这有效烫平了极端暴跌，保护了资金本金，使组合年化亏损大比例收缩，在弱势中凸显极强的生存防御效力。
          </p>
        </div>
      </div>
    </div>
  )
}

export default Performance
