import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listBackgroundTasks } from '../src/api'
import AdminCenterPanel from '../src/components/AdminCenterPanel'

vi.mock('../src/api', async () => {
  const actual = await vi.importActual<typeof import('../src/api')>('../src/api')
  return {
    ...actual,
    listBackgroundTasks: vi.fn(),
  }
})

function healthPayload() {
  return {
    version: { app_version: 'v3.6.2', branch: 'master', commit: 'abc1234', commit_full: 'abc123456', commit_time: '' },
    runtime: { started_at: '2026-05-21T09:00:00Z', server_time: '2026-05-21T10:00:00Z' },
    databases: {
      main: { ok: true, backend: 'postgresql', error: '' },
      llm_audit: { ok: true, backend: 'postgresql', error: '' },
    },
    dingtalk: { notify_enabled: true },
    recent_errors: [],
    recent_failed_tasks: [],
  }
}

function renderPanel(overrides = {}) {
  const props = {
    open: true,
    onClose: vi.fn(),
    onOpenUsers: vi.fn(),
    onOpenDingTalk: vi.fn(),
    onOpenAiQuality: vi.fn(),
    ...overrides,
  }
  render(<AdminCenterPanel {...props} />)
  return props
}

describe('AdminCenterPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(healthPayload()), { status: 200 })))
    vi.mocked(listBackgroundTasks).mockResolvedValue([
      {
        task_id: 'task_1',
        type: 'ledger_merge',
        status: 'succeeded',
        progress: 100,
        message: '完成',
        result: null,
        error: null,
        created_by: 1,
        created_at: '2026-05-21T09:00:00Z',
        updated_at: '2026-05-21T09:01:00Z',
        started_at: '2026-05-21T09:00:00Z',
        finished_at: '2026-05-21T09:01:00Z',
      },
    ])
  })

  it('opens on system health tab', async () => {
    renderPanel()

    expect(screen.getByText('管理员中心')).toBeInTheDocument()
    expect(await screen.findByText('v3.6.2')).toBeInTheDocument()
    expect(screen.getAllByText('postgresql').length).toBeGreaterThan(0)
  })

  it('shows background task list tab', async () => {
    renderPanel()

    fireEvent.click(screen.getByText('后台任务'))

    await waitFor(() => expect(listBackgroundTasks).toHaveBeenCalledWith(100))
    expect(screen.getByText('task_1')).toBeInTheDocument()
    expect(screen.getByText('ledger_merge')).toBeInTheDocument()
  })

  it('launches existing admin panels from tabs', () => {
    const props = renderPanel()

    fireEvent.click(screen.getByText('用户'))
    fireEvent.click(screen.getByText('打开用户管理'))
    expect(props.onOpenUsers).toHaveBeenCalled()

    fireEvent.click(screen.getByText('钉钉'))
    fireEvent.click(screen.getByText('打开钉钉管理'))
    expect(props.onOpenDingTalk).toHaveBeenCalled()

    fireEvent.click(screen.getByText('AI 质量'))
    fireEvent.click(screen.getByText('打开 AI 质量仪表盘'))
    expect(props.onOpenAiQuality).toHaveBeenCalled()
  })
})
