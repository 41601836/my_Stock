import React, { useState, useEffect, useRef } from 'react'
import { Activity, Search, Shield, ChevronDown, CheckCircle, AlertTriangle, Crosshair, Target, BarChart3 } from 'lucide-react'
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip as RechartsTooltip } from 'recharts'

const Diagnose = () => {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [selectedStock, setSelectedStock] = useState(null)
  
  const [strategies, setStrategies] = useState([])
  const [selectedStrategy, setSelectedStrategy] = useState('current')
  
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const searchRef = useRef(null)

  // Fetch available strategies on mount
  useEffect(() => {
    fetch('/api/strategies')
      .then(res => res.json())
      .then(data => {
        if (data.strategies) {
          setStrategies(data.strategies)
        }
      })
      .catch(e => console.error("Failed to load strategies", e))
  }, [])

  // Handle outside click for search suggestions
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  // Search stock logic with debounce
  useEffect(() => {
    if (!query) {
      setSuggestions([])
      return
    }
    
    const timer = setTimeout(() => {
      fetch(`/api/market/search-stock?query=${encodeURIComponent(query)}`)
        .then(res => res.json())
        .then(data => {
          if (data.stocks) {
            setSuggestions(data.stocks)
            setShowSuggestions(true)
          }
        })
        .catch(console.error)
    }, 300)

    return () => clearTimeout(timer)
  }, [query])

  const handleSelectStock = (stock) => {
    setSelectedStock(stock)
    setQuery(`${stock.ts_code} - ${stock.name}`)
    setShowSuggestions(false)
  }

  const runDiagnosis = async () => {
    if (!selectedStock) return
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await fetch(`/api/market/diagnose?ts_code=${selectedStock.ts_code}&strategy=${selectedStrategy}`)
      const data = await res.json()
      if (data.error) {
        setError(data.error)
      } else {
        setResult(data)
      }
    } catch (e) {
      setError("网络错误或服务器未响应")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#060B14] p-8 text-gray-200 font-sans">
      <div className="max-w-6xl mx-auto space-y-8">
        
        {/* Header */}
        <div className="flex items-center gap-4">
          <div className="p-3 bg-indigo-500/10 rounded-xl border border-indigo-500/20">
            <Activity className="w-8 h-8 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">诊股看盘 <span className="text-indigo-400">Diagnosis</span></h1>
            <p className="text-gray-400 text-sm mt-1">自下而上：选择指定股票，使用多维量化策略进行深度体检</p>
          </div>
        </div>

        {/* Control Panel */}
        <div className="bg-[#0E1524] rounded-2xl border border-[#222F4C] p-6 shadow-2xl">
          <div className="flex flex-col md:flex-row gap-6">
            
            {/* Search Box */}
            <div className="flex-1 relative" ref={searchRef}>
              <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">1. 选择股票标的</label>
              <div className="relative">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value)
                    if(selectedStock) setSelectedStock(null)
                  }}
                  onFocus={() => {if (suggestions.length > 0) setShowSuggestions(true)}}
                  placeholder="输入股票代码 (如 688679) 或 名称 (如 通源环境)"
                  className="w-full bg-[#1A253D] border border-[#2A3F5F] text-white rounded-xl py-3 pl-12 pr-4 focus:outline-none focus:border-indigo-500 transition-colors"
                />
              </div>
              
              {/* Autocomplete Dropdown */}
              {showSuggestions && suggestions.length > 0 && (
                <div className="absolute z-50 mt-2 w-full bg-[#1A253D] border border-[#2A3F5F] rounded-xl shadow-xl overflow-hidden">
                  {suggestions.map(s => (
                    <div 
                      key={s.ts_code}
                      onClick={() => handleSelectStock(s)}
                      className="px-4 py-3 hover:bg-indigo-500/20 cursor-pointer flex items-center justify-between border-b border-[#222F4C] last:border-0"
                    >
                      <div className="flex items-center gap-3">
                        <span className="font-mono font-bold text-indigo-300">{s.ts_code}</span>
                        <span className="font-bold text-white">{s.name}</span>
                      </div>
                      <span className="text-xs text-gray-400">{s.industry} | {s.market}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Strategy Select */}
            <div className="md:w-1/3">
              <label className="block text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">2. 选择检验策略</label>
              <div className="relative">
                <Target className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
                <select 
                  value={selectedStrategy}
                  onChange={(e) => setSelectedStrategy(e.target.value)}
                  className="w-full bg-[#1A253D] border border-[#2A3F5F] text-white rounded-xl py-3 pl-12 pr-10 focus:outline-none focus:border-indigo-500 appearance-none transition-colors"
                >
                  <option value="current">⚡ 当前主路由策略 (自动适配牛熊)</option>
                  <option value="base_bull">🐂 经典牛市多头策略 (Base Bull)</option>
                  <option value="base_range">🐻 经典震荡防御策略 (Base Range)</option>
                  <option value="scanner">🎯 5维因子+筹码+主力扫描策略</option>
                  {strategies.map(s => (
                    <option key={s.name} value={s.name}>
                      🧬 {s.name.replace('.yaml', '')} (自定义基因)
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500 pointer-events-none" />
              </div>
            </div>

            {/* Submit Button */}
            <div className="md:w-40 flex items-end">
              <button 
                onClick={runDiagnosis}
                disabled={!selectedStock || loading}
                className="w-full h-[50px] bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-colors flex items-center justify-center gap-2"
              >
                {loading ? (
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                ) : (
                  <>
                    <Crosshair className="w-5 h-5" />
                    深度诊断
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Results Area */}
        {error && (
          <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-4 flex items-center gap-3 text-rose-400 mt-6">
            <AlertTriangle className="w-5 h-5" />
            <p className="font-medium">{error}</p>
          </div>
        )}

        {result && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 animate-fade-in-up mt-6">
            
            {/* Left Column: Basic Info & Score */}
            <div className="col-span-1 space-y-6">
              
              {/* Stock Card */}
              <div className="bg-[#0E1524] rounded-2xl border border-[#222F4C] p-6 relative overflow-hidden group">
                <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <h2 className="text-3xl font-black text-white">{result.name}</h2>
                    <a 
                      href={`http://stockpage.10jqka.com.cn/${result.ts_code.substring(0, 6)}/`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-indigo-400 hover:text-indigo-300 font-mono text-sm inline-flex items-center gap-1 mt-1 hover:underline"
                      title="去同花顺查看详细盘面"
                    >
                      {result.ts_code} ↗
                    </a>
                  </div>
                  <div className={`text-right ${result.pct_chg >= 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
                    <div className="text-2xl font-bold font-mono">{result.close.toFixed(2)}</div>
                    <div className="text-sm font-bold font-mono">
                      {result.pct_chg > 0 ? '+' : ''}{result.pct_chg.toFixed(2)}%
                    </div>
                  </div>
                </div>
                <div className="inline-block px-3 py-1 bg-white/5 border border-white/10 rounded-lg text-xs text-gray-300 font-medium">
                  所属行业: {result.industry}
                </div>
              </div>

              {/* Score Card */}
              <div className="bg-gradient-to-b from-[#151D30] to-[#0E1524] rounded-2xl border border-[#222F4C] p-6 text-center">
                <h3 className="text-sm font-bold text-gray-400 uppercase tracking-widest mb-4">策略匹配总分</h3>
                <div className="relative inline-flex items-center justify-center w-40 h-40">
                  <svg className="w-full h-full transform -rotate-90">
                    <circle cx="80" cy="80" r="70" fill="none" stroke="#1A253D" strokeWidth="12" />
                    <circle 
                      cx="80" cy="80" r="70" fill="none" 
                      stroke={result.final_score >= 80 ? '#34d399' : result.final_score >= 50 ? '#818cf8' : '#fbbf24'} 
                      strokeWidth="12" 
                      strokeDasharray="439.8" 
                      strokeDashoffset={439.8 - (439.8 * result.final_score) / 100} 
                      className="transition-all duration-1000 ease-out"
                    />
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-5xl font-black text-white font-mono">{result.final_score}</span>
                    <span className="text-xs text-gray-500 font-mono mt-1">/ 100</span>
                  </div>
                </div>
                <p className="mt-4 text-sm text-gray-400">
                  基于 <span className="text-indigo-300 font-mono">{result.strategy}</span> 策略模型的综合量化评估
                </p>
              </div>

            </div>

            {/* Right Column: Radar & Breakdown */}
            <div className="col-span-1 lg:col-span-2 space-y-6">
              
              <div className="bg-[#0E1524] rounded-2xl border border-[#222F4C] p-6 flex flex-col h-full">
                <h3 className="text-lg font-bold text-white mb-6 flex items-center gap-2">
                  <Shield className="w-5 h-5 text-indigo-400" />
                  因子多维雷达图 (Factor Radar)
                </h3>
                
                <div className="flex-1 min-h-[300px] w-full relative">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart cx="50%" cy="50%" outerRadius="75%" data={result.radar_data}>
                      <PolarGrid stroke="#222F4C" />
                      <PolarAngleAxis 
                        dataKey="subject" 
                        tick={{ fill: '#8b949e', fontSize: 11, fontFamily: 'monospace' }} 
                      />
                      <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
                      <RechartsTooltip 
                        contentStyle={{ backgroundColor: '#1A253D', border: '1px solid #2A3F5F', borderRadius: '8px' }}
                        itemStyle={{ color: '#818cf8', fontWeight: 'bold' }}
                      />
                      <Radar 
                        name="因子匹配度 (%)" 
                        dataKey="A" 
                        stroke="#818cf8" 
                        strokeWidth={2}
                        fill="#818cf8" 
                        fillOpacity={0.3} 
                        activeDot={{ r: 6, fill: '#818cf8', stroke: '#fff', strokeWidth: 2 }}
                      />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              </div>

            </div>
            
            {/* Full Width Bottom: Strengths and Weaknesses */}
            <div className="col-span-1 lg:col-span-3 grid grid-cols-1 md:grid-cols-2 gap-6">
              
              <div className="bg-emerald-900/10 border border-emerald-500/20 rounded-2xl p-6">
                <h4 className="text-emerald-400 font-bold mb-4 flex items-center gap-2">
                  <CheckCircle className="w-5 h-5" />
                  模型眼中的“加分项” (Tailwinds)
                </h4>
                {result.strengths.length > 0 ? (
                  <ul className="space-y-3">
                    {result.strengths.map((s, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 mt-1.5 flex-shrink-0"></div>
                        <span className="font-mono">{s}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-sm text-gray-500 italic">该策略下暂无突出加分项</div>
                )}
              </div>

              <div className="bg-amber-900/10 border border-amber-500/20 rounded-2xl p-6">
                <h4 className="text-amber-400 font-bold mb-4 flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5" />
                  模型眼中的“扣分项” (Headwinds)
                </h4>
                {result.weaknesses.length > 0 ? (
                  <ul className="space-y-3">
                    {result.weaknesses.map((w, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                        <div className="w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 flex-shrink-0"></div>
                        <span className="font-mono">{w}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-sm text-gray-500 italic">该策略下暂无明显短板</div>
                )}
              </div>

            </div>

            {/* Core Metrics Summary */}
            <div className="col-span-1 lg:col-span-3 bg-[#0B1220] border border-[#222F4C] rounded-2xl p-6 mt-2">
              <h4 className="text-gray-400 font-bold mb-4 flex items-center gap-2 text-sm uppercase tracking-wider">
                <BarChart3 className="w-4 h-4" />
                核心指标明细 (Core Metrics Snapshot)
              </h4>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-[#151D30]/80 rounded-xl p-4 border border-[#1A253D] flex flex-col gap-1">
                  <span className="text-xs text-gray-500 font-semibold tracking-wide">筹码胜率 (Winner Rate)</span>
                  <span className="text-xl font-bold font-mono text-emerald-400">
                    {result.raw_metrics?.winner_rate?.toFixed(2) || '0.00'}%
                  </span>
                </div>
                <div className="bg-[#151D30]/80 rounded-xl p-4 border border-[#1A253D] flex flex-col gap-1">
                  <span className="text-xs text-gray-500 font-semibold tracking-wide">筹码集中度 (Concentration)</span>
                  <span className="text-xl font-bold font-mono text-indigo-400">
                    {result.raw_metrics?.chip_concentration?.toFixed(2) || '0.00'}%
                  </span>
                </div>
                <div className="bg-[#151D30]/80 rounded-xl p-4 border border-[#1A253D] flex flex-col gap-1">
                  <span className="text-xs text-gray-500 font-semibold tracking-wide">主力净流入 (Net Inflow)</span>
                  <span className={`text-xl font-bold font-mono ${result.raw_metrics?.net_mf_amount > 0 ? 'text-rose-500' : 'text-emerald-500'}`}>
                    {result.raw_metrics?.net_mf_amount > 0 ? '+' : ''}{(result.raw_metrics?.net_mf_amount / 10000).toFixed(2) || '0.00'}亿
                  </span>
                </div>
                <div className="bg-[#151D30]/80 rounded-xl p-4 border border-[#1A253D] flex flex-col gap-1">
                  <span className="text-xs text-gray-500 font-semibold tracking-wide">20日换手率 (Turnover 20d)</span>
                  <span className="text-xl font-bold font-mono text-amber-400">
                    {result.raw_metrics?.turnover_rate_20d?.toFixed(2) || '0.00'}%
                  </span>
                </div>
              </div>
            </div>

          </div>
        )}

      </div>
    </div>
  )
}

export default Diagnose
