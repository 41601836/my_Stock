import React, { useState, useEffect } from 'react'
import { Server, ChevronDown, Check, Loader2 } from 'lucide-react'

export default function StrategySelector({ upsertToast }) {
  const [strategies, setStrategies] = useState([])
  const [currentStrategy, setCurrentStrategy] = useState('custom')
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)

  const fetchStrategies = async () => {
    try {
      const res = await fetch('/api/strategies')
      if (res.ok) {
        const data = await res.json()
        setStrategies(data.strategies || [])
        setCurrentStrategy(data.current || 'custom')
      }
    } catch (e) {
      console.error("Failed to fetch strategies", e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStrategies()
  }, [])

  const handleSwitch = async (name) => {
    if (name === currentStrategy) {
      setIsOpen(false)
      return
    }
    
    setSwitching(true)
    const toastId = `switch-${Date.now()}`
    upsertToast(toastId, 'pending', `🔄 正在切换至策略 [${name}]...`)
    
    try {
      const res = await fetch('/api/strategies/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
      })
      const data = await res.json()
      
      if (res.ok && data.status === 'success') {
        upsertToast(toastId, 'success', `✅ ${data.message}`)
        setCurrentStrategy(name)
      } else {
        throw new Error(data.message || '未知错误')
      }
    } catch (e) {
      upsertToast(toastId, 'error', `❌ 策略切换失败: ${e.message}`)
    } finally {
      setSwitching(false)
      setIsOpen(false)
    }
  }

  // 点击外部关闭下拉菜单
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (isOpen && !e.target.closest('.strategy-selector-container')) {
        setIsOpen(false)
      }
    }
    document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [isOpen])

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-700/50 bg-[#151d32] text-gray-400 text-xs font-mono">
        <Loader2 className="h-3 w-3 animate-spin" />
        加载策略...
      </div>
    )
  }

  return (
    <div className="relative strategy-selector-container">
      {/* 触发按钮 */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={switching}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-mono transition-all ${
          currentStrategy !== 'custom'
            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20'
            : 'bg-[#151d32] text-gray-400 border-slate-700/50 hover:bg-slate-800'
        }`}
      >
        <Server className="h-3.5 w-3.5" />
        <div className="flex flex-col items-start leading-none gap-0.5 text-left">
          <span className="opacity-70 text-[10px]">STRATEGY</span>
          <span className="font-semibold tracking-wide">
            {currentStrategy === 'custom' ? 'Custom / Not Saved' : currentStrategy.replace('strategy_', '').replace('.yaml', '')}
          </span>
        </div>
        {switching ? (
          <Loader2 className="h-3 w-3 animate-spin ml-1" />
        ) : (
          <ChevronDown className={`h-3.5 w-3.5 ml-1 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        )}
      </button>

      {/* 下拉列表 */}
      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-72 bg-[#111827] border border-[#1F2937] rounded-xl shadow-2xl overflow-hidden z-50 animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="px-3 py-2 bg-[#1F2937]/50 border-b border-[#1F2937] flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-300">金牌策略库 (Archives)</span>
            <span className="text-[10px] text-gray-500 font-mono">{strategies.length} AVAILABLE</span>
          </div>
          
          <div className="max-h-64 overflow-y-auto p-1">
            {strategies.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-gray-500">
                暂无存档策略。<br/>请前往「胜率猎手」跑出最优解。
              </div>
            ) : (
              strategies.map((strat) => (
                <button
                  key={strat.name}
                  onClick={() => handleSwitch(strat.name)}
                  className={`w-full text-left flex items-start justify-between px-3 py-2.5 rounded-lg transition-colors ${
                    currentStrategy === strat.name
                      ? 'bg-emerald-500/10 text-emerald-300'
                      : 'text-gray-300 hover:bg-[#1F2937]'
                  }`}
                >
                  <div className="flex flex-col gap-1">
                    <span className="text-sm font-medium tracking-wide">
                      {strat.name.replace('strategy_', '').replace('.yaml', '')} 策略
                    </span>
                    <span className="text-[10px] font-mono opacity-60 flex gap-2">
                      <span>TopN:{strat.top_n_stocks}</span>
                      <span>Mult:{strat.multiplier}</span>
                    </span>
                  </div>
                  {currentStrategy === strat.name && (
                    <Check className="h-4 w-4 text-emerald-500 mt-1" />
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
