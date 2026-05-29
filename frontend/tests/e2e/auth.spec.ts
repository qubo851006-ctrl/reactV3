import { expect, test } from '@playwright/test'

import { mockBootstrap, mockUnauthenticated } from './helpers'

// 登录态路由冒烟:验证 AuthGate 根据 /api/auth/me 正确分流到登录页 / 主界面。
// 这一层独立于业务 UI 细节,是所有页面的前提,稳定且增量价值高。

test('未登录时落到登录页,不进主界面', async ({ page }) => {
  await mockUnauthenticated(page)
  await page.goto('/')

  // 登录页第一步:姓名/部门搜索框(用正则避开省略号字符差异)
  await expect(page.getByPlaceholder(/搜索姓名或部门/)).toBeVisible()
  // 主界面独有的"新建对话"不应出现
  await expect(page.getByRole('button', { name: '新建对话' })).toHaveCount(0)
})

test('已登录时直接进入主界面', async ({ page }) => {
  await mockBootstrap(page)
  await page.goto('/')

  await expect(page.getByRole('button', { name: '新建对话' })).toBeVisible()
  // 不应停留在登录页
  await expect(page.getByPlaceholder(/搜索姓名或部门/)).toHaveCount(0)
})
