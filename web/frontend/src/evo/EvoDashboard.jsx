/**
 * EvoDashboard.jsx —— 进化层仪表盘首页
 *  6 个卡片：模块状态、经典/EVO 推荐概览、因子数量、拥挤度概览、衰减警告、快速导航
 */
import React, { useEffect, useState } from 'react'
import { Zap, GitCompare, Shield, Brain, Target, Activity, ChevronRight } from 'lucide-react'
import * as EvoApi from './EvoApi'

function Card({ title, icon: Icon, iconColor, children, accent, action }) {
  return (
    <div className={`rounded-xl border p-4 flex flex-col gap-3
      bg-[#111827] border-[#1F2937] ${accent ? `ring-1 ring-offset-0 ring-offset-transparent ${accent}` : ''}`}>
      <div className="flex items-center justify-between gap-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`p-1.5 rounded-lg shrink-0 ${iconColor || 'bg-purple-500/15 text-purple-300 border border-purple-500/30'}`}>
            {Icon ? <Icon className="h-4 w-4" /> : null}
          </div>
          <h3 className="text-sm font-semibold text-slate-100 truncate">{title}</h3>
        </div>
        {action || null}
      </div>
      <div className="flex-1 min-h-[60px]">{children}</div>
    </div>
  )
}

function ModuleChip({ key: k, enabled, meta }) {
  return (
    <div className={`px-2 py-1 rounded-lg text-[11px] border flex items-center gap-1.5
      ${enabled
        ? `${meta.color.replace('text-', 'bg-').replace('-300', '-500/10')} ${meta.color} border-${meta.color.split('-')[1]}-500/30`
        : 'bg-slate-900/40 text-slate-600 border-slate-800/60 grayscale'}`}>
      <span>{meta.icon}</span>
      <span>{meta.label}</span>
      <span className={`ml-1 h-1.5 w-1.5 rounded-full ${enabled ? 'bg-emerald-400' : 'bg-slate-600'}`} />
    </div>
  )
}

export default function EvoDashboard({ evoStatus }) {
  const [stats, setStats] = useState(null)
  const [factors, setFactors] = useState(null)

  useEffect(() => {
    Promise.all([EvoApi.status(), EvoApi.factorsList()]).then(([s, f]) => {
      if (!s.error) setStats(s)
      if (!f.error) setFactors(f)
    })
  }, [])

  const modules = (stats || evoStatus || {}).modules || {}
  const enabledCount = Object.values(modules).filter(Boolean).length
  const totalCount = Object.keys(EvoApi.MODULE_META).length

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {/* 1. 模块状态总览 */}
        <Card
          title="进化层模块总览"
          icon={Zap}
          iconColor="bg-amber-500/15 text-amber-300 border border-amber-500/30"
          action={<div className="text-[11px] font-mono text-amber-300 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/30">
            {enabledCount}/{totalCount} 启用
          </div>}
        >
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(EvoApi.MODULE_META).map(([k, meta]) => (
              <ModuleChip key={k} k={k} enabled={!!modules[k]} meta={meta} />
            ))}
          </div>
        </Card>

        {/* 2. 经典 vs 进化 快速跳转 */}
        <Card
          title="A/B 对比分析（核心验证页）"
          icon={GitCompare}
          iconColor="bg-sky-500/15 text-sky-300 border border-sky-500/30"
          action={<a href="#/evo/compare" className="text-[11px] text-sky-300 flex items-center gap-0.5">
            进入 <ChevronRight className="h-3 w-3" />
          </a>}
        >
          <div className="text-xs text-slate-400 leading-relaxed">
            并排对比「经典今日推荐 vs 进化今日推荐」：
            <ul className="mt-2 space-y-0.5 pl-4 list-disc marker:text-sky-400/80">
              <li>Top10 列表的新增/剔除/共同项</li>
              <li>进化层各模块贡献徽章</li>
              <li>重合度与熔断提示（&lt; 20% 自动降级）</li>
            </ul>
          </div>
        </Card>

        {/* 3. 因子体系 */}
        <Card
          title="因子体系规模"
          icon={Target}
          iconColor="bg-purple-500/15 text-purple-300 border border-purple-500/30"
        >
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-700/40">
              <div className="text-[10px] text-slate-500 font-mono">经典因子</div>
              <div className="text-2xl font-bold text-purple-300 mt-1">
                {factors?.classic?.count || '—'}
              </div>
            </div>
            <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-700/40">
              <div className="text-[10px] text-slate-500 font-mono">EVO 交叉</div>
              <div className="text-2xl font-bold text-amber-300 mt-1">
                {factors?.evo_cross?.enabled_count || '—'}
              </div>
            </div>
          </div>
        </Card>

        {/* 4. 拥挤度监控 */}
        <Card
          title="拥挤度监控"
          icon={Activity}
          iconColor="bg-amber-500/15 text-amber-300 border border-amber-500/30"
        >
          <StatusBlock name="crowding_monitor" modules={modules} desc={
            <>因子截面自相关 &gt; 0.7 自动半权重；&gt; 0.85 直接禁用——拥挤度 0.968 的 ROE 预期差因子已被自动排除出当前组合。</>
          } />
        </Card>

        {/* 5. Graham 价值过滤器 */}
        <Card
          title="Graham 价值安全边际"
          icon={Shield}
          iconColor="bg-rose-500/15 text-rose-300 border border-rose-500/30"
          action={<a href="#/evo/graham" className="text-[11px] text-rose-300 flex items-center gap-0.5">
            进入 <ChevronRight className="h-3 w-3" />
          </a>}
        >
          <StatusBlock name="graham_filter" modules={modules} desc={
            <>7 项安全边际检查（A股宽松代理版）。≥4 项 → 画像分 +5；≤1 项 → 画像分 -10。当前全市场 ≥4 项共 3,689 只。</>
          } />
        </Card>

        {/* 6. ML 排序学习 */}
        <Card
          title="LambdaRank ML 排序"
          icon={Brain}
          iconColor="bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
        >
          <StatusBlock name="lambdarank" modules={modules} desc={
            <>LightGBM LambdaRank 优化 Top-K 排序（测试段 NDCG@10 相对 IC 基线 +98.7%）。每只股票输出 18 项 SHAP 贡献。当前 β=0.1 灰度接入组合，可一行配置回滚。</>
          } />
        </Card>
      </div>

      <div className="rounded-xl bg-slate-900/40 border border-slate-700/40 p-4 text-[11px] text-slate-500 leading-relaxed font-mono">
        💡 进化层提示：顶部 ⚡ EVO 按钮随时可切回经典模式；所有 EVO 请求均走 /api/evo/*，不影响 /api/* 的经典接口。
        每个模块独立配置在 <code className="px-1 py-0.5 rounded bg-slate-800 text-amber-300">config/evo.yaml</code>，可随时关闭/调整超参，热加载无需重启。
      </div>
    </div>
  )
}

function StatusBlock({ name, modules, desc }) {
  const meta = EvoApi.MODULE_META[name] || {}
  const on = !!modules[name]
  return (
    <div className="flex flex-col gap-2 h-full">
      <div className={`flex items-center gap-1.5 text-xs
        ${on ? 'text-emerald-300' : 'text-slate-500'}`}>
        <span>{meta.icon}</span>
        <span>{on ? `${meta.label} 已启用` : `${meta.label} 未启用`}</span>
        <span className={`ml-1 h-1.5 w-1.5 rounded-full ${on ? 'bg-emerald-400' : 'bg-slate-600'}`} />
      </div>
      <div className="text-[11px] text-slate-400 leading-relaxed flex-1">{desc}</div>
    </div>
  )
}
