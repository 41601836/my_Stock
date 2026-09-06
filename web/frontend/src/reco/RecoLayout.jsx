import React from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Medal, BarChart3, Flame, Calendar } from 'lucide-react'

// 子页 Tab 配置：id 是精确路由路径（index 页即"上榜统计"）
const SUB_TABS = [
  { id: '/reco-history',        label: '上榜统计', icon: <BarChart3 className="h-3.5 w-3.5" /> },
  { id: '/reco-history/streak', label: '连续上榜', icon: <Flame className="h-3.5 w-3.5" /> },
  { id: '/reco-history/daily',  label: '每日统计', icon: <Calendar className="h-3.5 w-3.5" /> },
]

export default function RecoLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const isActive = (tabId) => location.pathname === tabId

  return (
    <div className="space-y-6" id="reco-layout">

      {/* ── 共享标题栏（策略归属：胜率猎手优化器） ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-amber-500/15 border border-amber-500/30">
            <Medal className="h-6 w-6 text-amber-400" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2 flex-wrap">
              今日策略推荐统计
              <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30">
                策略：胜率猎手优化器
              </span>
            </h2>
            <p className="text-xs text-gray-500 font-mono">
              已部署策略每日推荐名单的累计追踪（数据源：recommendation_tracker）
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
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
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
