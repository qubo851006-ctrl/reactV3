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
