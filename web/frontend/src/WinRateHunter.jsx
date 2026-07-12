import React, { useState, useEffect } from 'react'
import { Rocket, History, RefreshCw, Crosshair, Terminal } from 'lucide-react'

export default function WinRateHunter({ upsertToast, removeToast, pollTask }) {
  const [params, setParams] = useState({
    start: '20260101',
    end: '20260703',
    generations: 5,
    population: 20
  })
  
  const [isStarted, setIsStarted] = useState(false)
  const [hunterResult, setHunterResult] = useState(null)
  const [portfolio, setPortfolio] = useState(null)
  const [loadingResult, setLoadingResult] = useState(false)

  const fetchResult = async () => {
    setLoadingResult(true)
    try {
      const [res1, res2] = await Promise.all([
        fetch('http://localhost:8000/api/hunter/result'),
        fetch('http://localhost:8000/api/portfolio')
      ])
      
      if (res1.ok) {
        const data1 = await res1.json()
        if (!data1.error) setHunterResult(data1)
      }
      if (res2.ok) {
        const data2 = await res2.json()
        setPortfolio(data2)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoadingResult(false)
    }
  }

  useEffect(() => {
    fetchResult()
  }, [])

  const handleRun = async () => {
    const toastId = `hunter-${Date.now()}`
    upsertToast(toastId, 'pending', '🧬 正在启动胜率猎手遗传算法引擎...')
    setIsStarted(true)
    try {
      const res = await fetch('/api/hunter/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      upsertToast(toastId, 'pending', `🧬 ${data.message}`)
      pollTask(toastId, data.task_id)
      setTimeout(() => setIsStarted(false), 5000)
    } catch (e) {
      upsertToast(toastId, 'error', `❌ 启动失败: ${e.message}`)
      setTimeout(() => removeToast(toastId), 6000)
      setIsStarted(false)
    }
  }

  return (
    <div className="space-y-6 max-w-4xl mx-auto pb-10">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-rose-400 to-fuchsia-500 flex items-center gap-2">
            <Crosshair className="h-6 w-6 text-rose-400" />
            胜率猎手 (Win Rate Hunter)
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            基于达尔文遗传算法的深度参数寻优引擎。在多维参数空间中搜寻绝对胜率最高的策略基因。
          </p>
        </div>
        <button 
          onClick={fetchResult}
          className="flex items-center gap-2 px-4 py-2 bg-[#111827] border border-[#374151] hover:border-gray-500 rounded-lg text-sm text-gray-300 transition-all"
        >
          <RefreshCw className={`h-4 w-4 ${loadingResult ? 'animate-spin' : ''}`} />
          刷新最新结论
        </button>
      </div>

      {/* 结论展示面板 */}
      {hunterResult && (
        <div className="bg-gradient-to-br from-[#0f172a] to-[#1e1b4b] rounded-2xl border border-indigo-500/30 p-6 shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 right-0 -mt-4 -mr-4 text-indigo-500/10">
            <Crosshair className="w-48 h-48" />
          </div>
          <div className="relative z-10">
            <div className="flex items-center gap-3 mb-6">
              <span className="text-2xl">🏆</span>
              <h3 className="text-lg font-bold text-indigo-100 tracking-wide">
                全局最优进化基因 <span className="text-xs font-normal text-indigo-300/70 ml-2 font-mono">结论产出于 {hunterResult.timestamp}</span>
              </h3>
            </div>
            
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-black/20 rounded-xl border border-white/5 p-4 flex flex-col gap-1">
                <span className="text-xs text-indigo-300/70 uppercase tracking-wider font-semibold">历史绝对胜率</span>
                <span className="text-2xl font-bold text-emerald-400 font-mono">{hunterResult.best_win_rate}%</span>
              </div>
              <div className="bg-black/20 rounded-xl border border-white/5 p-4 flex flex-col gap-1">
                <span className="text-xs text-indigo-300/70 uppercase tracking-wider font-semibold">超额卡玛比率</span>
                <span className="text-2xl font-bold text-amber-400 font-mono">{hunterResult.best_calmar}</span>
              </div>
              <div className="bg-black/20 rounded-xl border border-white/5 p-4 flex flex-col gap-1">
                <span className="text-xs text-indigo-300/70 uppercase tracking-wider font-semibold">最优持仓数量</span>
                <span className="text-2xl font-bold text-white font-mono">{hunterResult.best_params.top_n_stocks} 只</span>
              </div>
              <div className="bg-black/20 rounded-xl border border-white/5 p-4 flex flex-col gap-1">
                <span className="text-xs text-indigo-300/70 uppercase tracking-wider font-semibold">最优因子乘数</span>
                <span className="text-2xl font-bold text-white font-mono">{hunterResult.best_params.multiplier}x</span>
              </div>
            </div>
            
            <div className="mt-5 text-xs text-indigo-200/50 flex gap-4">
              <span>寻优区间: {hunterResult.start} - {hunterResult.end}</span>
              <span>种群/代数: {hunterResult.population} / {hunterResult.generations}</span>
              <span className="text-emerald-400/70 ml-auto">已自动应用至内核配置 ✓</span>
            </div>
            
            {/* 动态展示被选出的股票池 */}
            {portfolio && portfolio.length > 0 && (
              <div className="mt-8 border-t border-white/10 pt-6">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></div>
                  <h4 className="text-sm font-bold text-white tracking-wide">实盘应用：基于最优基因的实时选股 ({portfolio.length}只)</h4>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm text-gray-300">
                    <thead className="text-xs text-indigo-300/70 bg-white/5 font-mono">
                      <tr>
                        <th className="px-4 py-3 rounded-tl-lg">排名</th>
                        <th className="px-4 py-3">代码</th>
                        <th className="px-4 py-3">名称</th>
                        <th className="px-4 py-3">版块/行业</th>
                        <th className="px-4 py-3 text-right">综合得分</th>
                        <th className="px-4 py-3 text-right">5日</th>
                        <th className="px-4 py-3 text-right">10日</th>
                        <th className="px-4 py-3 text-right">20日</th>
                        <th className="px-4 py-3 text-right rounded-tr-lg">今日涨幅</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {portfolio.map((s, idx) => (
                        <tr key={idx} className="hover:bg-white/5 transition-colors">
                          <td className="px-4 py-3 font-mono text-emerald-400 font-bold">#{s.rank}</td>
                          <td className="px-4 py-3 font-mono">
                            <a 
                              href={`http://stockpage.10jqka.com.cn/${s.stock_code.substring(0, 6)}/`} 
                              target="_blank" 
                              rel="noopener noreferrer"
                              className="text-indigo-400 hover:text-indigo-300 hover:underline cursor-pointer"
                              title="在同花顺查看该股票详情"
                            >
                              {s.stock_code}
                            </a>
                          </td>
                          <td className="px-4 py-3 font-bold">
                            <a 
                              href={`http://stockpage.10jqka.com.cn/${s.stock_code.substring(0, 6)}/`} 
                              target="_blank" 
                              rel="noopener noreferrer"
                              className="text-white hover:text-indigo-200 hover:underline cursor-pointer"
                              title="在同花顺查看该股票详情"
                            >
                              {s.name}
                            </a>
                          </td>
                          <td className="px-4 py-3 text-xs">{s.industry}</td>
                          <td className="px-4 py-3 text-right font-mono">{s.score.toFixed(4)}</td>
                          <td className={`px-4 py-3 text-right font-mono ${s.return_5d >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                            {s.return_5d > 0 ? '+' : ''}{(s.return_5d * 100).toFixed(2)}%
                          </td>
                          <td className={`px-4 py-3 text-right font-mono ${s.return_10d >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                            {s.return_10d > 0 ? '+' : ''}{(s.return_10d * 100).toFixed(2)}%
                          </td>
                          <td className={`px-4 py-3 text-right font-mono ${s.return_20d >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                            {s.return_20d > 0 ? '+' : ''}{(s.return_20d * 100).toFixed(2)}%
                          </td>
                          <td className={`px-4 py-3 text-right font-mono font-bold ${s.daily_change >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                            {s.daily_change > 0 ? '+' : ''}{(s.daily_change * 100).toFixed(2)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

          </div>
        </div>
      )}

      {/* 控制面板 */}
      <div className="bg-[#111827] rounded-2xl border border-[#1F2937] p-6 shadow-xl">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div className="space-y-2">
            <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">起始日期</label>
            <input 
              type="text" 
              value={params.start}
              onChange={e => setParams({...params, start: e.target.value})}
              className="w-full bg-[#0D1220] border border-[#374151] rounded-lg px-4 py-2.5 text-sm text-gray-100 focus:ring-2 focus:ring-rose-500/50 outline-none transition-all"
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">结束日期</label>
            <input 
              type="text" 
              value={params.end}
              onChange={e => setParams({...params, end: e.target.value})}
              className="w-full bg-[#0D1220] border border-[#374151] rounded-lg px-4 py-2.5 text-sm text-gray-100 focus:ring-2 focus:ring-rose-500/50 outline-none transition-all"
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">进化代数</label>
            <input 
              type="number" 
              value={params.generations}
              onChange={e => setParams({...params, generations: Number(e.target.value)})}
              className="w-full bg-[#0D1220] border border-[#374151] rounded-lg px-4 py-2.5 text-sm text-gray-100 focus:ring-2 focus:ring-rose-500/50 outline-none transition-all"
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider">种群规模</label>
            <input 
              type="number" 
              value={params.population}
              onChange={e => setParams({...params, population: Number(e.target.value)})}
              className="w-full bg-[#0D1220] border border-[#374151] rounded-lg px-4 py-2.5 text-sm text-gray-100 focus:ring-2 focus:ring-rose-500/50 outline-none transition-all"
            />
          </div>
        </div>

        <div className="mt-8 flex justify-end">
          <button 
            onClick={handleRun}
            disabled={isStarted}
            className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-rose-600 to-fuchsia-600 hover:from-rose-500 hover:to-fuchsia-500 text-white rounded-xl font-medium transition-all shadow-lg shadow-rose-500/25 active:scale-95 disabled:opacity-50"
          >
            {isStarted ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
            <span>{isStarted ? '引擎已点火' : '启动达尔文进化'}</span>
          </button>
        </div>
      </div>

      {/* 说明 */}
      <div className="bg-[#111827]/50 rounded-2xl border border-[#1F2937] p-6 text-sm text-gray-400 leading-relaxed">
        <h3 className="text-gray-200 font-semibold mb-3 flex items-center gap-2">
          <Terminal className="h-4 w-4 text-purple-400" />
          运行机制说明
        </h3>
        <ul className="list-disc list-inside space-y-2 ml-1">
          <li>胜率猎手在后台运行期间，不会阻塞其他页面的监控与浏览。</li>
          <li>系统会通过全局 Toast 气泡实时跟进任务状态（执行中、成功或失败）。</li>
          <li>每一次执行会涉及 <span className="font-mono text-rose-300 bg-rose-500/10 px-1 rounded">generations × population</span> 次横截面回测，请耐心等待。</li>
          <li>当进化完成后，胜出者的基因（参数组合）将被系统<strong className="text-emerald-400">自动采纳</strong>并写入底层架构中，所有模型将会热更新。</li>
        </ul>
      </div>
    </div>
  )
}
