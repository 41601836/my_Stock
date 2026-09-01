import React, { useState, useEffect, useCallback } from 'react'
import { RefreshCw, Target, TrendingDown, Shield, Zap, Filter, ChevronDown, ChevronRight, AlertCircle, XCircle, Flame } from 'lucide-react'

// ── 画像等级配置 ───────────────────────────────────────────────────────────────
const GRADE_CFG = {
  A: { color: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.35)', emoji: '🔥', label: 'A级·强烈推荐', glow: '0 0 20px rgba(16,185,129,0.25)' },
  B: { color: '#38bdf8', bg: 'rgba(56,189,248,0.10)', border: 'rgba(56,189,248,0.35)', emoji: '✅', label: 'B级·符合画像', glow: '0 0 20px rgba(56,189,248,0.2)' },
  C: { color: '#f59e0b', bg: 'rgba(245,158,11,0.10)', border: 'rgba(245,158,11,0.3)',  emoji: '⚠️', label: 'C级·勉强通过', glow: 'none' },
  D: { color: '#f43f5e', bg: 'rgba(244,63,94,0.10)',  border: 'rgba(244,63,94,0.3)',   emoji: '❌', label: 'D级·画像不符', glow: 'none' },
}

// ── 格式化工具 ─────────────────────────────────────────────────────────────────
const fmtChg = (v) => {
  if (v == null) return '--'
  const s = Math.abs(v).toFixed(2)
  return v >= 0 ? `+${s}%` : `-${s}%`
}
const chgColor = (v) => v > 0 ? '#f43f5e' : v < 0 ? '#10b981' : '#8b949e'

