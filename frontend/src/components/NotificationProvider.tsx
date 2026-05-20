import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { NotificationContext } from './NotificationContext'
import type { NoticeInput, NoticeType, NotificationContextValue } from './NotificationContext'

/**
 * Global notification provider — surfaces "AI task done" toasts at the
 * top-right of the viewport plus a system-notification (Notification API)
 * when the user has granted permission.
 *
 * Behaviours:
 * - Toast: stays 6.5s, max 4 stacked, click ✕ to dismiss
 * - Page title: flashes between '【已完成】<原标题>' and '<原标题>' every
 *   850ms for 9 seconds — pulls the eye even when the tab is backgrounded
 * - System notification: only fires when the user has explicitly granted
 *   Notification.permission === 'granted'
 * - 'Default' permission state shows a per-toast "开启系统通知" button
 *   so the prompt is contextual (not on first page load)
 *
 * Lifted from V2 with one change: notification tag prefix is now
 * 'reactv3-…' instead of 'reactv2-…' so notifications from both apps
 * don't collide if a user opens them side by side.
 */
interface Notice extends NoticeInput {
  id: number
}

const TYPE_CLASS: Record<NoticeType, string> = {
  success: 'border-emerald-400/40 bg-emerald-500/15 text-emerald-50',
  error: 'border-red-400/40 bg-red-500/15 text-red-50',
  info: 'border-sky-400/40 bg-sky-500/15 text-sky-50',
}

const DOT_CLASS: Record<NoticeType, string> = {
  success: 'bg-emerald-300',
  error: 'bg-red-300',
  info: 'bg-sky-300',
}

const DEFAULT_BADGE: Record<NoticeType, string> = {
  success: '已完成',
  error: '处理失败',
  info: '新提醒',
}

