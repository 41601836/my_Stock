import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom'
import { LayoutDashboard, TrendingUp, BarChart3, Terminal, Activity, Wifi, ShieldAlert, Download, ScanSearch, CheckCircle2, Loader2, XCircle, X, Crosshair, RefreshCw, Zap, Globe, Menu, ChevronDown, ChevronUp, Target } from 'lucide-react'
import Dashboard from './Dashboard'
import Performance from './Performance'
import Factors from './Factors'
import Logs from './Logs'
import JackMode from './JackMode'
import Scanner from './Scanner'
import ScanHistory from './ScanHistory'
import WinRateHunter from './WinRateHunter'
import StrategySelector from './StrategySelector'
import Diagnosis from './Diagnosis'
import Diagnose from './Diagnose'
import Overview from './Overview'
import PortraitAnalysis from './PortraitAnalysis'
import PositionPick from './PositionPick'

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

  const currentPath = location.pathname === '/' ? 'dashboard' : location.pathname.substring(1)

  const [marketStatus, setMarketStatus] = useState(null)
  const [apiOnline, setApiOnline] = useState(false)
  const [loading, setLoading] = useState(true)
  // 手机端侧边栏抽屉状态
  const [sidebarOpen, setSidebarOpen] = useState(false)
  // 手机端操作菜单折叠状态
  const [actionsOpen, setActionsOpen] = useState(false)
  const [visitorStats, setVisitorStats] = useState(null)

  // ── 全局缩放级别（手机端专用，持久化到 localStorage）──────────
  const ZOOM_STEP = 0.1
  const ZOOM_MIN  = 0.6
  const ZOOM_MAX  = 1.5
  const [zoomLevel, setZoomLevel] = useState(() => {
    const saved = parseFloat(localStorage.getItem('ui_zoom') || '1.0')
    return isNaN(saved) ? 1.0 : Math.min(Math.max(saved, ZOOM_MIN), ZOOM_MAX)
  })

  // 同步缩放到 #zoom-root DOM 元素
  useEffect(() => {
    const el = document.getElementById('zoom-root')
    if (!el) return
    el.style.transform = `scale(${zoomLevel})`
    // 同步调整宽高，防止缩小后出现空白
    el.style.width = `${(100 / zoomLevel).toFixed(4)}vw`
    el.style.minHeight = `${(100 / zoomLevel).toFixed(4)}vh`
    localStorage.setItem('ui_zoom', String(zoomLevel))
  }, [zoomLevel])

  const zoomIn  = () => setZoomLevel(v => parseFloat(Math.min(v + ZOOM_STEP, ZOOM_MAX).toFixed(2)))
  const zoomOut = () => setZoomLevel(v => parseFloat(Math.max(v - ZOOM_STEP, ZOOM_MIN).toFixed(2)))
  const zoomReset = () => setZoomLevel(1.0)

  const [toasts, setToasts] = useState([])
  const intervals = useRef({})

  const removeToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
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

  const pollTask = useCallback((toastId, taskId) => {
    if (intervals.current[toastId]) clearInterval(intervals.current[toastId])
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
          clearInterval(tid)
          delete intervals.current[toastId]
          setTimeout(() => removeToast(toastId), 1000)
        } else if (['ERROR', 'TIMEOUT'].includes(data.status)) {
          clearInterval(tid)
          delete intervals.current[toastId]
          upsertToast(toastId, 'error', `❌ ${data.error ? data.error.slice(0, 80) : data.status}`)
          setTimeout(() => removeToast(toastId), 8000)
        }
      } catch (_) {}
    }, 2000)
    intervals.current[toastId] = tid
  }, [upsertToast, removeToast])

  useEffect(() => {
    return () => Object.values(intervals.current).forEach(clearInterval)
  }, [])

  useEffect(() => {
    let deviceId = localStorage.getItem('device_id')
    if (!deviceId) {
      deviceId = 'device_' + Math.random().toString(36).substring(2) + Date.now().toString(36)
      localStorage.setItem('device_id', deviceId)
    }
    
    const trackVisitor = async () => {
      try {
        await fetch('/api/stats/track', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: location.pathname, device_id: deviceId })
        })
        const res = await fetch('/api/stats/summary')
        if (res.ok) {
          const stats = await res.json()
          setVisitorStats(stats)
        }
      } catch (err) {
        console.error('Track error:', err)
      }
    }
    trackVisitor()
  }, [location.pathname])

  const handleFetch = useCallback(async () => {
    setActionsOpen(false)
    const toastId = `fetch-${Date.now()}`
    upsertToast(toastId, 'pending', '📡 正在启动数据拉取任务...')
    try {
      const res = await fetch('/api/run-fetch', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.status === 'busy') {
        upsertToast(toastId, 'error', `${data.message}`)
        setTimeout(() => removeToast(toastId), 6000)
        return
      }
      upsertToast(toastId, 'pending', `📡 ${data.message}`)
      pollTask(toastId, data.task_id)
    } catch (e) {
      upsertToast(toastId, 'error', `❌ 启动失败: ${e.message}`)
      setTimeout(() => removeToast(toastId), 6000)
    }
  }, [upsertToast, pollTask, removeToast])

  const handleScan = useCallback(async () => {
    if (marketStatus?.db_health === 'ERROR') {
      const toastId = `scan-${Date.now()}`
      upsertToast(toastId, 'error', '❌ 数据熔断: 发现底层数据严重异常或断层，为防止生成错误信号，扫描功能已被系统锁定！')
      setTimeout(() => removeToast(toastId), 6000)
      return
    }
    setActionsOpen(false)
    const toastId = `scan-${Date.now()}`
    upsertToast(toastId, 'pending', '🔍 正在启动因子扫描任务...')
    try {
      const res = await fetch('/api/run-scan', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.status === 'busy') {
        upsertToast(toastId, 'error', `${data.message}`)
        setTimeout(() => removeToast(toastId), 6000)
        return
      }
      upsertToast(toastId, 'pending', `🔍 ${data.message}`)
      pollTask(toastId, data.task_id)
    } catch (e) {
      upsertToast(toastId, 'error', `❌ 启动失败: ${e.message}`)
      setTimeout(() => removeToast(toastId), 6000)
    }
  }, [upsertToast, pollTask, removeToast, marketStatus])

  const handleBacktest = useCallback(async () => {
    setActionsOpen(false)
    const toastId = `bt-${Date.now()}`
    upsertToast(toastId, 'pending', '📊 正在启动回测更新...')
    try {
      const res = await fetch('/api/run-backtest', { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.status === 'busy') {
        upsertToast(toastId, 'error', `${data.message}`)
        setTimeout(() => removeToast(toastId), 6000)
        return
      }
      upsertToast(toastId, 'pending', `📊 ${data.message}`)
      pollTask(toastId, data.task_id)
    } catch (e) {
      upsertToast(toastId, 'error', `❌ 启动失败: ${e.message}`)
      setTimeout(() => removeToast(toastId), 6000)
    }
  }, [upsertToast, pollTask, removeToast])

  useEffect(() => {
    const fetchStatus = () => {
      fetch('/api/status')
        .then(res => { if (!res.ok) throw new Error('offline'); return res.json() })
        .then(data => { setMarketStatus(data); setApiOnline(true); setLoading(false) })
        .catch(() => { setApiOnline(false); setLoading(false) })
    }
    fetchStatus()
    const t = setInterval(fetchStatus, 8000)
    return () => clearInterval(t)
  }, [])

  // 导航并关闭手机端抽屉
  const handleNav = (path) => { navigate(path); setSidebarOpen(false) }

  const navItems = [
    { id: '/overview',      label: '市场宏观全览',   Icon: Globe },
    { id: '/',             label: '核心策略仪表盘', Icon: LayoutDashboard },
    { id: '/performance',  label: '周度绩效时序',   Icon: TrendingUp },
    { id: '/factors',      label: '因子自适应权重', Icon: BarChart3 },
    { id: '/portrait',       label: 'T+1 画像分析',   Icon: Target },
    { id: '/position-pick',  label: '🎯 画像建仓决策', Icon: Crosshair },
    { id: '/jack',         label: '游资策略模拟',   Icon: Zap },
    { id: '/scanner',      label: '建仓机会扫描',   Icon: Crosshair },
    { id: '/scan-history', label: '扫描历史追踪',   Icon: Activity },
    { id: '/diagnose',     label: '诊股看盘',       Icon: ScanSearch },
    { id: '/diagnosis',    label: '建仓逻辑诊断',   Icon: Activity },
    { id: '/logs',         label: 'Agent 进化日志', Icon: Terminal },
    { id: '/hunter',       label: '胜率猎手优化器', Icon: Crosshair },
  ]

  // 手机底部 Tab 只展示核心 5 项
  const mobileNavItems = [
    { id: '/overview',  label: '全览',   Icon: Globe },
    { id: '/',         label: '仪表盘', Icon: LayoutDashboard },
    { id: '/scanner',  label: '扫描',   Icon: Crosshair },
    { id: '/diagnose', label: '诊股',   Icon: ScanSearch },
  ]

  const pageTitle = {
    overview: '市场宏观全览', dashboard: '策略实时仪表盘',
    performance: '多轨回测绩效曲线', factors: '因子自适应权重监控',
    portrait: 'T+1 上涨画像分析',
    'position-pick': '🎯 T+1 画像建仓决策',
    jack: '游资策略模拟', scanner: '建仓机会实时扫描',
    diagnose: '诊股看盘', diagnosis: '建仓策略归因诊断',
    logs: 'Agent 进化巡航监控', hunter: '胜率猎手进化引擎',
  }

  // 侧边栏内容（桌面 & 手机共用）
  const SidebarContent = () => (
    <>
      <div>
        <div className="p-5 border-b border-[#1F2937] flex items-center space-x-3">
          <div className="p-2 bg-purple-500/10 rounded-lg border border-purple-500/30">
            <Activity className="h-5 w-5 text-purple-400" />
          </div>
          <div>
            <h1 className="text-base font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-indigo-300">鞋底刺 向心刺</h1>
            <span className="text-xs text-gray-500 font-mono">策略控制台 v2.0</span>
          </div>
        </div>
        <nav className="p-3 space-y-0.5">
          {navItems.map(({ id, label, Icon }) => {
            const isActive = location.pathname === id
            return (
              <button key={id} onClick={() => handleNav(id)}
                className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-sm transition-all ${isActive ? 'bg-purple-600 text-white shadow-lg shadow-purple-600/20' : 'text-gray-400 hover:bg-[#1F2937] hover:text-gray-100'}`}>
                <Icon className="h-4 w-4 shrink-0" />
                <span>{label}</span>
              </button>
            )
          })}
        </nav>
      </div>
      <div className="p-4 border-t border-[#1F2937] bg-[#0E1321] text-xs text-gray-500 space-y-1.5">
        <div className="flex items-center justify-between">
          <span>策略引擎:</span>
          {apiOnline
            ? <span className="flex items-center text-emerald-400 font-mono"><Wifi className="h-3 w-3 mr-1" />ONLINE</span>
            : <span className="flex items-center text-rose-500 font-mono"><ShieldAlert className="h-3 w-3 mr-1" />OFFLINE</span>}
        </div>
        <div className="font-mono">数据截止: {marketStatus?.db_latest_date || '—'}</div>
        
        {visitorStats && (
          <div className="pt-2 mt-2 border-t border-[#1F2937]/50 flex justify-between items-center text-[10px]">
            <span className="flex items-center gap-1 text-emerald-400/80 font-mono" title="今日访客(UV) / 今日浏览(PV)">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              探针: {visitorStats.today_uv} / {visitorStats.today_pv}
            </span>
            <span className="opacity-40 font-mono" title="累计访客(UV) / 累计浏览(PV)">
              总 {visitorStats.total_uv}/{visitorStats.total_pv}
            </span>
          </div>
        )}
      </div>
    </>
  )

  return (
    <div className="flex h-screen bg-[#0B0F19] text-gray-100 overflow-hidden font-sans">

      {/* ─── 桌面端侧边栏 (md+) ─────────────────────────────────── */}
      <aside className="hidden md:flex w-56 lg:w-64 bg-[#111827] border-r border-[#1F2937] flex-col justify-between shrink-0">
        <SidebarContent />
      </aside>

      {/* ─── 手机端遮罩 ────────────────────────────────────────── */}
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" onClick={() => setSidebarOpen(false)} />
      )}

      {/* ─── 手机端抽屉侧边栏 ──────────────────────────────────── */}
      <aside className={`md:hidden fixed top-0 left-0 h-full w-64 z-50 bg-[#111827] border-r border-[#1F2937] flex flex-col justify-between transition-transform duration-300 ease-in-out ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="absolute top-3 right-3">
          <button onClick={() => setSidebarOpen(false)} className="p-1.5 rounded-lg text-gray-400 hover:bg-[#1F2937]">
            <X className="h-4 w-4" />
          </button>
        </div>
        <SidebarContent />
      </aside>

      {/* ─── 主体内容 ─────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-hidden bg-[#0D1220] min-w-0">

        {/* 顶栏 */}
        <header className="h-12 md:h-16 border-b border-[#1F2937] flex items-center justify-between px-3 md:px-8 bg-[#111827] shrink-0 gap-2">
          <div className="flex items-center gap-2 min-w-0">
            {/* 手机端汉堡菜单 */}
            <button onClick={() => setSidebarOpen(true)} className="md:hidden p-1.5 rounded-lg text-gray-400 hover:bg-[#1F2937] shrink-0">
              <Menu className="h-5 w-5" />
            </button>
            <h2 className="text-sm md:text-lg font-semibold text-gray-100 truncate">
              {pageTitle[currentPath] || '策略控制台'}
            </h2>
          </div>

          {/* 桌面端完整按钮组 */}
          <div className="hidden md:flex items-center gap-3">
            <div className="flex items-center gap-2 mr-2 text-xs font-mono text-gray-400 bg-[#151d32] px-3 py-1.5 rounded border border-slate-700/50 relative group cursor-help z-50">
              <span className={`h-2 w-2 rounded-full ${marketStatus?.db_health === 'ERROR' ? 'bg-rose-500 animate-ping' : marketStatus?.db_health === 'PARTIAL_DATA' ? 'bg-amber-400 animate-pulse' : (marketStatus?.db_latest_date && marketStatus.db_latest_date !== '—' ? 'bg-emerald-400' : 'bg-rose-400')}`} />
              {marketStatus?.db_health === 'ERROR' ? <span className="text-rose-400 font-bold">数据异常熔断锁定</span> : marketStatus?.db_health === 'PARTIAL_DATA' ? `数据更新至: ${marketStatus?.db_latest_date} (部分暂缺)` : `数据更新至: ${marketStatus?.db_latest_date || '加载中...'}`}
              
              {/* 健康状态 Tooltip */}
              {marketStatus?.health_issues && marketStatus.health_issues.length > 0 && (
                <div className="absolute top-full left-0 mt-2 w-80 p-3 bg-gray-900 border border-gray-700 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all">
                  <div className="text-gray-300 font-bold mb-1">系统巡检报告:</div>
                  <ul className="list-disc pl-4 space-y-1 text-gray-400 whitespace-normal">
                    {marketStatus.health_issues.map((issue, idx) => (
                      <li key={idx} className={marketStatus.db_health === 'ERROR' ? 'text-rose-400' : ''}>{issue}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <button onClick={handleFetch} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-sky-600/20 text-sky-400 border border-sky-600/30 hover:bg-sky-600/30 active:scale-95 transition-all">
              <Download className="h-3.5 w-3.5" /><span>拉取数据</span>
            </button>
            <button 
              onClick={handleScan} 
              disabled={marketStatus?.db_health === 'ERROR'}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${marketStatus?.db_health === 'ERROR' ? 'bg-rose-900/20 text-rose-500/50 border-rose-900/30 cursor-not-allowed' : 'bg-amber-600/20 text-amber-400 border-amber-600/30 hover:bg-amber-600/30 active:scale-95'}`}
            >
              <ScanSearch className="h-3.5 w-3.5" /><span>扫描因子</span>
            </button>
            <button onClick={handleBacktest} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600/20 text-emerald-400 border border-emerald-600/30 hover:bg-emerald-600/30 active:scale-95 transition-all">
              <RefreshCw className="h-3.5 w-3.5" /><span>更新回测</span>
            </button>
            <StrategySelector upsertToast={upsertToast} />
            <button onClick={() => navigate('/logs')} className="text-xs px-3 py-1 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20 font-mono hover:bg-purple-500/20 transition-colors">
              自适应路由模式
            </button>
          </div>

          {/* 手机端折叠操作菜单 */}
          <div className="md:hidden relative shrink-0">
            <button onClick={() => setActionsOpen(v => !v)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-purple-600/20 text-purple-400 border border-purple-600/30 active:scale-95 transition-all">
              操作
              {actionsOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </button>
            {actionsOpen && (
              <div className="absolute right-0 top-full mt-1 w-40 bg-[#111827] border border-[#1F2937] rounded-xl shadow-2xl z-50 overflow-hidden">
                <div className="px-3 py-2 text-[10px] text-gray-500 font-mono border-b border-[#1F2937]">
                  数据: {marketStatus?.db_latest_date || '—'} {marketStatus?.db_health === 'PARTIAL_DATA' && <span className="text-amber-400">(暂缺)</span>}
                </div>
                <button onClick={handleFetch} className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-sky-400 hover:bg-[#1F2937] transition-colors">
                  <Download className="h-4 w-4" />拉取数据
                </button>
                <button onClick={handleScan} className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-amber-400 hover:bg-[#1F2937] transition-colors">
                  <ScanSearch className="h-4 w-4" />扫描因子
                </button>
                <button onClick={handleBacktest} className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-emerald-400 hover:bg-[#1F2937] transition-colors">
                  <RefreshCw className="h-4 w-4" />更新回测
                </button>
              </div>
            )}
          </div>
        </header>

        {/* 内容区：手机底部为 Tab 栏留出空间 */}
        <div className="content-safe-bottom flex-1 overflow-y-auto p-3 md:p-8 md:pb-8">
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
              <Route path="/portrait" element={<PortraitAnalysis />} />
              <Route path="/position-pick" element={<PositionPick />} />
              <Route path="/jack" element={<JackMode />} />
              <Route path="/scanner" element={<Scanner />} />
              <Route path="/scan-history" element={<ScanHistory />} />
              <Route path="/diagnose" element={<Diagnose />} />
              <Route path="/diagnosis" element={<Diagnosis />} />
              <Route path="/logs" element={<Logs />} />
              <Route path="/hunter" element={<WinRateHunter upsertToast={upsertToast} removeToast={removeToast} pollTask={pollTask} />} />
            </Routes>
          )}
        </div>
      </main>

      {/* ─── 手机端悬浮缩放控制器（仅手机可见，桌面由 CSS 隐藏）── */}
      <div className="zoom-fab">
        {/* 放大按钮 */}
        <button onClick={zoomIn} title="放大" aria-label="放大">＋</button>
        {/* 分隔线 */}
        <div className="zoom-fab-divider" />
        {/* 百分比（点击重置） */}
        <button className="zoom-pct" onClick={zoomReset} title="点击重置" aria-label="重置缩放">
          {Math.round(zoomLevel * 100)}%
        </button>
        {/* 分隔线 */}
        <div className="zoom-fab-divider" />
        {/* 缩小按钮 */}
        <button onClick={zoomOut} title="缩小" aria-label="缩小">－</button>
      </div>

      {/* ─── 手机端底部 Tab 导航栏 ────────────────────────────── */}
      <nav className="mobile-tab-bar md:hidden fixed bottom-0 left-0 right-0 z-30 bg-[#111827]/95 backdrop-blur-md border-t border-[#1F2937] flex items-stretch">
        {mobileNavItems.map(({ id, label, Icon }) => {
          const isActive = location.pathname === id
          return (
            <button key={id} onClick={() => handleNav(id)}
              className={`flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-all active:scale-95 relative ${isActive ? 'text-purple-400' : 'text-gray-500'}`}>
              {isActive && <span className="absolute top-0 left-1/2 -translate-x-1/2 h-0.5 w-8 bg-purple-500 rounded-b-full" />}
              <Icon className="h-5 w-5" />
              <span>{label}</span>
            </button>
          )
        })}
        {/* 更多按钮 */}
        <button onClick={() => setSidebarOpen(true)}
          className="flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium text-gray-500 active:scale-95">
          <Menu className="h-5 w-5" />
          <span>更多</span>
        </button>
      </nav>

      {/* ─── 全局 Toast 浮层 ──────────────────────────────────── */}
      <div className="fixed bottom-16 md:bottom-6 right-4 md:right-6 z-50 flex flex-col gap-2 w-72 md:w-80 pointer-events-none">
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
