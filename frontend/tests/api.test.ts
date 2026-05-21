/**
 * Tests for src/api.ts — the network layer.
 *
 * Focus areas chosen because they're the parts that silently swallow
 * problems if they break:
 * - submitLlmFeedback: must NOT crash the UI when the audit DB is down,
 *   must NOT call fetch at all when trace_ids is empty, must fire one
 *   request per trace_id otherwise
 * - getErrorMessage: thin but used everywhere as the fallback string
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getBackgroundTask, getErrorMessage, listBackgroundTasks, startComplianceExtractTask, startLedgerExtractTask, startLedgerMergeTask, startTrainingExtractTask, submitLlmFeedback } from '../src/api'

describe('getErrorMessage', () => {
  it('returns the Error.message for Error instances', () => {
    expect(getErrorMessage(new Error('boom'), 'fallback')).toBe('boom')
  })

  it('returns the fallback for non-Error values', () => {
    expect(getErrorMessage(null, 'fallback')).toBe('fallback')
    expect(getErrorMessage(undefined, 'fallback')).toBe('fallback')
    expect(getErrorMessage('a string', 'fallback')).toBe('fallback')
    expect(getErrorMessage(42, 'fallback')).toBe('fallback')
  })
})

describe('submitLlmFeedback', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )
  })

  afterEach(() => {
    fetchSpy.mockRestore()
  })

  it('makes no network call when trace_ids is empty', async () => {
    await submitLlmFeedback([], true, null)
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('makes no network call when trace_ids is undefined-ish', async () => {
    // @ts-expect-error — test the defensive guard against runtime undefined
    await submitLlmFeedback(undefined, true, null)
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('fires one POST per trace_id', async () => {
    await submitLlmFeedback(['trace1', 'trace2', 'trace3'], true, null)
    expect(fetchSpy).toHaveBeenCalledTimes(3)
    const urls = fetchSpy.mock.calls.map(([url]) => String(url))
    expect(urls).toEqual([
      '/api/llm-traces/trace1/feedback',
      '/api/llm-traces/trace2/feedback',
      '/api/llm-traces/trace3/feedback',
    ])
  })

  it('sends accepted=true with no edited_to when payload is null', async () => {
    await submitLlmFeedback(['t'], true, null)
    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body))
    expect(body).toEqual({ accepted: true, edited_to: null })
  })

  it('serialises object edited_to as JSON string', async () => {
    await submitLlmFeedback(['t'], true, { 字段: '修正后' })
    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body))
    expect(body.accepted).toBe(true)
    expect(typeof body.edited_to).toBe('string')
    expect(JSON.parse(body.edited_to)).toEqual({ 字段: '修正后' })
  })

  it('passes string edited_to through unchanged', async () => {
    await submitLlmFeedback(['t'], false, 'plain text')
    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body))
    expect(body.edited_to).toBe('plain text')
  })

  it('does NOT throw when the network rejects', async () => {
    fetchSpy.mockRejectedValueOnce(new Error('network gone'))
    await expect(
      submitLlmFeedback(['t'], true, null),
    ).resolves.toBeUndefined()
  })

  it('does NOT throw when the server returns 500', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response('Internal Server Error', { status: 500 }),
    )
    await expect(
      submitLlmFeedback(['t'], true, null),
    ).resolves.toBeUndefined()
  })

  it('keeps going when one trace fails and others succeed', async () => {
    fetchSpy
      .mockResolvedValueOnce(new Response('ok', { status: 200 }))
      .mockRejectedValueOnce(new Error('temporary'))
      .mockResolvedValueOnce(new Response('ok', { status: 200 }))
    await expect(
      submitLlmFeedback(['a', 'b', 'c'], true, null),
    ).resolves.toBeUndefined()
    // All 3 were attempted despite the middle one failing.
    expect(fetchSpy).toHaveBeenCalledTimes(3)
  })
})

describe('background task API helpers', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        task_id: 'task_123',
        type: 'ledger_merge',
        status: 'succeeded',
        progress: 100,
        message: '完成',
        result: { total_contract: 1 },
        error: null,
      }), { status: 200 }),
    )
  })

  afterEach(() => {
    fetchSpy.mockRestore()
  })

  it('starts ledger merge tasks through the async endpoint', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, task_id: 'task_123' }), { status: 200 }),
    )
    const file = new File([new Uint8Array([0x50, 0x4b])], 'contract.xlsx')

    const result = await startLedgerMergeTask(file, null, null)

    expect(result.task_id).toBe('task_123')
    expect(fetchSpy).toHaveBeenCalledWith('/api/ledger-merge/merge-task', expect.objectContaining({
      method: 'POST',
      body: expect.any(FormData),
    }))
  })

  it('starts training extract tasks through the async endpoint', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, task_id: 'task_training' }), { status: 200 }),
    )
    const notice = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'notice.pdf', { type: 'application/pdf' })
    const signin = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'signin.jpg', { type: 'image/jpeg' })

    const result = await startTrainingExtractTask(notice, signin, 'legal', 'vision-test')

    expect(result.task_id).toBe('task_training')
    expect(fetchSpy).toHaveBeenCalledWith('/api/training/extract-task', expect.objectContaining({
      method: 'POST',
      body: expect.any(FormData),
    }))
  })

  it('starts ledger extract tasks through the async endpoint', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, task_id: 'task_ledger' }), { status: 200 }),
    )
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'case.pdf', { type: 'application/pdf' })

    const result = await startLedgerExtractTask([file], 'vision-test')

    expect(result.task_id).toBe('task_ledger')
    expect(fetchSpy).toHaveBeenCalledWith('/api/ledger/extract-task', expect.objectContaining({
      method: 'POST',
      body: expect.any(FormData),
    }))
  })

  it('starts compliance extract tasks through the async endpoint', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true, task_id: 'task_compliance' }), { status: 200 }),
    )
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'compliance.pdf', { type: 'application/pdf' })

    const result = await startComplianceExtractTask(file, 'vision-test')

    expect(result.task_id).toBe('task_compliance')
    expect(fetchSpy).toHaveBeenCalledWith('/api/compliance/extract-task', expect.objectContaining({
      method: 'POST',
      body: expect.any(FormData),
    }))
  })

  it('fetches background task status by id', async () => {
    const task = await getBackgroundTask('task_123')

    expect(task.status).toBe('succeeded')
    expect(fetchSpy).toHaveBeenCalledWith('/api/tasks/task_123', expect.objectContaining({
      credentials: 'include',
    }))
  })

  it('lists background tasks', async () => {
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ tasks: [{ task_id: 'task_1', status: 'queued' }] }), { status: 200 }),
    )

    const tasks = await listBackgroundTasks(25)

    expect(tasks).toHaveLength(1)
    expect(fetchSpy).toHaveBeenCalledWith('/api/tasks?limit=25', expect.objectContaining({
      credentials: 'include',
    }))
  })
})
