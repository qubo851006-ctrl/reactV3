import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * 错误边界（v3.6.17）。
 *
 * React 渲染期/生命周期里抛出的异常默认会卸载整棵组件树 → 整页白屏。
 * 本组件捕获子树异常，渲染兜底 UI 而非白屏，并保留"重试 / 刷新"出口。
 *
 * 两种用法：
 *   - 顶层（main.tsx）：fullPage 全屏兜底，是白屏的最后一道防线。
 *   - 区域级（如各业务 Flow）：内联卡片兜底，单个模块崩溃不连累外壳，
 *     侧栏/头部/其他会话仍可用，点"重试"即可重挂该模块。
 *
 * 错误边界必须是类组件（React 未提供 Hook 版）。
 */
interface Props {
  children: ReactNode
  /** 区域名，用于内联兜底文案，如"三表合并"。 */
  label?: string
  /** true=全屏兜底（顶层用）；省略=内联卡片兜底（区域级用）。 */
  fullPage?: boolean
  /** 自定义兜底渲染，优先级最高。 */
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 记录到控制台便于排查；后续可在此接入前端日志上报。
    console.error(
      `[ErrorBoundary] ${this.props.label ?? 'app'} 渲染异常：`,
      error,
      info.componentStack,
    )
  }

  private reset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    if (this.props.fallback) return this.props.fallback(error, this.reset)

    if (this.props.fullPage) {
      return (
        <div className="h-screen w-full flex flex-col items-center justify-center bg-slate-950 px-6 text-center select-none">
          <div className="text-5xl mb-4">😵</div>
          <div className="text-lg font-semibold text-slate-100 mb-2">应用遇到错误</div>
          <div className="text-sm text-slate-400 mb-6 max-w-md break-words">
            页面渲染时出现异常，已停止以避免数据错乱。请刷新页面重试；若反复出现请联系管理员。
          </div>
          <div className="text-xs text-slate-500 mb-6 max-w-lg break-words font-mono">
            {error.message}
          </div>
          <button
            onClick={() => window.location.reload()}
            className="px-5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm transition-colors"
          >
            刷新页面
          </button>
        </div>
      )
    }

    const label = this.props.label ?? '该模块'
    return (
      <div className="bg-slate-800 border border-rose-500/40 rounded-2xl p-5 my-3">
        <div className="flex items-center gap-2 text-rose-300 text-sm font-medium mb-2">
          <span>⚠️</span>
          <span>{label}出错了</span>
        </div>
        <div className="text-xs text-slate-400 mb-3 break-words">
          该模块渲染时出现异常，已隔离以免影响其它功能。可点"重试"重新加载，或刷新整个页面。
        </div>
        <div className="text-xs text-slate-500 mb-3 break-words font-mono">{error.message}</div>
        <div className="flex items-center gap-2">
          <button
            onClick={this.reset}
            className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs transition-colors"
          >
            重试
          </button>
          <button
            onClick={() => window.location.reload()}
            className="px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 text-xs transition-colors"
          >
            刷新页面
          </button>
        </div>
      </div>
    )
  }
}
