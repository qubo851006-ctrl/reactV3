import { createContext, useContext } from 'react'

export type NoticeType = 'success' | 'error' | 'info'

export interface NoticeInput {
  type: NoticeType
  title: string
  message?: string
  titleBadge?: string
}

export interface NotificationContextValue {
  notify: (notice: NoticeInput) => void
  notifySuccess: (title: string, message?: string) => void
  notifyError: (title: string, message?: string) => void
  /**
   * Diagnostic — wired to the "测试通知" menu entry.
   * Handles the three-state Notification API permission flow:
   *   - 'default'   → ask for permission, then notify on grant
   *   - 'granted'   → fire a success toast + system notification immediately
   *   - 'denied'    → fire an error toast pointing the user to browser settings
   * Always shows a toast (in-app) regardless of permission state, so the
   * user gets visible feedback even when browser-level notifications are off.
   */
  sendTestNotification: () => Promise<void>
}

export const NotificationContext = createContext<NotificationContextValue | null>(null)

/**
 * Read the active notifier. Throws if a component renders outside the
 * `<NotificationProvider>` tree — surfaces the wiring bug early instead
 * of silently swallowing notifications.
 */
export function useNotifier(): NotificationContextValue {
  const context = useContext(NotificationContext)
  if (!context) {
    throw new Error('useNotifier must be used inside NotificationProvider')
  }
  return context
}