// ── 5维评分条 ─────────────────────────────────────────────────────────────────
function DimensionBars({ details, strategy }) {
  const leftDims = [
    { key: '位置分', label: '📉 位置', desc: '低位筹码', color: '#10b981' },
    { key: '估值分', label: '💰 估值', desc: 'PE合理',   color: '#a78bfa' },
    { key: '温度分', label: '🌡️ 温度', desc: '游资冷',   color: '#38bdf8' },
    { key: '筹码分', label: '💎 筹码', desc: '高集中',   color: '#f59e0b' },
    { key: '因子分', label: '📊 因子', desc: '极强信号', color: '#ec4899' },
  ]
  const rightDims = [
    { key: '突破分', label: '🚀 突破', desc: '上方无压', color: '#10b981' },
    { key: '动能分', label: '🔥 动能', desc: '短期强势', color: '#f43f5e' },
    { key: '活跃分', label: '🌡️ 活跃', desc: '资金活跃', color: '#38bdf8' },
    { key: '集中分', label: '💎 集中', desc: '高度集中', color: '#f59e0b' },
    { key: '流入分', label: '💰 流入', desc: '主力抢筹', color: '#ec4899' },
  ]
  const dims = strategy === 'right' ? rightDims : leftDims;

  return (
    <div style={{ display: 'grid', gap: 8, marginTop: 14 }}>
      {dims.map(({ key, label, desc, color }) => {
        const val = details?.[key] ?? 0
        const pct = (val / 20) * 100
        return (
          <div key={key}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11 }}>
              <span style={{ color: '#8b949e', fontFamily: 'monospace' }}>{label} <span style={{ color: '#444' }}>({desc})</span></span>
              <span style={{ color, fontWeight: 700, fontFamily: 'monospace' }}>{val} / 20</span>
            </div>
            <div style={{ height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{
                height: '100%', width: `${pct}%`, borderRadius: 4,
                background: `linear-gradient(90deg, ${color}88, ${color})`,
                transition: 'width 0.8s cubic-bezier(0.4,0,0.2,1)',
                boxShadow: pct >= 90 ? `0 0 8px ${color}` : 'none',
              }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── 精选股票卡片 ───────────────────────────────────────────────────────────────
function PickCard({ pick, strategy }) {
  const cfg = GRADE_CFG[pick.portrait_grade] || GRADE_CFG.C
  const rankColors = ['#f59e0b', '#94a3b8', '#b45309', '#10b981', '#38bdf8']
  const rankLabels = ['🥇 首选', '🥈 次选', '🥉 备选', '🏅 四选', '🏅 五选']
  const rank = pick.pick_rank

  return (
    <div style={{
      background: `linear-gradient(145deg, ${cfg.bg}, rgba(15,19,30,0.9))`,
      border: `1px solid ${cfg.border}`,
      borderRadius: 18,
      padding: '24px 28px',
      boxShadow: cfg.glow,
      transition: 'transform 0.2s',
      cursor: 'default',
      position: 'relative',
      overflow: 'hidden',
    }}
      onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-3px)'}
      onMouseLeave={e => e.currentTarget.style.transform = 'translateY(0)'}
    >
      <div style={{
        position: 'absolute', top: -40, right: -40, width: 140, height: 140,
        borderRadius: '50%', background: `radial-gradient(circle, ${cfg.color}18 0%, transparent 70%)`,
        pointerEvents: 'none',
      }} />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 13, fontWeight: 800, color: rankColors[rank - 1] || '#8b949e', fontFamily: 'monospace', letterSpacing: 1 }}>
          {rankLabels[rank - 1] || `#${rank}`}
        </span>
        <span style={{
          padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 700,
          background: cfg.bg, border: `1px solid ${cfg.border}`, color: cfg.color,
        }}>
          {cfg.emoji} {cfg.label}
        </span>
      </div>

      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 22, fontWeight: 900, color: '#e6edf3', letterSpacing: 0.5 }}>{pick.name}</div>
        <div style={{ fontSize: 12, color: '#8b949e', fontFamily: 'monospace', marginTop: 3, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>{pick.ts_code}</span>
          <span>·</span>
          <span>{pick.sub_industry}</span>
          <span>·</span>
          <a
            href={`https://quote.eastmoney.com/${pick.ts_code.substring(7).toLowerCase()}${pick.ts_code.substring(0, 6)}.html`}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: '#38bdf8',
              textDecoration: 'none',
              borderBottom: '1px dashed #38bdf8',
              paddingBottom: 1,
            }}
            onMouseEnter={e => e.currentTarget.style.color = '#0ea5e9'}
            onMouseLeave={e => e.currentTarget.style.color = '#38bdf8'}
          >
            东方财富网 ↗
          </a>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 20, marginBottom: 14, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 2 }}>画像分</div>
          <div style={{ fontSize: 28, fontWeight: 900, color: cfg.color, fontFamily: 'monospace', lineHeight: 1 }}>{pick.portrait_score}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 2 }}>今日涨跌</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: chgColor(pick.pct_chg), fontFamily: 'monospace', lineHeight: 1 }}>{fmtChg(pick.pct_chg)}</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 2 }}>建议仓位</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#a78bfa', fontFamily: 'monospace', lineHeight: 1 }}>{pick.suggested_weight}%</div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 2 }}>收盘价</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#c9d1d9', fontFamily: 'monospace', lineHeight: 1 }}>¥{pick.close}</div>
        </div>
      </div>

      <div style={{
        padding: '8px 12px', background: 'rgba(255,255,255,0.04)', borderRadius: 8,
        fontSize: 12, color: '#a8b3c4', lineHeight: 1.6, marginBottom: 14,
        borderLeft: `3px solid ${cfg.color}66`,
      }}>
        {pick.pick_reason}
      </div>

      <DimensionBars details={pick.portrait_details} strategy={strategy} />

      <div style={{ display: 'flex', gap: 16, marginTop: 14, fontSize: 11, fontFamily: 'monospace', color: '#6b7280' }}>
        <span>筹码胜率 <span style={{ color: '#8b949e' }}>{pick.winner_rate}%</span></span>
        <span>净流入 <span style={{ color: pick.big_net_inflow > 0 ? '#f43f5e' : pick.big_net_inflow < 0 ? '#10b981' : '#8b949e' }}>{pick.big_net_inflow > 0 ? '+' : ''}{pick.big_net_inflow}亿</span></span>
        <span>建仓评分 <span style={{ color: '#8b949e' }}>{pick.build_score}</span></span>
      </div>
    </div>
  )
}

