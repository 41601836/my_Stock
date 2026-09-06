import React from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Crosshair, Layers, BarChart3, Flame, Calendar } from 'lucide-react'

// 子页 Tab 配置：id 是精确路由路径
const SUB_TABS = [
  { id: '/scanner',        label: '实时全市场',  icon: <Crosshair className="h-3.5 w-3.5" /> },
  { id: '/scanner/sector', label: '专属板块',    icon: <Layers className="h-3.5 w-3.5" /> },
  { id: '/scanner/summary',label: '上榜频率',    icon: <BarChart3 className="h-3.5 w-3.5" /> },
  { id: '/scanner/streak', label: '连续上榜',    icon: <Flame className="h-3.5 w-3.5" /> },
  { id: '/scanner/daily',  label: '每日快照',    icon: <Calendar className="h-3.5 w-3.5" /> },
]

export default function ScannerLayout() {
  const navigate = useNavigate()
  const location = useLocation()

  // 精确匹配：/scanner 只在 index 时点亮，子路由各自精确匹配
  const isActive = (tabId) => location.pathname === tabId

  return (
    <div className="space-y-6" id="scanner-layout">

      {/* ── 共享标题栏 ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-purple-500/15 border border-purple-500/30">
            <Crosshair className="h-6 w-6 text-purple-400 animate-pulse" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-100">建仓机会扫描</h2>
            <p className="text-xs text-gray-500 font-mono">
              实时扫描 · 专属板块 · 历史累计追踪
            </p>
          </div>
        </div>
      </div>

      {/* ── 子页 Tab 导航（flex-wrap 适配手机溢出） ── */}
      <div className="flex gap-1 bg-[#080F1C] p-1 rounded-xl border border-[#1A2840] w-fit flex-wrap">
        {SUB_TABS.map(t => {
          const active = isActive(t.id)
          return (
            <button key={t.id} onClick={() => navigate(t.id)}
              className={`flex items-center gap-1.5 py-2 px-3 sm:px-4 rounded-lg text-xs font-medium transition-all ${
                active
                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                  : 'text-gray-500 hover:text-gray-300'
              }`}>
              {t.icon}{t.label}
            </button>
          )
        })}
      </div>

      {/* ── 子路由内容区 ── */}
      <Outlet />
    </div>
  )
}
