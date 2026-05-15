import type { Stage, SkillKey, SessionMeta } from '../types'
import type { AuthUser } from './AuthGate'
import { APP_TITLE } from '../appMeta'
import { SKILLS } from '../skills/registry'

interface Props {
  stage: Stage
  useKb: boolean
  user: AuthUser
  sessions: SessionMeta[]
  currentSessionId: string
  creatingSession?: boolean
  onSkill: (skill: SkillKey) => void
  onClearLedger: () => void
  onClearChat: () => void
  onToggleKb: (v: boolean) => void
  onNewSession: () => void
  onSwitchSession: (id: string) => void
  onDeleteSession: (id: string) => void
}

function groupSessions(sessions: SessionMeta[]) {
  const now = new Date()
  const today: SessionMeta[] = []
  const yesterday: SessionMeta[] = []
  const older: SessionMeta[] = []

  for (const s of sessions) {
    const d = new Date(s.updated_at)
    const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000)
    if (diffDays < 1) today.push(s)
    else if (diffDays < 2) yesterday.push(s)
    else older.push(s)
  }
  return { today, yesterday, older }
}

function SessionItem({
  session,
  isCurrent,
  onSwitch,
  onDelete,
}: {
  session: SessionMeta
  isCurrent: boolean
  onSwitch: () => void
  onDelete: () => void
}) {
  function handleDeleteClick(e: React.MouseEvent) {
    e.stopPropagation()
    onDelete()
  }

  return (
    <div
      className={`
        relative flex items-center w-full rounded-lg px-2.5 py-2 mb-0.5 cursor-pointer text-left
        transition-colors group
        ${isCurrent
          ? 'bg-indigo-600/30 text-white'
          : 'text-slate-400 hover:bg-slate-700/40 hover:text-slate-200'}
      `}
      onClick={onSwitch}
    >
      <span
        className="flex-1 text-xs truncate leading-tight"
        title={session.title}
      >
        {session.title}
      </span>
      <button
        onClick={handleDeleteClick}
        className="ml-1 flex-shrink-0 p-0.5 rounded text-slate-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
        title="删除对话"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      </button>
    </div>
  )
}

export default function Sidebar({
  stage, useKb, user, sessions, currentSessionId, creatingSession = false,
  onSkill, onClearLedger, onClearChat, onToggleKb,
  onNewSession, onSwitchSession, onDeleteSession,
}: Props) {
  const busy = stage !== 'idle'
  const { today, yesterday, older } = groupSessions(sessions)

  return (
    <aside className="w-60 flex-shrink-0 flex flex-col bg-slate-900 border-r border-slate-700/50 h-screen">
      {/* Logo */}
      <div className="px-5 py-4 border-b border-slate-700/50">
        <div className="flex items-center gap-2">
          <span className="text-2xl">📋</span>
          <div>
            <div className="text-sm font-semibold text-white leading-tight">{APP_TITLE}</div>
            <div className="text-xs text-slate-400 mt-0.5">AI 驱动的智能管理工具</div>
          </div>
        </div>
      </div>

      {/* Session list */}
      <div className="px-3 pt-3 pb-2 border-b border-slate-700/50">
        <button
          onClick={onNewSession}
          disabled={creatingSession}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-slate-300 hover:text-white hover:bg-slate-700/50 transition-colors border border-slate-700/50 hover:border-slate-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {creatingSession ? (
            <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          )}
          {creatingSession ? '创建中…' : '新建对话'}
        </button>

        {sessions.length > 0 && (
          <div className="mt-2 max-h-48 overflow-y-auto">
            {today.length > 0 && (
              <>
                <div className="text-[10px] font-medium text-slate-600 uppercase tracking-wider px-1 mb-1 mt-1">今天</div>
                {today.map(s => (
                  <SessionItem
                    key={s.id}
                    session={s}
                    isCurrent={s.id === currentSessionId}
                    onSwitch={() => onSwitchSession(s.id)}
                    onDelete={() => onDeleteSession(s.id)}
                  />
                ))}
              </>
            )}
            {yesterday.length > 0 && (
              <>
                <div className="text-[10px] font-medium text-slate-600 uppercase tracking-wider px-1 mb-1 mt-2">昨天</div>
                {yesterday.map(s => (
                  <SessionItem
                    key={s.id}
                    session={s}
                    isCurrent={s.id === currentSessionId}
                    onSwitch={() => onSwitchSession(s.id)}
                    onDelete={() => onDeleteSession(s.id)}
                  />
                ))}
              </>
            )}
            {older.length > 0 && (
              <>
                <div className="text-[10px] font-medium text-slate-600 uppercase tracking-wider px-1 mb-1 mt-2">较早</div>
                {older.map(s => (
                  <SessionItem
                    key={s.id}
                    session={s}
                    isCurrent={s.id === currentSessionId}
                    onSwitch={() => onSwitchSession(s.id)}
                    onDelete={() => onDeleteSession(s.id)}
                  />
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Skills */}
      <div className="px-3 pt-3 flex-1 overflow-y-auto">
        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider px-2 mb-2">快捷技能</div>
        {SKILLS.map(s => (
          <button
            key={s.key}
            onClick={() => onSkill(s.key)}
            disabled={busy}
            className={`
              w-full text-left px-3 py-3 rounded-xl mb-1.5 transition-all duration-150
              ${busy
                ? 'opacity-40 cursor-not-allowed'
                : 'hover:bg-slate-700/60 active:bg-slate-700 cursor-pointer'}
              group
            `}
          >
            <div className="flex items-center gap-2.5">
              <span className={`w-8 h-8 flex-shrink-0 flex items-center justify-center rounded-lg text-base ${s.iconBg} ${s.iconText}`}>
                {s.icon}
              </span>
              <div>
                <div className="text-sm font-medium text-slate-200 group-hover:text-white transition-colors">{s.label}</div>
                <div className="text-xs text-slate-500 mt-0.5 leading-tight">{s.sidebarDesc}</div>
              </div>
            </div>
          </button>
        ))}

        {/* Divider */}
        <div className="border-t border-slate-700/50 my-3" />

        <div className="text-xs font-medium text-slate-500 uppercase tracking-wider px-2 mb-2">管理操作</div>
        {user.role === 'admin' && (
          <button
            onClick={onClearLedger}
            disabled={busy}
            className="w-full text-left px-3 py-2.5 rounded-lg mb-1 text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-700/40 transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <span>🗂️</span> 清空台账
          </button>
        )}
        <button
          onClick={onClearChat}
          disabled={busy}
          className="w-full text-left px-3 py-2.5 rounded-lg mb-1 text-sm text-slate-400 hover:text-slate-200 hover:bg-slate-700/40 transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <span>🗑️</span> 清空对话
        </button>
      </div>

      {/* Knowledge base toggles */}
      <div className="px-4 py-3 border-t border-slate-700/50 space-y-3">
        {/* 企业知识库 */}
        <label className="flex items-center gap-3 cursor-pointer">
          <div className="relative flex-shrink-0">
            <input
              type="checkbox"
              className="sr-only peer"
              checked={useKb}
              onChange={e => onToggleKb(e.target.checked)}
            />
            <div className="w-9 h-5 bg-slate-600 rounded-full peer-checked:bg-indigo-500 transition-colors" />
            <div className="absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform peer-checked:translate-x-4" />
          </div>
          <div>
            <div className="text-xs font-medium text-slate-300">📚 企业知识库</div>
            <div className="text-xs text-slate-500 mt-0.5">{useKb ? '已启用' : '智弈智枢检索'}</div>
          </div>
        </label>


      </div>
    </aside>
  )
}