// ── 漏斗层 ────────────────────────────────────────────────────────────────────
function FunnelLayer({ icon: Icon, title, desc, inCount, outCount, rejectList, color, isLast }) {
  const [expanded, setExpanded] = useState(false)
  const hasRejects = rejectList?.length > 0

  return (
    <div>
      <div style={{
        background: '#131c2e', border: `1px solid ${color}44`,
        borderRadius: 14, padding: '16px 20px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
              background: `${color}20`, border: `2px solid ${color}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Icon size={16} style={{ color }} />
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3' }}>{title}</div>
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2, fontFamily: 'monospace' }}>{desc}</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            <span style={{ fontSize: 20, fontWeight: 900, color: '#e6edf3', fontFamily: 'monospace' }}>{inCount}</span>
            <span style={{ fontSize: 11, color: '#444' }}>→</span>
            <span style={{ fontSize: 20, fontWeight: 900, color, fontFamily: 'monospace' }}>{outCount}</span>
            {inCount - outCount > 0 && (
              <span style={{
                fontSize: 10, padding: '2px 6px', borderRadius: 999,
                background: 'rgba(244,63,94,0.12)', color: '#f43f5e', fontFamily: 'monospace',
              }}>-{inCount - outCount}</span>
            )}
          </div>
        </div>

        {hasRejects && (
          <button onClick={() => setExpanded(v => !v)} style={{
            marginTop: 12, display: 'flex', alignItems: 'center', gap: 6,
            background: 'none', border: 'none', color: '#8b949e', fontSize: 11,
            cursor: 'pointer', padding: '4px 0', fontFamily: 'monospace',
          }}>
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {expanded ? '收起' : `查看被排除的 ${rejectList.length} 支股票`}
          </button>
        )}

        {expanded && hasRejects && (
          <div style={{ marginTop: 8, display: 'grid', gap: 4 }}>
            {rejectList.map(r => (
              <div key={r.ts_code} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '6px 10px', background: 'rgba(244,63,94,0.06)',
                borderRadius: 8, fontSize: 11, fontFamily: 'monospace', flexWrap: 'wrap', gap: 4,
              }}>
                <span style={{ color: '#c9d1d9' }}>
                  <a
                    href={`https://quote.eastmoney.com/${r.ts_code.substring(7).toLowerCase()}${r.ts_code.substring(0, 6)}.html`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: '#38bdf8', textDecoration: 'none' }}
                    onMouseEnter={e => e.currentTarget.style.textDecoration = 'underline'}
                    onMouseLeave={e => e.currentTarget.style.textDecoration = 'none'}
                  >
                    {r.name}
                  </a>{' '}
                  <span style={{ color: '#555' }}>({r.ts_code})</span>
                  {r.portrait_grade && (
                    <span style={{ marginLeft: 6, color: (GRADE_CFG[r.portrait_grade] || GRADE_CFG.D).color }}>
                      {(GRADE_CFG[r.portrait_grade] || GRADE_CFG.D).emoji}{r.portrait_grade} {r.portrait_score}
                    </span>
                  )}
                </span>
                <span style={{ color: '#f43f5e', fontSize: 10 }}>{r.reject_reason}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {!isLast && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '4px 0' }}>
          <div style={{ width: 2, height: 10, background: '#1f2d4a' }} />
          <div style={{ width: 0, height: 0, borderLeft: '6px solid transparent', borderRight: '6px solid transparent', borderTop: '8px solid #1f2d4a' }} />
        </div>
      )}
    </div>
  )
}

