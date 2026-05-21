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

export default function UserMenu({ user, onLogout, onOpenAdmin, onOpenLlmDashboard, onOpenDingTalkAdmin, onOpenOpsHealth }: Props) {
  const { notifyError, notifySuccess, sendTestNotification } = useNotifier()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  async function sendDingtalkTestNotification() {
    try {
      const r = await fetch('/api/admin/dingtalk/test-notification', {
        method: 'POST',
        credentials: 'include',
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok || !d.ok) {
        notifyError('钉钉通知测试失败', '请检查 Webhook、加签密钥和后端日志')
        return
      }
      notifySuccess('钉钉通知测试已发送', '请查看钉钉群是否收到测试消息')
    } catch {
      notifyError('钉钉通知测试失败', '无法连接后端服务')
    }
  }

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-slate-700/50 transition-colors"
      >
        <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center text-xs font-semibold text-white flex-shrink-0">
          {user.name[0]}
        </div>
        <div className="text-left">
          <div className="text-xs font-medium text-white leading-tight">{user.name}</div>
          <div className="text-[10px] text-slate-500 leading-tight">
            {user.role === 'admin' ? '管理员' : '普通用户'}
          </div>
        </div>
        <svg className="w-3 h-3 text-slate-500 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-52 bg-slate-800 border border-slate-700/60 rounded-xl shadow-2xl z-50 overflow-hidden">
          {/* 用户信息头 */}
          <div className="px-3 py-2.5 border-b border-slate-700/50">
            <div className="text-sm font-medium text-white">{user.name}</div>
            <div className="text-xs text-slate-400 mt-0.5">
              {user.department} · {user.role === 'admin' ? '管理员' : '普通用户'}
            </div>
          </div>

          {/* 管理员专属菜单 */}
          {user.role === 'admin' && (
            <>
              <button
                onClick={() => { onOpenAdmin(); setOpen(false) }}
                className="w-full text-left px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors flex items-center gap-2.5"
              >
                <span className="text-base">👥</span>
                <span>用户管理</span>
              </button>
              {onOpenLlmDashboard && (
                <button
                  onClick={() => { onOpenLlmDashboard(); setOpen(false) }}
                  className="w-full text-left px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors flex items-center gap-2.5"
                >
                  <span className="text-base">📊</span>
                  <span>AI 质量仪表盘</span>
                </button>
              )}
              {onOpenDingTalkAdmin ? (
                <button
                  onClick={() => { onOpenDingTalkAdmin(); setOpen(false) }}
                  className="w-full text-left px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors flex items-center gap-2.5"
                >
                  <span className="text-base">钉</span>
                  <span>钉钉管理</span>
                </button>
              ) : (
                <button
                  onClick={() => { void sendDingtalkTestNotification(); setOpen(false) }}
                  className="w-full text-left px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors flex items-center gap-2.5"
                >
                  <span className="text-base">钉</span>
                  <span>测试钉钉通知</span>
                </button>
              )}
              {onOpenOpsHealth && (
                <button
                  onClick={() => { onOpenOpsHealth(); setOpen(false) }}
                  className="w-full text-left px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors flex items-center gap-2.5"
                >
                  <span className="text-base">Ops</span>
                  <span>运维面板</span>
                </button>
              )}
            </>
          )}

          {/* 测试系统通知 — 所有用户都能看到 */}
          <button
            onClick={() => { void sendTestNotification(); setOpen(false) }}
            className="w-full text-left px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors flex items-center gap-2.5 border-t border-slate-700/50"
            title="点击测试 Windows 系统通知是否工作"
          >
            <span className="text-base">🔔</span>
            <span>测试系统通知</span>
          </button>

          {/* 退出 */}
          <button
            onClick={() => { onLogout(); setOpen(false) }}
            className="w-full text-left px-3 py-2.5 text-sm text-red-400 hover:bg-red-500/10 transition-colors flex items-center gap-2.5 border-t border-slate-700/50"
          >
            <span className="text-base">🚪</span>
            <span>退出当前设备</span>
          </button>
        </div>
      )}
    </div>
  )
}
