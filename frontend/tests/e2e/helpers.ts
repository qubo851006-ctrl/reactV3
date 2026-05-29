import type { Page } from '@playwright/test'

/**
 * 公共 mock:让前端启动后处于"已登录管理员"状态。
 *
 * 这几个端点是任何页面加载时都会打的(鉴权 + 会话列表 + 模型路由),
 * 每个 E2E 都需要,所以集中在这里,避免每个 spec 重复粘贴。
 *
 * 注意:这是 mock 模式 E2E —— 只验证前端在给定后端响应下的渲染与交互,
 * 不连真实后端。真实链路集成测试是另一个量级的投入(见 docs/CI.md)。
 */
export async function mockBootstrap(page: Page): Promise<void> {
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
}

/**
 * 模拟"未登录"状态:/api/auth/me 返回 401。
 * 用于验证前端在未鉴权时落到登录页。
 */
export async function mockUnauthenticated(page: Page): Promise<void> {
  await page.route('**/api/auth/me', route => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: '未登录' }),
  }))
}
