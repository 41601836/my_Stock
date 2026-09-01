import React, { useState, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, ReferenceLine, Cell
} from 'recharts'
import { RefreshCw, TrendingUp, TrendingDown, Target, Zap, ShieldCheck, AlertTriangle } from 'lucide-react'

// ── 画像等级配置 ──────────────────────────────────────────────────────────────
const GRADE_CFG = {
  A: { color: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.3)', emoji: '🔥', label: 'A级·强烈推荐' },
  B: { color: '#38bdf8', bg: 'rgba(56,189,248,0.10)', border: 'rgba(56,189,248,0.3)', emoji: '✅', label: 'B级·符合画像' },
  C: { color: '#f59e0b', bg: 'rgba(245,158,11,0.10)', border: 'rgba(245,158,11,0.3)', emoji: '⚠️', label: 'C级·勉强通过' },
  D: { color: '#f43f5e', bg: 'rgba(244,63,94,0.10)',  border: 'rgba(244,63,94,0.3)',  emoji: '❌', label: 'D级·画像不符' },
}

// ── 因子中文名映射 ────────────────────────────────────────────────────────────
const FACTOR_NAMES = {
  score:                   '因子综合得分',
  winner_rate:             '历史胜率（越低反而更好）',
  chips_concentration:     '筹码集中度',
  profit_ratio_estimate:   '获利筹码比例（越低越好）',
  pe_ttm:                  '市盈率PE（越低越好）',
  hot_money_score:         '游资热度（越低越好）',
  return_5d:               '5日涨幅（越低越好）',
  return_20d:              '20日涨幅',
  return_60d:              '60日涨幅',
  volatility_60d:          '60日波动率',
  north_net_inflow_ratio:  '主力净流入比率',
  vol_ratio:               '量比（5日/60日）',
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────
const fmtPct = (v) => v != null ? `${(v * 100).toFixed(1)}%` : '--'
const fmtRet = (v) => {
  if (v == null) return '--'
  const s = (v * 100).toFixed(2)
  return v >= 0 ? `+${s}%` : `${s}%`
}
const retColor = (v) => v > 0 ? '#f43f5e' : v < 0 ? '#10b981' : '#9ca3af'  // 平盘显示灰色

// ── 自定义 Tooltip ────────────────────────────────────────────────────────────
const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: 8, padding: '8px 12px', fontSize: 11, fontFamily: 'monospace' }}>
      <div style={{ color: '#8b949e', marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color || '#e6edf3' }}>
          {p.name}: <span style={{ color: '#e6edf3', fontWeight: 700 }}>{typeof p.value === 'number' ? (p.name?.includes('%') || p.name?.includes('率') ? fmtPct(p.value) : p.value.toFixed(4)) : p.value}</span>
        </div>
      ))}
    </div>
  )
}

// ── 胜率颜色 ──────────────────────────────────────────────────────────────────
const wrColor = (wr) => {
  if (wr >= 0.75) return '#10b981'
  if (wr >= 0.60) return '#38bdf8'
  if (wr >= 0.45) return '#f59e0b'
  return '#f43f5e'
}

