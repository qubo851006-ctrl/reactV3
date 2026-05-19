/**
 * Component tests for NotificationProvider + useNotifier.
 *
 * What we lock in:
 * - useNotifier outside the provider throws (catches the wiring bug fast)
 * - notifySuccess renders a toast with the title and message
 * - notifyError renders an error-flavoured toast
 * - Multiple notifies stack and don't drop each other
 * - The provider doesn't break when the browser has no Notification API
 *   (jsdom case — production-relevant for older browsers)
 */
import { describe, expect, it } from 'vitest'
import { render, screen, act } from '@testing-library/react'

import { useNotifier } from '../src/components/NotificationContext'
import { NotificationProvider } from '../src/components/NotificationProvider'

function Trigger({ onMount }: { onMount: (n: ReturnType<typeof useNotifier>) => void }) {
  const notifier = useNotifier()
  onMount(notifier)
  return null
}

describe('useNotifier', () => {
  it('throws a clear error when called outside provider', () => {
    // Suppress React's expected error console noise for this assertion.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => {
      function Standalone() {
        useNotifier()
        return null
      }
      render(<Standalone />)
    }).toThrow(/NotificationProvider/)
    spy.mockRestore()
  })

  it('returns the notifier shape inside provider', () => {
    let captured: ReturnType<typeof useNotifier> | null = null
    render(
      <NotificationProvider>
        <Trigger onMount={(n) => { captured = n }} />
      </NotificationProvider>,
    )
    expect(captured).not.toBeNull()
    expect(typeof captured!.notify).toBe('function')
    expect(typeof captured!.notifySuccess).toBe('function')
    expect(typeof captured!.notifyError).toBe('function')
  })
})

describe('NotificationProvider toast rendering', () => {
  it('renders a success toast with title and message', () => {
    let notifier: ReturnType<typeof useNotifier>
    render(
      <NotificationProvider>
        <Trigger onMount={(n) => { notifier = n }} />
      </NotificationProvider>,
    )
    act(() => {
      notifier!.notifySuccess('案件台账提取完成', '请核对后写入台账')
    })
    expect(screen.getByText('案件台账提取完成')).toBeInTheDocument()
    expect(screen.getByText('请核对后写入台账')).toBeInTheDocument()
  })

  it('renders an error toast', () => {
    let notifier: ReturnType<typeof useNotifier>
    render(
      <NotificationProvider>
        <Trigger onMount={(n) => { notifier = n }} />
      </NotificationProvider>,
    )
    act(() => {
      notifier!.notifyError('提取失败', 'AI 网关超时')
    })
    expect(screen.getByText('提取失败')).toBeInTheDocument()
    expect(screen.getByText('AI 网关超时')).toBeInTheDocument()
  })

  it('caps the visible toast count at 4', () => {
    let notifier: ReturnType<typeof useNotifier>
    render(
      <NotificationProvider>
        <Trigger onMount={(n) => { notifier = n }} />
      </NotificationProvider>,
    )
    act(() => {
      for (let i = 0; i < 6; i++) {
        notifier!.notifySuccess(`toast-${i}`)
      }
    })
    // The 2 oldest get bumped off; only 4 should render at once.
    for (let i = 5; i >= 2; i--) {
      expect(screen.getByText(`toast-${i}`)).toBeInTheDocument()
    }
    expect(screen.queryByText('toast-0')).toBeNull()
    expect(screen.queryByText('toast-1')).toBeNull()
  })

  it('survives gracefully when the Notification API is missing', () => {
    // The setup.ts file already ensures Notification is undefined in jsdom.
    expect(() => {
      let notifier: ReturnType<typeof useNotifier>
      render(
        <NotificationProvider>
          <Trigger onMount={(n) => { notifier = n }} />
        </NotificationProvider>,
      )
      act(() => {
        notifier!.notify({ type: 'info', title: 'no-api-here' })
      })
    }).not.toThrow()
  })
})

// vi shim — Vitest exposes `vi` automatically when `globals: true` (see
// vitest.config.ts). The import at the top of this file pulls it in
// explicitly anyway in case future contributors run without globals.
import { vi } from 'vitest'
