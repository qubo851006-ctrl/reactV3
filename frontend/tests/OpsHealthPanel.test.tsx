import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import OpsHealthPanel from '../src/components/OpsHealthPanel'

function healthPayload() {
  return {
    version: {
      app_version: 'v3.6.2',
      branch: 'master',
      commit: 'abc1234',
      commit_full: 'abc123456789',
      commit_time: '2026-05-21T10:00:00Z',
    },
    runtime: {
      started_at: '2026-05-21T09:00:00Z',
      server_time: '2026-05-21T10:00:00Z',
    },
    databases: {
      main: { ok: true, backend: 'postgresql', error: '' },
      llm_audit: { ok: false, backend: 'not_configured', error: 'LLM_AUDIT_DATABASE_URL not configured' },
    },
    dingtalk: {
      notify_enabled: true,
      webhook_url_configured: true,
      webhook_secret_configured: false,
      enterprise_enabled: true,
    },
    recent_errors: [
      { file: 'uvicorn.err.log', line: 'ERROR example failed', modified_at: '2026-05-21T10:00:00Z' },
    ],
    recent_failed_tasks: [
      {
        task_id: 'task_1',
        type: 'ledger_merge',
        message: '失败',
        error: 'boom',
        created_by: 1,
        created_at: '2026-05-21T09:00:00Z',
        started_at: '2026-05-21T09:01:00Z',
        finished_at: '2026-05-21T09:02:00Z',
        updated_at: '2026-05-21T09:02:00Z',
      },
    ],
  }
}

describe('OpsHealthPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('loads and renders operational health summary', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(healthPayload()), { status: 200 }))

    render(<OpsHealthPanel open onClose={vi.fn()} />)

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/admin/ops/health', expect.objectContaining({
      credentials: 'include',
    })))
    expect(await screen.findByText('v3.6.2')).toBeInTheDocument()
    expect(await screen.findByText('master')).toBeInTheDocument()
    expect(screen.getByText('abc1234')).toBeInTheDocument()
    expect(screen.getByText('postgresql')).toBeInTheDocument()
    expect(screen.getByText('ERROR example failed')).toBeInTheDocument()
    expect(screen.getByText('ledger_merge')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
  })

  it('can refresh the health payload', async () => {
    vi.mocked(fetch).mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify(healthPayload()), { status: 200 }),
    ))

    render(<OpsHealthPanel open onClose={vi.fn()} />)
    await screen.findByText('master')
    fireEvent.click(screen.getByText('刷新'))

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
  })

  it('shows load errors', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ detail: 'admin only' }), { status: 403 }))

    render(<OpsHealthPanel open onClose={vi.fn()} />)

    expect(await screen.findByText('admin only')).toBeInTheDocument()
  })
})