export default function PortraitAnalysis() {
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState(null)
  const [days, setDays]     = useState(10)
  const [activeTab, setActiveTab] = useState('overview') // overview | factors | samples

  const fetchData = async (d = days) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/portrait/analysis?days=${d}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      if (json.error) throw new Error(json.error)
      setData(json)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData(days) }, [])

  const handleDaysChange = (d) => {
    setDays(d)
    fetchData(d)
  }

  // ── 渲染 ────────────────────────────────────────────────────────────────────
  return (
    <div style={{ fontFamily: 'Inter, monospace', color: '#e6edf3', minHeight: '100vh' }}>

      {/* 页头 */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h2 style={{ fontSize: 22, fontWeight: 800, margin: 0, background: 'linear-gradient(135deg, #a78bfa, #38bdf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              📊 T+1 上涨画像分析
            </h2>
            <p style={{ color: '#8b949e', fontSize: 12, margin: '4px 0 0', fontFamily: 'monospace' }}>
              基于实证推荐记录，解析上涨 vs 下跌股票的多维因子差异
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* 天数选择器 */}
            {[7, 10, 20].map(d => (
              <button key={d} onClick={() => handleDaysChange(d)}
                style={{
                  padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600, fontFamily: 'monospace', cursor: 'pointer', transition: 'all 0.2s',
                  background: days === d ? 'rgba(139,92,246,0.25)' : 'rgba(255,255,255,0.05)',
                  border: days === d ? '1px solid rgba(139,92,246,0.5)' : '1px solid #30363d',
                  color: days === d ? '#a78bfa' : '#8b949e',
                }}>
                近{d}天
              </button>
            ))}
            <button onClick={() => fetchData(days)}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px', borderRadius: 8, fontSize: 12, background: 'rgba(56,189,248,0.15)', border: '1px solid rgba(56,189,248,0.3)', color: '#38bdf8', cursor: 'pointer' }}>
              <RefreshCw size={13} /> 刷新
            </button>
          </div>
        </div>
      </div>

      {/* 加载 / 错误 */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: '#8b949e', fontFamily: 'monospace' }}>
          <div style={{ width: 36, height: 36, border: '3px solid #30363d', borderTopColor: '#a78bfa', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto 16px' }} />
          正在计算画像分析数据...
        </div>
      )}
      {error && (
        <div style={{ background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.3)', borderRadius: 12, padding: '16px 20px', color: '#f43f5e', fontFamily: 'monospace', fontSize: 13 }}>
          ❌ {error}
        </div>
      )}

      {/* 主内容 */}
      {!loading && !error && data && (
        <>
          {/* ── 顶部汇总卡片 ── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16, marginBottom: 28 }}>
            {[
              { label: '分析样本', value: data.summary.total, unit: '条', icon: Target, color: '#a78bfa' },
              { label: '整体T+1胜率', value: fmtPct(data.summary.win_rate), unit: '', icon: TrendingUp, color: wrColor(data.summary.win_rate) },
              { label: '平均T+1收益', value: fmtRet(data.summary.avg_ret_1d), unit: '', icon: Zap, color: retColor(data.summary.avg_ret_1d) },
              { label: '分析周期', value: data.summary.analysis_days, unit: '天', icon: ShieldCheck, color: '#38bdf8' },
            ].map(({ label, value, unit, icon: Icon, color }) => (
              <div key={label} style={{ background: '#151d30', border: '1px solid #222f4c', borderRadius: 14, padding: '18px 20px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <Icon size={15} style={{ color }} />
                  <span style={{ fontSize: 11, color: '#8b949e', fontFamily: 'monospace' }}>{label}</span>
                </div>
                <div style={{ fontSize: 26, fontWeight: 800, color, fontFamily: 'monospace', lineHeight: 1 }}>
                  {value}<span style={{ fontSize: 13, fontWeight: 400, color: '#8b949e', marginLeft: 4 }}>{unit}</span>
                </div>
              </div>
            ))}
          </div>

          {/* ── Tab 切换 ── */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 24, background: '#0e1524', borderRadius: 10, padding: 4, width: 'fit-content' }}>
            {[
              { id: 'overview', label: '📈 胜率总览' },
              { id: 'factors',  label: '🔬 因子对比' },
              { id: 'samples',  label: '📋 样本明细' },
            ].map(({ id, label }) => (
              <button key={id} onClick={() => setActiveTab(id)}
                style={{
                  padding: '8px 18px', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', transition: 'all 0.2s', border: 'none',
                  background: activeTab === id ? '#1f2d4a' : 'transparent',
                  color: activeTab === id ? '#a78bfa' : '#8b949e',
                  boxShadow: activeTab === id ? '0 2px 8px rgba(0,0,0,0.3)' : 'none',
                }}>
                {label}
              </button>
            ))}
          </div>

          {/* ═══════════════ TAB: 胜率总览 ═══════════════ */}
          {activeTab === 'overview' && (
            <div style={{ display: 'grid', gap: 20 }}>

              {/* 画像等级胜率 */}
              {data.grade_stats?.length > 0 && (
                <div style={{ background: '#151d30', border: '1px solid #222f4c', borderRadius: 14, padding: '20px 24px' }}>
                  <h3 style={{ fontSize: 14, fontWeight: 700, color: '#e6edf3', margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>🏷️</span> 画像等级 T+1 胜率
                    <span style={{ fontSize: 11, color: '#8b949e', fontWeight: 400, marginLeft: 4 }}>基于5维评分：位置/估值/温度/筹码/因子</span>
                  </h3>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
                    {data.grade_stats.map(g => {
                      const cfg = GRADE_CFG[g.grade] || GRADE_CFG.C
                      return (
                        <div key={g.grade} style={{ background: cfg.bg, border: `1px solid ${cfg.border}`, borderRadius: 12, padding: '16px 20px' }}>
                          <div style={{ fontSize: 13, fontWeight: 700, color: cfg.color, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                            {cfg.emoji} {cfg.label}
                          </div>
                          <div style={{ fontSize: 28, fontWeight: 900, color: wrColor(g.win_rate), fontFamily: 'monospace', lineHeight: 1 }}>
                            {fmtPct(g.win_rate)}
                          </div>
                          <div style={{ fontSize: 11, color: '#8b949e', marginTop: 6, fontFamily: 'monospace' }}>
                            {g.up}/{g.total} 上涨 · 均收益 <span style={{ color: retColor(g.avg_ret) }}>{fmtRet(g.avg_ret)}</span>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* 每日胜率时序 */}
              <div style={{ background: '#151d30', border: '1px solid #222f4c', borderRadius: 14, padding: '20px 24px' }}>
                <h3 style={{ fontSize: 14, fontWeight: 700, color: '#e6edf3', margin: '0 0 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span>📅</span> 每日 T+1 胜率时序
                </h3>
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={data.daily_win_rate} margin={{ top: 4, right: 20, left: -10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2d4a" />
                    <XAxis dataKey="recommend_date" tick={{ fill: '#8b949e', fontSize: 10 }} tickFormatter={d => d?.slice(4)} />
                    <YAxis tick={{ fill: '#8b949e', fontSize: 10 }} tickFormatter={v => `${(v*100).toFixed(0)}%`} domain={[0, 1]} />
                    <Tooltip content={<ChartTooltip />} />
                    <ReferenceLine y={0.5} stroke="#f59e0b" strokeDasharray="4 4" strokeOpacity={0.6} label={{ value: '50%', fill: '#f59e0b', fontSize: 10 }} />
                    <Line type="monotone" dataKey="win_rate" name="当日胜率" stroke="#a78bfa" strokeWidth={2} dot={{ fill: '#a78bfa', r: 4 }} activeDot={{ r: 6 }} />
                    <Line type="monotone" dataKey="avg_ret" name="平均收益" stroke="#10b981" strokeWidth={1.5} strokeDasharray="4 2" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* 三个分桶胜率图 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
                {[
                  { title: '📊 按 factor_score 分桶', data: data.score_buckets, key: 'score_buckets' },
                  { title: '📊 按历史胜率(winner_rate)分桶', data: data.wr_buckets, key: 'wr_buckets' },
                  { title: '📊 按筹码集中度分桶', data: data.chip_buckets, key: 'chip_buckets' },
                ].map(({ title, data: bData }) => (
                  <div key={title} style={{ background: '#151d30', border: '1px solid #222f4c', borderRadius: 14, padding: '18px 20px' }}>
                    <h3 style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3', margin: '0 0 14px' }}>{title}</h3>
                    <ResponsiveContainer width="100%" height={160}>
                      <BarChart data={bData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1f2d4a" />
                        <XAxis dataKey="bucket" tick={{ fill: '#8b949e', fontSize: 10 }} />
                        <YAxis tick={{ fill: '#8b949e', fontSize: 10 }} tickFormatter={v => `${(v*100).toFixed(0)}%`} domain={[0, 1]} />
                        <Tooltip content={<ChartTooltip />} />
                        <Bar dataKey="win_rate" name="T+1胜率" radius={[4,4,0,0]}>
                          {bData?.map((entry, i) => (
                            <Cell key={i} fill={wrColor(entry.win_rate)} fillOpacity={0.85} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                    {/* 表格补充 */}
                    <div style={{ marginTop: 12, fontSize: 11, fontFamily: 'monospace', color: '#8b949e' }}>
                      {bData?.map(b => (
                        <div key={b.bucket} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: '1px solid #1a2540' }}>
                          <span>{b.bucket}</span>
                          <span style={{ color: wrColor(b.win_rate) }}>{fmtPct(b.win_rate)}</span>
                          <span style={{ color: '#6b7280' }}>{b.up}/{b.total}</span>
                          <span style={{ color: retColor(b.avg_ret) }}>{fmtRet(b.avg_ret)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ═══════════════ TAB: 因子对比 ═══════════════ */}
          {activeTab === 'factors' && (
            <div style={{ background: '#151d30', border: '1px solid #222f4c', borderRadius: 14, padding: '20px 24px' }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: '#e6edf3', margin: '0 0 20px', display: 'flex', alignItems: 'center', gap: 8 }}>
                🔬 上涨组 vs 下跌组 · 关键因子均值对比
                <span style={{ fontSize: 11, color: '#8b949e', fontWeight: 400 }}>绿色=上涨组更优，红色=下跌组更大</span>
              </h3>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'monospace', fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: '#0e1524', color: '#8b949e', fontSize: 11 }}>
                      <th style={{ padding: '10px 16px', textAlign: 'left', borderBottom: '1px solid #222f4c' }}>因子</th>
                      <th style={{ padding: '10px 16px', textAlign: 'right', borderBottom: '1px solid #222f4c', color: '#10b981' }}>上涨组均值</th>
                      <th style={{ padding: '10px 16px', textAlign: 'right', borderBottom: '1px solid #222f4c', color: '#f43f5e' }}>下跌组均值</th>
                      <th style={{ padding: '10px 16px', textAlign: 'right', borderBottom: '1px solid #222f4c' }}>差值</th>
                      <th style={{ padding: '10px 16px', textAlign: 'center', borderBottom: '1px solid #222f4c' }}>方向</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.factor_compare?.map((f, i) => {
                      const upBetter = f.direction === 'up_better'
                      return (
                        <tr key={f.factor} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(30,40,70,0.3)' }}>
                          <td style={{ padding: '9px 16px', color: '#c9d1d9', borderBottom: '1px solid #1a2540' }}>
                            <div style={{ fontWeight: 600 }}>{FACTOR_NAMES[f.factor] || f.factor}</div>
                          </td>
                          <td style={{ padding: '9px 16px', textAlign: 'right', color: '#10b981', borderBottom: '1px solid #1a2540', fontWeight: 600 }}>
                            {f.up_mean.toFixed(4)}
                          </td>
                          <td style={{ padding: '9px 16px', textAlign: 'right', color: '#f43f5e', borderBottom: '1px solid #1a2540', fontWeight: 600 }}>
                            {f.dn_mean.toFixed(4)}
                          </td>
                          <td style={{ padding: '9px 16px', textAlign: 'right', color: upBetter ? '#10b981' : '#f43f5e', borderBottom: '1px solid #1a2540' }}>
                            {f.diff > 0 ? '+' : ''}{f.diff.toFixed(4)}
                          </td>
                          <td style={{ padding: '9px 16px', textAlign: 'center', borderBottom: '1px solid #1a2540' }}>
                            <span style={{
                              display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 700,
                              background: upBetter ? 'rgba(16,185,129,0.15)' : 'rgba(244,63,94,0.15)',
                              color: upBetter ? '#10b981' : '#f43f5e',
                              border: `1px solid ${upBetter ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}`,
                            }}>
                              {upBetter ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                              {upBetter ? '上涨更高' : '下跌更高'}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* 关键结论 */}
              <div style={{ marginTop: 20, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
                {[
                  { icon: '📉', title: '获利筹码比例 → 低位更好', desc: '上涨组中位数远低于下跌组，说明处于60日低位区的股票更容易被主力拉升', color: '#10b981' },
                  { icon: '💰', title: '历史胜率 → 反直觉！低反而更好', desc: 'winner_rate < 60% 的股票实际胜率 72%+，高历史胜率股票往往已"涨完"', color: '#f59e0b' },
                  { icon: '🌡️', title: '游资热度 → 未过热才是机会', desc: 'hot_money_score 低代表游资尚未介入，处于布局阶段，T+1更有拉升空间', color: '#38bdf8' },
                  { icon: '📊', title: 'PE估值 → 低估值才是保险', desc: '上涨组 PE 均值 < 下跌组约一半，基本面合理是抗风险的底线', color: '#a78bfa' },
                ].map(({ icon, title, desc, color }) => (
                  <div key={title} style={{ background: '#0e1524', border: '1px solid #1f2d4a', borderRadius: 10, padding: '14px 16px' }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color, marginBottom: 6 }}>{icon} {title}</div>
                    <div style={{ fontSize: 11, color: '#8b949e', lineHeight: 1.6 }}>{desc}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ═══════════════ TAB: 样本明细 ═══════════════ */}
          {activeTab === 'samples' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
              {/* 上涨样本（A股规范：红涨） */}
              <div style={{ background: '#151d30', border: '1px solid rgba(244,63,94,0.22)', borderRadius: 14, padding: '18px 20px' }}>
                <h3 style={{ fontSize: 14, fontWeight: 700, color: '#f43f5e', margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <TrendingUp size={16} /> 近期最佳上涨样本 (Top 15)
                </h3>
                <div style={{ fontSize: 11, fontFamily: 'monospace', overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ color: '#8b949e', borderBottom: '1px solid #1a2540' }}>
                        <th style={{ padding: '6px 8px', textAlign: 'left' }}>股票</th>
                        <th style={{ padding: '6px 8px', textAlign: 'right' }}>T+1</th>
                        <th style={{ padding: '6px 8px', textAlign: 'right' }}>画像</th>
                        <th style={{ padding: '6px 8px', textAlign: 'right' }}>获利筹</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_up_stocks?.map(s => {
                        const cfg = GRADE_CFG[s.portrait_grade] || GRADE_CFG.C
                        const ret = s.ret_1d
                        const retC = ret > 0 ? '#f43f5e' : ret < 0 ? '#10b981' : '#9ca3af'
                        return (
                          <tr key={`${s.ts_code}-${s.recommend_date}`} style={{ borderBottom: '1px solid #1a2540' }}>
                            <td style={{ padding: '6px 8px', color: '#c9d1d9' }}>
                              <div style={{ fontWeight: 700 }}>{s.name}</div>
                              <div style={{ color: '#8b949e', fontSize: 10 }}>{s.recommend_date?.slice(4)}</div>
                            </td>
                            <td style={{ padding: '6px 8px', textAlign: 'right', color: retC, fontWeight: 700 }}>
                              {fmtRet(ret)}
                            </td>
                            <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                              <span style={{ color: cfg.color, fontWeight: 700 }}>{cfg.emoji}{s.portrait_grade} {s.portrait_score}</span>
                            </td>
                            <td style={{ padding: '6px 8px', textAlign: 'right', color: '#8b949e' }}>
                              {(s.profit_ratio_estimate * 100).toFixed(1)}%
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* 下跌样本（A股规范：绿跌） */}
              <div style={{ background: '#151d30', border: '1px solid rgba(16,185,129,0.22)', borderRadius: 14, padding: '18px 20px' }}>
                <h3 style={{ fontSize: 14, fontWeight: 700, color: '#10b981', margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <TrendingDown size={16} /> 近期最深下跌样本 (反向参考)
                </h3>
                <div style={{ fontSize: 11, fontFamily: 'monospace', overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ color: '#8b949e', borderBottom: '1px solid #1a2540' }}>
                        <th style={{ padding: '6px 8px', textAlign: 'left' }}>股票</th>
                        <th style={{ padding: '6px 8px', textAlign: 'right' }}>T+1</th>
                        <th style={{ padding: '6px 8px', textAlign: 'right' }}>画像</th>
                        <th style={{ padding: '6px 8px', textAlign: 'right' }}>获利筹</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.top_dn_stocks?.map(s => {
                        const cfg = GRADE_CFG[s.portrait_grade] || GRADE_CFG.C
                        const ret = s.ret_1d
                        const retC = ret > 0 ? '#f43f5e' : ret < 0 ? '#10b981' : '#9ca3af'
                        return (
                          <tr key={`${s.ts_code}-${s.recommend_date}`} style={{ borderBottom: '1px solid #1a2540' }}>
                            <td style={{ padding: '6px 8px', color: '#c9d1d9' }}>
                              <div style={{ fontWeight: 700 }}>{s.name}</div>
                              <div style={{ color: '#8b949e', fontSize: 10 }}>{s.recommend_date?.slice(4)}</div>
                            </td>
                            <td style={{ padding: '6px 8px', textAlign: 'right', color: retC, fontWeight: 700 }}>
                              {fmtRet(ret)}
                            </td>
                            <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                              <span style={{ color: cfg.color, fontWeight: 700 }}>{cfg.emoji}{s.portrait_grade} {s.portrait_score}</span>
                            </td>
                            <td style={{ padding: '6px 8px', textAlign: 'right', color: '#8b949e' }}>
                              {(s.profit_ratio_estimate * 100).toFixed(1)}%
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* 分析区间说明 */}
          <div style={{ marginTop: 20, padding: '10px 16px', background: '#0e1524', border: '1px solid #1f2d4a', borderRadius: 10, fontSize: 11, color: '#8b949e', fontFamily: 'monospace', display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={13} style={{ color: '#f59e0b' }} />
            分析区间：{data.summary.date_range} · 共 {data.summary.total} 条推荐记录 · {data.summary.up_count} 条上涨 / {data.summary.dn_count} 条下跌
          </div>
        </>
      )}

      {/* 旋转动画 */}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
