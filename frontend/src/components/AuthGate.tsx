import { useEffect, useState } from 'react'
import IdentityLogin from './IdentityLogin'

export interface AuthUser {
  id: number
  name: string
  department: string
  role: 'admin' | 'user'
}

interface Props {
  children: (user: AuthUser, onLogout: () => void) => React.ReactNode
}

export default function AuthGate({ children }: Props) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [checking, setChecking] = useState(true)

  // 启动时检查 Cookie 是否仍有效
  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(r => (r.ok ? r.json() : null))
      .then(data => { if (data?.user) setUser(data.user) })
      .catch(() => {})
      .finally(() => setChecking(false))
  }, [])

  // 监听 api.ts 派发的 401 事件，自动回到登录页
  useEffect(() => {
    const handler = () => setUser(null)
    window.addEventListener('auth:unauthorized', handler)
    return () => window.removeEventListener('auth:unauthorized', handler)
  }, [])

  function handleLogout() {
    fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => {})
    setUser(null)
  }

  if (checking) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="flex gap-1">
          {[0, 150, 300].map(d => (
            <span
              key={d}
              className="w-2 h-2 bg-slate-600 rounded-full animate-bounce"
              style={{ animationDelay: `${d}ms` }}
            />
          ))}
        </div>
      </div>
    )
  }

  if (!user) return <IdentityLogin onLogin={setUser} />

  return <>{children(user, handleLogout)}</>
}
