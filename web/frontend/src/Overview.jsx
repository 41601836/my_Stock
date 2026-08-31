import React, { useState, useEffect } from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts'
import { RefreshCw, TrendingUp, Flame, ShieldAlert, ArrowUpRight, ArrowDownRight, Compass, Zap, Activity, Info, X } from 'lucide-react'

const regimeConfig = {
  BULL: { label: 'BULL  牛市全速', subLabel: '火力全开，满仓跟进', icon: Flame, color: '#10b981', bg: 'rgba(16,185,129,0.08)', border: 'rgba(16,185,129,0.25)', glow: '0 0 24px rgba(16,185,129,0.15)' },
  RANGE: { label: 'RANGE  震荡轮动', subLabel: '高抛低吸，快进快出', icon: Compass, color: '#38bdf8', bg: 'rgba(56,189,248,0.08)', border: 'rgba(56,189,248,0.25)', glow: '0 0 24px rgba(56,189,248,0.15)' },
  BEAR: { label: 'BEAR  避险模式', subLabel: '强制减仓 50% 或清仓', icon: ShieldAlert, color: '#f43f5e', bg: 'rgba(244,63,94,0.08)', border: 'rgba(244,63,94,0.25)', glow: '0 0 24px rgba(244,63,94,0.15)' },
}

function getTempLevel(median) {
  if (median == null) return { label: '数据加载中', color: '#6b7280' }
  if (median < 15) return { label: '🚨 极端冰点 · 抄底窗口', color: '#f43f5e', bg: 'rgba(244,63,94,0.1)' }
  if (median < 35) return { label: '⚠️ 低温偏冷 · 谨慎布局', color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' }
  if (median < 65) return { label: '✅ 健康中庸 · 正常操作', color: '#10b981', bg: 'rgba(16,185,129,0.1)' }
  if (median < 80) return { label: '⚠️ 偏热警戒 · 轻仓止盈', color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' }
  return { label: '🔥 过热高危 · 紧急减仓', color: '#f43f5e', bg: 'rgba(244,63,94,0.1)' }
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: 10, padding: '10px 14px', fontSize: 11, fontFamily: 'monospace', boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}>
      <div style={{ color: '#8b949e', marginBottom: 6 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.fill, marginBottom: 2 }}>{p.name}: <span style={{ color: '#e6edf3', fontWeight: 700 }}>{p.value?.toFixed(2)}%</span></div>
      ))}
    </div>
  )
}

