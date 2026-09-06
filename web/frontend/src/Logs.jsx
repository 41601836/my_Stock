import React, { useState, useEffect, useCallback } from 'react'
import { Terminal, Zap, CheckCircle, Clock, ChevronRight, AlertTriangle, Play, Square, RotateCcw } from 'lucide-react'

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
  const [actionLoading, setActionLoading] = useState(false)
  const [toast, setToast] = useState(null)

  const fetchAgentData = useCallback(() => {
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

  // 最高超额卡玛判定：文案与颜色严格跟随实际数值，杜绝固定宣传语
  const rawCalmar = agentData.best_results?.best_excess_calmar
  const bestCalmar = Number(rawCalmar)
  const calmarVerdict = !Number.isFinite(bestCalmar)
    ? { num: '—', numCls: 'text-gray-400', text: '巡航启动中，暂无完成的网格测试' }
    : bestCalmar >= 0.5
      ? { num: bestCalmar.toFixed(4), numCls: 'text-emerald-400', text: '已达 0.50 有效准入门槛，组合超额绩效优秀' }
      : bestCalmar > 0
        ? { num: bestCalmar.toFixed(4), numCls: 'text-yellow-400', text: '未达 0.50 有效准入门槛，继续寻优中' }
        : { num: bestCalmar.toFixed(4), numCls: 'text-rose-400', text: '超额卡玛为负，未跑赢基准，维持原样继续寻优' }

  // 状态横幅：图标与颜色严格跟随后端心跳判定 (RUNNING/INTERRUPTED/IDLE)
  const statusStr = agentData.status || ''
  const isRunning = statusStr.startsWith('RUNNING')
  const isInterrupted = statusStr.startsWith('INTERRUPTED')
  const StatusIcon = isInterrupted ? AlertTriangle : isRunning ? CheckCircle : Clock
  const statusIconWrap = isInterrupted
    ? 'bg-rose-500/10 border-rose-500/30'
    : isRunning
      ? 'bg-emerald-500/10 border-emerald-500/30'
      : 'bg-gray-500/10 border-gray-500/30'
  const statusIconCls = isInterrupted ? 'text-rose-400' : isRunning ? 'text-emerald-400' : 'text-gray-400'
  const statusTextCls = isInterrupted ? 'text-rose-300' : 'text-gray-200'

  useEffect(() => { fetchAgentData() }, [fetchAgentData])

  // 巡航运行期间定时轮询，让状态/轨迹/日志自动刷新
  useEffect(() => {
    if (!isRunning && !isInterrupted) return
    const interval = setInterval(fetchAgentData, 15000)
    return () => clearInterval(interval)
  }, [isRunning, isInterrupted, fetchAgentData])

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 4000)
  }

  const handleCruiseAction = async (endpoint, successMsg) => {
    if (actionLoading) return
    setActionLoading(true)
    try {
      const res = await fetch(`/api/agent/cruise/${endpoint}`, { method: 'POST' })
      const data = await res.json()
      if (data.status === 'error' || data.status === 'busy') {
        showToast(data.message || '操作失败', 'error')
      } else {
        showToast(data.message || successMsg, data.status === 'PENDING' || data.status === 'STOPPING' ? 'success' : 'info')
        // 延迟刷新给后端一点处理时间
        setTimeout(fetchAgentData, 800)
      }
    } catch (e) {
      showToast(`网络错误: ${e.message}`, 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleStart = () => handleCruiseAction('start', '巡航已启动')
  const handleStop = () => handleCruiseAction('stop', '巡航已停止')
  const handleReset = () => {
    if (!confirm('确认重置巡航？这将停止当前巡航并归档历史报告。')) return
    handleCruiseAction('reset', '巡航已重置')
  }

  return (
    <div className="space-y-6">
      {/* 系统状态横幅 */}
      <div className="p-5 bg-[#151D30] rounded-2xl border border-[#222F4C] flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center space-x-4">
          <div className={`p-3 rounded-xl border ${statusIconWrap}`}>
            <StatusIcon className={`h-6 w-6 ${statusIconCls}`} />
          </div>
          <div>
            <h4 className="font-bold text-gray-200 font-sans">Agent 自主进化巡航系统</h4>
            <p className={`text-xs font-mono mt-0.5 ${statusTextCls}`}>{agentData.status}</p>
          </div>
        </div>
        <div className="flex flex-col items-end space-y-2">
          <div className="flex items-center space-x-2">
            {/* 启动按钮：IDLE / INTERRUPTED 时显示 */}
            {!isRunning && (
              <button
                onClick={handleStart}
                disabled={actionLoading}
                title="启动 Agent 自主进化巡航，后台自动寻优因子组合（增量续跑）"
                className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-mono rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Play className="h-3.5 w-3.5" />
                <span>{actionLoading ? '处理中...' : '启动巡航'}</span>
              </button>
            )}
            {/* 停止按钮：RUNNING 时显示 */}
            {isRunning && (
              <button
                onClick={handleStop}
                disabled={actionLoading}
                title="向巡航进程发送 SIGTERM，安全退出并导出当前寻优报告"
                className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-mono rounded-lg bg-rose-500/20 border border-rose-500/40 text-rose-400 hover:bg-rose-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Square className="h-3.5 w-3.5" />
                <span>{actionLoading ? '处理中...' : '停止巡航'}</span>
              </button>
            )}
            {/* 重置按钮：始终显示 */}
            <button
              onClick={handleReset}
              disabled={actionLoading}
              title="停止并归档历史报告，重置为初始状态"
              className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-mono rounded-lg bg-gray-500/15 border border-gray-500/30 text-gray-400 hover:bg-gray-500/25 hover:text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>重置</span>
            </button>
          </div>
          <div className="flex items-center space-x-1 text-xs text-gray-500 font-mono">
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
                    <th className="p-3 text-right pr-5">超额卡玛</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#222F4C]/40">
                  {agentData.trajectory.map((item, idx) => (
                    <tr key={idx} className={`hover:bg-[#1A253D]/40 transition-colors ${item.excess_calmar_ratio >= 0.5 ? 'bg-emerald-500/5' : ''}`}>
                      <td className="p-3 pl-5 text-gray-300">{item.combo_index}</td>
                      <td className="p-3 text-gray-300">{item.tested_params?.top_n}</td>
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
            <div className={`font-bold text-2xl ${calmarVerdict.numCls}`}>
              {calmarVerdict.num}
            </div>
            <div className="text-gray-500">{calmarVerdict.text}</div>
          </div>
        </div>
      </div>

      {/* Toast 提示 */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-xl border text-sm font-mono shadow-lg max-w-md
          ${toast.type === 'error' ? 'bg-rose-500/20 border-rose-500/40 text-rose-200' :
            toast.type === 'success' ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-200' :
              'bg-blue-500/20 border-blue-500/40 text-blue-200'}`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}

export default Logs
