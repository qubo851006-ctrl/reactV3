import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ErrorBoundary from '../src/components/ErrorBoundary'

/** 受控抛错组件：boom=true 时在渲染期抛出。 */
function Boom({ boom, message = 'kaboom' }: { boom: boolean; message?: string }) {
  if (boom) throw new Error(message)
  return <div>正常内容</div>
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    // React 会把边界捕获的错误同时打到 console.error，静音以免污染测试输出。
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('子树正常时透传渲染 children', () => {
    render(
      <ErrorBoundary>
        <div>hello world</div>
      </ErrorBoundary>,
    )
    expect(screen.getByText('hello world')).toBeInTheDocument()
  })

  it('子组件抛错时渲染内联兜底（含 label 与错误信息），不白屏', () => {
    render(
      <ErrorBoundary label="三台账合并">
        <Boom boom message="解析失败" />
      </ErrorBoundary>,
    )
    expect(screen.getByText('三台账合并出错了')).toBeInTheDocument()
    expect(screen.getByText('解析失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })

  it('fullPage 模式渲染全屏兜底 + 刷新按钮', () => {
    render(
      <ErrorBoundary fullPage>
        <Boom boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText('应用遇到错误')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeInTheDocument()
  })

  it('点"重试"清除错误态，子树恢复正常后重新渲染 children', () => {
    function Harness() {
      const [boom, setBoom] = useState(true)
      return (
        <div>
          <button onClick={() => setBoom(false)}>修好它</button>
          <ErrorBoundary label="测试模块">
            <Boom boom={boom} />
          </ErrorBoundary>
        </div>
      )
    }
    render(<Harness />)
    // 初始：兜底可见
    expect(screen.getByText('测试模块出错了')).toBeInTheDocument()
    // 先修复底层条件，再点重试 → 边界重置后子树正常渲染
    fireEvent.click(screen.getByText('修好它'))
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(screen.getByText('正常内容')).toBeInTheDocument()
    expect(screen.queryByText('测试模块出错了')).not.toBeInTheDocument()
  })

  it('未传 label 时内联兜底用默认"该模块"', () => {
    render(
      <ErrorBoundary>
        <Boom boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText('该模块出错了')).toBeInTheDocument()
  })

  it('自定义 fallback 优先级最高', () => {
    render(
      <ErrorBoundary fallback={(error) => <div>自定义：{error.message}</div>}>
        <Boom boom message="X" />
      </ErrorBoundary>,
    )
    expect(screen.getByText('自定义：X')).toBeInTheDocument()
  })
})
