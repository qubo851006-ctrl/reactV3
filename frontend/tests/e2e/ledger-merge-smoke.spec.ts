import { expect, test } from '@playwright/test'

test('login session can open ledger merge flow and show task result', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user: { id: 1, name: '管理员', department: '法务部', role: 'admin' },
    }),
  }))
  await page.route('**/api/chat/sessions', async route => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: 's1', title: '新会话' }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ sessions: [] }),
    })
  })
  await page.route('**/api/model-routes', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      default_chat_model: 'qwen2.5-72b',
      default_vision_model: 'qwen2.5-vl-72b',
      chat_models: ['qwen2.5-72b'],
      vision_models: ['qwen2.5-vl-72b'],
    }),
  }))
  await page.route('**/api/chat', route => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: [
      'data: {"type":"done","reply":"请上传三台账文件","next_stage":"waiting_ledger_merge_files","kb_conversation_id":""}',
      '',
      '',
    ].join('\n'),
  }))
  await page.route('**/api/ledger-merge/merge-task', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true, task_id: 'task_e2e' }),
  }))
  await page.route('**/api/tasks/task_e2e', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      task_id: 'task_e2e',
      type: 'ledger_merge',
      status: 'succeeded',
      progress: 100,
      message: '完成',
      result: {
        result_id: 'merge_e2e',
        total_contract: 1,
        matched_purchase: 0,
        matched_finance: 0,
        fully_matched: 0,
        partial_matched: 0,
        unmatched: 1,
      },
      error: null,
    }),
  }))

  await page.goto('/')
  await expect(page.getByText('法度云图')).toBeVisible()

  await page.getByRole('textbox').fill('三台账合并')
  await page.getByRole('button').last().click()
  await expect(page.getByText('三台账合并').last()).toBeVisible()

  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'contract.xlsx',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from([0x50, 0x4b, 0x03, 0x04]),
  })
  await page.getByRole('button', { name: '开始合并' }).click()

  await expect(page.getByText('合并结果')).toBeVisible()
  await expect(page.getByText('1 条').first()).toBeVisible()
})
