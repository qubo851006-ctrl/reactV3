import { useEffect, useState } from 'react'
import type { AuthUser } from './AuthGate'

interface ManagedUser {
  id: number
  name: string
  department: string
  role: string
  status: string
  last_login_at: string | null
  active_sessions: number
}

interface Notice {
  type: 'ok' | 'err'
  text: string
}

interface Props {
  open: boolean
  onClose: () => void
  currentUser: AuthUser
}

export default function UserAdminPanel({ open, onClose, currentUser }: Props) {
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [selected, setSelected] = useState<ManagedUser | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDept, setNewDept] = useState('法务部')
  const [newRole, setNewRole] = useState('user')

  const load = () => {
    fetch('/api/admin/users', { credentials: 'include' })
      .then(r => r.json())
      .then(d => setUsers(d.users ?? []))
      .catch(() => {})
  }

  useEffect(() => { if (open) load() }, [open])

  function showNotice(type: 'ok' | 'err', text: string) {
    setNotice({ type, text })
  }

  async function createUser() {
    if (!newName.trim()) return
    const r = await fetch('/api/admin/users', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newName.trim(), department: newDept, role: newRole }),
    })
    const d = await r.json()
    if (!r.ok) { showNotice('err', (d as { detail?: string }).detail ?? '创建失败'); return }
    showNotice('ok', `用户「${newName.trim()}」已创建，初始短码：${d.short_code}（请复制后告知用户）`)
    setNewName('')
    setCreating(false)
    load()
  }

  async function resetCode(userId: number) {
    const r = await fetch(`/api/admin/users/${userId}/reset-code`, {
      method: 'POST',
      credentials: 'include',
    })
    if (!r.ok) { showNotice('err', '重置失败'); return }
    const d = await r.json()
    showNotice('ok', `新短码：${d.short_code}（请复制后告知用户，关闭提示后不再显示）`)
  }

  async function revokeSessions(userId: number) {
    await fetch(`/api/admin/users/${userId}/revoke-sessions`, {
      method: 'POST',
      credentials: 'include',
    })
    showNotice('ok', '已强制下线该用户所有设备')
    load()
  }

  async function patchUser(userId: number, patch: Record<string, string>) {
    const r = await fetch(`/api/admin/users/${userId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!r.ok) { showNotice('err', '操作失败'); return }
    load()
    setSelected(prev => (prev?.id === userId ? { ...prev, ...patch } : prev))
  }

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      )}
      <div
        className={`
          fixed top-0 right-0 z-50 h-full w-[460px] max-w-full
          bg-slate-900 border-l border-slate-700/60 shadow-2xl flex flex-col
          transition-transform duration-300 ease-in-out
          ${open ? 'translate-x-0' : 'translate-x-full'}
        `}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/60 flex-shrink-0">
          <div>
            <div className="text-sm font-semibold text-white">用户管理</div>
            <div className="text-xs text-slate-500 mt-0.5">管理员面板 · {users.length} 个用户</div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Notice */}
        {notice && (
          <div
            className={`mx-4 mt-3 px-3 py-2 rounded-lg text-xs flex-shrink-0 ${
              notice.type === 'ok'
                ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300'
                : 'bg-red-500/10 border border-red-500/20 text-red-300'
            }`}
          >
            <span className="pr-4">{notice.text}</span>
            <button
              onClick={() => setNotice(null)}
              className="float-right text-slate-500 hover:text-slate-300 font-bold"
            >
              ×
            </button>
          </div>
        )}

        {/* Body: list + detail */}
        <div className="flex flex-1 overflow-hidden">
          {/* ── 用户列表 ── */}
          <div className="w-[180px] flex-shrink-0 border-r border-slate-700/60 flex flex-col overflow-hidden">
            <div className="px-3 pt-3 pb-2 flex-shrink-0">
              <button
                onClick={() => { setCreating(true); setSelected(null) }}
                className="w-full text-center py-1.5 rounded-lg text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
              >
                + 新增用户
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-2 pb-2">
              {users.map(u => (
                <button
                  key={u.id}
                  onClick={() => { setSelected(u); setCreating(false) }}
                  className={`w-full text-left px-2.5 py-2 rounded-xl mb-1 transition-all ${
                    selected?.id === u.id && !creating
                      ? 'bg-slate-700 border border-slate-600'
                      : 'hover:bg-slate-800'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div
                      className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 ${
                        u.status === 'active' ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-500'
                      }`}
                    >
                      {u.name[0]}
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-slate-200 truncate">{u.name}</div>
                      <div className="text-[10px] text-slate-500">
                        {u.role === 'admin' ? '管理员' : '用户'} ·{' '}
                        {u.status === 'active' ? '启用' : '停用'}
                      </div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* ── 详情面板 ── */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {creating ? (
              /* 新增用户表单 */
              <div>
                <div className="text-xs font-semibold text-slate-300 mb-4">新增用户</div>
                {[
                  { label: '姓名', value: newName, onChange: setNewName, placeholder: '请输入姓名' },
                  { label: '部门', value: newDept, onChange: setNewDept, placeholder: '例：法务部' },
                ].map(f => (
                  <div key={f.label} className="mb-3">
                    <label className="block text-[10px] text-slate-500 mb-1">{f.label}</label>
                    <input
                      value={f.value}
                      onChange={e => f.onChange(e.target.value)}
                      placeholder={f.placeholder}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-indigo-500 transition-colors"
                    />
                  </div>
                ))}
                <div className="mb-4">
                  <label className="block text-[10px] text-slate-500 mb-1">角色</label>
                  <select
                    value={newRole}
                    onChange={e => setNewRole(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white outline-none focus:border-indigo-500 transition-colors"
                  >
                    <option value="user">普通用户</option>
                    <option value="admin">管理员</option>
                  </select>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={createUser}
                    className="flex-1 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-lg transition-colors"
                  >
                    创建
                  </button>
                  <button
                    onClick={() => setCreating(false)}
                    className="flex-1 py-2 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded-lg transition-colors"
                  >
                    取消
                  </button>
                </div>
              </div>
            ) : selected ? (
              /* 用户详情 */
              <div>
                <div className="flex items-center gap-3 mb-5">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center text-base font-semibold ${
                      selected.status === 'active' ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-500'
                    }`}
                  >
                    {selected.name[0]}
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">{selected.name}</div>
                    <div className="text-xs text-slate-500">{selected.department}</div>
                  </div>
                </div>

                <div className="space-y-3 text-xs mb-5">
                  {/* 角色 */}
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">角色</span>
                    <select
                      value={selected.role}
                      disabled={selected.id === currentUser.id}
                      onChange={e => patchUser(selected.id, { role: e.target.value })}
                      className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-white text-xs outline-none focus:border-indigo-500 disabled:opacity-50"
                    >
                      <option value="user">普通用户</option>
                      <option value="admin">管理员</option>
                    </select>
                  </div>
                  {/* 状态 */}
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">状态</span>
                    <select
                      value={selected.status}
                      disabled={selected.id === currentUser.id}
                      onChange={e => patchUser(selected.id, { status: e.target.value })}
                      className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-white text-xs outline-none focus:border-indigo-500 disabled:opacity-50"
                    >
                      <option value="active">启用</option>
                      <option value="disabled">停用</option>
                    </select>
                  </div>
                  {/* 最近登录 */}
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">最近登录</span>
                    <span className="text-slate-300">
                      {selected.last_login_at
                        ? new Date(selected.last_login_at).toLocaleString('zh-CN', {
                            month: '2-digit', day: '2-digit',
                            hour: '2-digit', minute: '2-digit',
                          })
                        : '从未登录'}
                    </span>
                  </div>
                  {/* 活跃设备 */}
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">活跃设备</span>
                    <span className="text-slate-300">{selected.active_sessions} 台</span>
                  </div>
                </div>

                <div className="space-y-2">
                  <button
                    onClick={() => resetCode(selected.id)}
                    className="w-full py-2 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs rounded-lg transition-colors flex items-center justify-center gap-1.5"
                  >
                    🔑 重置短码
                  </button>
                  {selected.id !== currentUser.id && (
                    <button
                      onClick={() => revokeSessions(selected.id)}
                      className="w-full py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 text-xs rounded-lg transition-colors border border-red-500/20 flex items-center justify-center gap-1.5"
                    >
                      ⚡ 强制下线所有设备
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="text-center text-slate-600 text-xs mt-10">
                ← 从左侧选择用户查看详情
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
