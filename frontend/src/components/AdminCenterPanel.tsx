import { useEffect, useState } from 'react'
import { listBackgroundTasks, listAuditLogs, type BackgroundTask, type AuditLogEntry } from '../api'
import OpsHealthPanel from './OpsHealthPanel'

type TabKey = 'overview' | 'tasks' | 'audit' | 'users' | 'dingtalk' | 'ai'

interface Props {
  open: boolean
  onClose: () => void
  onOpenUsers: () => void
  onOpenDingTalk: () => void
  onOpenAiQuality: () => void
}

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'overview', label: '系统健康' },
  { key: 'tasks', label: '后台任务' },
  { key: 'audit', label: '操作审计' },
  { key: 'users', label: '用户' },
  { key: 'dingtalk', label: '钉钉' },
  { key: 'ai', label: 'AI 质量' },
]

export default function AdminCenterPanel({ open, onClose, onOpenUsers, onOpenDingTalk, onOpenAiQuality }: Props) {
  const [tab, setTab] = useState<TabKey>('overview')

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={onClose} />}
      <div
        className={`
          fixed top-0 right-0 z-50 flex h-full w-[840px] max-w-full flex-col
          border-l border-slate-700/60 bg-slate-900 shadow-2xl
          transition-transform duration-300 ease-in-out
          ${open ? 'translate-x-0' : 'translate-x-full'}
        `}
      >
        <header className="flex items-center justify-between border-b border-slate-700/60 px-5 py-4">
          <div>
            <div className="text-sm font-semibold text-white">管理员中心</div>
            <div className="mt-0.5 text-xs text-slate-500">用户、钉钉、AI 质量、后台任务与系统健康统一入口</div>
          </div>
          <button onClick={onClose} className="text-slate-500 transition-colors hover:text-slate-300">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </header>

        <div className="flex min-h-0 flex-1">
          <nav className="w-40 flex-shrink-0 space-y-1 border-r border-slate-700/60 p-3">
            {TABS.map(item => (
              <button
                key={item.key}
                onClick={() => setTab(item.key)}
                className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  tab === item.key
                    ? 'border border-indigo-500/30 bg-indigo-500/15 text-indigo-200'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                {item.label}
              </button>
            ))}
          </nav>

          <main className="min-w-0 flex-1 overflow-y-auto">
            {tab === 'overview' && <EmbeddedOpsHealth />}
            {tab === 'tasks' && <TaskListPanel />}
            {tab === 'audit' && <AuditLogPanel />}
            {tab === 'users' && (
              <LaunchPanel
                title="用户管理"
                desc="管理账号、角色、状态、钉钉 userId、重置短码和强制下线。"
                button="打开用户管理"
                onOpen={onOpenUsers}
              />
            )}
            {tab === 'dingtalk' && (
              <LaunchPanel
                title="钉钉管理"
                desc="测试群通知、企业应用凭证、个人工作通知、通讯录同步和通知日志。"
                button="打开钉钉管理"
                onOpen={onOpenDingTalk}
              />
            )}
            {tab === 'ai' && (
              <LaunchPanel
                title="AI 质量仪表盘"
                desc="查看各场景调用量、接受率、修改率、错误率、token 和耗时，并钻取单条 trace。"
                button="打开 AI 质量仪表盘"
                onOpen={onOpenAiQuality}
              />
            )}
          </main>
        </div>
      </div>
    </>
  )
}

function EmbeddedOpsHealth() {
  return (
    <div className="relative h-full">
      <OpsHealthPanel open onClose={() => {}} embedded />
    </div>
  )
}

function LaunchPanel({ title, desc, button, onOpen }: {
  title: string
  desc: string
  button: string
  onOpen: () => void
}) {
  return (
    <div className="max-w-2xl p-6">
      <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
        <div className="text-base font-semibold text-white">{title}</div>
        <div className="mt-2 text-sm leading-6 text-slate-400">{desc}</div>
        <button
          onClick={onOpen}
          className="mt-5 rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white transition-colors hover:bg-indigo-500"
        >
          {button}
        </button>
      </div>
    </div>
  )
}

