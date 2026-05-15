import { useEffect, useState } from 'react'
import type { AuthUser } from './AuthGate'
import { APP_TITLE } from '../appMeta'

interface SlimUser {
  id: number
  name: string
  department: string
}

interface Props {
  onLogin: (user: AuthUser) => void
}

export default function IdentityLogin({ onLogin }: Props) {
  const [users, setUsers] = useState<SlimUser[]>([])
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<SlimUser | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetch('/api/auth/users-lite')
      .then(r => r.json())
      .then(d => setUsers(d.users ?? []))
      .catch(() => {})
  }, [])

  const filtered = users.filter(
    u => u.name.includes(search) || u.department.includes(search)
  )

  async function handleLogin() {
    if (!selected || !code.trim()) return
    setLoading(true)
    setError('')
    try {
      const r = await fetch('/api/auth/bind-device', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ user_id: selected.id, short_code: code.trim() }),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setError((d as { detail?: string }).detail ?? '姓名或短码不正确')
        return
      }
      const d = await r.json()
      onLogin(d.user)
    } catch {
      setError('无法连接服务器，请检查后端是否启动')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-lg">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="text-4xl mb-3">📋</div>
          <h1 className="text-xl font-semibold text-white">{APP_TITLE}</h1>
          <p className="text-sm text-slate-500 mt-1">部门内部工具 · 请确认当前使用人</p>
        </div>

        <div className="bg-slate-900 border border-slate-700/60 rounded-2xl p-6 shadow-2xl">
          {!selected ? (
            /* ── Step 1：选择姓名 ── */
            <>
              <div className="text-xs font-medium text-slate-400 mb-3">选择您的姓名</div>
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="搜索姓名或部门…"
                className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30 transition-colors mb-3"
              />
              {users.length === 0 ? (
                <div className="text-center py-8 text-slate-500 text-sm">加载成员列表中…</div>
              ) : filtered.length === 0 ? (
                <div className="text-center py-8 text-slate-500 text-sm">未找到匹配成员</div>
              ) : (
                <div className="grid grid-cols-3 gap-2 max-h-60 overflow-y-auto pr-1">
                  {filtered.map(u => (
                    <button
                      key={u.id}
                      onClick={() => { setSelected(u); setCode(''); setError('') }}
                      className="text-left px-3 py-2.5 rounded-xl border border-slate-700/50 hover:border-indigo-500/50 hover:bg-slate-800 transition-all"
                    >
                      <div className="text-sm font-medium text-slate-200">{u.name}</div>
                      <div className="text-xs text-slate-500 mt-0.5 truncate">{u.department}</div>
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            /* ── Step 2：输入短码 ── */
            <>
              <button
                onClick={() => { setSelected(null); setError('') }}
                className="text-xs text-slate-500 hover:text-slate-300 mb-4 flex items-center gap-1 transition-colors"
              >
                ← 重新选择
              </button>

              {/* 已选用户卡片 */}
              <div className="bg-slate-800 rounded-xl px-4 py-3 mb-4 flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-indigo-600 flex items-center justify-center text-base font-medium text-white flex-shrink-0">
                  {selected.name[0]}
                </div>
                <div>
                  <div className="text-sm font-medium text-white">{selected.name}</div>
                  <div className="text-xs text-slate-400">{selected.department}</div>
                </div>
              </div>

              <label className="block text-xs font-medium text-slate-400 mb-1.5">
                首次短码
                <span className="ml-1 text-slate-600">（由管理员发放）</span>
              </label>
              <input
                type="password"
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                onKeyDown={e => e.key === 'Enter' && handleLogin()}
                placeholder="请输入 4–6 位数字短码"
                autoFocus
                className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30 transition-colors mb-3 tracking-[0.3em]"
              />

              {error && (
                <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-3">
                  {error}
                </div>
              )}

              <button
                onClick={handleLogin}
                disabled={loading || !code.trim()}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-xl transition-colors"
              >
                {loading ? '验证中…' : '进入系统'}
              </button>
            </>
          )}
        </div>

        <p className="text-center text-xs text-slate-600 mt-4">
          验证成功后，本设备 30 天内无需重复确认
        </p>
      </div>
    </div>
  )
}
