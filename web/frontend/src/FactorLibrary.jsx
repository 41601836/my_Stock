/**
 * FactorLibrary.jsx —— 因子有效性面板（零侵入，平行于经典层）
 * =========================================================
 * 依托 factor_lib 公共因子库，展示因子评级、分类统计、独立因子池等。
 * 数据源：/api/factor-lib/*（后端新增路由，不影响经典路由）
 *
 * 零侵入：删除本文件 + routes.config 中对应条目即回滚。
 */

import React, { useState, useEffect, useMemo } from 'react'
import {
  BarChart3, TrendingUp, Shield, Star, Layers,
  ArrowUpDown, Filter, ChevronDown, ChevronUp,
  Loader2, AlertCircle, Sparkles, Target, Award,
} from 'lucide-react'

const API_BASE = '/api/factor-lib'

// ── 颜色映射 ─────────────────────────────────────────────────
const GRADE_COLORS = {
  'S':  'text-amber-300 bg-amber-500/10 border-amber-500/30',
  'A+': 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
  'A':  'text-emerald-400 bg-emerald-500/5 border-emerald-500/20',
  'B+': 'text-sky-300 bg-sky-500/10 border-sky-500/30',
  'B':  'text-sky-400 bg-sky-500/5 border-sky-500/20',
  'C+': 'text-slate-300 bg-slate-500/10 border-slate-500/30',
  'C':  'text-slate-400 bg-slate-500/5 border-slate-500/20',
  'D':  'text-rose-400 bg-rose-500/10 border-rose-500/30',
}

const GRADE_BAR = {
  'S':  'bg-gradient-to-r from-amber-500 to-amber-400',
  'A+': 'bg-gradient-to-r from-emerald-500 to-emerald-400',
  'A':  'bg-emerald-500/70',
  'B+': 'bg-sky-500/70',
  'B':  'bg-sky-500/50',
  'C+': 'bg-slate-500/50',
  'C':  'bg-slate-500/30',
  'D':  'bg-rose-500/50',
}

// ── 工具函数 ─────────────────────────────────────────────────
const fmt = (v, d = 2) => v === null || v === undefined || isNaN(v) ? '—' : Number(v).toFixed(d)
const fmtPct = (v) => v === null || v === undefined || isNaN(v) ? '—' : `${(v * 100).toFixed(2)}%`

function StatCard({ icon: Icon, label, value, sub, accent = 'sky' }) {
  const accentMap = {
    sky:   'from-sky-500/20 to-sky-500/5 text-sky-300',
    amber: 'from-amber-500/20 to-amber-500/5 text-amber-300',
    emerald:'from-emerald-500/20 to-emerald-500/5 text-emerald-300',
    rose:  'from-rose-500/20 to-rose-500/5 text-rose-300',
    violet:'from-violet-500/20 to-violet-500/5 text-violet-300',
  }
  return (
    <div className="bg-[#0F172A]/60 backdrop-blur-sm border border-white/5 rounded-2xl p-4 hover:border-white/10 transition-all">
      <div className="flex items-center gap-3 mb-2">
        <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${accentMap[accent]} flex items-center justify-center`}>
          <Icon className="w-4.5 h-4.5" />
        </div>
        <span className="text-xs text-slate-400 font-medium">{label}</span>
      </div>
      <div className="text-2xl font-bold text-white tracking-tight">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  )
}

function GradeBadge({ grade }) {
  const cls = GRADE_COLORS[grade] || 'text-slate-400 bg-slate-500/5 border-slate-500/20'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-bold border ${cls}`}>
      {grade || '—'}
    </span>
  )
}

