import React from 'react'
import { AlertTriangle, RefreshCw, Home } from 'lucide-react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo)
    this.setState({ errorInfo })
  }

  handleReload = () => {
    window.location.reload()
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
    window.location.href = '/'
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-[#0B0F19] text-gray-100 flex items-center justify-center p-4 select-none">
          <div className="max-w-md w-full bg-[#111827] border border-rose-500/30 rounded-2xl p-6 shadow-2xl shadow-rose-950/20 text-center">
            <div className="w-12 h-12 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center mx-auto mb-4">
              <AlertTriangle className="h-6 w-6 text-rose-400" />
            </div>

            <h2 className="text-lg font-bold text-gray-100 mb-2">
              页面渲染中断
            </h2>

            <p className="text-xs text-gray-400 mb-4 leading-relaxed">
              客户端组件在执行过程中触发了运行时异常，已安全拦截以保护数据。
            </p>

            {this.state.error && (
              <div className="mb-6 p-3 bg-black/40 border border-gray-800 rounded-lg text-left overflow-hidden">
                <p className="text-[11px] font-mono text-rose-400 break-all line-clamp-3">
                  {this.state.error?.message || String(this.state.error)}
                </p>
              </div>
            )}

            <div className="flex items-center justify-center gap-3">
              <button
                onClick={this.handleReload}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-cyan-600/20 text-cyan-300 border border-cyan-500/30 hover:bg-cyan-600/30 active:scale-95 transition-all"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                刷新页面
              </button>

              <button
                onClick={this.handleReset}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-gray-800 text-gray-200 border border-gray-700 hover:bg-gray-700 active:scale-95 transition-all"
              >
                <Home className="h-3.5 w-3.5" />
                返回首页
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
