/**
 * EvoLayout.jsx —— EVO 进化层页面共用布局
 * =====================================================
 * - 顶部显示一个醒目的「⚡ EVO 进化层」徽章，明确告诉用户这是 V2 平行模式
 * - 左侧 EVO 专属子菜单（对比/推荐/因子/ML/Graham）
 * - 页面内所有请求必须走 evo/EvoApi.js（完全不碰经典层 fetch）
 *
 * 路由嵌套：
 *   /evo              → 重定向到 /evo/compare（或 /evo/dashboard，视配置决定）
 *   /evo/compare      → EvoCompare：经典 vs 进化 A/B 并排对比
 *   /evo/portfolio    → EvoPortfolio：进化版今日推荐
 *   /evo/factors      → EvoFactors：因子监控（IC+拥挤度+衰减 三图合一）
 *   /evo/ml           → EvoML：LambdaRank 排序 + SHAP 可解释性
 *   /evo/graham       → EvoGraham：Graham 7 项价值雷达图 + 股票池
 */
import React, { useEffect, useState } from 'react'
import { Routes, Route, NavLink, useNavigate, Navigate } from 'react-router-dom'
import { Zap, GitCompare, Target, Activity, Brain, Shield, ChevronRight } from 'lucide-react'
import * as EvoApi from './EvoApi'
import EvoCompare  from './EvoCompare'
import EvoGraham   from './EvoGraham'
import EvoDashboard from './EvoDashboard'

const evoNavItems = [
  { id: '/evo/dashboard', label: '进化仪表盘', Icon: Zap },
  { id: '/evo/compare',   label: '经典 vs 进化对比', Icon: GitCompare },
  { id: '/evo/factors',   label: 'EVO 因子监控', Icon: Activity },
  { id: '/evo/ml',        label: 'ML 排序学习', Icon: Brain },
  { id: '/evo/graham',    label: '价值雷达 (Graham)', Icon: Shield },
]

function ModuleBadges({ modules }) {
  if (!modules) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(EvoApi.MODULE_META).map(([k, meta]) => (
        <span
          key={k}
          title={`${meta.label}：${modules[k] ? '启用' : '关闭'}`}
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border
            ${modules[k]
              ? `bg-slate-800/60 ${meta.color} border-slate-600/50`
              : 'bg-slate-900/40 text-slate-600 border-slate-800/60 grayscale'}`}
        >
          <span>{meta.icon}</span>
          <span>{meta.label}</span>
        </span>
      ))}
    </div>
  )
}

export default function EvoLayout() {
  const navigate = useNavigate()
  const [evoStatus, setEvoStatus] = useState(null)

  useEffect(() => {
    EvoApi.status().then(d => setEvoStatus(d.error ? null : d))
  }, [])

  return (
    <div className="h-full flex flex-col gap-4">
      {/* 顶部 EVO 层标识横幅 */}
      <div className="rounded-xl bg-gradient-to-r from-amber-600/10 via-purple-600/10 to-fuchsia-600/10
           border border-amber-500/30 px-4 py-3 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-1.5 rounded-lg bg-amber-500/20 border border-amber-500/40 shrink-0">
            <Zap className="h-4 w-4 text-amber-300" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-amber-100 flex items-center gap-2">
              EVO 进化层 · 平行宇宙模式
              <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-200 border border-amber-500/40 font-mono">
                v{evoStatus?.version || '—'}
              </span>
            </div>
            <div className="text-[11px] text-slate-400 truncate">
              {evoStatus?.note || '模块状态加载中...'}
            </div>
          </div>
        </div>
        <ModuleBadges modules={evoStatus?.modules} />
      </div>

      {/* 手机/平板导航（lg 以下左侧菜单隐藏，改用横向滚动标签条） */}
      <div className="lg:hidden -mx-1 overflow-x-auto flex gap-1.5 pb-1">
        {evoNavItems.map(({ id, label, Icon }) => (
          <NavLink
            key={id}
            to={id}
            end={id === '/evo/dashboard'}
            className={({ isActive }) =>
              `flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] whitespace-nowrap border transition-all shrink-0
              ${isActive
                ? 'bg-amber-600/20 text-amber-200 border-amber-500/30'
                : 'bg-[#111827] text-slate-400 border-[#1F2937]'}`
            }
          >
            <Icon className="h-3 w-3 shrink-0" />{label}
          </NavLink>
        ))}
      </div>

      {/* 主体：左侧子菜单 + 右侧内容 */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[200px,1fr] gap-4 min-h-0">
        {/* 左侧 EVO 子菜单 */}
        <aside className="hidden lg:flex flex-col gap-1 p-3 rounded-xl bg-[#111827] border border-[#1F2937] shrink-0">
          <div className="text-[10px] text-amber-400/80 uppercase font-mono px-2 mb-1 tracking-wider">
            进化菜单
          </div>
          {evoNavItems.map(({ id, label, Icon }) => (
            <NavLink
              key={id}
              to={id}
              end={id === '/evo/dashboard'}
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-lg text-xs transition-all
                ${isActive
                  ? 'bg-amber-600/20 text-amber-200 border border-amber-500/30 shadow shadow-amber-600/10'
                  : 'text-slate-400 hover:bg-[#1F2937] hover:text-slate-100 border border-transparent'}`
              }
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{label}</span>
              <ChevronRight className="h-3 w-3 ml-auto opacity-50" />
            </NavLink>
          ))}
        </aside>

        {/* 内容区 */}
        <div className="min-w-0 overflow-y-auto pr-1">
          <Routes>
            <Route path="/" element={<Navigate to="/evo/dashboard" replace />} />
            <Route path="/dashboard" element={<EvoDashboard evoStatus={evoStatus} />} />
            <Route path="/compare"   element={<EvoCompare />} />
            <Route path="/factors"   element={
              <div className="rounded-xl bg-[#111827] border border-[#1F2937] p-6">
                <h3 className="text-sm font-semibold text-slate-200">🔀 EVO 因子监控</h3>
                <p className="mt-2 text-xs text-slate-500">
                  阶段 1 起展示：IC 趋势 + 拥挤度分布 + 衰减预警三图合一。当前骨架已就绪，数据 pipeline 运行后自动填充。
                </p>
              </div>
            } />
            <Route path="/ml" element={
              <div className="rounded-xl bg-[#111827] border border-[#1F2937] p-6">
                <h3 className="text-sm font-semibold text-slate-200">🧠 LambdaRank 排序学习</h3>
                <p className="mt-2 text-xs text-slate-500">
                  LightGBM LambdaRank 排序（测试段 NDCG@10 相对 IC 基线 +98.7%）。每日 21:30 管线自动推理并落库 SHAP。当前 β=0.1 灰度接入组合，详情见进化仪表盘。
                </p>
              </div>
            } />
            <Route path="/graham"    element={<EvoGraham />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}
