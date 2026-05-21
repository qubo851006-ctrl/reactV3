import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LedgerMergeFlow from '../src/components/LedgerMergeFlow'
import { NotificationContext } from '../src/components/NotificationContext'
import {
  downloadMergedExcel,
  getBackgroundTask,
  startLedgerMergeTask,
} from '../src/api'

vi.mock('../src/api', () => ({
  startLedgerMergeTask: vi.fn(),
  getBackgroundTask: vi.fn(),
  downloadMergedExcel: vi.fn(),
  getErrorMessage: (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback,
}))

const notifier = {
  notify: vi.fn(),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  sendTestNotification: vi.fn(),
}

function renderFlow(onComplete = vi.fn()) {
  render(
    <NotificationContext.Provider value={notifier}>
      <LedgerMergeFlow onComplete={onComplete} onCancel={vi.fn()} />
    </NotificationContext.Provider>,
  )
}

function xlsxFile(name = 'contract.xlsx') {
  return new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], name, {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

describe('LedgerMergeFlow background task path', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('submits files, polls the task, and renders merge stats', async () => {
    vi.mocked(startLedgerMergeTask).mockResolvedValue({ ok: true, task_id: 'task_123' })
    vi.mocked(getBackgroundTask).mockResolvedValue({
      task_id: 'task_123',
      type: 'ledger_merge',
      status: 'succeeded',
      progress: 100,
      message: '完成',
      result: {
        result_id: 'merge_123',
        total_contract: 3,
        matched_purchase: 2,
        matched_finance: 1,
        fully_matched: 1,
        partial_matched: 1,
        unmatched: 1,
      },
      error: null,
      created_by: 1,
      created_at: null,
      updated_at: null,
      started_at: null,
      finished_at: null,
    })

    renderFlow()

    const upload = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(upload, { target: { files: [xlsxFile()] } })
    fireEvent.click(screen.getByRole('button', { name: '开始合并' }))

    await waitFor(() => expect(startLedgerMergeTask).toHaveBeenCalledTimes(1))
    expect(startLedgerMergeTask).toHaveBeenCalledWith(expect.any(File), null, null)
    await waitFor(() => expect(screen.getByText('合并结果')).toBeInTheDocument())
    expect(screen.getByText('3 条')).toBeInTheDocument()
    expect(notifier.notifySuccess).toHaveBeenCalledWith('三台账合并完成', '合同系统 3 条，全部匹配 1 条。')
  })

  it('shows failed task errors without rendering stats', async () => {
    vi.mocked(startLedgerMergeTask).mockResolvedValue({ ok: true, task_id: 'task_failed' })
    vi.mocked(getBackgroundTask).mockResolvedValue({
      task_id: 'task_failed',
      type: 'ledger_merge',
      status: 'failed',
      progress: 80,
      message: '失败',
      result: null,
      error: 'Excel 列名缺失',
      created_by: 1,
      created_at: null,
      updated_at: null,
      started_at: null,
      finished_at: null,
    })

    renderFlow()

    const upload = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(upload, { target: { files: [xlsxFile()] } })
    fireEvent.click(screen.getByRole('button', { name: '开始合并' }))

    await waitFor(() => expect(screen.getByText('Excel 列名缺失')).toBeInTheDocument())
    expect(screen.queryByText('合并结果')).toBeNull()
    expect(notifier.notifyError).toHaveBeenCalledWith('三台账合并失败', 'Excel 列名缺失')
  })

  it('downloads the completed result id', async () => {
    const onComplete = vi.fn()
    vi.mocked(startLedgerMergeTask).mockResolvedValue({ ok: true, task_id: 'task_123' })
    vi.mocked(getBackgroundTask).mockResolvedValue({
      task_id: 'task_123',
      type: 'ledger_merge',
      status: 'succeeded',
      progress: 100,
      message: '完成',
      result: {
        result_id: 'merge_abc',
        total_contract: 1,
        matched_purchase: 0,
        matched_finance: 0,
        fully_matched: 0,
        partial_matched: 0,
        unmatched: 1,
      },
      error: null,
      created_by: 1,
      created_at: null,
      updated_at: null,
      started_at: null,
      finished_at: null,
    })

    renderFlow(onComplete)

    const upload = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(upload, { target: { files: [xlsxFile()] } })
    fireEvent.click(screen.getByRole('button', { name: '开始合并' }))
    await screen.findByText('下载合并台账 Excel')
    fireEvent.click(screen.getByText('下载合并台账 Excel'))

    expect(downloadMergedExcel).toHaveBeenCalledWith('merge_abc')
    expect(onComplete).toHaveBeenCalledWith(expect.stringContaining('三台账合并完成'))
  })
})
