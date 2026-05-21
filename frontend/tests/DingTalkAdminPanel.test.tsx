import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DingTalkAdminPanel from '../src/components/DingTalkAdminPanel'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

function mockLogResponses() {
  vi.mocked(fetch)
    .mockResolvedValueOnce(new Response(JSON.stringify({
      logs: [{
        id: 1,
        task: '三台账合并',
        level: 'success',
        stage: '合并生成',
        title: '三台账合并完成',
        summary: '合同条数：3',
        user_name: '管理员',
        at_user_id: 'ding-admin',
        sent: true,
        skipped_reason: null,
        http_status: 200,
        provider_code: null,
        provider_message: null,
        error: null,
        created_at: '2026-05-21T09:00:00Z',
      }],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      logs: [{
        id: 1,
        status: 'ok',
        root_dept_id: '1',
        department_count: 2,
        remote_user_count: 3,
        matched_count: 1,
        created_count: 0,
        updated_count: 1,
        skipped_count: 2,
        error: null,
        started_at: '2026-05-21T09:00:00Z',
        finished_at: '2026-05-21T09:01:00Z',
      }],
    }), { status: 200 }))
}

describe('DingTalkAdminPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('loads notification and sync logs when opened', async () => {
    mockLogResponses()

    render(<DingTalkAdminPanel open onClose={vi.fn()} />)

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/admin/dingtalk/notification-logs', expect.any(Object)))
    expect(fetch).toHaveBeenCalledWith('/api/admin/dingtalk/sync-logs', expect.any(Object))
    expect(await screen.findByText('三台账合并')).toBeInTheDocument()
    expect(screen.getByText('ok')).toBeInTheDocument()
  })

  it('can send a group notification test and refresh logs', async () => {
    mockLogResponses()
    vi.mocked(fetch)
      .mockImplementationOnce(() => jsonResponse({ ok: true }))
      .mockImplementationOnce(() => jsonResponse({ logs: [] }))
      .mockImplementationOnce(() => jsonResponse({ logs: [] }))

    render(<DingTalkAdminPanel open onClose={vi.fn()} />)
    await screen.findByText('三台账合并')

    const groupButton = screen.getByText(/Webhook/).closest('button')
    expect(groupButton).not.toBeNull()
    fireEvent.click(groupButton!)

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith('/api/admin/dingtalk/test-notification', expect.objectContaining({ method: 'POST' }))
    })
  })

  it('shows backend errors for failed admin actions', async () => {
    mockLogResponses()
    vi.mocked(fetch).mockImplementationOnce(() => jsonResponse({ detail: 'Webhook 未配置' }, 400))

    render(<DingTalkAdminPanel open onClose={vi.fn()} />)
    await screen.findByText('三台账合并')

    const groupButton = screen.getByText(/Webhook/).closest('button')
    fireEvent.click(groupButton!)

    expect(await screen.findByText('Webhook 未配置')).toBeInTheDocument()
  })
})