function TaskListPanel() {
  const [tasks, setTasks] = useState<BackgroundTask[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      setTasks(await listBackgroundTasks(100))
    } catch (e) {
      setError(e instanceof Error ? e.message : '后台任务加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <div className="space-y-4 p-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-white">后台任务</div>
          <div className="mt-1 text-xs text-slate-500">最近 100 条任务，后续培训、案件、审计等长任务会统一进入这里。</div>
        </div>
        <button onClick={() => void load()} disabled={loading} className="text-xs text-indigo-300 hover:text-indigo-200 disabled:opacity-50">
          {loading ? '刷新中' : '刷新'}
        </button>
      </div>

      {error && <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}

      <div className="overflow-hidden rounded-xl border border-slate-700/60">
        {tasks.length === 0 ? (
          <div className="px-3 py-10 text-center text-xs text-slate-600">{loading ? '正在加载后台任务' : '暂无后台任务'}</div>
        ) : tasks.map(task => (
          <div key={task.task_id} className="border-b border-slate-800 px-3 py-3 text-xs last:border-b-0">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <span className="font-medium text-slate-200">{task.type}</span>
                <span className="ml-2 text-slate-500">{task.task_id}</span>
              </div>
              <StatusBadge status={task.status} />
            </div>
            <div className="mt-2 flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-700">
                <div className="h-full bg-indigo-500" style={{ width: `${Math.max(0, Math.min(100, task.progress || 0))}%` }} />
              </div>
              <span className="w-10 text-right text-slate-500">{task.progress}%</span>
            </div>
            <div className="mt-2 text-slate-400">{task.message || '-'}</div>
            {task.error && <div className="mt-1 break-words text-red-300">{task.error}</div>}
            <div className="mt-1 text-slate-600">{formatTime(task.finished_at || task.updated_at || task.created_at)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function AuditLogPanel() {
  const [logs, setLogs] = useState<AuditLogEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [actionFilter, setActionFilter] = useState('')

  async function load(action = actionFilter) {
    setLoading(true)
    setError('')
    try {
      setLogs(await listAuditLogs(action.trim(), 200))
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作审计加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="space-y-4 p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white">操作审计</div>
          <div className="mt-1 text-xs text-slate-500">谁在何时对什么做了什么。最近 200 条，登录、台账写入、培训归档、授权请示等关键操作均留痕。</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <input
            value={actionFilter}
            onChange={e => setActionFilter(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') void load() }}
            placeholder="按操作类型筛选"
            className="w-32 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none"
          />
          <button onClick={() => void load()} disabled={loading} className="text-xs text-indigo-300 hover:text-indigo-200 disabled:opacity-50">
            {loading ? '查询中' : '查询'}
          </button>
        </div>
      </div>

      {error && <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}

      <div className="overflow-hidden rounded-xl border border-slate-700/60">
        {logs.length === 0 ? (
          <div className="px-3 py-10 text-center text-xs text-slate-600">{loading ? '正在加载操作审计' : '暂无操作记录'}</div>
        ) : logs.map(log => (
          <div key={log.id} className="border-b border-slate-800 px-3 py-3 text-xs last:border-b-0">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <span className="font-medium text-slate-200">{log.user_name || (log.user_id != null ? `用户#${log.user_id}` : '系统')}</span>
                <span className="ml-2 rounded-full border border-slate-600/40 bg-slate-700/30 px-2 py-0.5 text-slate-300">{log.action}</span>
              </div>
              <span className="shrink-0 text-slate-600">{formatTime(log.created_at)}</span>
            </div>
            <div className="mt-2 break-words text-slate-400">{log.summary || '-'}</div>
            {(log.target_type || log.target_id) && (
              <div className="mt-1 text-slate-600">
                对象：{log.target_type || '-'}{log.target_id ? ` / ${log.target_id}` : ''}
              </div>
            )}
            {log.ip_address && <div className="mt-1 text-slate-600">IP：{log.ip_address}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === 'succeeded'
    ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'
    : status === 'failed'
      ? 'border-red-500/20 bg-red-500/10 text-red-300'
      : status === 'running'
        ? 'border-indigo-500/20 bg-indigo-500/10 text-indigo-300'
        : 'border-slate-500/20 bg-slate-500/10 text-slate-400'
  return <span className={`rounded-full border px-2 py-0.5 ${cls}`}>{status}</span>
}

function formatTime(value: string | null) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
