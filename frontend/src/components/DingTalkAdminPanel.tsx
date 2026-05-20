import { useEffect, useState } from 'react'

interface Notice {
  type: 'ok' | 'err'
  text: string
}

interface NotificationLog {
  id: number
  task: string
  level: string
  stage: string | null
  title: string
  summary: string
  user_name: string | null
  at_user_id: string | null
  sent: boolean
  skipped_reason: string | null
  http_status: number | null
  provider_code: string | null
  provider_message: string | null
  error: string | null
  created_at: string
}

interface SyncLog {
  id: number
  status: string
  root_dept_id: string | null
  department_count: number
  remote_user_count: number
  matched_count: number
  created_count: number
  updated_count: number
  skipped_count: number
  error: string | null
  started_at: string
  finished_at: string | null
}

interface Props {
  open: boolean
  onClose: () => void
}

export default function DingTalkAdminPanel({ open, onClose }: Props) {
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busy, setBusy] = useState('')
  const [notificationLogs, setNotificationLogs] = useState<NotificationLog[]>([])
  const [syncLogs, setSyncLogs] = useState<SyncLog[]>([])

  const showNotice = (type: 'ok' | 'err', text: string) => setNotice({ type, text })

  async function requestJson(url: string, init: RequestInit = {}) {
    const r = await fetch(url, { ...init, credentials: 'include' })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error((d as { detail?: string }).detail ?? '请求失败')
    return d
  }

  async function runAction(name: string, action: () => Promise<string>) {
    setBusy(name)
    setNotice(null)
    try {
      const message = await action()
      showNotice('ok', message)
      await loadLogs()
    } catch (e) {
      showNotice('err', e instanceof Error ? e.message : '操作失败')
    } finally {
      setBusy('')
    }
  }

  async function loadLogs() {
    const [notifyData, syncData] = await Promise.all([
      requestJson('/api/admin/dingtalk/notification-logs'),
      requestJson('/api/admin/dingtalk/sync-logs'),
    ])
    setNotificationLogs(notifyData.logs ?? [])
    setSyncLogs(syncData.logs ?? [])
  }

  useEffect(() => {
    if (open) void loadLogs().catch(() => {})
  }, [open])

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={onClose} />}
      <div
        className={`
          fixed top-0 right-0 z-50 h-full w-[720px] max-w-full
          bg-slate-900 border-l border-slate-700/60 shadow-2xl flex flex-col
          transition-transform duration-300 ease-in-out
          ${open ? 'translate-x-0' : 'translate-x-full'}
        `}
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-slate-700/60">
          <div>
            <div className="text-sm font-semibold text-white">钉钉管理</div>
            <div className="text-xs text-slate-500 mt-0.5">企业应用、通知测试、通讯录同步与日志</div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </header>

        {notice && (
          <div
            className={`mx-5 mt-4 px-3 py-2 rounded-lg text-xs ${
              notice.type === 'ok'
                ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300'
                : 'bg-red-500/10 border border-red-500/20 text-red-300'
            }`}
          >
            <span>{notice.text}</span>
            <button onClick={() => setNotice(null)} className="float-right text-slate-500 hover:text-slate-300 font-bold">
              ×
            </button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          <section>
            <div className="text-xs font-semibold text-slate-300 mb-3">连通性测试</div>
            <div className="grid grid-cols-2 gap-3">
              <ActionButton
                title="测试群通知"
                desc="发送一条 Webhook 群机器人消息"
                busy={busy === 'group'}
                onClick={() => runAction('group', async () => {
                  const d = await requestJson('/api/admin/dingtalk/test-notification', { method: 'POST' })
                  if (!d.ok) throw new Error('群通知发送失败，请检查 Webhook 配置')
                  return '群通知测试已发送'
                })}
              />
              <ActionButton
                title="测试企业凭证"
                desc="验证 AppKey、AppSecret 与 access_token"
                busy={busy === 'token'}
                onClick={() => runAction('token', async () => {
                  const d = await requestJson('/api/admin/dingtalk/test-enterprise-token', { method: 'POST' })
                  return `企业应用凭证有效，token 长度 ${d.token_length}`
                })}
              />
              <ActionButton
                title="测试个人工作通知"
                desc="给当前管理员发送企业应用通知"
                busy={busy === 'work'}
                onClick={() => runAction('work', async () => {
                  const d = await requestJson('/api/admin/dingtalk/test-work-notice', { method: 'POST' })
                  if (!d.ok) throw new Error('个人工作通知发送失败，请检查 AgentId 和 userId')
                  return '个人工作通知测试已发送'
                })}
              />
              <ActionButton
                title="同步通讯录"
                desc="只绑定已有 V3 用户，不自动创建账号"
                busy={busy === 'sync'}
                onClick={() => runAction('sync', async () => {
                  const d = await requestJson('/api/admin/dingtalk/sync-users', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ root_dept_id: 1, create_missing_users: false }),
                  })
                  if (d.status !== 'ok') throw new Error(d.error || '通讯录同步失败')
                  return `同步完成：远端 ${d.remote_user_count} 人，匹配 ${d.matched_count} 人，更新 ${d.updated_count} 人，跳过 ${d.skipped_count} 人`
                })}
              />
            </div>
          </section>

          <section>
            <div className="flex items-center justify-between mb-3">
              <div className="text-xs font-semibold text-slate-300">最近同步日志</div>
              <button onClick={() => void loadLogs()} className="text-xs text-indigo-300 hover:text-indigo-200">刷新</button>
            </div>
            <div className="rounded-xl border border-slate-700/60 overflow-hidden">
              {syncLogs.length === 0 ? (
                <Empty text="暂无同步日志" />
              ) : syncLogs.slice(0, 5).map(log => (
                <div key={log.id} className="px-3 py-2 border-b last:border-b-0 border-slate-800 text-xs">
                  <div className="flex items-center justify-between gap-3">
                    <span className={log.status === 'ok' ? 'text-emerald-300' : 'text-red-300'}>{log.status}</span>
                    <span className="text-slate-500">{formatTime(log.started_at)}</span>
                  </div>
                  <div className="text-slate-400 mt-1">
                    部门 {log.department_count} · 远端 {log.remote_user_count} · 匹配 {log.matched_count} · 更新 {log.updated_count} · 跳过 {log.skipped_count}
                  </div>
                  {log.error && <div className="text-red-300 mt-1 break-words">{log.error}</div>}
                </div>
              ))}
            </div>
          </section>

          <section>
            <div className="text-xs font-semibold text-slate-300 mb-3">最近通知日志</div>
            <div className="rounded-xl border border-slate-700/60 overflow-hidden">
              {notificationLogs.length === 0 ? (
                <Empty text="暂无通知日志" />
              ) : notificationLogs.slice(0, 12).map(log => (
                <div key={log.id} className="px-3 py-2 border-b last:border-b-0 border-slate-800 text-xs">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <span className={log.sent ? 'text-emerald-300' : 'text-amber-300'}>{log.sent ? '已发送' : '未发送'}</span>
                      <span className="text-slate-400 ml-2">{log.task}</span>
                      {log.stage && <span className="text-slate-500 ml-2">{log.stage}</span>}
                    </div>
                    <span className="text-slate-500 flex-shrink-0">{formatTime(log.created_at)}</span>
                  </div>
                  <div className="text-slate-500 mt-1 truncate">{log.summary}</div>
                  {(log.skipped_reason || log.provider_message || log.error) && (
                    <div className="text-slate-500 mt-1 truncate">
                      {log.skipped_reason || log.provider_message || log.error}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </>
  )
}

function ActionButton({ title, desc, busy, onClick }: {
  title: string
  desc: string
  busy: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="text-left rounded-xl border border-slate-700/60 bg-slate-800/50 px-4 py-3 hover:border-indigo-500/50 hover:bg-slate-800 disabled:opacity-60 disabled:cursor-wait transition-colors"
    >
      <div className="text-sm font-medium text-white">{busy ? '处理中…' : title}</div>
      <div className="text-xs text-slate-500 mt-1 leading-5">{desc}</div>
    </button>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="px-3 py-6 text-center text-xs text-slate-600">{text}</div>
}

function formatTime(value: string | null) {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
