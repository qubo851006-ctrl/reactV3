# 钉钉通知配置

阶段 1 接入钉钉自定义群机器人，用于 V3 长任务完成或失败后的旁路提醒。阶段 2 增加钉钉企业应用工作通知和组织人员同步。所有能力默认关闭；未配置时，V3 行为与当前版本一致。

## 配置步骤

1. 在钉钉群中添加“自定义机器人”。
2. 安全设置建议选择“加签”，复制 Webhook 地址和加签密钥。
3. 在后端 `.env` 中配置：

```env
DINGTALK_NOTIFY_ENABLED=true
DINGTALK_NOTIFY_ON_SUCCESS=true
DINGTALK_NOTIFY_ON_FAILURE=true
DINGTALK_NOTIFY_ON_WARNING=true
DINGTALK_NOTIFY_MENTION_USER=true
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=...
DINGTALK_WEBHOOK_SECRET=SEC...
DINGTALK_NOTIFY_BASE_URL=https://192.168.9.226:8443
DINGTALK_NOTIFY_TIMEOUT_SECONDS=2
```

## 企业应用配置

企业应用用于给指定钉钉用户发送工作通知，并从钉钉通讯录同步人员绑定信息。

```env
DINGTALK_ENTERPRISE_ENABLED=true
DINGTALK_WORK_NOTICE_ENABLED=true
DINGTALK_ORG_SYNC_ENABLED=true
DINGTALK_APP_KEY=
DINGTALK_APP_SECRET=
DINGTALK_AGENT_ID=
DINGTALK_ORG_SYNC_ROOT_DEPT_ID=1
DINGTALK_ORG_SYNC_CREATE_USERS=false
DINGTALK_SSO_ENABLED=false
```

钉钉开放平台侧需要给企业内部应用开通对应权限：

- 获取企业内部应用 access_token
- 发送企业会话消息或工作通知
- 读取通讯录部门
- 读取通讯录成员基础信息

`DINGTALK_ORG_SYNC_CREATE_USERS=false` 是推荐默认值：同步只绑定或更新已有 V3 用户，不会自动把钉钉通讯录所有人创建成 V3 登录账号。

## 当前触发范围

- 合规审查信息识别成功或失败
- 授权请示识别成功或失败
- 三台账合并成功或失败
- 培训信息识别成功或失败
- 案件台账信息识别成功或失败
- 审计问题分析成功或失败

## 通知分级与日志

- 成功、失败、需要人工确认分别使用 `success`、`error`、`warning` 级别。
- 失败消息会尽量带上阶段，例如 OCR 识别、AI 字段提取、台账匹配、文件暂存、合并生成。
- 每次通知都会尝试写入 `notification_logs`，记录任务、级别、阶段、用户、是否发送成功、跳过原因、HTTP 状态和钉钉返回码。
- 管理员可通过 `GET /api/admin/dingtalk/notification-logs` 查看最近 200 条通知日志。
- 通知日志写入失败也不会影响业务接口。

## 管理员入口

- 右上角用户菜单中，管理员可点击“测试钉钉通知”发送一条测试消息。
- 用户管理面板中预留“钉钉 userId”字段，供后续企业应用定向通知和免登绑定使用。
- 管理员可调用 `POST /api/admin/dingtalk/test-enterprise-token` 测试企业应用凭证。
- 管理员可调用 `POST /api/admin/dingtalk/test-work-notice` 测试企业应用工作通知。
- 管理员可调用 `POST /api/admin/dingtalk/sync-users` 同步通讯录人员绑定信息。
- 管理员可调用 `GET /api/admin/dingtalk/sync-logs` 查看最近 50 次同步日志。

## 群内 @ 指定人

- 若 V3 用户配置了“钉钉 userId”，群机器人消息会带 `atUserIds` 并在消息末尾 @ 该用户。
- 未配置“钉钉 userId”时，只发送普通群通知。
- 若 `DINGTALK_NOTIFY_MENTION_USER=false`，即使用户配置了“钉钉 userId”也不会 @。
- 这仍是群消息提醒，不是企业应用私聊消息。

## 企业应用私聊

- 若 `DINGTALK_ENTERPRISE_ENABLED=true` 且 `DINGTALK_WORK_NOTICE_ENABLED=true`，并且当前 V3 用户绑定了“钉钉 userId”，通知层会发送企业应用工作通知。
- 群机器人 Webhook 保持可用，可作为并行通知或兜底通知。
- 企业应用工作通知仍只发送任务类型、发起人、状态、阶段、摘要、时间和 V3 链接，不发送正文或文件内容。

## 钉钉免登

- 若 `DINGTALK_ENTERPRISE_ENABLED=true` 且 `DINGTALK_SSO_ENABLED=true`，V3 登录页会在钉钉容器内尝试自动免登。
- 前端通过钉钉 JSAPI 获取 `authCode`，后端调用 `/topapi/v2/user/getuserinfo` 换取 `userid/unionid/name`。
- 后端复用 V3 现有 `sid` Cookie 会话，不新增第二套登录态。
- 匹配顺序为：`dingtalk_user_id`、`dingtalk_union_id`、唯一姓名匹配。
- 未匹配到 V3 已启用用户时，不自动创建账号，返回“请联系管理员开通”。
- 非钉钉环境或免登失败时，登录页会回落到原短码登录。

## 稳定性约束

- 钉钉通知失败不会影响业务接口。
- 通知请求使用短超时，默认 2 秒。
- 群消息只包含任务类型、发起人、状态、摘要、时间和 V3 链接。
- 不发送 PDF 原文、案件全文、审计完整内容或文件正文。
