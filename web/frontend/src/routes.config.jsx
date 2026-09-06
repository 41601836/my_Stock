/**
 * routes.config.jsx —— 经典层单一路由表（Single Source of Truth）
 * =====================================================
 * 一份配置同时驱动：侧边栏分组导航 / <Routes> 路由注册 / 顶栏页面标题。
 * 新增页面只需在此加一行；EVO 进化层保持独立（/evo/*，见 App.jsx 与 evo/EvoLayout.jsx）。
 *
 * 字段说明：
 *   path      路由路径（也是唯一键）
 *   label     侧边栏显示名
 *   title     顶栏页面标题
 *   group     侧边栏分组 id（NAV_GROUPS 之一；为 null 表示不出现在侧边栏）
 *   Icon      lucide 图标组件
 *   Component 页面组件（懒加载可后续在此统一替换）
 *   props     可选：向页面注入的运行时依赖（marketStatus / toast 工具等）
 */
import {
  LayoutDashboard, Globe, ScanSearch, FileSearch, Activity,
  Target, Zap, TrendingUp, BarChart3, Trophy, Terminal, Medal, Sparkles, Layers,
} from 'lucide-react'
import Dashboard from './Dashboard'
import Overview from './Overview'
import Performance from './Performance'
import Factors from './Factors'
import PortraitAnalysis from './PortraitAnalysis'
import PositionPick from './PositionPick'
import JackMode from './JackMode'
import ScannerLayout from './scanner/ScannerLayout'
import ScannerRealtime from './scanner/ScannerRealtime'
import ScannerSector from './scanner/ScannerSector'
import ScannerSummary from './scanner/ScannerSummary'
import ScannerStreak from './scanner/ScannerStreak'
import ScannerDaily from './scanner/ScannerDaily'
import RecoLayout from './reco/RecoLayout'
import RecoSummary from './reco/RecoSummary'
import RecoStreak from './reco/RecoStreak'
import RecoDaily from './reco/RecoDaily'
import ScanHistory from './ScanHistory'
import Diagnose from './Diagnose'
import Diagnosis from './Diagnosis'
import Logs from './Logs'
import WinRateHunter from './WinRateHunter'
import FactorLibrary from './FactorLibrary'
import MultiFactor202609 from './MultiFactor202609'

// 侧边栏分组（顺序即展示顺序；折叠状态持久化在 localStorage 'nav_groups_collapsed'）
export const NAV_GROUPS = [
  { id: 'overview', title: '全局总览' },
  { id: 'decision', title: '每日决策' },
  { id: 'review',   title: '绩效复盘' },
  { id: 'system',   title: '系统' },
]

export const ROUTES = [
  // ── 全局总览 ──────────────────────────────────────────────
  { path: '/',          label: '核心策略仪表盘', title: '策略实时仪表盘',     group: 'overview', Icon: LayoutDashboard, Component: Dashboard,
    props: (ctx) => ({ marketStatus: ctx.marketStatus }) },
  { path: '/overview',  label: '市场宏观全览',   title: '市场宏观全览',       group: 'overview', Icon: Globe, Component: Overview },

  // ── 每日决策（按工作流排序：扫 → 诊 → 画像 → 建仓）────────
  // /scanner 采用父子路由结构：侧边栏只显示父项，子路由通过 scanner/ 目录下的页面组件承载
  { path: '/scanner',      label: '建仓机会扫描', title: '建仓机会实时扫描',     group: 'decision', Icon: ScanSearch, Component: ScannerLayout,
    children: [
      { index: true, title: '全市场实时扫描', element: <ScannerRealtime /> },
      { path: 'sector',  title: '专属板块扫描', element: <ScannerSector /> },
      { path: 'summary', title: '上榜频率统计', element: <ScannerSummary /> },
      { path: 'streak',  title: '连续上榜追踪', element: <ScannerStreak /> },
      { path: 'daily',   title: '每日快照',     element: <ScannerDaily /> },
    ]
  },
  { path: '/scan-history',  label: '扫描历史追踪',  title: '建仓扫描历史追踪',     group: 'decision', Icon: ScanSearch, Component: ScanHistory },
  // 今日策略推荐统计（策略：胜率猎手优化器；数据源 recommendation_tracker）
  { path: '/reco-history',  label: '今日策略推荐统计', title: '今日策略推荐统计',    group: 'decision', Icon: Medal, Component: RecoLayout,
    children: [
      { index: true, title: '上榜统计', element: <RecoSummary /> },
      { path: 'streak',  title: '连续上榜', element: <RecoStreak /> },
      { path: 'daily',   title: '每日统计', element: <RecoDaily /> },
    ]
  },
  // 旧路径永久重定向（兼容上次 Tab 整合产物 + V1.0.0 书签）
  { path: '/scanner/history', redirect: '/scan-history' },
  { path: '/diagnose',      label: '诊股看盘',       title: '诊股看盘',             group: 'decision', Icon: FileSearch, Component: Diagnose },
  { path: '/diagnosis',     label: '策略归因诊断',   title: '建仓策略归因诊断',     group: 'decision', Icon: Activity, Component: Diagnosis },
  { path: '/portrait',      label: 'T+1 画像分析',   title: 'T+1 上涨画像分析',     group: 'decision', Icon: Target, Component: PortraitAnalysis },
  { path: '/portrait-pick', label: '🎯 画像建仓决策', title: 'T+1 画像建仓决策',     group: 'decision', Icon: Target, Component: PositionPick },
  { path: '/position-pick', redirect: '/portrait-pick' },
  { path: '/portrait/pick', redirect: '/portrait-pick' },
  { path: '/jack',          label: '游资策略模拟',   title: '游资策略模拟',         group: 'decision', Icon: Zap, Component: JackMode },

  // ── 绩效复盘 ──────────────────────────────────────────────
  { path: '/performance', label: '周度绩效时序',   title: '多轨回测绩效曲线',     group: 'review', Icon: TrendingUp, Component: Performance },
  { path: '/factors',     label: '因子自适应权重', title: '因子自适应权重监控',   group: 'review', Icon: BarChart3, Component: Factors },
  { path: '/hunter',      label: '胜率猎手优化器', title: '胜率猎手进化引擎',     group: 'review', Icon: Trophy, Component: WinRateHunter,
    props: (ctx) => ({ upsertToast: ctx.upsertToast, removeToast: ctx.removeToast, pollTask: ctx.pollTask }) },

  // ── 系统 ──────────────────────────────────────────────────
  { path: '/logs',        label: 'Agent 进化日志', title: 'Agent 进化巡航监控',   group: 'system', Icon: Terminal, Component: Logs },
  // FactorLib 因子库（平行层，删除本行 + FactorLibrary.jsx 即回滚）
  { path: '/factor-lib',  label: '因子有效性分析', title: '因子有效性分析',       group: 'system', Icon: Sparkles, Component: FactorLibrary },
  // MF202609 多因子分析（平行层，删除本行 + MultiFactor202609.jsx 即回滚）
  { path: '/mf202609',    label: '202609多因子分析', title: '202609多因子分析',   group: 'system', Icon: Layers, Component: MultiFactor202609 },
]

// 顶栏页面标题解析：支持嵌套 children（Tab 子页）与 redirect 项
export function resolveTitle(pathname) {
  for (const r of ROUTES) {
    if (r.redirect) continue
    if (r.path === pathname) return r.title
    if (r.children) {
      for (const c of r.children) {
        const full = c.index ? r.path : `${r.path}/${c.path}`
        if (full === pathname) return c.title || r.title
      }
    }
  }
  return '策略控制台'
}