export default function Overview() {
  const [data, setData] = useState(null)
  const [regimeData, setRegimeData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  
  const [selectedTheme, setSelectedTheme] = useState(null)
  const [themeStocks, setThemeStocks] = useState(null)
  const [loadingTheme, setLoadingTheme] = useState(false)

  const [showStyleStocks, setShowStyleStocks] = useState(false)
  const [styleStocksData, setStyleStocksData] = useState(null)
  const [loadingStyleStocks, setLoadingStyleStocks] = useState(false)

  const fetchStyleStocks = async (date, style) => {
    setShowStyleStocks(true)
    setLoadingStyleStocks(true)
    setStyleStocksData(null)
    try {
      const res = await fetch(`/api/market/style-stocks?date=${encodeURIComponent(date)}&style=${encodeURIComponent(style)}`)
      if (!res.ok) throw new Error('获取风格个股失败')
      const data = await res.json()
      setStyleStocksData(data)
    } catch (err) {
      console.error(err)
      setStyleStocksData({ error: err.message })
    } finally {
      setLoadingStyleStocks(false)
    }
  }

  const fetchThemeStocks = async (sector, sort = 'desc') => {
    setSelectedTheme(sector)
    setLoadingTheme(true)
    setThemeStocks(null)
    try {
      const res = await fetch(`/api/market/theme-stocks?sector=${encodeURIComponent(sector)}&sort=${sort}`)
      if (!res.ok) throw new Error('获取题材股票失败')
      const data = await res.json()
      setThemeStocks(data)
    } catch (err) {
      console.error(err)
      setThemeStocks({ error: err.message })
    } finally {
      setLoadingTheme(false)
    }
  }

  const fetchOverview = async () => {
    setLoading(true)
    try {
      const [res1, res2] = await Promise.all([
        fetch('/api/market/overview'),
        fetch('/api/market/regime-dashboard')
      ])
      if (!res1.ok || !res2.ok) throw new Error('获取市场行情全览数据失败，请检查后台服务连接')
      setData(await res1.json())
      setRegimeData(await res2.json())
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchOverview() }, [])

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 320 }}>
        <div style={{ textAlign: 'center', color: '#6e7681' }}>
          <div style={{ fontSize: 12, fontFamily: 'monospace', marginTop: 12 }}>正在载入大盘量化温度数据...</div>
        </div>
      </div>
    )
  }
  if (error) {
    return (
      <div style={{ padding: '16px 20px', borderRadius: 12, background: 'rgba(244,63,94,0.08)', border: '1px solid rgba(244,63,94,0.3)', color: '#f87171', fontSize: 12, fontFamily: 'monospace' }}>
        ❌ {error}
      </div>
    )
  }

  const pieData = [
    { name: '上涨', value: data?.adv_dec?.up || 0, color: '#f43f5e' },
    { name: '下跌', value: data?.adv_dec?.down || 0, color: '#10b981' },
    { name: '平盘', value: data?.adv_dec?.flat || 0, color: '#374151' },
  ]
  const totalStocks = pieData.reduce((s, d) => s + d.value, 0)
  const upPct = totalStocks > 0 ? (pieData[0].value / totalStocks * 100).toFixed(1) : 0
  const median = data?.temperature?.median_winner
  const tempLevel = getTempLevel(median)
  const regime = data?.regime || 'RANGE'
  const regCfg = regimeConfig[regime] || regimeConfig.RANGE
  const RegIcon = regCfg.icon
  const maxFlow = Math.max(...[...(data?.inflow_rank || []), ...(data?.outflow_rank || [])].map(i => Math.abs(i.flow_value)), 1.0)
  const dateStr = data?.date ? `${data.date.substring(0,4)}-${data.date.substring(4,6)}-${data.date.substring(6)}` : '—'

  const card = (children, accentColor = '#a78bfa', extraStyle = {}) => ({
    background: 'linear-gradient(135deg, #0d1117 0%, #161b22 100%)',
    border: '1px solid #21262d',
    borderRadius: 16,
    padding: '20px 22px',
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    position: 'relative',
    overflow: 'hidden',
    ...extraStyle,
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, fontFamily: '"Inter", "SF Pro Display", sans-serif' }}>

      {/* 顶部状态栏 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 18px', background: '#0d1117', border: '1px solid #21262d', borderRadius: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#f43f5e', boxShadow: '0 0 8px #f43f5e' }} />
          <span style={{ fontSize: 11, color: '#8b949e', fontFamily: 'monospace' }}>市场宏观全览</span>
          <span style={{ fontSize: 11, color: '#30363d' }}>·</span>
          <span style={{ fontSize: 11, color: '#6e7681', fontFamily: 'monospace' }}>基准日 {dateStr}</span>
        </div>
        <button onClick={fetchOverview} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderRadius: 8, background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.25)', color: '#a78bfa', fontSize: 11, cursor: 'pointer', fontFamily: 'monospace' }}>
          <RefreshCw size={12} /> 刷新
        </button>
      </div>

      {/* 第一行：4 核心指标卡（手机单列、sm双列、桌面四列） */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">

        {/* 赚钱效应 */}
        <div style={card(null, '#f43f5e')}>
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg, transparent, #f43f5e60, transparent)' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 10, color: '#8b949e', fontFamily: 'monospace', letterSpacing: '0.05em' }}>今日赚钱效应  ADV/DEC</span>
            <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 20, background: 'rgba(244,63,94,0.15)', border: '1px solid rgba(244,63,94,0.35)', color: '#f43f5e', fontFamily: 'monospace' }}>上涨 {upPct}%</span>
          </div>
          <div style={{ height: 120, position: 'relative' }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={36} outerRadius={50} paddingAngle={2} dataKey="value" startAngle={90} endAngle={-270}>
                  {pieData.map((e, i) => <Cell key={i} fill={e.color} strokeWidth={0} />)}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 800, color: '#f43f5e', fontFamily: 'monospace' }}>{upPct}%</div>
              <div style={{ fontSize: 9, color: '#6e7681' }}>上涨占比</div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {pieData.map((d, i) => (
              <div key={i} style={{ flex: 1, textAlign: 'center', padding: '6px 2px', borderRadius: 8, background: `${d.color}10`, border: `1px solid ${d.color}25` }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: d.color, fontFamily: 'monospace' }}>{d.value}</div>
                <div style={{ fontSize: 9, color: '#6e7681', marginTop: 1 }}>{d.name}</div>
              </div>
            ))}
          </div>
          <div style={{ background: 'rgba(139,148,158,0.05)', border: '1px solid #21262d', borderRadius: 8, padding: '7px 10px', fontSize: 10, color: '#6e7681', fontFamily: 'monospace', lineHeight: 1.6 }}>
            <Info size={10} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle', color: '#8b949e' }} />
            上涨数 &gt; 下跌代表大盘赚钱效应好，利于新开仓。
          </div>
        </div>

        {/* 筹码温度 */}
        <div style={card(null, '#f59e0b')}>
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg, transparent, #f59e0b60, transparent)' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 10, color: '#8b949e', fontFamily: 'monospace', letterSpacing: '0.05em' }}>筹码获利中位数  WINNER RATE</span>
          </div>
          <div style={{ fontSize: 36, fontWeight: 800, color: '#f59e0b', fontFamily: 'monospace', lineHeight: 1 }}>
            {median}<span style={{ fontSize: 14, marginLeft: 4, opacity: 0.7 }}>%</span>
          </div>
          <div>
            <div style={{ height: 5, borderRadius: 3, background: '#21262d', overflow: 'hidden', marginBottom: 10 }}>
              <div style={{ height: '100%', width: `${Math.min(median || 0, 100)}%`, borderRadius: 3, background: 'linear-gradient(90deg, #38bdf8, #f59e0b, #f43f5e)', transition: 'width 0.8s ease' }} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              <div style={{ padding: '7px 8px', borderRadius: 8, background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.2)', textAlign: 'center' }}>
                <div style={{ fontSize: 9, color: '#6e7681', marginBottom: 3 }}>超买 (≥50%)</div>
                <div style={{ fontSize: 15, fontWeight: 700, color: '#f43f5e', fontFamily: 'monospace' }}>{data?.temperature?.overbought_ratio}%</div>
              </div>
              <div style={{ padding: '7px 8px', borderRadius: 8, background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.2)', textAlign: 'center' }}>
                <div style={{ fontSize: 9, color: '#6e7681', marginBottom: 3 }}>超跌 (&lt;10%)</div>
                <div style={{ fontSize: 15, fontWeight: 700, color: '#10b981', fontFamily: 'monospace' }}>{data?.temperature?.oversold_ratio}%</div>
              </div>
            </div>
          </div>
          <div style={{ padding: '6px 10px', borderRadius: 8, background: tempLevel.bg || 'rgba(16,185,129,0.1)', border: `1px solid ${tempLevel.color}30`, color: tempLevel.color, fontSize: 10, fontFamily: 'monospace', textAlign: 'center', fontWeight: 700 }}>
            {tempLevel.label}
          </div>
          <div style={{ background: 'rgba(139,148,158,0.05)', border: '1px solid #21262d', borderRadius: 8, padding: '7px 10px', fontSize: 10, color: '#6e7681', fontFamily: 'monospace', lineHeight: 1.6 }}>
            <Info size={10} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle', color: '#8b949e' }} />
            中位数 &lt;15% + 超跌 &gt;40% → 黄金抄底；中位数 &gt;75% + 超买 &gt;60% → 紧急减仓。
          </div>
        </div>

        {/* 市场路由 (精简版，只保留状态) */}
        <div style={card(null, regCfg.color)}>
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, transparent, ${regCfg.color}60, transparent)` }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 10, color: '#8b949e', fontFamily: 'monospace', letterSpacing: '0.05em' }}>策略决策路由  MARKET REGIME</span>
          </div>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '18px 12px', borderRadius: 12, background: regCfg.bg, border: `1px solid ${regCfg.border}`, boxShadow: regCfg.glow }}>
            <RegIcon size={32} color={regCfg.color} style={{ filter: `drop-shadow(0 0 8px ${regCfg.color}60)` }} />
            <div style={{ fontSize: 13, fontWeight: 800, color: regCfg.color, fontFamily: 'monospace', letterSpacing: '0.06em', textAlign: 'center' }}>{regCfg.label}</div>
            <div style={{ fontSize: 10, color: '#8b949e', textAlign: 'center' }}>{regCfg.subLabel}</div>
          </div>
          <div style={{ background: 'rgba(139,148,158,0.05)', border: '1px solid #21262d', borderRadius: 8, padding: '7px 10px', fontSize: 10, color: '#6e7681', fontFamily: 'monospace', lineHeight: 1.6 }}>
            <Info size={10} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle', color: '#8b949e' }} />
            {regimeData?.position_advice?.advice || '根据行情动态调整仓位'}
          </div>
        </div>

        {/* 策略参数 */}
        <div style={card(null, '#a78bfa')}>
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg, transparent, #a78bfa60, transparent)' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 10, color: '#8b949e', fontFamily: 'monospace', letterSpacing: '0.05em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>策略引擎参数  CONFIG</span>
            <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 20, background: 'rgba(167,139,250,0.15)', border: '1px solid rgba(167,139,250,0.35)', color: '#a78bfa', fontFamily: 'monospace', flexShrink: 0 }}>LIVE</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7, flex: 1 }}>
            {[
              { k: '因子配置', v: 'Custom_V2 自适应' },
              { k: '寻优引擎', v: '胜率猎手 GA' },
              { k: '风险模型', v: 'MVO Ledoit-Wolf' },
              { k: '行业上限', v: '30% / 60%' },
            ].map(({ k, v }) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 10px', borderRadius: 8, background: 'rgba(167,139,250,0.04)', border: '1px solid rgba(167,139,250,0.1)', gap: 8 }}>
                <span style={{ fontSize: 10, color: '#6e7681', fontFamily: 'monospace', flexShrink: 0 }}>{k}</span>
                <span style={{ fontSize: 10, color: '#a78bfa', fontFamily: 'monospace', fontWeight: 700, whiteSpace: 'nowrap', textAlign: 'right' }}>{v}</span>
              </div>
            ))}
          </div>
          <div style={{ padding: '6px 10px', borderRadius: 8, background: 'rgba(56,189,248,0.08)', border: '1px solid rgba(56,189,248,0.2)', fontSize: 10, color: '#38bdf8', fontFamily: 'monospace', textAlign: 'center' }}>
            行业持仓风控已锁定
          </div>
        </div>
      </div>

      {/* 新增：路由层判定细节 */}
      {regimeData && !regimeData.error && (
        <div style={{ background: 'linear-gradient(135deg, #0d1117 0%, #161b22 100%)', border: '1px solid #21262d', borderRadius: 16, padding: '22px 24px', position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, transparent, ${regCfg.color}60, transparent)` }} />
          {/* 标题区域：竖排，避免手机挤压 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
              <Activity size={15} color={regCfg.color} style={{ flexShrink: 0 }} />
              <span style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3', whiteSpace: 'nowrap' }}>底层路由触发条件诊断</span>
              <span style={{ fontSize: 10, color: '#4b5563', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>REGIME TRIGGERS</span>
            </div>
            <p style={{ fontSize: 11, color: '#6e7681', marginTop: 0, marginBottom: 10 }}>为什么是 {regime}？实时监测大盘波动率、回撤及上涨动能</p>
            {/* 触发徽章单独一行，可换行 */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {regimeData.triggers?.map((t, i) => (
                <div key={i} style={{ padding: '4px 10px', borderRadius: 6, background: `rgba(244,63,94,0.1)`, border: `1px solid rgba(244,63,94,0.3)`, color: '#f43f5e', fontSize: 10, fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                  🚨 触发: {t.name} ({t.value})
                </div>
              ))}
              {(!regimeData.triggers || regimeData.triggers.length === 0) && (
                <div style={{ padding: '4px 10px', borderRadius: 6, background: 'rgba(56,189,248,0.1)', border: '1px solid rgba(56,189,248,0.3)', color: '#38bdf8', fontSize: 10, fontFamily: 'monospace' }}>
                  ✓ 当前运行在安全区间
                </div>
              )}
            </div>
          </div>
          
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
            {[
              { label: '近20日收益率', val: regimeData.indicators.return_20d + '%', threshold: `Bull >5% / Bear <-3%`, status: regimeData.indicators.return_20d > 5 ? 'good' : regimeData.indicators.return_20d < -3 ? 'bad' : 'normal' },
              { label: '近5日最大回撤', val: regimeData.indicators.mdd_5d + '%', threshold: `Dark < -5%`, status: regimeData.indicators.mdd_5d < -5 ? 'bad' : 'normal' },
              { label: '20日滚动波动率', val: regimeData.indicators.vol_20d + '%', threshold: `> ${regimeData.thresholds.vol_75pct}% (75分位过热)`, status: regimeData.indicators.vol_20d > regimeData.thresholds.vol_75pct ? 'bad' : 'normal' },
              { label: '上涨家数占比', val: regimeData.indicators.up_ratio + '%', threshold: `Dark < 30%`, status: regimeData.indicators.up_ratio < 30 ? 'bad' : 'normal' },
              { label: '周度绩效诊断', val: regimeData.indicators.return_5d + '%', threshold: `Dark < -4.5%`, status: regimeData.indicators.return_5d < -4.5 ? 'bad' : 'normal' },
            ].map((idx, i) => {
              const colorMap = { good: '#f43f5e', bad: '#10b981', normal: '#a78bfa' }
              const c = colorMap[idx.status]
              return (
                <div key={i} style={{ padding: '12px 14px', borderRadius: 10, background: '#0d1117', border: '1px solid #21262d', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontSize: 10, color: '#8b949e', fontFamily: 'monospace' }}>{idx.label}</span>
                  <span style={{ fontSize: 16, fontWeight: 700, color: c, fontFamily: 'monospace' }}>{idx.val}</span>
                  <span style={{ fontSize: 9, color: '#4b5563', fontFamily: 'monospace', marginTop: 2 }}>阈值: {idx.threshold}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 第二行：风格轮动 */}
      <div style={{ background: 'linear-gradient(135deg, #0d1117 0%, #161b22 100%)', border: '1px solid #21262d', borderRadius: 16, padding: '22px 24px', position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg, transparent, #a78bfa60, transparent)' }} />
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <TrendingUp size={15} color="#a78bfa" />
            <span style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3' }}>近 5 日主力风格强弱走势</span>
            <span style={{ fontSize: 10, color: '#4b5563', fontFamily: 'monospace' }}>STYLE ROTATION</span>
          </div>
          <p style={{ fontSize: 11, color: '#6e7681', marginTop: 4 }}>全市场三类风格个股的日均涨跌幅，诊断主力资金当日偏好方向</p>
        </div>
        <div style={{ height: 250 }}>
          {data?.style_rotation?.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.style_rotation} margin={{ top: 4, right: 8, left: -20, bottom: 0 }} barGap={4}>
                <CartesianGrid strokeDasharray="3 3" stroke="#21262d" vertical={false} />
                <XAxis dataKey="date" stroke="#4b5563" fontSize={10} tickLine={false} axisLine={false} fontFamily="monospace" />
                <YAxis stroke="#4b5563" fontSize={10} tickLine={false} axisLine={false} unit="%" fontFamily="monospace" />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                <Legend wrapperStyle={{ fontSize: 10, paddingTop: 14, fontFamily: 'monospace' }} formatter={(v) => <span style={{ color: '#8b949e' }}>{v}</span>} />
                <Bar name="💜 题材炒作 (游资)" dataKey="高换手风格 (Turnover)" fill="#c084fc" radius={[4,4,0,0]} maxBarSize={36} cursor="pointer" onClick={(data) => {if(data && data.date) fetchStyleStocks(data.date, '高换手风格 (Turnover)')}} />
                <Bar name="💚 强庄控盘 (机构)" dataKey="筹码锁仓风格 (Chips)" fill="#10b981" radius={[4,4,0,0]} maxBarSize={36} cursor="pointer" onClick={(data) => {if(data && data.date) fetchStyleStocks(data.date, '筹码锁仓风格 (Chips)')}} />
                <Bar name="💛 资金扫货 (主力)" dataKey="大单大市风格 (Inflow)" fill="#f59e0b" radius={[4,4,0,0]} maxBarSize={36} cursor="pointer" onClick={(data) => {if(data && data.date) fetchStyleStocks(data.date, '大单大市风格 (Inflow)')}} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#4b5563', fontSize: 12, fontFamily: 'monospace' }}>暂无风格轮动数据</div>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
          {[
            { dot: '#c084fc', title: '怎么看 READ', text: '看最近一天的柱子方向与长度。柱朝上越长，当天该风格股涨得越猛。' },
            { dot: '#10b981', title: '怎么买 EXECUTE', text: '💛 橙柱最高 → 优先大单流入高的个股；💜 紫柱最高 → 适当小仓位配短线题材。' },
            { dot: '#f43f5e', title: '避险灯 SHIELD', text: '三柱多日齐刷刷朝下 & 均值 < -1.5%，系统性踩踏，立刻清仓现金为王。' },
          ].map(({ dot, title, text }) => (
            <div key={title} style={{ padding: '10px 12px', borderRadius: 10, background: '#0d1117', border: '1px solid #21262d' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <div style={{ width: 7, height: 7, borderRadius: '50%', background: dot }} />
                <span style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', fontFamily: 'monospace' }}>{title}</span>
              </div>
              <p style={{ fontSize: 10, color: '#6e7681', lineHeight: 1.6, margin: 0 }}>{text}</p>
            </div>
          ))}
        </div>
      </div>

      {/* 第三行：游资热点 */}
      <div style={{ background: 'linear-gradient(135deg, #0d1117 0%, #12101e 100%)', border: '1px solid #2d1f4e', borderRadius: 16, padding: '22px 24px', position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg, transparent, #c084fc80, transparent)' }} />
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Zap size={15} color="#c084fc" />
            <span style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3' }}>今日游资热点题材排行</span>
            <span style={{ fontSize: 10, color: '#4b5563', fontFamily: 'monospace' }}>HOT MONEY THEMES</span>
          </div>
          <p style={{ fontSize: 11, color: '#6e7681', marginTop: 4 }}>换手率超高 + 主力大单净流入为正 = 游资真实吸筹题材（换手权重 60% + 净买入 40%）</p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {data?.hot_money_themes?.length > 0 ? data.hot_money_themes.map((item, i) => {
            const rankColors = ['#f59e0b', '#94a3b8', '#b45309', '#6b7280', '#6b7280', '#6b7280', '#6b7280', '#6b7280', '#6b7280', '#6b7280']
            const rc = rankColors[i] || '#6b7280'
            // 连续天数信号颜色映射
            const sigColorMap = {
              gray: { color: '#6b7280', bg: 'rgba(107,114,128,0.12)', border: 'rgba(107,114,128,0.3)' },
              yellow: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.3)' },
              green: { color: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.3)' },
              orange: { color: '#f97316', bg: 'rgba(249,115,22,0.12)', border: 'rgba(249,115,22,0.3)' },
              red: { color: '#f43f5e', bg: 'rgba(244,63,94,0.12)', border: 'rgba(244,63,94,0.3)' },
            }
            const sc = sigColorMap[item.signal_color] || sigColorMap.gray
            return (
              <div 
                key={i} 
                onClick={() => fetchThemeStocks(item.sector)}
                style={{ background: 'rgba(167,139,250,0.04)', border: `1px solid rgba(167,139,250,${0.15 - i * 0.02})`, borderRadius: 12, padding: '14px', display: 'flex', flexDirection: 'column', gap: 8, position: 'relative', overflow: 'hidden', cursor: 'pointer', transition: 'all 0.2s ease', ...(selectedTheme === item.sector ? { background: 'rgba(167,139,250,0.1)', borderColor: 'rgba(167,139,250,0.5)', boxShadow: '0 0 15px rgba(167,139,250,0.2)' } : {}) }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(167,139,250,0.08)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = selectedTheme === item.sector ? 'rgba(167,139,250,0.1)' : 'rgba(167,139,250,0.04)' }}
              >
                {/* 排名勋章 */}
                <div style={{ position: 'absolute', top: 8, right: 8, width: 20, height: 20, borderRadius: '50%', background: `${rc}20`, border: `1px solid ${rc}50`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ fontSize: 9, fontWeight: 800, color: rc, fontFamily: 'monospace' }}>#{i+1}</span>
                </div>
                {/* 题材名称 */}
                <div style={{ fontSize: 12, fontWeight: 700, color: '#e6edf3', paddingRight: 28, lineHeight: 1.3 }} title={item.sector}>{item.sector}</div>
                {/* 连续天数 + 操盘信号 */}
                <div style={{ padding: '5px 8px', borderRadius: 6, background: sc.bg, border: `1px solid ${sc.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 9, color: sc.color, fontFamily: 'monospace', fontWeight: 700 }}>🔥 连续 {item.streak_days ?? 1} 天</span>
                  <span style={{ fontSize: 8, color: sc.color, fontFamily: 'monospace', opacity: 0.85 }}>{item.signal}</span>
                </div>
                {/* 指标数值 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'monospace' }}>
                    <span style={{ color: '#6e7681' }}>换手率</span>
                    <span style={{ color: '#e6edf3', fontWeight: 700 }}>{item.avg_turnover}%</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'monospace' }}>
                    <span style={{ color: '#6e7681' }}>成交额</span>
                    <span style={{ color: '#f87171', fontWeight: 700 }}>{item.total_amount} 亿</span>
                  </div>
                </div>
                {/* 热度进度条 */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: '#6e7681', fontFamily: 'monospace', marginBottom: 4 }}>
                    <span>游资热度</span>
                    <span style={{ color: '#c084fc', fontWeight: 700 }}>{item.hot_score}</span>
                  </div>
                  <div style={{ height: 4, borderRadius: 3, background: '#1a1025', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${item.hot_score}%`, borderRadius: 3, background: 'linear-gradient(90deg, #7c3aed, #c084fc)', boxShadow: '0 0 6px rgba(192,132,252,0.4)', transition: 'width 1s ease' }} />
                  </div>
                </div>
              </div>
            )
          }) : (
            <div style={{ gridColumn: '1/-1', textAlign: 'center', color: '#4b5563', fontSize: 12, fontFamily: 'monospace', padding: '32px 0' }}>暂无游资热度题材排行</div>
          )}
        </div>
      </div>

      
      {/* 第四行：机构强庄控盘题材 */}
      <div style={{ background: 'linear-gradient(135deg, #0d1117 0%, #0d1a12 100%)', border: '1px solid #1a3024', borderRadius: 16, padding: '22px 24px', position: 'relative', overflow: 'hidden', marginTop: '16px' }}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg, transparent, #10b98180, transparent)' }} />
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3' }}>今日机构强庄控盘排行</span>
            <span style={{ fontSize: 10, color: '#4b5563', fontFamily: 'monospace' }}>INSTITUTION THEMES</span>
          </div>
          <p style={{ fontSize: 11, color: '#6e7681', marginTop: 4 }}>筹码高度密集，机构重仓长线锁仓方向</p>
        </div>
        
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {data?.inst_themes?.length > 0 ? data.inst_themes.map((item, i) => {
            const isResonantHot = data?.hot_money_themes?.some(t => t.sector === item.sector)
            const isResonantMain = data?.main_cap_themes?.some(t => t.sector === item.sector)
            const rankColors = ['#10b981', '#059669', '#047857', '#065f46', '#064e3b', '#6b7280', '#6b7280', '#6b7280', '#6b7280', '#6b7280']
            const rc = rankColors[i] || '#6b7280'
            const sigColorMap = {
              gray: { color: '#6b7280', bg: 'rgba(107,114,128,0.12)', border: 'rgba(107,114,128,0.3)' },
              yellow: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.3)' },
              green: { color: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.3)' },
              orange: { color: '#f97316', bg: 'rgba(249,115,22,0.12)', border: 'rgba(249,115,22,0.3)' },
              red: { color: '#f43f5e', bg: 'rgba(244,63,94,0.12)', border: 'rgba(244,63,94,0.3)' },
            }
            const sc = sigColorMap[item.signal_color] || sigColorMap.gray
            
            return (
              <div 
                key={i} 
                onClick={() => fetchThemeStocks(item.sector, 'desc')}
                style={{ background: 'rgba(16,185,129,0.04)', border: `1px solid rgba(16,185,129,${0.15 - i * 0.02})`, borderRadius: 12, padding: '14px', display: 'flex', flexDirection: 'column', gap: 8, position: 'relative', overflow: 'hidden', cursor: 'pointer', transition: 'all 0.2s ease', ...(selectedTheme === item.sector ? { background: 'rgba(16,185,129,0.1)', borderColor: 'rgba(16,185,129,0.5)', boxShadow: '0 0 15px rgba(16,185,129,0.2)' } : {}) }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(16,185,129,0.08)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = selectedTheme === item.sector ? 'rgba(16,185,129,0.1)' : 'rgba(16,185,129,0.04)' }}
              >
                {/* 排名勋章 */}
                <div style={{ position: 'absolute', top: 8, right: 8, width: 20, height: 20, borderRadius: '50%', background: `${rc}20`, border: `1px solid ${rc}50`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ fontSize: 9, fontWeight: 800, color: rc, fontFamily: 'monospace' }}>#{i+1}</span>
                </div>
                
                {/* 题材名称 */}
                <div style={{ fontSize: 12, fontWeight: 700, color: '#e6edf3', paddingRight: 28, lineHeight: 1.3 }} title={item.sector}>
                  {item.sector}
                </div>
                
                {/* 连续天数 + 操盘信号 */}
                <div style={{ padding: '5px 8px', borderRadius: 6, background: sc.bg, border: `1px solid ${sc.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 9, color: sc.color, fontFamily: 'monospace', fontWeight: 700 }}>💎 连续 {item.streak_days ?? 1} 天</span>
                  <span style={{ fontSize: 8, color: sc.color, fontFamily: 'monospace', opacity: 0.85 }}>{item.signal}</span>
                </div>
                
                {/* 共振标签 */}
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {isResonantHot && (
                    <span style={{ fontSize: 9, background: 'rgba(192,132,252,0.15)', color: '#c084fc', padding: '2px 6px', borderRadius: 4, fontWeight: 700, border: '1px solid rgba(192,132,252,0.3)' }}>
                      🔥 游资共振
                    </span>
                  )}
                  {isResonantMain && (
                    <span style={{ fontSize: 9, background: 'rgba(244,63,94,0.15)', color: '#f43f5e', padding: '2px 6px', borderRadius: 4, fontWeight: 700, border: '1px solid rgba(244,63,94,0.3)' }}>
                      💛 主力共振
                    </span>
                  )}
                </div>
                
                {/* 核心指标 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'monospace' }}>
                    <span style={{ color: '#6e7681' }}>锁仓度</span>
                    <span style={{ color: '#10b981', fontWeight: 700 }}>{item.chips_peak}%</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'monospace' }}>
                    <span style={{ color: '#6e7681' }}>净流入</span>
                    <span style={{ color: item.net_inflow > 0 ? '#f43f5e' : item.net_inflow < 0 ? '#10b981' : '#e6edf3', fontWeight: 700 }}>{item.net_inflow > 0 ? `+${item.net_inflow}` : item.net_inflow} 亿</span>
                  </div>
                </div>
                
                {/* 强度进度条 */}
                <div>
                  <div style={{ height: 4, borderRadius: 3, background: '#0d2018', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${item.chips_peak}%`, borderRadius: 3, background: 'linear-gradient(90deg, #059669, #10b981)', boxShadow: '0 0 6px rgba(16,185,129,0.4)', transition: 'width 1s ease' }} />
                  </div>
                </div>
              </div>
            )
          }) : (
            <div style={{ gridColumn: '1/-1', textAlign: 'center', color: '#4b5563', fontSize: 12, fontFamily: 'monospace', padding: '32px 0' }}>暂无机构控盘排行</div>
          )}
        </div>
      </div>


      {/* 第五行：主力大资金扫货题材 */}
      <div style={{ background: 'linear-gradient(135deg, #0d1117 0%, #150a0a 100%)', border: '1px solid #3e1b1b', borderRadius: 16, padding: '22px 24px', position: 'relative', overflow: 'hidden', marginTop: '16px' }}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg, transparent, #f43f5e80, transparent)' }} />
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3' }}>今日主力扫货题材排行</span>
            <span style={{ fontSize: 10, color: '#4b5563', fontFamily: 'monospace' }}>MAIN CAPITAL THEMES</span>
          </div>
          <p style={{ fontSize: 11, color: '#6e7681', marginTop: 4 }}>单日大单狂买方向，如果持续天数长说明主力持续建仓</p>
        </div>
        
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {data?.main_cap_themes?.length > 0 ? data.main_cap_themes.map((item, i) => {
            const isResonantHot = data?.hot_money_themes?.some(t => t.sector === item.sector)
            const isResonantInst = data?.inst_themes?.some(t => t.sector === item.sector)
            const rankColors = ['#f43f5e', '#e11d48', '#be123c', '#9f1239', '#881337', '#6b7280', '#6b7280', '#6b7280', '#6b7280', '#6b7280']
            const rc = rankColors[i] || '#6b7280'
            const sigColorMap = {
              gray: { color: '#6b7280', bg: 'rgba(107,114,128,0.12)', border: 'rgba(107,114,128,0.3)' },
              yellow: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.3)' },
              green: { color: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.3)' },
              orange: { color: '#f97316', bg: 'rgba(249,115,22,0.12)', border: 'rgba(249,115,22,0.3)' },
              red: { color: '#f43f5e', bg: 'rgba(244,63,94,0.12)', border: 'rgba(244,63,94,0.3)' },
            }
            const sc = sigColorMap[item.signal_color] || sigColorMap.gray
            
            return (
              <div 
                key={i} 
                onClick={() => fetchThemeStocks(item.sector, 'desc')}
                style={{ background: 'rgba(244,63,94,0.04)', border: `1px solid rgba(244,63,94,${0.15 - i * 0.02})`, borderRadius: 12, padding: '14px', display: 'flex', flexDirection: 'column', gap: 8, position: 'relative', overflow: 'hidden', cursor: 'pointer', transition: 'all 0.2s ease', ...(selectedTheme === item.sector ? { background: 'rgba(244,63,94,0.1)', borderColor: 'rgba(244,63,94,0.5)', boxShadow: '0 0 15px rgba(244,63,94,0.2)' } : {}) }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(244,63,94,0.08)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = selectedTheme === item.sector ? 'rgba(244,63,94,0.1)' : 'rgba(244,63,94,0.04)' }}
              >
                {/* 排名勋章 */}
                <div style={{ position: 'absolute', top: 8, right: 8, width: 20, height: 20, borderRadius: '50%', background: `${rc}20`, border: `1px solid ${rc}50`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ fontSize: 9, fontWeight: 800, color: rc, fontFamily: 'monospace' }}>#{i+1}</span>
                </div>
                
                {/* 题材名称 */}
                <div style={{ fontSize: 12, fontWeight: 700, color: '#e6edf3', paddingRight: 28, lineHeight: 1.3 }} title={item.sector}>
                  {item.sector}
                </div>

                {/* 连续天数 + 操盘信号 */}
                <div style={{ padding: '5px 8px', borderRadius: 6, background: sc.bg, border: `1px solid ${sc.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 9, color: sc.color, fontFamily: 'monospace', fontWeight: 700 }}>💛 连续 {item.streak_days ?? 1} 天</span>
                  <span style={{ fontSize: 8, color: sc.color, fontFamily: 'monospace', opacity: 0.85 }}>{item.signal}</span>
                </div>
                
                {/* 共振标签 */}
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {isResonantHot && (
                    <span style={{ fontSize: 9, background: 'rgba(192,132,252,0.15)', color: '#c084fc', padding: '2px 6px', borderRadius: 4, fontWeight: 700, border: '1px solid rgba(192,132,252,0.3)' }}>
                      🔥 游资共振
                    </span>
                  )}
                  {isResonantInst && (
                    <span style={{ fontSize: 9, background: 'rgba(16,185,129,0.15)', color: '#10b981', padding: '2px 6px', borderRadius: 4, fontWeight: 700, border: '1px solid rgba(16,185,129,0.3)' }}>
                      💎 机构共振
                    </span>
                  )}
                </div>
                
                {/* 核心指标 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'monospace' }}>
                    <span style={{ color: '#6e7681' }}>绝对净流入</span>
                    <span style={{ color: item.net_inflow > 0 ? '#f43f5e' : item.net_inflow < 0 ? '#10b981' : '#e6edf3', fontWeight: 700 }}>{item.net_inflow > 0 ? `+${item.net_inflow}` : item.net_inflow} 亿</span>
                  </div>
                </div>
                
                {/* 强度进度条 */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: '#6e7681', fontFamily: 'monospace', marginBottom: 4 }}>
                    <span>流入占比</span>
                    <span style={{ color: '#f43f5e', fontWeight: 700 }}>{item.inflow_ratio}%</span>
                  </div>
                  <div style={{ height: 4, borderRadius: 3, background: '#1a1013', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${item.inflow_ratio}%`, borderRadius: 3, background: 'linear-gradient(90deg, #be123c, #f43f5e)', boxShadow: '0 0 6px rgba(244,63,94,0.4)', transition: 'width 1s ease' }} />
                  </div>
                </div>
              </div>
            )
          }) : (
            <div style={{ gridColumn: '1/-1', textAlign: 'center', color: '#4b5563', fontSize: 12, fontFamily: 'monospace', padding: '32px 0' }}>暂无资金扫货排行</div>
          )}
        </div>
      </div>

      {/* 第五行：主力出货警戒线 */}
      <div style={{ background: 'linear-gradient(135deg, #0d1117 0%, #1a0d0d 100%)', border: '1px solid #301a1a', borderRadius: 16, padding: '20px 22px', position: 'relative', overflow: 'hidden', marginTop: '16px' }}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: 'linear-gradient(90deg, transparent, #10b98160, transparent)' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <ArrowDownRight size={14} color="#10b981" />
          <span style={{ fontSize: 12, fontWeight: 700, color: '#e6edf3' }}>大资金净流出 TOP 10</span>
          <span style={{ fontSize: 10, color: '#4b5563', fontFamily: 'monospace' }}>OUTFLOW</span>
        </div>
        <p style={{ fontSize: 10, color: '#6e7681', marginBottom: 16 }}>主力出货方向 — 上榜题材反弹勿追，防阴跌</p>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-x-8 gap-y-4">
          {data?.outflow_rank?.length > 0 ? data.outflow_rank.map((item, i) => (
            <div key={i}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span 
                  onClick={() => fetchThemeStocks(item.sector, 'asc')}
                  style={{ fontSize: 11, fontFamily: 'monospace', color: '#e6edf3', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline', textUnderlineOffset: 2, textDecorationColor: '#10b981' }}
                >
                  {i+1}. {item.sector}
                </span>
                <span style={{ fontSize: 11, fontFamily: 'monospace', color: '#10b981', fontWeight: 700 }}>{item.flow_value} 亿</span>
              </div>
              <div style={{ height: 4, borderRadius: 3, background: '#200d0d', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${(Math.abs(item.flow_value)/maxFlow*100).toFixed(1)}%`, borderRadius: 3, background: 'linear-gradient(90deg, #047857, #10b981)', boxShadow: '0 0 6px rgba(16,185,129,0.3)', transition: 'width 0.8s ease' }} />
              </div>
            </div>
          )) : <div style={{ color: '#4b5563', fontSize: 11, fontFamily: 'monospace', padding: '20px 0', textAlign: 'center' }}>暂无数据</div>}
        </div>
      </div>

      {/* 题材龙头股 Modal */}
      {selectedTheme && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(4px)' }}>
          <div style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: 16, width: 600, maxWidth: '90%', padding: '24px', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', position: 'relative' }}>
            <button 
              onClick={() => setSelectedTheme(null)} 
              style={{ position: 'absolute', top: 16, right: 16, background: 'transparent', border: 'none', color: '#8b949e', cursor: 'pointer' }}
            >
              <X size={20} />
            </button>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
              <Zap size={20} color="#c084fc" />
              <h3 style={{ margin: 0, fontSize: 18, color: '#e6edf3', fontFamily: 'monospace' }}>{selectedTheme} <span style={{ fontSize: 12, color: '#8b949e', fontWeight: 400 }}>活跃个股明细</span></h3>
            </div>
            
            {loadingTheme ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#8b949e', fontSize: 13, fontFamily: 'monospace' }}>加载中...</div>
            ) : themeStocks?.error ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#f43f5e', fontSize: 13, fontFamily: 'monospace' }}>{themeStocks.error}</div>
            ) : themeStocks?.stocks?.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: '60vh', overflowY: 'auto', paddingRight: 8 }}>
                {themeStocks.stocks.map((s, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: 'rgba(255,255,255,0.03)', border: '1px solid #21262d', borderRadius: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span style={{ fontSize: 12, color: '#8b949e', fontFamily: 'monospace', width: 24 }}>{i+1}.</span>
                      <div>
                        <a 
                          href={`https://quote.eastmoney.com/${s.ts_code.substring(7).toLowerCase()}${s.ts_code.substring(0, 6)}.html`} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          style={{ textDecoration: 'none', cursor: 'pointer' }}
                          title="在东方财富查看该股票详情"
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <div style={{ fontSize: 14, fontWeight: 700, color: '#e6edf3' }} className="hover:text-indigo-400">{s.name}</div>
                            {s.market && <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 4, background: 'rgba(167,139,250,0.12)', color: '#a78bfa', fontFamily: 'monospace', border: '1px solid rgba(167,139,250,0.25)' }}>{s.market}</span>}
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3 }}>
                            <div style={{ fontSize: 10, color: '#6e7681', fontFamily: 'monospace' }} className="hover:text-indigo-300">{s.ts_code}</div>
                            {s.industry && s.industry !== '--' && <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 4, background: 'rgba(34,211,238,0.08)', color: '#22d3ee', fontFamily: 'monospace', border: '1px solid rgba(34,211,238,0.2)' }}>{s.industry}</span>}
                          </div>
                        </a>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 20, textAlign: 'right' }}>
                      <div>
                        <div style={{ fontSize: 10, color: '#6e7681', fontFamily: 'monospace', marginBottom: 2 }}>涨跌幅</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: s.pct_chg > 0 ? '#f43f5e' : s.pct_chg < 0 ? '#10b981' : '#e6edf3', fontFamily: 'monospace' }}>
                          {s.pct_chg > 0 ? '+' : ''}{s.pct_chg}%
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: 10, color: '#6e7681', fontFamily: 'monospace', marginBottom: 2 }}>近5日</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: (s.pct_chg_5d ?? 0) > 0 ? '#f43f5e' : (s.pct_chg_5d ?? 0) < 0 ? '#10b981' : '#e6edf3', fontFamily: 'monospace' }}>
                          {(s.pct_chg_5d ?? 0) > 0 ? '+' : ''}{s.pct_chg_5d ?? 0}%
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: 10, color: '#6e7681', fontFamily: 'monospace', marginBottom: 2 }}>换手率</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3', fontFamily: 'monospace' }}>{s.turnover_rate}%</div>
                      </div>
                      <div style={{ width: 70 }}>
                        <div style={{ fontSize: 10, color: '#6e7681', fontFamily: 'monospace', marginBottom: 2 }}>净买入</div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: s.net_inflow > 0 ? '#f43f5e' : '#10b981', fontFamily: 'monospace' }}>
                          {s.net_inflow > 0 ? '+' : ''}{s.net_inflow} 亿
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#8b949e', fontSize: 13, fontFamily: 'monospace' }}>无数据</div>
            )}
          </div>
        </div>
      )}

      {/* 风格轮动穿透弹窗 */}
      {showStyleStocks && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }} onClick={() => setShowStyleStocks(false)} />
          <div style={{ position: 'relative', width: '100%', maxWidth: 700, background: '#161b22', border: '1px solid #30363d', borderRadius: 16, padding: '24px', boxShadow: '0 20px 40px rgba(0,0,0,0.8)' }}>
            <button 
              onClick={() => setShowStyleStocks(false)}
              style={{ position: 'absolute', top: 20, right: 20, background: 'transparent', border: 'none', color: '#8b949e', cursor: 'pointer', padding: 4 }}
            >
              <X size={20} />
            </button>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
              <TrendingUp size={20} color="#a78bfa" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: '#8b949e', fontFamily: 'monospace', marginBottom: 2 }}>
                  {styleStocksData?.date} · 支撑个股明细 (Top 20)
                </div>
                <div style={{ fontSize: 16, fontWeight: 800, color: '#a78bfa', fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {styleStocksData?.style}
                </div>
              </div>
            </div>
            
            {loadingStyleStocks ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#8b949e', fontSize: 13, fontFamily: 'monospace' }}>加载中...</div>
            ) : styleStocksData?.error ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#f43f5e', fontSize: 13, fontFamily: 'monospace' }}>{styleStocksData.error}</div>
            ) : styleStocksData?.stocks?.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: '60vh', overflowY: 'auto', paddingRight: 8 }}>
                {styleStocksData.stocks.map((s, i) => {
                  let metricValue = ''
                  let metricLabel = ''
                  let metricColor = '#e6edf3'
                  if (styleStocksData.style.includes('Turnover')) {
                    metricLabel = '换手率'
                    metricValue = `${s.turnover_rate}%`
                    metricColor = '#c084fc'
                  } else if (styleStocksData.style.includes('Chips')) {
                    metricLabel = '筹码锁仓'
                    metricValue = `${s.chips_peak_pct}%`
                    metricColor = '#10b981'
                  } else if (styleStocksData.style.includes('Inflow')) {
                    metricLabel = '净买入'
                    metricValue = `${s.net_mf_amount > 0 ? '+' : ''}${s.net_mf_amount} 亿`
                    metricColor = s.net_mf_amount > 0 ? '#f43f5e' : '#10b981'
                  }
                  
                  return (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', background: 'rgba(255,255,255,0.03)', border: '1px solid #21262d', borderRadius: 10, gap: 8 }}>
                      {/* 左侧：序号 + 名称信息 */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 }}>
                        <span style={{ fontSize: 11, color: '#6e7681', fontFamily: 'monospace', width: 20, flexShrink: 0, textAlign: 'right' }}>{i+1}.</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <a 
                            href={`https://quote.eastmoney.com/${String(s.ts_code || '').substring(7).toLowerCase()}${String(s.ts_code || '').substring(0, 6)}.html`} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            style={{ textDecoration: 'none', cursor: 'pointer', display: 'block' }}
                            title="在东方财富查看该股票详情"
                          >
                            {/* 第一行：名称 + 市场标签 */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'nowrap', minWidth: 0 }}>
                              <div style={{ fontSize: 14, fontWeight: 700, color: '#e6edf3', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, minWidth: 0 }}>{s.name}</div>
                              {s.market && <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 4, background: 'rgba(167,139,250,0.12)', color: '#a78bfa', fontFamily: 'monospace', border: '1px solid rgba(167,139,250,0.25)', whiteSpace: 'nowrap', flexShrink: 0 }}>{s.market}</span>}
                            </div>
                            {/* 第二行：代码 + 行业标签 */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 3, flexWrap: 'nowrap', minWidth: 0 }}>
                              <div style={{ fontSize: 10, color: '#6e7681', fontFamily: 'monospace', whiteSpace: 'nowrap', flexShrink: 0 }}>{s.ts_code}</div>
                              {s.industry && s.industry !== '--' && <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 4, background: 'rgba(34,211,238,0.08)', color: '#22d3ee', fontFamily: 'monospace', border: '1px solid rgba(34,211,238,0.2)', whiteSpace: 'nowrap', flexShrink: 0 }}>{s.industry.length > 5 ? s.industry.slice(0, 5) + '…' : s.industry}</span>}
                            </div>
                          </a>
                        </div>
                      </div>
                      {/* 右侧：数据指标 */}
                      <div style={{ display: 'flex', gap: 12, textAlign: 'right', flexShrink: 0 }}>
                        <div>
                          <div style={{ fontSize: 9, color: '#6e7681', fontFamily: 'monospace', marginBottom: 2, whiteSpace: 'nowrap' }}>涨跌幅</div>
                          <div style={{ fontSize: 13, fontWeight: 700, color: s.pct_chg > 0 ? '#f43f5e' : s.pct_chg < 0 ? '#10b981' : '#e6edf3', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                            {s.pct_chg > 0 ? '+' : ''}{s.pct_chg}%
                          </div>
                        </div>
                        <div>
                          <div style={{ fontSize: 9, color: '#6e7681', fontFamily: 'monospace', marginBottom: 2, whiteSpace: 'nowrap' }}>近5日</div>
                          <div style={{ fontSize: 13, fontWeight: 700, color: (s.pct_chg_5d ?? 0) > 0 ? '#f43f5e' : (s.pct_chg_5d ?? 0) < 0 ? '#10b981' : '#e6edf3', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                            {(s.pct_chg_5d ?? 0) > 0 ? '+' : ''}{s.pct_chg_5d ?? 0}%
                          </div>
                        </div>
                        <div style={{ minWidth: 52 }}>
                          <div style={{ fontSize: 9, color: '#6e7681', fontFamily: 'monospace', marginBottom: 2, whiteSpace: 'nowrap' }}>{metricLabel}</div>
                          <div style={{ fontSize: 13, fontWeight: 700, color: metricColor, fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                            {metricValue}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#8b949e', fontSize: 13, fontFamily: 'monospace' }}>无数据</div>
            )}
          </div>
        </div>
      )}

    </div>
  )
}