function getInitialNotificationPermission(): NotificationPermission | 'unsupported' {
  // Use a truthy check (not `'Notification' in window`) so a browser
  // extension or polyfill that defines window.Notification = undefined
  // can't trick us into reading .permission on undefined.
  if (typeof window !== 'undefined' && window.Notification != null) {
    return window.Notification.permission
  }
  return 'unsupported'
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notices, setNotices] = useState<Notice[]>([])
  const [notificationPermission, setNotificationPermission] =
    useState<NotificationPermission | 'unsupported'>(getInitialNotificationPermission)
  const nextId = useRef(1)
  const titleTimer = useRef<number | null>(null)
  const titlePulseTimer = useRef<number | null>(null)
  const originalTitle = useRef('')

  useEffect(() => {
    if (typeof document !== 'undefined') {
      originalTitle.current = document.title
    }
    return () => {
      if (titleTimer.current) window.clearTimeout(titleTimer.current)
      if (titlePulseTimer.current) window.clearInterval(titlePulseTimer.current)
    }
  }, [])

  const flashTitle = useCallback((badge: string) => {
    if (typeof document === 'undefined') return
    if (!originalTitle.current) originalTitle.current = document.title
    if (titleTimer.current) window.clearTimeout(titleTimer.current)
    if (titlePulseTimer.current) window.clearInterval(titlePulseTimer.current)
    let highlighted = false
    const badgeTitle = `【${badge}】${originalTitle.current}`
    document.title = badgeTitle
    titlePulseTimer.current = window.setInterval(() => {
      highlighted = !highlighted
      document.title = highlighted ? badgeTitle : originalTitle.current
    }, 850)
    titleTimer.current = window.setTimeout(() => {
      if (titlePulseTimer.current) {
        window.clearInterval(titlePulseTimer.current)
        titlePulseTimer.current = null
      }
      document.title = originalTitle.current
      titleTimer.current = null
    }, 9000)
  }, [])

  const dismiss = useCallback((id: number) => {
    setNotices(current => current.filter(notice => notice.id !== id))
  }, [])

  const showSystemNotification = useCallback((input: NoticeInput) => {
    if (typeof window === 'undefined' || window.Notification == null) return
    if (window.Notification.permission !== 'granted') return
    new window.Notification(input.title, {
      body: input.message || DEFAULT_BADGE[input.type],
      // silent=true: 不出声(用户偏好,办公环境不打扰别人)
      silent: true,
      // requireInteraction=true: 通知停在 Windows 通知中心,不会自动消失。
      // 用户必须主动点 dismiss 才会消失 — 跟 Claude Code / VS Code 风格一致。
      // 适合 AI 长任务完成的场景:用户可能切到别的标签做事,回来后还能看到。
      requireInteraction: true,
      tag: `reactv3-${input.type}`,
    })
  }, [])

  const requestSystemPermission = useCallback(async (): Promise<NotificationPermission | 'unsupported'> => {
    if (typeof window === 'undefined' || window.Notification == null) {
      setNotificationPermission('unsupported')
      return 'unsupported'
    }
    const permission = await window.Notification.requestPermission()
    setNotificationPermission(permission)
    return permission
  }, [])

  const notify = useCallback((input: NoticeInput) => {
    const id = nextId.current++
    const notice: Notice = { ...input, id }
    setNotices(current => [notice, ...current].slice(0, 4))
    flashTitle(input.titleBadge || DEFAULT_BADGE[input.type])
    showSystemNotification(input)
    window.setTimeout(() => dismiss(id), 6500)
  }, [dismiss, flashTitle, showSystemNotification])

  const sendTestNotification = useCallback(async (): Promise<void> => {
    // 1. Browser doesn't support Notification API at all (rare — old browsers).
    if (typeof window === 'undefined' || window.Notification == null) {
      notify({
        type: 'error',
        title: '系统通知不可用',
        message: '当前浏览器不支持 Notification API,请用 Chrome / Edge / Firefox 最新版',
      })
      return
    }

    // 2. User previously denied — can't ask again, point them to settings.
    if (window.Notification.permission === 'denied') {
      notify({
        type: 'error',
        title: '系统通知已被禁用',
        message: '请在浏览器地址栏左侧锁形图标 → 网站设置 → 通知,改为"允许"',
      })
      return
    }

    // 3. Never asked yet — request now. If user denies in the popup,
    //    requestPermission returns 'denied'.
    if (window.Notification.permission === 'default') {
      const result = await requestSystemPermission()
      if (result !== 'granted') {
        notify({
          type: 'error',
          title: '未授予通知权限',
          message: '系统通知功能需要浏览器授权才能工作',
        })
        return
      }
    }

    // 4. Permission granted — fire BOTH an in-app toast AND a Windows
    //    system notification so the user can confirm each independently.
    notify({
      type: 'success',
      title: '测试通知 — 系统通知工作正常',
      message: '如果你看到 Windows 通知中心也有一条,说明完整链路通了。AI 任务完成时会用同样方式提醒。',
    })
  }, [notify])

  const value = useMemo<NotificationContextValue>(() => ({
    notify,
    notifySuccess: (title, message) => notify({ type: 'success', title, message }),
    notifyError: (title, message) => notify({ type: 'error', title, message }),
    sendTestNotification,
  }), [notify, sendTestNotification])

  return (
    <NotificationContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-5 top-5 z-[80] flex w-[360px] max-w-[calc(100vw-24px)] flex-col gap-3">
        {notices.map(notice => (
          <div
            key={notice.id}
            className={`pointer-events-auto rounded-xl border px-4 py-3 shadow-2xl shadow-black/30 backdrop-blur-md ${TYPE_CLASS[notice.type]}`}
          >
            <div className="flex items-start gap-3">
              <span className={`mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full ${DOT_CLASS[notice.type]}`} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold leading-5">{notice.title}</div>
                {notice.message && (
                  <div className="mt-1 text-xs leading-5 text-slate-200/90">{notice.message}</div>
                )}
                {notificationPermission === 'default' && (
                  <button
                    type="button"
                    onClick={requestSystemPermission}
                    className="mt-2 rounded-md bg-white/10 px-2.5 py-1 text-xs font-medium text-white hover:bg-white/15"
                  >
                    开启系统通知
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismiss(notice.id)}
                className="ml-2 rounded-md px-1.5 text-base leading-5 text-slate-200/70 hover:bg-white/10 hover:text-white"
                aria-label="关闭提醒"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>
    </NotificationContext.Provider>
  )
}
