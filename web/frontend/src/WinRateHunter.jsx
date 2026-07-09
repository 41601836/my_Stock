import React, { useState } from 'react'
import { Rocket, History, RefreshCw, Crosshair, Terminal } from 'lucide-react'

export default function WinRateHunter({ upsertToast, removeToast, pollTask }) {
  const [params, setParams] = useState({
    start: '20260101',
    end: '20260703',
    generations: 5,
    population: 20
  })
  
  const [isStarted, setIsStarted] = useState(false)

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
      </div>

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
