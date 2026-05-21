import { useEffect, useRef, useState } from 'react'
import type { AuthUser } from './AuthGate'
import { useNotifier } from './NotificationContext'

interface Props {
  user: AuthUser
  onLogout: () => void
  onOpenAdmin: () => void
  onOpenLlmDashboard?: () => void
  onOpenDingTalkAdmin?: () => void
  onOpenOpsHealth?: () => void
}

export default function UserMenu({ user, onLogout, onOpenAdmin }: Props) {
  const { sendTestNotification } = useNotifier()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const roleLabel = user.role === 'admin' ? '管理员' : '普通用户'

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-2 rounded-lg px-3 py-1.5 transition-colors hover:bg-slate-700/50"
      >
        <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-indigo-600 text-xs font-semibold text-white">
          {user.name[0]}
        </div>
        <div className="text-left">
          <div className="text-xs font-medium leading-tight text-white">{user.name}</div>
          <div className="text-[10px] leading-tight text-slate-500">{roleLabel}</div>
        </div>
        <svg className="ml-0.5 h-3 w-3 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-52 overflow-hidden rounded-xl border border-slate-700/60 bg-slate-800 shadow-2xl">
          <div className="border-b border-slate-700/50 px-3 py-2.5">
            <div className="text-sm font-medium text-white">{user.name}</div>
            <div className="mt-0.5 text-xs text-slate-400">
              {user.department} / {roleLabel}
            </div>
          </div>

          {user.role === 'admin' && (
            <button
              onClick={() => {
                onOpenAdmin()
                setOpen(false)
              }}
              className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm text-slate-300 transition-colors hover:bg-slate-700/50"
            >
              <span className="text-base">Admin</span>
              <span>管理员中心</span>
            </button>
          )}

          <button
            onClick={() => {
              void sendTestNotification()
              setOpen(false)
            }}
            className="flex w-full items-center gap-2.5 border-t border-slate-700/50 px-3 py-2.5 text-left text-sm text-slate-300 transition-colors hover:bg-slate-700/50"
            title="测试 Windows 系统通知是否可用"
          >
            <span className="text-base">Test</span>
            <span>测试系统通知</span>
          </button>

          <button
            onClick={() => {
              onLogout()
              setOpen(false)
            }}
            className="flex w-full items-center gap-2.5 border-t border-slate-700/50 px-3 py-2.5 text-left text-sm text-red-400 transition-colors hover:bg-red-500/10"
          >
            <span className="text-base">Exit</span>
            <span>退出当前设备</span>
          </button>
        </div>
      )}
    </div>
  )
}
