import { expect, test } from '@playwright/test'

import { mockBootstrap } from './helpers'

// 三台账合并导航冒烟:确认从快捷技能按钮能进入合并上传流程。
//
// 定位:mock 模式 E2E 验证"关键路径不崩 + flow 切换正确",不验证合并
// 业务计算(那部分由后端单测覆盖,且 mock 下断言完整结果既脆弱又无意义)。
// 入口用稳定的 role+name selector(快捷技能按钮),不再用 getByRole('button').last()。
test('三台账合并:从快捷技能进入合并上传流程', async ({ page }) => {
  await mockBootstrap(page)

  await page.goto('/')
  // "新建对话"是主界面独有,登录页没有 —— 用它确认已进入主界面
  await expect(page.getByRole('button', { name: '新建对话' })).toBeVisible()

  // 稳定入口:点快捷技能按钮(name 含"三台账合并"),前端进入 waiting_ledger_merge_files 阶段
  await page.getByRole('button', { name: /三台账合并/ }).first().click()

  // 进入合并上传流程:"开始合并"按钮是该流程独有,确认 flow 切换成功
  await expect(page.getByRole('button', { name: '开始合并' })).toBeVisible()
})