// ── 主页面 ────────────────────────────────────────────────────────────────────
export default function PositionPick() {
  const [strategy, setStrategy] = useState('left')
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/portrait/position-pick?top_n=30&strategy=${strategy}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      if (json.meta?.error) throw new Error(json.meta.error)
      setData(json)
      setLastRefresh(new Date().toLocaleTimeString('zh-CN'))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [strategy])

  useEffect(() => { fetchData() }, [fetchData])

  const funnel = data?.funnel || {}
  const picks  = data?.picks  || []
  const meta   = data?.meta   || {}

  const funnelSteps = [
    {
      icon: Target, color: '#8b949e',
      title: '候选池',
      desc: `因子建仓评分 Top ${funnel.layer0_total || 30} 只（已排除ST/新股/资金流出）`,
      inCount: funnel.layer0_total || 0,
      outCount: funnel.layer0_total || 0,
      rejectList: [],
    },
    {
      icon: Shield, color: '#38bdf8',
      title: '层一：画像等级过滤',
      desc: funnel.layer1_remark || `portrait_score ≥ ${funnel.layer1_threshold || (strategy === 'right' ? 45 : 50)}（C+ 级以上）→ 通过`,
      inCount: funnel.layer0_total || 0,
      outCount: funnel.layer1_pass || 0,
      rejectList: funnel.layer1_reject || [],
    },
    {
      icon: TrendingDown, color: '#f59e0b',
      title: '层二：短期热度过滤',
      desc: strategy === 'right' ? '今日涨幅 ≤ 9.5%（防高位烂板）' : '今日涨幅 ≤ 4.5%（避免追高追板）',
      inCount: funnel.layer1_pass || 0,
      outCount: funnel.layer2_pass || 0,
      rejectList: funnel.layer2_reject || [],
    },
    {
      icon: Zap, color: '#a78bfa',
      title: '层三：仓位分散过滤',
      desc: '同一细分行业最多 1 支（取画像分最高者）',
      inCount: funnel.layer2_pass || 0,
      outCount: funnel.layer3_pass || 0,
      rejectList: funnel.layer3_reject || [],
    },
  ]

  return (
    <div style={{ fontFamily: 'Inter, "Noto Sans SC", monospace', color: '#e6edf3', minHeight: '100vh' }}>

      {/* 页头 */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h2 style={{
              fontSize: 24, fontWeight: 900, margin: 0,
              background: 'linear-gradient(135deg, #10b981, #38bdf8, #a78bfa)',
              WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
              display: 'flex', alignItems: 'center', gap: 12
            }}>
              🎯 T+1 画像建仓决策
            </h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '10px 0 0' }}>
              <div style={{
                display: 'flex', background: 'rgba(255,255,255,0.05)', borderRadius: 8, padding: 3, border: '1px solid rgba(255,255,255,0.1)'
              }}>
                <button onClick={() => setStrategy('left')} style={{
                  padding: '4px 16px', borderRadius: 6, fontSize: 12, fontWeight: 700, border: 'none', cursor: 'pointer', fontFamily: 'monospace',
                  background: strategy === 'left' ? '#38bdf8' : 'transparent', color: strategy === 'left' ? '#000' : '#8b949e', transition: 'all 0.2s',
                }}>
                  左侧低吸
                </button>
                <button onClick={() => setStrategy('right')} style={{
                  padding: '4px 16px', borderRadius: 6, fontSize: 12, fontWeight: 700, border: 'none', cursor: 'pointer', fontFamily: 'monospace',
                  background: strategy === 'right' ? '#f43f5e' : 'transparent', color: strategy === 'right' ? '#fff' : '#8b949e', transition: 'all 0.2s',
                }}>
                  右侧突破
                </button>
              </div>
              <span style={{ color: '#8b949e', fontSize: 12, fontFamily: 'monospace' }}>
                三层过滤框架 · 自动精选 1-3 支最优建仓股票
              </span>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {lastRefresh && <span style={{ fontSize: 11, color: '#555', fontFamily: 'monospace' }}>更新: {lastRefresh}</span>}
            <button onClick={fetchData} disabled={loading} style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px',
              borderRadius: 10, fontSize: 12, fontWeight: 600, cursor: loading ? 'default' : 'pointer',
              background: 'rgba(56,189,248,0.15)', border: '1px solid rgba(56,189,248,0.3)',
              color: '#38bdf8', transition: 'all 0.2s', opacity: loading ? 0.6 : 1,
            }}>
              <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
              {loading ? '计算中...' : '刷新决策'}
            </button>
          </div>
        </div>
      </div>

      {/* 加载态 */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '80px 0', color: '#8b949e' }}>
          <div style={{
            width: 40, height: 40, border: '3px solid #1f2d4a',
            borderTopColor: '#10b981', borderRadius: '50%',
            animation: 'spin 1s linear infinite', margin: '0 auto 16px',
          }} />
          <div style={{ fontFamily: 'monospace', fontSize: 13 }}>正在执行三层画像过滤漏斗...</div>
          <div style={{ fontSize: 11, color: '#555', marginTop: 6 }}>因子打分 → 画像评分 → 三层过滤 → 仓位分配</div>
        </div>
      )}

      {/* 错误态 */}
      {error && !loading && (
        <div style={{
          background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.3)',
          borderRadius: 12, padding: '16px 20px', color: '#f43f5e', fontSize: 13, fontFamily: 'monospace',
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <AlertCircle size={16} /> ❌ {error}
        </div>
      )}

      {/* 主内容 */}
      {!loading && !error && data && (
        <div style={{ display: 'grid', gap: 28 }}>

          {/* ── 精选区 ── */}
          <section>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
              <Flame size={18} style={{ color: '#f59e0b' }} />
              <h3 style={{ fontSize: 16, fontWeight: 800, margin: 0, color: '#e6edf3' }}>今日精选建仓</h3>
              <span style={{
                padding: '3px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700,
                background: picks.length > 0 ? 'rgba(16,185,129,0.15)' : 'rgba(244,63,94,0.15)',
                color: picks.length > 0 ? '#10b981' : '#f43f5e',
                border: `1px solid ${picks.length > 0 ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)'}`,
              }}>
                {picks.length > 0 ? `精选 ${picks.length} 支` : '今日暂无符合条件'}
              </span>
            </div>

            {picks.length === 0 ? (
              <div style={{
                background: '#151d30', border: '1px solid #222f4c', borderRadius: 14,
                padding: '40px 24px', textAlign: 'center', color: '#8b949e',
              }}>
                <XCircle size={36} style={{ color: '#f43f5e', margin: '0 auto 12px', display: 'block' }} />
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>三层过滤后无符合条件的股票</div>
                <div style={{ fontSize: 12, lineHeight: 1.7 }}>
                  可能原因：今日候选股画像分普遍偏低，或涨幅已超出安全阈值。<br />
                  建议明日盘后重新扫描，或尝试切换到{strategy === 'left' ? '右侧突破' : '左侧低吸'}策略。
                </div>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20 }}>
                {picks.map(pick => <PickCard key={pick.ts_code} pick={pick} strategy={strategy} />)}
              </div>
            )}
          </section>

          {/* ── 三层漏斗 ── */}
          <section>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
              <Filter size={18} style={{ color: '#a78bfa' }} />
              <h3 style={{ fontSize: 16, fontWeight: 800, margin: 0, color: '#e6edf3' }}>三层过滤漏斗</h3>
              <span style={{ fontSize: 11, color: '#8b949e', fontFamily: 'monospace' }}>
                {funnel.layer0_total} → {funnel.layer1_pass} → {funnel.layer2_pass} → {funnel.layer3_pass}
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, alignItems: 'start' }}>
              {/* 漏斗步骤 */}
              <div style={{ display: 'grid', gap: 0 }}>
                {funnelSteps.map((step, i) => (
                  <FunnelLayer key={step.title} {...step} isLast={i === funnelSteps.length - 1} />
                ))}
              </div>

              {/* 规则说明 + 数据元信息 */}
              <div style={{ display: 'grid', gap: 14 }}>
                <div style={{ background: '#151d30', border: '1px solid #222f4c', borderRadius: 14, padding: '18px 20px' }}>
                  <h4 style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3', margin: '0 0 14px' }}>📖 {strategy === 'right' ? '右侧突破' : '左侧低吸'}策略说明</h4>
                  {strategy === 'right' ? [
                    { icon: <Shield size={13} />, color: '#38bdf8', title: '层一·画像等级 ≥ C+', desc: `右侧画像分 ≥ ${funnel.layer1_threshold || 45}：获利盘极高（上方无压）· 短期动能强 · 游资极为活跃 · 大单主力抢筹` },
                    { icon: <TrendingDown size={13} />, color: '#f59e0b', title: '层二·防烂板', desc: '今日涨幅 ≤ 9.5%。放宽涨幅限制以追逐强势，但避开可能被砸烂的高位涨停板' },
                    { icon: <Zap size={13} />, color: '#a78bfa', title: '层三·行业分散', desc: '同一细分行业最多 1 支，取画像分最高者留下。防止仓位集中板块，降低系统性风险' },
                  ].map(({ icon, color, title, desc }) => (
                    <div key={title} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: '1px solid #1a2540' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color, fontSize: 12, fontWeight: 700, marginBottom: 6 }}>
                        {icon} {title}
                      </div>
                      <div style={{ fontSize: 11, color: '#8b949e', lineHeight: 1.6 }}>{desc}</div>
                    </div>
                  )) : [
                    { icon: <Shield size={13} />, color: '#38bdf8', title: '层一·画像等级 ≥ C+', desc: `T+1 实证5维画像分 ≥ ${funnel.layer1_threshold || 50}：位置分/估值分/温度分/筹码分/因子分 加权综合，实证过线股票 T+1 上涨概率显著提升` },
                    { icon: <TrendingDown size={13} />, color: '#f59e0b', title: '层二·短期热度过滤', desc: '今日涨幅 ≤ 4.5%。实证：当日涨 >4.5% 的股票 T+1 回撤概率显著提升，追高胜率不足 40%' },
                    { icon: <Zap size={13} />, color: '#a78bfa', title: '层三·行业分散', desc: '同一细分行业最多 1 支，取画像分最高者留下。防止仓位集中板块，降低系统性风险' },
                  ].map(({ icon, color, title, desc }) => (
                    <div key={title} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: '1px solid #1a2540' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color, fontSize: 12, fontWeight: 700, marginBottom: 6 }}>
                        {icon} {title}
                      </div>
                      <div style={{ fontSize: 11, color: '#8b949e', lineHeight: 1.6 }}>{desc}</div>
                    </div>
                  ))}
                  <div style={{ fontSize: 10, color: '#444', fontFamily: 'monospace' }}>⚠️ 仅供参考，不构成投资建议</div>
                </div>

                <div style={{ background: '#151d30', border: '1px solid #222f4c', borderRadius: 14, padding: '16px 20px' }}>
                  <h4 style={{ fontSize: 12, fontWeight: 700, color: '#8b949e', margin: '0 0 12px', fontFamily: 'monospace' }}>数据源信息</h4>
                  <div style={{ display: 'grid', gap: 6, fontSize: 11, fontFamily: 'monospace', color: '#8b949e' }}>
                    {[
                      ['行情日期', meta.scan_date],
                      ['因子日期', meta.factor_date],
                      ['筹码日期', meta.cyq_date],
                      ['扫描总数', meta.top_n_scanned ? `${meta.top_n_scanned} 只` : '--'],
                      ['最终精选', `${picks.length} 支`],
                    ].map(([k, v]) => (
                      <div key={k} style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>{k}</span>
                        <span style={{ color: k === '最终精选' ? '#10b981' : '#c9d1d9', fontWeight: k === '最终精选' ? 700 : 400 }}>{v || '--'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* 免责声明 */}
          <div style={{
            padding: '12px 16px', background: '#0e1524', border: '1px solid #1f2d4a',
            borderRadius: 10, fontSize: 11, color: '#555', fontFamily: 'monospace',
            display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <AlertCircle size={12} style={{ color: '#f59e0b', flexShrink: 0 }} />
            本工具基于量化因子模型与T+1实证画像自动筛选，结果仅供策略研究参考，不构成任何投资建议。市场有风险，操作需谨慎。
          </div>
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