function ScoreBar({ score, maxScore = 7, grade }) {
  const pct = Math.min(100, (score / maxScore) * 100)
  return (
    <div className="flex items-center gap-2 w-28">
      <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${GRADE_BAR[grade] || 'bg-slate-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-slate-300 font-mono w-8 text-right">{score.toFixed(1)}</span>
    </div>
  )
}

// ── Tab 切换 ─────────────────────────────────────────────────
const TABS = [
  { id: 'ranking',  label: '因子评级排名', icon: Award },
  { id: 'categories', label: '分类统计',  icon: Layers },
  { id: 'independent', label: '独立因子池', icon: Target },
]

export default function FactorLibrary() {
  const [activeTab, setActiveTab] = useState('ranking')
  const [overview, setOverview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // 加载总览
  useEffect(() => {
    let mounted = true
    async function load() {
      try {
        const res = await fetch(`${API_BASE}/overview`)
        const data = await res.json()
        if (mounted) {
          if (data.success) setOverview(data)
          else setError(data.error || '加载失败')
          setLoading(false)
        }
      } catch (e) {
        if (mounted) { setError(e.message); setLoading(false) }
      }
    }
    load()
    return () => { mounted = false }
  }, [])

  return (
    <div className="p-5 space-y-5 max-w-[1400px] mx-auto">
      {/* 页面标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-amber-400" />
            因子有效性分析
            <span className="text-xs font-normal text-slate-500 ml-2">factor_lib · 公共因子库</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            基于 IC、分层测试、回测、防过拟的 7 维星级评级体系
          </p>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-4 text-rose-300 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          加载失败: {error}
        </div>
      )}

      {/* 总览卡片 */}
      {overview && !error && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <StatCard icon={BarChart3} label="总因子数" value={overview.total_factors} sub={`注册 ${overview.registry_total} 个`} accent="sky" />
          <StatCard icon={Star} label="平均得分" value={overview.avg_score} sub="满分 7.0" accent="amber" />
          <StatCard icon={Award} label="S 级" value={overview.s_count} sub="顶级因子" accent="amber" />
          <StatCard icon={TrendingUp} label="A 级" value={overview.a_count} sub="优秀因子" accent="emerald" />
          <StatCard icon={Shield} label="B 级" value={overview.b_count} sub="良好因子" accent="sky" />
          <StatCard icon={Layers} label="分类数" value={overview.category_count} sub="因子大类" accent="violet" />
        </div>
      )}

      {/* 加载中 */}
      {loading && (
        <div className="flex items-center justify-center py-20 text-slate-400">
          <Loader2 className="w-6 h-6 animate-spin mr-2" />
          加载因子库数据...
        </div>
      )}

      {/* Tab 切换 */}
      {!loading && !error && (
        <>
          <div className="flex gap-1 bg-[#0F172A]/40 p-1 rounded-xl border border-white/5 w-fit">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  activeTab === tab.id
                    ? 'bg-white/10 text-white shadow-sm'
                    : 'text-slate-400 hover:text-slate-300 hover:bg-white/5'
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab 内容 */}
          {activeTab === 'ranking' && <RankingTab />}
          {activeTab === 'categories' && <CategoriesTab />}
          {activeTab === 'independent' && <IndependentTab />}
        </>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Tab 1: 因子评级排名
// ═══════════════════════════════════════════════════════════════

function RankingTab() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [gradeFilter, setGradeFilter] = useState('')
  const [catFilter, setCatFilter] = useState('')
  const [sortBy, setSortBy] = useState('total_score')
  const [sortDir, setSortDir] = useState('desc')

  const loadData = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ limit: 100, offset: 0 })
      if (gradeFilter) params.set('grade', gradeFilter)
      if (catFilter) params.set('category', catFilter)
      const res = await fetch(`${API_BASE}/ranking?${params}`)
      const d = await res.json()
      if (d.success) {
        setData(d.data)
        setTotal(d.total)
      }
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  useEffect(() => { loadData() }, [gradeFilter, catFilter])

  const sortedData = useMemo(() => {
    const arr = [...data]
    arr.sort((a, b) => {
      let av = a[sortBy], bv = b[sortBy]
      if (av === null || av === undefined) av = -Infinity
      if (bv === null || bv === undefined) bv = -Infinity
      return sortDir === 'desc' ? bv - av : av - bv
    })
    return arr
  }, [data, sortBy, sortDir])

  const categories = useMemo(() => {
    const set = new Set(data.map(d => d.category).filter(Boolean))
    return Array.from(set).sort()
  }, [data])

  const handleSort = (col) => {
    if (sortBy === col) setSortDir(sortDir === 'desc' ? 'asc' : 'desc')
    else { setSortBy(col); setSortDir('desc') }
  }

  const SortHeader = ({ col, label, width }) => (
    <th
      className={`px-3 py-2 text-left text-xs font-semibold cursor-pointer hover:text-sky-300 transition-colors ${width || ''}`}
      onClick={() => handleSort(col)}
    >
      <div className="flex items-center gap-1">
        {label}
        {sortBy === col && (
          <ArrowUpDown className={`w-3 h-3 ${sortDir === 'desc' ? 'text-sky-400' : 'text-sky-400 rotate-180'}`} />
        )}
      </div>
    </th>
  )

  return (
    <div className="space-y-3">
      {/* 筛选栏 */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex items-center gap-2 text-xs">
          <Filter className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-slate-500">等级:</span>
          <select
            value={gradeFilter}
            onChange={e => setGradeFilter(e.target.value)}
            className="bg-[#0F172A] border border-white/10 rounded-lg px-2 py-1 text-xs text-slate-300 focus:outline-none focus:border-sky-500/50"
          >
            <option value="">全部</option>
            {['S','A+','A','B+','B','C+','C','D'].map(g => (
              <option key={g} value={g}>{g} 级</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">分类:</span>
          <select
            value={catFilter}
            onChange={e => setCatFilter(e.target.value)}
            className="bg-[#0F172A] border border-white/10 rounded-lg px-2 py-1 text-xs text-slate-300 focus:outline-none focus:border-sky-500/50"
          >
            <option value="">全部</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="text-xs text-slate-500 ml-auto">
          共 <span className="text-slate-300 font-mono">{total}</span> 个因子
        </div>
      </div>

      {/* 表格 */}
      <div className="bg-[#0F172A]/40 backdrop-blur-sm border border-white/5 rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-slate-400 border-b border-white/5 bg-white/[0.02]">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-semibold w-12">#</th>
                <th className="px-3 py-2 text-left text-xs font-semibold">因子</th>
                <th className="px-3 py-2 text-left text-xs font-semibold w-16">等级</th>
                <SortHeader col="total_score" label="综合得分" />
                <SortHeader col="icir" label="ICIR" />
                <SortHeader col="ic_mean" label="IC均值" />
                <SortHeader col="monotonicity" label="单调性" />
                <SortHeader col="sharpe" label="夏普比" />
                <SortHeader col="annual_return" label="年化收益" />
                <SortHeader col="max_drawdown" label="最大回撤" />
                <th className="px-3 py-2 text-left text-xs font-semibold w-24">分类</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.03]">
              {loading ? (
                <tr><td colSpan={11} className="text-center py-12 text-slate-500">
                  <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" />加载中...
                </td></tr>
              ) : sortedData.length === 0 ? (
                <tr><td colSpan={11} className="text-center py-12 text-slate-500">无数据</td></tr>
              ) : sortedData.map((row, i) => (
                <tr key={row.factor} className="hover:bg-white/[0.03] transition-colors">
                  <td className="px-3 py-2.5 text-slate-500 font-mono text-xs">{i + 1}</td>
                  <td className="px-3 py-2.5">
                    <div className="font-mono text-slate-200 text-sm">{row.factor}</div>
                    {row.description && <div className="text-xs text-slate-500 truncate max-w-[200px]">{row.description}</div>}
                  </td>
                  <td className="px-3 py-2.5"><GradeBadge grade={row.grade} /></td>
                  <td className="px-3 py-2.5"><ScoreBar score={row.total_score || 0} grade={row.grade} /></td>
                  <td className="px-3 py-2.5 font-mono text-xs text-slate-300">{fmt(row.icir, 3)}</td>
                  <td className="px-3 py-2.5 font-mono text-xs text-slate-400">{fmt(row.ic_mean, 4)}</td>
                  <td className="px-3 py-2.5 font-mono text-xs text-slate-400">{fmt(row.monotonicity, 3)}</td>
                  <td className="px-3 py-2.5 font-mono text-xs text-slate-300">{fmt(row.sharpe, 2)}</td>
                  <td className={`px-3 py-2.5 font-mono text-xs ${(row.annual_return || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {fmtPct(row.annual_return)}
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs text-rose-400">{fmtPct(row.max_drawdown)}</td>
                  <td className="px-3 py-2.5">
                    <span className="text-xs text-slate-400 bg-white/5 px-2 py-0.5 rounded-md">{row.category}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Tab 2: 分类统计
// ═══════════════════════════════════════════════════════════════

function CategoriesTab() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${API_BASE}/categories`)
        const d = await res.json()
        if (d.success) setData(d.categories)
      } catch (e) { console.error(e) }
      setLoading(false)
    }
    load()
  }, [])

  const maxScore = Math.max(...data.map(c => c.avg_score || 0), 1)

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {loading ? (
        <div className="col-span-full text-center py-16 text-slate-500">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2" />加载中...
        </div>
      ) : data.map(cat => (
        <div
          key={cat.category}
          className="bg-[#0F172A]/60 backdrop-blur-sm border border-white/5 rounded-2xl p-5 hover:border-white/10 transition-all group"
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="text-base font-bold text-white">{cat.category}</h3>
              <p className="text-xs text-slate-500 mt-0.5">{cat.n_factors} 个因子</p>
            </div>
            <div className="text-right">
              <div className="text-2xl font-bold text-amber-300">{fmt(cat.avg_score, 2)}</div>
              <div className="text-xs text-slate-500">平均得分</div>
            </div>
          </div>

          <div className="h-2 bg-white/5 rounded-full overflow-hidden mb-4">
            <div
              className="h-full bg-gradient-to-r from-amber-500 to-amber-400 rounded-full transition-all"
              style={{ width: `${(cat.avg_score / maxScore) * 100}%` }}
            />
          </div>

          <div className="grid grid-cols-3 gap-2 text-center">
            <div>
              <div className="text-sm font-mono text-sky-300">{fmt(cat.avg_icir, 2)}</div>
              <div className="text-xs text-slate-500">ICIR</div>
            </div>
            <div>
              <div className="text-sm font-mono text-emerald-300">{fmt(cat.avg_sharpe, 2)}</div>
              <div className="text-xs text-slate-500">夏普</div>
            </div>
            <div>
              <div className="text-xs">
                {cat.best_factor && <GradeBadge grade={cat.best_grade} />}
              </div>
              <div className="text-xs text-slate-500 mt-1 truncate">{cat.best_factor || '—'}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Tab 3: 独立因子池
// ═══════════════════════════════════════════════════════════════

function IndependentTab() {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`${API_BASE}/independent-factors`)
        const d = await res.json()
        if (d.success) setData(d.data)
      } catch (e) { console.error(e) }
      setLoading(false)
    }
    load()
  }, [])

  return (
    <div className="space-y-4">
      <div className="bg-gradient-to-r from-violet-500/10 to-sky-500/10 border border-violet-500/20 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <Target className="w-5 h-5 text-violet-400 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-white">独立因子池</h3>
            <p className="text-xs text-slate-400 mt-1">
              通过层次聚类（Ward 法）将因子划分为 {data.length || '若干'} 个独立簇，每簇选取代表性因子，
              用于多因子组合时降低因子间相关性，提升组合稳定性。
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        {loading ? (
          <div className="col-span-full text-center py-16 text-slate-500">
            <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2" />加载中...
          </div>
        ) : data.map((item, i) => (
          <div
            key={item.cluster}
            className="bg-[#0F172A]/60 backdrop-blur-sm border border-white/5 rounded-2xl p-5 hover:border-white/10 transition-all"
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-slate-500 font-medium">簇 {item.cluster}</span>
              {item.grade && <GradeBadge grade={item.grade} />}
            </div>

            <div className="font-mono text-lg font-bold text-white mb-1">
              {item.representative}
            </div>

            <div className="text-xs text-slate-500 mb-4">
              {item.members?.split(',').length || 0} 个成员因子
            </div>

            {item.total_score !== undefined && (
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500">综合得分</span>
                  <span className="text-slate-300 font-mono">{fmt(item.total_score, 1)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500">ICIR</span>
                  <span className="text-sky-300 font-mono">{fmt(item.icir, 3)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500">夏普比</span>
                  <span className="text-emerald-300 font-mono">{fmt(item.sharpe, 2)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500">年化收益</span>
                  <span className={`font-mono ${(item.annual_return || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {fmtPct(item.annual_return)}
                  </span>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {data.length > 0 && (
        <div className="bg-[#0F172A]/40 border border-white/5 rounded-2xl p-5">
          <h4 className="text-sm font-semibold text-white mb-3">各簇成员因子</h4>
          <div className="space-y-3">
            {data.map(item => (
              <div key={item.cluster} className="flex items-start gap-3">
                <span className="text-xs text-slate-500 font-mono w-12 flex-shrink-0 pt-1">簇{item.cluster}</span>
                <div className="flex flex-wrap gap-1.5">
                  {(item.members || '').split(',').map(m => (
                    <span key={m} className="text-xs font-mono bg-white/5 text-slate-300 px-2 py-0.5 rounded-md">
                      {m.trim()}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
