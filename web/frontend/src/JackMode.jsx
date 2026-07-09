import React, { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { Flame, ShieldAlert, Award, Star, Activity, ArrowUpRight, ArrowDownRight, Calendar, User, MessageSquare } from 'lucide-react'

// ── 模拟博主实盘发帖与交易时间线 ──────────────────────────────────────
const JACK_TIMELINE = [
  {
    date: '2026-05-14',
    stock: '通鼎互联',
    position: '94.44%',
    profit: '-5.48%',
    action: '买入',
    tweet: '“空仓了四天，然后今天竟然这样”',
    status: 'down',
    details: '全仓买入首日即遭遇单日重锤，回撤开始。'
  },
  {
    date: '2026-05-15',
    stock: '通鼎互联',
    position: '0.00%',
    profit: '-2.28%',
    action: '割肉清仓',
    tweet: '“没什么好看的，这种神仙行情，我怕了还不行吗”',
    status: 'down',
    details: '心痛割肉通鼎互联，资产回撤至 72.6万。'
  },
  {
    date: '2026-05-19',
    stock: '深科技',
    position: '94.84%',
    profit: '+1.63%',
    action: '买入',
    tweet: '“今天干对了，但是干得太少了！明天继续干！”',
    status: 'up',
    details: '在集合竞价再次满仓打入深科技，小幅回血。'
  },
  {
    date: '2026-05-20',
    stock: '华工科技',
    position: '91.54%',
    profit: '+3.91%',
    action: '换仓买入',
    tweet: '“连红第二天了！明天继续！”',
    status: 'up',
    details: '深科技止盈赚2.4万，随即换仓华工科技继续获利。'
  },
  {
    date: '2026-05-26',
    stock: '京东方A',
    position: '95.46%',
    profit: '+9.02%',
    action: '持股',
    tweet: '“明天空仓休息！今天师父的社区那边都爆了！太爽了！”',
    status: 'up',
    details: '京东方A单日大涨，账面浮盈扩大至 8.47万。'
  },
  {
    date: '2026-05-29',
    stock: '天通股份',
    position: '94.47%',
    profit: '-3.55%',
    action: '买入',
    tweet: '“没有一个对大A是不服的，我服，下周一我空仓”',
    status: 'down',
    details: '买入天通股份即遭遇逆风，心情再度郁闷。'
  },
  {
    date: '2026-06-04',
    stock: '东材科技',
    position: '96.47%',
    profit: '+4.92%',
    action: '换仓买入',
    tweet: '“涨停是涨停了！但是错过了！再也是也满足了！明天继续！”',
    status: 'up',
    details: '太极实业大赚清仓，换仓东材科技继续大涨。'
  },
  {
    date: '2026-06-05',
    stock: '通鼎互联',
    position: '95.37%',
    profit: '-6.53%',
    action: '追高买入',
    tweet: '“今天都不太想说话！太恶心了！垃圾行情！”',
    status: 'down',
    details: '东材科技高位跌停离场，再度满仓砸入通鼎互联遭遇闷杀。'
  },
  {
    date: '2026-06-08',
    stock: '通鼎互联',
    position: '0.00%',
    profit: '-6.74%',
    action: '全仓割肉',
    tweet: '“清仓防守！今天大家还好吗？”',
    status: 'down',
    details: '通鼎互联暴跌中认赔离场，单日资产折损5.3万。'
  },
  {
    date: '2026-06-12',
    stock: '太极实业',
    position: '91.18%',
    profit: '-7.95%',
    action: '买入',
    tweet: '“下周换策略打法了！这么下去不行了！”',
    status: 'down',
    details: '买入太极实业遭遇股灾级重挫，单日浮亏达8.2万。'
  },
  {
    date: '2026-06-15',
    stock: '韩建河山',
    position: '92.30%',
    profit: '-1.46%',
    action: '割肉换仓',
    tweet: '“不要看！我没脸！”',
    status: 'down',
    details: '割肉太极实业，换仓韩建河山继续下跌，资产跌至谷底67.7万。'
  },
  {
    date: '2026-06-16',
    stock: '京基智农',
    position: '96.04%',
    profit: '+10.95%',
    action: '割肉换仓',
    tweet: '“我好像又行了，哈哈哈”',
    status: 'up',
    details: '割肉韩建河山，一把梭哈买入京基智农，喜获涨停，单日暴赚7.4万回血！'
  },
  {
    date: '2026-06-25',
    stock: '长电科技',
    position: '94.67%',
    profit: '+3.93%',
    action: '买入',
    tweet: '“涨停！”',
    status: 'up',
    details: '端午节空仓一周后，集合竞价满仓长电科技斩获佳绩。'
  },
  {
    date: '2026-07-02',
    stock: '多氟多',
    position: '0.00%',
    profit: '+1.25%',
    action: '清仓锁定',
    tweet: '“今天空仓是空真的漂亮！躲过股灾级别回调！”',
    status: 'up',
    details: '多氟多冲高清仓，获利2.95万。全仓空仓，成功规避当日暴跌。'
  },
  {
    date: '2026-07-03',
    stock: '空仓',
    position: '0.00%',
    profit: '0.00%',
    action: '观望',
    tweet: '“今天师父的抄底策略牛逼，但是我还没有上，可惜了！”',
    status: 'up',
    details: '锁定88.3万资产战果，以空仓状态结束本轮操作实盘。'
  }
]

function JackMode() {
  const [data, setData] = useState([])
  const [metrics, setMetrics] = useState({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/jack-performance')
      .then(res => res.json())
      .then(res => {
        setData(res.chart_data)
        setMetrics(res.metrics)
        setLoading(false)
      })
      .catch(err => {
        console.error(err)
        setLoading(false)
      })
  }, [])

  return (
    <div className="space-y-8" id="jack-mode-view">
      {/* 🔮 游资自适应路由业绩看板 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        <div className="p-6 bg-[#151D30]/80 backdrop-blur-md rounded-2xl border border-[#222F4C] hover:border-purple-500/40 transition-all duration-300 space-y-1">
          <span className="text-xs text-gray-400 font-mono">年化绝对收益</span>
          <div className="text-2xl font-bold font-mono text-emerald-400 flex items-center">
            <Award className="h-5 w-5 mr-1.5 text-emerald-400 animate-pulse" />
            <span>{metrics.portfolio_ann_return || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono block">累计净收益: {metrics.portfolio_total_return || '0.00%'}</span>
        </div>

        <div className="p-6 bg-[#151D30]/80 backdrop-blur-md rounded-2xl border border-[#222F4C] hover:border-purple-500/40 transition-all duration-300 space-y-1">
          <span className="text-xs text-gray-400 font-mono">绝对最大回撤</span>
          <div className="text-2xl font-bold font-mono text-rose-400 flex items-center">
            <ShieldAlert className="h-5 w-5 mr-1.5 text-rose-400" />
            <span>{metrics.portfolio_max_drawdown || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono block">绝对卡玛比率: {metrics.portfolio_calmar || '0.00'}</span>
        </div>

        <div className="p-6 bg-[#151D30]/80 backdrop-blur-md rounded-2xl border border-[#222F4C] hover:border-purple-500/40 transition-all duration-300 space-y-1">
          <span className="text-xs text-gray-400 font-mono">年化超额收益 (Alpha)</span>
          <div className="text-2xl font-bold font-mono text-purple-400 flex items-center">
            <Star className="h-5 w-5 mr-1.5 text-purple-400" />
            <span>{metrics.excess_ann_return || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono block">超额总收益: {metrics.excess_total_return || '0.00%'}</span>
        </div>

        <div className="p-6 bg-[#151D30]/80 backdrop-blur-md rounded-2xl border border-[#222F4C] hover:border-purple-500/40 transition-all duration-300 space-y-1">
          <span className="text-xs text-gray-400 font-mono">超额最大回撤与卡玛</span>
          <div className="text-2xl font-bold font-mono text-purple-300 flex items-center">
            <Activity className="h-5 w-5 mr-1.5 text-purple-300" />
            <span>{metrics.excess_max_drawdown || '0.00%'}</span>
          </div>
          <span className="text-xs text-gray-500 font-mono block">超额卡玛比率: {metrics.excess_calmar || '0.00'}</span>
        </div>
      </div>

      {/* 📈 散户/游资风格模拟曲线 (Recharts) */}
      <div className="p-6 bg-[#151D30]/60 backdrop-blur-md rounded-2xl border border-[#222F4C] space-y-4">
        <div className="flex items-center justify-between">
          <h4 className="font-bold text-gray-100 font-sans flex items-center space-x-2">
            <Flame className="h-5 w-5 text-purple-400 animate-bounce" />
            <span>散户/游资风格自适应路由累计净值走势 (组合 vs 基准 vs 超额 Alpha)</span>
          </h4>
          <span className="text-xs text-gray-500 font-mono">回测周期: {metrics.total_weeks || 0} 周 (最近 52 周)</span>
        </div>

        {loading ? (
          <div className="h-96 flex items-center justify-center text-gray-500 font-mono">加载时序数据中...</div>
        ) : (
          <div className="h-96 w-full font-mono text-xs">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data}
                margin={{ top: 10, right: 20, left: 0, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#222F4C" />
                <XAxis dataKey="date" stroke="#9CA3AF" tickLine={false} />
                <YAxis stroke="#9CA3AF" tickLine={false} domain={['auto', 'auto']} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#151D30', borderColor: '#222F4C', color: '#fff' }}
                  labelStyle={{ fontWeight: 'bold' }}
                />
                <Legend verticalAlign="top" height={36} />
                <Line
                  name="游资组合绝对净值 (Portfolio)"
                  type="monotone"
                  dataKey="portfolio"
                  stroke="#10B981"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 6 }}
                />
                <Line
                  name="等权大盘基准净值 (Benchmark)"
                  type="monotone"
                  dataKey="benchmark"
                  stroke="#9CA3AF"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  dot={false}
                />
                <Line
                  name="游资组合超额净值 (Excess Alpha)"
                  type="monotone"
                  dataKey="excess"
                  stroke="#A855F7"
                  strokeWidth={2.5}
                  dot={false}
                  activeDot={{ r: 6 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* 🛡️ 诊断与反思说明 */}
      <div className="p-6 bg-[#181127]/40 rounded-2xl border border-purple-900/30 grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
        <div className="space-y-2">
          <h4 className="font-bold text-gray-200 text-sm flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-purple-400" />
            <span>游资回测诊断：为何长期业绩跑输基准？</span>
          </h4>
          <p className="text-xs text-gray-400 leading-relaxed font-sans">
            该策略高度模拟散户在“牛市追强动量，震荡市抄底，熊市主观空仓”的习惯。
            数据表明，在缺乏基本面支撑和贝塔平滑控制下，<strong>“无脑开盘集合竞价梭哈”</strong>极易在牛市中买在日内最高点（追高闷杀），并在阴跌中不断“接飞刀式左侧抄底”被套，加之每周全仓轮动产生高达 <strong>15.6%</strong> 的交易摩擦成本，严重蚕食了本金。
          </p>
        </div>
        <div className="p-4 bg-[#0F1424] rounded-xl border border-[#222F4C] space-y-2 text-xs">
          <div className="flex justify-between">
            <span className="text-gray-400 font-mono">周绝对胜率:</span>
            <span className="font-bold font-mono text-emerald-400">{metrics.win_rate || '0.0%'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400 font-mono">周超额胜率:</span>
            <span className="font-bold font-mono text-purple-400">{metrics.ex_win_rate || '0.0%'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400 font-mono">每周全仓换手摩擦:</span>
            <span className="font-bold font-mono text-rose-400">双边 0.30% / 周</span>
          </div>
        </div>
      </div>

      {/* 🗺️ 博主“90后Jack”实盘回顾与交易时间轴对照 */}
      <div className="p-6 bg-[#151D30]/40 backdrop-blur-md rounded-2xl border border-[#222F4C] space-y-6">
        <div className="flex items-center space-x-2">
          <User className="h-5 w-5 text-purple-400" />
          <h3 className="text-base font-bold text-gray-100">博主“90后Jack”实盘发帖与交易时间线对照</h3>
        </div>

        <div className="relative border-l-2 border-[#222F4C] ml-4 pl-6 space-y-8">
          {JACK_TIMELINE.map((item, idx) => (
            <div key={idx} className="relative group">
              {/* 时间线圆点 */}
              <div className={`absolute -left-[31px] top-1 h-4.5 w-4.5 rounded-full border-4 border-[#0B0F19] transition-transform duration-300 group-hover:scale-125 ${
                item.status === 'up' ? 'bg-emerald-500' : 'bg-rose-500'
              }`} />

              <div className="p-5 bg-[#0F1424]/75 rounded-2xl border border-[#1F2937] hover:border-purple-500/30 transition-all duration-300 space-y-3">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 text-gray-400 font-mono">
                    <Calendar className="h-3.5 w-3.5" />
                    <span>{item.date}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 font-mono">
                      {item.action}
                    </span>
                    <span className={`flex items-center font-mono font-bold ${
                      item.status === 'up' ? 'text-emerald-400' : 'text-rose-400'
                    }`}>
                      {item.status === 'up' ? <ArrowUpRight className="h-3.5 w-3.5 mr-0.5" /> : <ArrowDownRight className="h-3.5 w-3.5 mr-0.5" />}
                      {item.profit}
                    </span>
                  </div>
                </div>

                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-bold text-gray-100">{item.stock}</span>
                  <span className="text-xs text-gray-500 font-mono">仓位 {item.position}</span>
                </div>

                <div className="p-3 bg-[#151D30]/80 rounded-lg border border-[#222F4C] italic text-gray-300 text-xs flex items-start gap-2">
                  <MessageSquare className="h-4 w-4 text-purple-400 flex-shrink-0 mt-0.5" />
                  <span className="font-sans leading-relaxed">{item.tweet}</span>
                </div>

                <p className="text-xs text-gray-500 leading-relaxed font-sans">{item.details}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default JackMode
