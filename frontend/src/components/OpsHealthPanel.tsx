import { useEffect, useState } from 'react'

interface StatusCheck {
  ok: boolean
  backend: string
  error: string
}

interface OpsHealth {
  version: {
    app_version: string
    branch: string
    commit: string
    commit_full: string
    commit_time: string
  }
  runtime: {
    started_at: string
    server_time: string
  }
  databases: {
    main: StatusCheck
    llm_audit: StatusCheck
  }
  dingtalk: Record<string, boolean>
  recent_errors: Array<{
    file: string
    line: string
    modified_at: string
  }>
  recent_failed_tasks: Array<{
    task_id: string
    type: string
    message: string
    error: string | null
    created_by: number | null
    created_at: string | null
    started_at: string | null
    finished_at: string | null
    updated_at: string | null
  }>
}

interface Props {
  open: boolean
  onClose: () => void
}

export default function OpsHealthPanel({ open, onClose }: Props) {
  const [data, setData] = useState<OpsHealth | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const r = await fetch('/api/admin/ops/health', { credentials: 'include' })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error((d as { detail?: string }).detail ?? '运维状态加载失败')
      setData(d as OpsHealth)
    } catch (e) {
      setError(e instanceof Error ? e.message : '运维状态加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) void load()
  }, [open])

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={onClose} />}
      <div
        className={`
          fixed top-0 right-0 z-50 h-full w-[760px] max-w-full
          bg-slate-900 border-l border-slate-700/60 shadow-2xl flex flex-col
          transition-transform duration-300 ease-in-out
          ${open ? 'translate-x-0' : 'translate-x-full'}
        `}
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-slate-700/60">
          <div>
            <div className="text-sm font-semibold text-white">运维面板</div>
            <div className="text-xs text-slate-500 mt-0.5">系统健康、版本、依赖状态与近期故障摘要</div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => void load()}
              disabled={loading}
              className="text-xs text-indigo-300 hover:text-indigo-200 disabled:opacity-50"
            >
              {loading ? '刷新中' : '刷新'}
            </button>
            <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {error && (
            <div className="px-3 py-2 rounded-lg text-xs bg-red-500/10 border border-red-500/20 text-red-300">
              {error}
            </div>
          )}

          {!data ? (
            <div className="text-sm text-slate-500 py-10 text-center">{loading ? '正在加载运维状态' : '暂无数据'}</div>
          ) : (
            <>
              <section className="grid grid-cols-2 gap-3">
                <InfoCard label="当前版本" value={data.version.app_version} />
                <InfoCard label="当前分支" value={data.version.branch} />
                <InfoCard label="当前 Commit" value={data.version.commit} sub={formatTime(data.version.commit_time)} />
                <InfoCard label="后端启动时间" value={formatTime(data.runtime.started_at)} />
                <InfoCard label="服务器时间" value={formatTime(data.runtime.server_time)} />
              </section>

              <section>
                <SectionTitle title="依赖状态" />
                <div className="grid grid-cols-2 gap-3">
                  <StatusCard title="主业务库" check={data.databases.main} />
                  <StatusCard title="LLM 审计库" check={data.databases.llm_audit} />
                </div>
              </section>

              <section>
                <SectionTitle title="钉钉配置状态" />
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {Object.entries(data.dingtalk).map(([key, value]) => (
                    <FlagPill key={key} label={labelDingTalk(key)} enabled={value} />
                  ))}
                </div>
              </section>

              <section>
                <SectionTitle title="最近错误日志摘要" />
                <div className="rounded-xl border border-slate-700/60 overflow-hidden">
                  {data.recent_errors.length === 0 ? (
                    <Empty text="最近日志中未发现错误摘要" />
                  ) : data.recent_errors.map((item, idx) => (
                    <div key={`${item.file}-${idx}`} className="px-3 py-2 border-b last:border-b-0 border-slate-800 text-xs">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-amber-300">{item.file}</span>
                        <span className="text-slate-500 flex-shrink-0">{formatTime(item.modified_at)}</span>
                      </div>
                      <div className="text-slate-400 mt-1 break-words font-mono leading-5">{item.line}</div>
                    </div>
                  ))}
                </div>
              </section>

              <section>
                <SectionTitle title="最近 10 次任务失败" />
                <div className="rounded-xl border border-slate-700/60 overflow-hidden">
                  {data.recent_failed_tasks.length === 0 ? (
                    <Empty text="暂无失败任务" />
                  ) : data.recent_failed_tasks.map(task => (
                    <div key={task.task_id} className="px-3 py-2 border-b last:border-b-0 border-slate-800 text-xs">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-red-300">{task.type}</span>
                        <span className="text-slate-500">{formatTime(task.finished_at || task.updated_at)}</span>
                      </div>
                      <div className="text-slate-400 mt-1">{task.message || task.task_id}</div>
                      {task.error && <div className="text-slate-500 mt-1 break-words">{task.error}</div>}
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </>
  )
}

function SectionTitle({ title }: { title: string }) {
  return <div className="text-xs font-semibold text-slate-300 mb-3">{title}</div>
}

function InfoCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 px-4 py-3 min-w-0">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm text-white font-medium mt-1 truncate">{value || '未知'}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  )
}

function StatusCard({ title, check }: { title: string; check: StatusCheck }) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-white">{title}</span>
        <span className={check.ok ? 'text-xs text-emerald-300' : 'text-xs text-red-300'}>
          {check.ok ? '正常' : '异常'}
        </span>
      </div>
      <div className="text-xs text-slate-500 mt-1">{check.backend}</div>
      {check.error && <div className="text-xs text-red-300 mt-2 break-words">{check.error}</div>}
    </div>
  )
}

function FlagPill({ label, enabled }: { label: string; enabled: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-2 text-xs">
      <span className="text-slate-300 truncate">{label}</span>
      <span className={enabled ? 'text-emerald-300' : 'text-slate-500'}>{enabled ? '是' : '否'}</span>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="px-3 py-6 text-center text-xs text-slate-600">{text}</div>
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

function labelDingTalk(key: string) {
  const labels: Record<string, string> = {
    notify_enabled: '群通知启用',
    webhook_url_configured: 'Webhook URL',
    webhook_secret_configured: 'Webhook 加签',
    enterprise_enabled: '企业应用启用',
    work_notice_enabled: '工作通知启用',
    org_sync_enabled: '组织同步启用',
    sso_enabled: '免登启用',
    corp_id_configured: 'CorpId',
    app_key_configured: 'AppKey',
    app_secret_configured: 'AppSecret',
    agent_id_configured: 'AgentId',
  }
  return labels[key] ?? key
}
