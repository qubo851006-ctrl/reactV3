import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import IdentityLogin from '../src/components/IdentityLogin'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

describe('IdentityLogin DingTalk SSO fallback', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    window.dd = undefined
  })

  afterEach(() => {
    window.dd = undefined
  })

  it('falls back to short-code login when DingTalk authCode is unavailable', async () => {
    const onLogin = vi.fn()
    window.dd = {}
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify({
        users: [{ id: 1, name: '管理员', department: '法务部' }],
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        enabled: true,
        corp_id: 'corp-1',
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        user: { id: 1, name: '管理员', department: '法务部', role: 'admin' },
      }), { status: 200 }))

    render(<IdentityLogin onLogin={onLogin} />)

    fireEvent.click(await screen.findByRole('button', { name: /管理员/ }))
    fireEvent.change(screen.getByPlaceholderText(/4/), { target: { value: '1234' } })
    fireEvent.click(screen.getAllByRole('button').at(-1)!)

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith({
      id: 1,
      name: '管理员',
      department: '法务部',
      role: 'admin',
    }))
    expect(fetch).toHaveBeenCalledWith('/api/auth/bind-device', expect.objectContaining({ method: 'POST' }))
    expect(fetch).not.toHaveBeenCalledWith('/api/auth/dingtalk/sso', expect.anything())
  })

  it('shows backend SSO errors and keeps the login form usable', async () => {
    window.dd = {
      runtime: {
        permission: {
          requestAuthCode: ({ onSuccess }) => onSuccess({ code: 'auth-code' }),
        },
      },
    }
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify({
        users: [{ id: 1, name: '管理员', department: '法务部' }],
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        enabled: true,
        corp_id: 'corp-1',
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        detail: '请联系管理员开通',
      }), { status: 403 }))

    render(<IdentityLogin onLogin={vi.fn()} />)

    expect(await screen.findByText('请联系管理员开通')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /管理员/ })).toBeInTheDocument()
  })
})
