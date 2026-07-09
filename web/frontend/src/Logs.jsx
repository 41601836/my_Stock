import React, { useState, useEffect } from 'react'
import { Terminal, Zap, CheckCircle, Clock, ChevronRight } from 'lucide-react'

function Logs() {
  const [agentData, setAgentData] = useState({ 
    status: 'IDLE', 
    recent_logs: [], 
    trajectory: [], 
    last_updated: '',
    best_results: {
      success: false,
      best_combination: '—',
      best_params: '—',
      best_excess_calmar: 0.0
    }
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/agent')
      .then(res => res.json())
      .then(data => {
        setAgentData(data)
        setLoading(false)
      })
      .catch(err => {
        console.error(err)
        setLoading(false)
      })
  }, [])

  return (
    <div className="space-y-6">
      {/* 系统状态横幅 */}
      <div className="p-5 bg-[#151D30] rounded-2xl border border-[#222F4C] flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30">
            <CheckCircle className="h-6 w-6 text-emerald-400" />
          </div>
          <div>
            <h4 className="font-bold text-gray-200 font-sans">Agent 自主进化巡航系统</h4>
            <p className="text-xs text-gray-400 font-mono mt-0.5">{agentData.status}</p>
          </div>
        </div>
        <div className="text-right text-xs text-gray-500 font-mono">
          <div className="flex items-center space-x-1 justify-end">
            <Clock className="h-3.5 w-3.5" />
            <span>最后更新: {agentData.last_updated}</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* 🧬 进化轨迹记录表 */}
        <div className="bg-[#151D30] rounded-2xl border border-[#222F4C] overflow-hidden">
          <div className="p-5 border-b border-[#222F4C] flex items-center space-x-2">
            <Zap className="h-5 w-5 text-yellow-400" />
            <h4 className="font-bold text-gray-200 font-sans">进化寻优轨迹 (最近 10 次网格测试)</h4>
          </div>
          {loading ? (
            <div className="p-8 text-center text-gray-500 font-mono text-xs">加载轨迹中...</div>
          ) : agentData.trajectory.length === 0 ? (
            <div className="p-8 text-center text-gray-500 font-mono text-xs">暂无寻优轨迹记录</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left font-mono border-collapse">
                <thead>
                  <tr className="bg-[#0E1524] text-gray-400 border-b border-[#222F4C]">
                    <th className="p-3 pl-5">组合 #</th>
                    <th className="p-3">top_n</th>
                    <th className="p-3">mult</th>
                    <th className="p-3 text-right pr-5">超额卡玛</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#222F4C]/40">
                  {agentData.trajectory.map((item, idx) => (
                    <tr key={idx} className={`hover:bg-[#1A253D]/40 transition-colors ${item.excess_calmar_ratio >= 0.5 ? 'bg-emerald-500/5' : ''}`}>
                      <td className="p-3 pl-5 text-gray-300">{item.combo_index}</td>
                      <td className="p-3 text-gray-300">{item.tested_params?.top_n}</td>
                      <td className="p-3 text-gray-300">{item.tested_params?.multiplier}</td>
                      <td className={`p-3 text-right pr-5 font-bold ${item.excess_calmar_ratio >= 0.5 ? 'text-emerald-400' : 'text-gray-400'}`}>
                        {item.excess_calmar_ratio >= 0.5 && <span className="mr-1">✓</span>}
                        {item.excess_calmar_ratio?.toFixed(4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* 🖥️ 系统日志控制台 */}
        <div className="bg-[#0B0F19] rounded-2xl border border-[#222F4C] overflow-hidden flex flex-col">
          <div className="p-5 border-b border-[#222F4C] flex items-center space-x-2 bg-[#111827]">
            <Terminal className="h-5 w-5 text-purple-400" />
            <h4 className="font-bold text-gray-200 font-sans">系统运行日志 (最近 15 条)</h4>
          </div>
          <div className="flex-1 p-4 overflow-y-auto font-mono text-xs text-gray-300 leading-relaxed space-y-0.5 bg-[#0B0F19]">
            {loading ? (
              <p className="text-gray-500">加载日志流中...</p>
            ) : agentData.recent_logs.length === 0 ? (
              <p className="text-gray-500">暂无日志记录</p>
            ) : (
              agentData.recent_logs.map((line, idx) => (
                <div key={idx} className="flex items-start space-x-2 hover:bg-[#151D30]/40 px-1 py-0.5 rounded">
                  <ChevronRight className="h-3 w-3 text-purple-500 mt-0.5 flex-shrink-0" />
                  <span className={
                    line.includes('✅') || line.includes('🔥') || line.includes('🎉') ? 'text-emerald-400' :
                    line.includes('⚠️') || line.includes('⚖️') ? 'text-yellow-400' :
                    line.includes('❌') || line.includes('Error') ? 'text-rose-400' :
                    line.includes('ℹ️') ? 'text-blue-300' : 'text-gray-400'
                  }>{line}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* 进化最佳结果横幅 */}
      <div className="p-6 bg-gradient-to-r from-purple-900/30 to-indigo-900/30 rounded-2xl border border-purple-500/30 space-y-3">
        <div className="flex items-center space-x-3">
          <Zap className="h-5 w-5 text-yellow-400" />
          <h4 className="font-bold text-gray-100 font-sans">🎉 本轮进化巡航最终战果</h4>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs font-mono">
          <div className="p-4 bg-[#0D1220]/60 rounded-xl border border-purple-500/20 space-y-1.5">
            <span className="text-gray-400">✅ 达标组合</span>
            <div className="text-emerald-400 font-bold leading-relaxed">
              {agentData.best_results?.best_combination || '—'}
            </div>
          </div>
          <div className="p-4 bg-[#0D1220]/60 rounded-xl border border-purple-500/20 space-y-1.5">
            <span className="text-gray-400">⚙️ 最佳超参配置</span>
            <div className="text-purple-400 font-bold">
              {agentData.best_results?.best_params || '—'}
            </div>
          </div>
          <div className="p-4 bg-[#0D1220]/60 rounded-xl border border-purple-500/20 space-y-1.5">
            <span className="text-gray-400">📈 最高超额卡玛</span>
            <div className="text-yellow-400 font-bold text-2xl">
              {agentData.best_results?.best_excess_calmar?.toFixed(4) || '0.0000'}
            </div>
            <div className="text-gray-500">超额卡玛指数组合评分表现优秀</div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Logs
