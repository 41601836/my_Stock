import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom'
import { LayoutDashboard, TrendingUp, BarChart3, Terminal, Activity, Wifi, ShieldAlert, Download, ScanSearch, CheckCircle2, Loader2, XCircle, X, Crosshair, RefreshCw, Zap, Globe } from 'lucide-react'
import Dashboard from './Dashboard'
import Performance from './Performance'
import Factors from './Factors'
import Logs from './Logs'
import JackMode from './JackMode'
import Scanner from './Scanner'
import WinRateHunter from './WinRateHunter'
import StrategySelector from './StrategySelector'
import Diagnosis from './Diagnosis'
import Diagnose from './Diagnose'
import Overview from './Overview'

// ── Toast 通知组件 ─────────────────────────────────────────────────
const TOAST_STYLES = {
  pending: 'bg-[#0F1929] border-sky-500/50 text-sky-300',
  running: 'bg-[#131C0D] border-amber-500/50 text-amber-300',
  success: 'bg-[#0D1F0D] border-emerald-500/50 text-emerald-300',
  error:   'bg-[#1F0D0D] border-rose-500/50 text-rose-300',
}

function ToastItem({ toast, onRemove }) {
  const icon = {
    pending: <Loader2 className="h-4 w-4 animate-spin flex-shrink-0 mt-0.5" />,
    running: <Loader2 className="h-4 w-4 animate-spin flex-shrink-0 mt-0.5" />,
    success: <CheckCircle2 className="h-4 w-4 flex-shrink-0 mt-0.5" />,
    error:   <XCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />,
  }[toast.type] || null

  return (
    <div className={`flex items-start justify-between gap-3 px-4 py-3 rounded-xl border text-xs font-mono shadow-2xl transition-all ${TOAST_STYLES[toast.type] || TOAST_STYLES.pending}`}>
      <div className="flex items-start gap-2 min-w-0">
        {icon}
        <span className="leading-relaxed break-words">{toast.message}</span>
      </div>
      <button onClick={() => onRemove(toast.id)} className="opacity-40 hover:opacity-100 transition-opacity flex-shrink-0 mt-0.5">
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

// ── 主应用 ──────────────────────────────────────────────────────────
function App() {
  const navigate = useNavigate()
  const location = useLocation()
  
  // Extract path to determine active tab equivalent
  const currentPath = location.pathname === '/' ? 'dashboard' : location.pathname.substring(1)
  
  const [marketStatus, setMarketStatus] = useState(null)
  const [apiOnline, setApiOnline] = useState(false)
  const [loading, setLoading] = useState(true)

  // Toast 状态管理
  const [toasts, setToasts] = useState([])
  // 用 ref 追踪所有活跃的轮询 interval，防止内存泄漏
  const intervals = useRef({})

  const removeToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
    // 同时清除对应的轮询 interval
    if (intervals.current[id]) {
      clearInterval(intervals.current[id])
      delete intervals.current[id]
    }
  }, [])

  const upsertToast = useCallback((id, type, message) => {
    setToasts(prev => {
      const exists = prev.find(t => t.id === id)
      if (exists) return prev.map(t => t.id === id ? { ...t, type, message } : t)
      return [...prev, { id, type, message }]
    })
  }, [])

  // 轮询任务状态，直到终态 (DONE / ERROR / TIMEOUT)
  const pollTask = useCallback((toastId, taskId) => {
    // 先清理可能存在的旧 interval
    if (intervals.current[toastId]) {
      clearInterval(intervals.current[toastId])
    }

    const tid = setInterval(async () => {
      try {
        const res = await fetch(`/api/task-status/${taskId}`)
        if (!res.ok) return
        const data = await res.json()

        if (data.status === 'PENDING') {
          upsertToast(toastId, 'pending', `⏳ 任务排队中... (${taskId})`)
        } else if (data.status === 'RUNNING') {
          upsertToast(toastId, 'running', `⚙️ 任务执行中 (${data.started_at || ''})`)
        } else if (data.status === 'DONE') {
          clearInterval(tid)
          delete intervals.current[toastId]
          if ((data.returncode ?? 0) === 0) {
            upsertToast(toastId, 'success', `✅ 执行成功！完成时间: ${data.finished_at || ''}`)
          } else {
            upsertToast(toastId, 'error', `⚠️ 执行完成但有错误 (退出码 ${data.returncode})`)
          }
          setTimeout(() => removeToast(toastId), 10000)
        } else if (data.status === 'NOT_FOUND') {
          // 后端重启导致 task_registry 清空，属于正常现象，静默关闭 toast
          clearInterval(tid)
          delete intervals.current[toastId]
          setTimeout(() => removeToast(toastId), 1000)
        } else if (['ERROR', 'TIMEOUT'].includes(data.status)) {
          clearInterval(tid)
          delete intervals.current[toastId]
          const errMsg = data.error ? data.error.slice(0, 80) : data.status
          upsertToast(toastId, 'error', `❌ ${errMsg}`)
          setTimeout(() => removeToast(toastId), 8000)
        }
      } catch (_) {
        // 网络异常时静默跳过本次轮询
      }
    }, 2000)

    intervals.current[toastId] = tid
  }, [upsertToast, removeToast])

  // 清理所有 interval on unmount
  useEffect(() => {
    return () => {
      Object.values(intervals.current).forEach(clearInterval)
    }
  }, [])

  // 手动拉取数据
  const handleFetch = useCallback(async () => {
    const toastId = `fetch-${Date.now()}`
    upsertToast(toastId, 'pending', '📡 正在启动数据拉取任务...')
    try {
      const res = await fetch('/api/run-fetch', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      upsertToast(toastId, 'pending', `📡 ${data.message}`)
      pollTask(toastId, data.task_id)
    } catch (e) {
      upsertToast(toastId, 'error', `❌ 启动失败: ${e.message}`)
      setTimeout(() => removeToast(toastId), 6000)
    }
  }, [upsertToast, pollTask, removeToast])

  // 手动扫描因子
  const handleScan = useCallback(async () => {
    const toastId = `scan-${Date.now()}`
    upsertToast(toastId, 'pending', '🔍 正在启动因子扫描任务...')
    try {
      const res = await fetch('/api/run-scan', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      upsertToast(toastId, 'pending', `🔍 ${data.message}`)
      pollTask(toastId, data.task_id)
    } catch (e) {
      upsertToast(toastId, 'error', `❌ 启动失败: ${e.message}`)
      setTimeout(() => removeToast(toastId), 6000)
    }
  }, [upsertToast, pollTask, removeToast])

  // 手动触发 simulation 回测，更新数据截止日期
  const handleBacktest = useCallback(async () => {
    const toastId = `bt-${Date.now()}`
    upsertToast(toastId, 'pending', '📊 正在启动回测更新...')
    try {
      const res = await fetch('/api/run-backtest', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      upsertToast(toastId, 'pending', `📊 ${data.message}`)
      pollTask(toastId, data.task_id)
    } catch (e) {
      upsertToast(toastId, 'error', `❌ 启动失败: ${e.message}`)
      setTimeout(() => removeToast(toastId), 6000)
    }
  }, [upsertToast, pollTask, removeToast])

  // 心跳轮询市场状态 (8s)
  useEffect(() => {
    const fetchStatus = () => {
      fetch('/api/status')
        .then(res => {
          if (!res.ok) throw new Error('offline')
          return res.json()
        })
        .then(data => {
          setMarketStatus(data)
          setApiOnline(true)
          setLoading(false)
        })
        .catch(() => {
          setApiOnline(false)
          setLoading(false)
        })
    }
    fetchStatus()
    const t = setInterval(fetchStatus, 8000)
    return () => clearInterval(t)
  }, [])

  const navItems = [
    { id: '/overview',    label: '市场宏观全览',   Icon: Globe },
    { id: '/',           label: '核心策略仪表盘', Icon: LayoutDashboard },
    { id: '/performance',label: '周度绩效时序',   Icon: TrendingUp },
    { id: '/factors',    label: '因子自适应权重', Icon: BarChart3 },
    { id: '/jack',       label: '游资策略模拟',   Icon: Zap },
    { id: '/scanner',    label: '建仓机会扫描',   Icon: Crosshair },
    { id: '/diagnose',   label: '诊股看盘',       Icon: ScanSearch },
    { id: '/diagnosis',  label: '建仓逻辑诊断',   Icon: Activity },
    { id: '/logs',       label: 'Agent 进化日志', Icon: Terminal },
    { id: '/hunter',     label: '胜率猎手优化器', Icon: Crosshair }, // Using Crosshair for now
  ]

  const pageTitle = {
    overview:    '大盘多因子量化温度与资金全览',
    dashboard:   '策略实时仪表盘',
    performance: '多轨回测绩效曲线',
    factors:     '因子自适应权重监控',
    jack:        '博主“90后Jack”游资回测与实盘对照模拟',
    scanner:     '建仓机会实时扫描（5维因子+筹码+主力资金）',
    diagnose:    '诊股看盘与全策略因子维度评价系统',
    diagnosis:   '建仓策略样本外归因诊断控制台',
    logs:        'Agent 进化巡航监控控制台',
    hunter:      '胜率猎手 (Win Rate Hunter) 进化引擎',
  }

  return (
    <div className="flex h-screen bg-[#0B0F19] text-gray-100 overflow-hidden font-sans">
      {/* ─── 侧边栏 ─────────────────────────────────────────────── */}
      <aside className="w-64 bg-[#111827] border-r border-[#1F2937] flex flex-col justify-between shrink-0">
        <div>
          {/* Logo */}
          <div className="p-6 border-b border-[#1F2937] flex items-center space-x-3">
            <div className="p-2 bg-purple-500/10 rounded-lg border border-purple-500/30">
              <Activity className="h-6 w-6 text-purple-400" />
            </div>
            <div>
              <h1 className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-indigo-300">Antigravity</h1>
              <span className="text-xs text-gray-500 font-mono">策略控制台 v2.0</span>
            </div>
          </div>

          {/* 导航 */}
          <nav className="p-4 space-y-1">
            {navItems.map(({ id, label, Icon }) => {
              const isActive = location.pathname === id;
              return (
                <button
                  key={id}
                  onClick={() => navigate(id)}
                  className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm transition-all ${
                    isActive
                      ? 'bg-purple-600 text-white shadow-lg shadow-purple-600/20'
                      : 'text-gray-400 hover:bg-[#1F2937] hover:text-gray-100'
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span>{label}</span>
                </button>
              )
            })}
          </nav>
        </div>

        {/* 底部状态 */}
        <div className="p-4 border-t border-[#1F2937] bg-[#0E1321] text-xs text-gray-500 space-y-1.5">
          <div className="flex items-center justify-between">
            <span>策略引擎:</span>
            {apiOnline ? (
              <span className="flex items-center text-emerald-400 font-mono">
                <Wifi className="h-3 w-3 mr-1" />ONLINE
              </span>
            ) : (
              <span className="flex items-center text-rose-500 font-mono">
                <ShieldAlert className="h-3 w-3 mr-1" />OFFLINE
              </span>
            )}
          </div>
          <div className="font-mono">数据截止: {marketStatus?.db_latest_date || '—'}</div>
        </div>
      </aside>

      {/* ─── 主体 ───────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-hidden bg-[#0D1220]">
        {/* 顶栏 */}
        <header className="h-16 border-b border-[#1F2937] flex items-center justify-between px-8 bg-[#111827] shrink-0">
          <h2 className="text-lg font-semibold text-gray-100">
            {pageTitle[currentPath] || '策略控制台'}
          </h2>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 mr-4 text-xs font-mono text-gray-400 bg-[#151d32] px-3 py-1.5 rounded border border-slate-700/50">
              <span className={`h-2 w-2 rounded-full ${marketStatus?.db_latest_date && marketStatus.db_latest_date !== '—' ? 'bg-emerald-400' : 'bg-rose-400'}`} />
              数据更新至: {marketStatus?.db_latest_date || '加载中...'}
            </div>

            {/* 拉取数据按钮 */}
            <button
              onClick={handleFetch}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-sky-600/20 text-sky-400 border border-sky-600/30 hover:bg-sky-600/30 hover:text-sky-200 active:scale-95 transition-all"
            >
              <Download className="h-3.5 w-3.5" />
              <span>拉取数据</span>
            </button>

            {/* 扫描因子按钮 */}
            <button
              onClick={handleScan}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-amber-600/20 text-amber-400 border border-amber-600/30 hover:bg-amber-600/30 hover:text-amber-200 active:scale-95 transition-all"
            >
              <ScanSearch className="h-3.5 w-3.5" />
              <span>扫描因子</span>
            </button>

            {/* 更新回测按钮 */}
            <button
              onClick={handleBacktest}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600/20 text-emerald-400 border border-emerald-600/30 hover:bg-emerald-600/30 hover:text-emerald-200 active:scale-95 transition-all"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>更新回测</span>
            </button>

            {/* 策略选择器 */}
            <StrategySelector upsertToast={upsertToast} />

            <button
              onClick={() => navigate('/logs')}
              title="点击查看 Agent 进化路由状态"
              className="text-xs px-3 py-1 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20 font-mono hover:bg-purple-500/20 hover:text-purple-300 transition-colors"
            >
              自适应路由模式
            </button>
          </div>
        </header>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto p-8">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <div className="flex flex-col items-center gap-4 text-gray-500">
                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-purple-500" />
                <span className="text-sm font-mono">连接策略引擎中...</span>
              </div>
            </div>
          ) : (
            <Routes>
              <Route path="/overview" element={<Overview />} />
              <Route path="/" element={<Dashboard marketStatus={marketStatus} />} />
              <Route path="/performance" element={<Performance />} />
              <Route path="/factors" element={<Factors />} />
              <Route path="/jack" element={<JackMode />} />
              <Route path="/scanner" element={<Scanner />} />
              <Route path="/diagnose" element={<Diagnose />} />
              <Route path="/diagnosis" element={<Diagnosis />} />
              <Route path="/logs" element={<Logs />} />
              <Route path="/hunter" element={<WinRateHunter upsertToast={upsertToast} removeToast={removeToast} pollTask={pollTask} />} />
            </Routes>
          )}
        </div>
      </main>

      {/* ─── 全局 Toast 浮层 ──────────────────────────────────────── */}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 w-80 pointer-events-none">
        {toasts.map(toast => (
          <div key={toast.id} className="pointer-events-auto">
            <ToastItem toast={toast} onRemove={removeToast} />
          </div>
        ))}
      </div>
    </div>
  )
}

export default App
