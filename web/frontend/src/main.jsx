import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './index.css'

// ═══════════════════════════════════════════════════════════════════
// fetchSafe: 对全局 fetch 的极简包装
// ----------------------------------------------------------------
// 背景：macOS / Linux 发行版的 /etc/hosts 通常把 localhost 同时
// 指向 127.0.0.1 (A) 和 ::1 (AAAA)。浏览器遵循 RFC 6555 Happy
// Eyeballs 会对两条路径竞争，率先失败的那条立刻把 Promise 推
// 到 .catch()，造成用户界面看到间歇性的
//   · 策略引擎 OFFLINE
//   · 页面红框 "❌ 错误: Failed to fetch"
// 即便另一条路径几百毫秒后其实能成功也是如此。
//
// 修复思路：对典型连接失败（TypeError 网络类错误 / 502 网关 /
// localhost 场景）自动重试 **最多 1 次**，重试时把主机强制改成
// 127.0.0.1 跳过 IPv6 竞态。非 localhost 环境（穿网、部署域）
// 只做同路径重试、不改主机，避免破坏生产路由。
// ═══════════════════════════════════════════════════════════════════
;(function installFetchSafe() {
  const _orig = window.fetch
  if (!_orig || typeof _orig !== 'function') return
  const LOCAL_RE = /^(https?:)?\/\/(localhost|\[::1\])(:\d+)?(\/|$)/i
  const NET_ERR = (e) =>
    e && (
      (e instanceof TypeError && /fetch|network|load/gi.test(e.message || '')) ||
      e.name === 'NetworkError' ||
      e.code === 'ECONNREFUSED' ||
      e.cause?.code === 'ECONNREFUSED'
    )
  window.fetch = function fetchSafe(input, init) {
    const req = (typeof input === 'string') ? input : (input && input.url ? input.url : '')
    return _orig.apply(this, arguments).catch((err) => {
      // 仅在连接类错误时给一次机会；HTTP 4xx/5xx 不重试（由调用方处理）
      if (!NET_ERR(err)) throw err
      const retryArgs = arguments
      // localhost 场景：把主机改写为 127.0.0.1 绕开 IPv6 Happy Eyeballs 竞态
      if (LOCAL_RE.test(req)) {
        const rewrite = req.replace(LOCAL_RE, (_m, _p, _h, port, _s) => {
          const proto = _p || location.protocol
          return `${proto}//127.0.0.1${port || ':8000'}${_s || '/'}`
        })
        return _orig.call(this, rewrite, init)
      }
      // 非 localhost：原样重试一次（穿网抖动自愈）
      return _orig.apply(this, retryArgs)
    })
  }
  window.fetch.__orig = _orig
})()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      {/* zoom-root: 全局缩放容器，由 App.jsx 内的 useEffect 动态修改 transform */}
      <div id="zoom-root">
        <App />
      </div>
    </BrowserRouter>
  </React.StrictMode>,
)
