import React, { useState, useEffect } from 'react'
import { HelpCircle, RefreshCw, BarChart } from 'lucide-react'

function Factors() {
  const [factorsData, setFactorsData] = useState({ range_factors: [], bull_factors: [] })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/factors')
      .then(res => res.json())
      .then(data => {
        setFactorsData(data)
        setLoading(false)
      })
      .catch(err => {
        console.error(err)
        setLoading(false)
      })
  }, [])

  const renderFactorBars = (factors) => {
    if (factors.length === 0) {
      return <div className="text-gray-500 text-xs font-mono p-4">暂无配置数据</div>
    }
    
    return (
      <div className="space-y-4">
        {factors.map((item) => {
          const val = item.weight
          const isPositive = val >= 0
          const absPct = Math.min(100, Math.abs(val) * 150) // 放大幅度用于展示
          
          return (
            <div key={item.factor} className="space-y-1">
              <div className="flex justify-between text-xs font-mono">
                <span className="text-gray-300 font-semibold">{item.factor}</span>
                <span className={isPositive ? 'text-emerald-400 font-bold' : 'text-indigo-400 font-bold'}>
                  {isPositive ? '+' : ''}{val.toFixed(4)}
                </span>
              </div>
              
              {/* 条形条 */}
              <div className="h-3 w-full bg-[#0E1524] rounded-full overflow-hidden border border-[#222F4C] flex">
                {isPositive ? (
                  <>
                    <div className="w-1/2"></div>
                    <div className="w-1/2 flex justify-start">
                      <div 
                        className="bg-emerald-500/80 rounded-r-full" 
                        style={{ width: `${absPct}%` }}
                      ></div>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="w-1/2 flex justify-end">
                      <div 
                        className="bg-indigo-400/80 rounded-l-full" 
                        style={{ width: `${absPct}%` }}
                      ></div>
                    </div>
                    <div className="w-1/2"></div>
                  </>
                )}
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* 🧭 双模型因子并列网格 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Range 核心模型 */}
        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-6">
          <div className="flex items-center justify-between border-b border-[#222F4C]/60 pb-4">
            <h4 className="font-bold font-sans flex items-center space-x-2 text-gray-200">
              <BarChart className="h-5 w-5 text-emerald-400" />
              <span>Range 震荡市因子分配权重 (已部署)</span>
            </h4>
            <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
              models/regime_weights.pkl
            </span>
          </div>
          
          {loading ? (
            <div className="text-center font-mono text-gray-500 py-12">读取因子配置中...</div>
          ) : (
            renderFactorBars(factorsData.range_factors)
          )}
        </div>

        {/* Bull 专轨模型 */}
        <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-6">
          <div className="flex items-center justify-between border-b border-[#222F4C]/60 pb-4">
            <h4 className="font-bold font-sans flex items-center space-x-2 text-gray-200">
              <BarChart className="h-5 w-5 text-indigo-400" />
              <span>Bull 牛市专轨因子分配权重 (已部署)</span>
            </h4>
            <span className="text-[10px] px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-mono">
              models/bull_weights_proposed.pkl
            </span>
          </div>

          {loading ? (
            <div className="text-center font-mono text-gray-500 py-12">读取因子配置中...</div>
          ) : (
            renderFactorBars(factorsData.bull_factors)
          )}
        </div>
      </div>

      {/* 💡 因子自适应与翻转原理说明 */}
      <div className="p-6 bg-[#151D30] rounded-2xl border border-[#222F4C] space-y-4">
        <h4 className="font-bold font-sans flex items-center space-x-2 text-gray-200">
          <HelpCircle className="h-5 w-5 text-purple-400" />
          <span>控制台因子与权重规则指南</span>
        </h4>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs text-gray-400 leading-relaxed font-sans">
          <div className="space-y-1">
            <h5 className="font-semibold text-gray-300">1. 因子方向自动翻转</h5>
            <p>
              若因子的 Rank IC 为负值，Agent 打分系统在运行调仓打分时，将自动对其取负，确保最终融合信号方向统一为「值越高，预期收益越高」。
            </p>
          </div>
          <div className="space-y-1">
            <h5 className="font-semibold text-gray-300">2. 特权加成因子</h5>
            <p>
              北向资金流 `north_net_inflow_ratio` 及 `profit_ratio_estimate` 等已被初筛为高Alpha正交特权因子，分配权重时自动施加了 multiplier (当前 1.5 倍) 放大系数以倾斜暴露。
            </p>
          </div>
          <div className="space-y-1">
            <h5 className="font-semibold text-gray-300">3. 动态状态路由</h5>
            <p>
              每一周调仓日，路由系统会智能测算当前状态。若是 Range 或 Bull 选用对应的条形图模型进行截面个股 rankpct 打分；若是 Dark / Bear 则跳过打分直接触发半仓基准跟踪避灾。
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Factors
