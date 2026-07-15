import React, { useState, useEffect } from 'react'
import { Landmark, ArrowUpRight, ArrowDownRight, Compass, ShieldCheck, Cpu } from 'lucide-react'

function Dashboard({ marketStatus }) {
  const [portfolio, setPortfolio] = useState([])
  const [loading, setLoading] = useState(true)

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
  const avgChange = isHolding ? portfolio.reduce((acc, item) => acc + item.daily_change, 0) / portfolio.length : 0

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
                <tr className="bg-[#0E1524] text-gray-400 font-mono text-xs border-b border-[#222F4C]">
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
                      <td className="p-4 pl-6 text-gray-400 font-semibold">{item.rank}</td>
                      <td className="p-4 font-bold">
                        <a 
                          href={`http://stockpage.10jqka.com.cn/${item.stock_code.substring(0, 6)}/`} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-indigo-400 hover:text-indigo-300 hover:underline cursor-pointer"
                          title="在同花顺查看该股票详情"
                        >
                          {item.stock_code}
                        </a>
                      </td>
                      <td className="p-4 font-sans font-semibold">
                        <a 
                          href={`http://stockpage.10jqka.com.cn/${item.stock_code.substring(0, 6)}/`} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-gray-100 hover:text-white hover:underline cursor-pointer"
                          title="在同花顺查看该股票详情"
                        >
                          {item.name}
                        </a>
                      </td>
                      <td className="p-4 text-gray-400 font-sans">{item.industry}</td>
                      <td className="p-4">
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
                      <td className={`p-4 text-right ${item.return_5d >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {item.return_5d > 0 ? '+' : ''}{(item.return_5d * 100).toFixed(2)}%
                      </td>
                      <td className={`p-4 text-right ${item.return_10d >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {item.return_10d > 0 ? '+' : ''}{(item.return_10d * 100).toFixed(2)}%
                      </td>
                      <td className={`p-4 text-right ${item.return_20d >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                        {item.return_20d > 0 ? '+' : ''}{(item.return_20d * 100).toFixed(2)}%
                      </td>
                      <td className="p-4 text-right text-gray-300">{item.close_price.toFixed(2)} 元</td>
                      <td className={`p-4 text-right pr-6 font-bold ${item.daily_change >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
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
