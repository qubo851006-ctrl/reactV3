import { useEffect, useRef, useState } from 'react'
import type { AuthUser } from './AuthGate'
import { APP_NAME, APP_TITLE, APP_VERSION } from '../appMeta'

declare global {
  interface Window {
    dd?: {
      runtime?: {
        permission?: {
          requestAuthCode?: (options: {
            corpId: string
            onSuccess: (result: { code: string }) => void
            onFail: (error: unknown) => void
          }) => void
        }
      }
      ready?: (callback: () => void) => void
      error?: (callback: (error: unknown) => void) => void
    }
  }
}

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
  const [ssoHint, setSsoHint] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetch('/api/auth/users-lite')
      .then(r => r.json())
      .then(d => setUsers(d.users ?? []))
      .catch(() => {})
  }, [])

  // 钉钉 SSO 免登（V3 专属）
  useEffect(() => {
    let cancelled = false

    async function tryDingTalkSso() {
      try {
        const cfgResp = await fetch('/api/auth/dingtalk/config')
        const cfg = await cfgResp.json()
        if (!cfg?.enabled || !cfg?.corp_id) return
        if (!/DingTalk/i.test(navigator.userAgent) && !window.dd) return
        setSsoHint('正在尝试钉钉免登…')
        await ensureDingTalkJsApi()
        if (cancelled) return
        const dd = window.dd
        const requestAuthCode = dd?.runtime?.permission?.requestAuthCode
        if (!requestAuthCode) {
          setSsoHint('当前钉钉环境暂不支持免登，仍可使用短码登录')
          return
        }
        const code = await new Promise<string>((resolve, reject) => {
          const run = () => requestAuthCode({
            corpId: cfg.corp_id,
            onSuccess: result => resolve(result.code),
            onFail: reject,
          })
          if (dd?.ready) dd.ready(run)
          else run()
          dd?.error?.(reject)
        })
        if (cancelled) return
        const loginResp = await fetch('/api/auth/dingtalk/sso', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ code }),
        })
        if (!loginResp.ok) {
          const d = await loginResp.json().catch(() => ({}))
          setSsoHint((d as { detail?: string }).detail ?? '钉钉免登失败，可使用短码登录')
          return
        }
        const d = await loginResp.json()
        onLogin(d.user)
      } catch {
        if (!cancelled) setSsoHint('钉钉免登未完成，可使用短码登录')
      }
    }

    tryDingTalkSso()
    return () => { cancelled = true }
  }, [onLogin])

  // ── 鼠标视差 + 国航客机跟随（侧视：facing + pitch 替代 360 旋转） ──
  const rootRef = useRef<HTMLDivElement>(null)
  const rightZoneRef = useRef<HTMLDivElement>(null)
  const planeRef = useRef<HTMLDivElement>(null)
  const planeFlipRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const hasHover = window.matchMedia('(hover: hover)').matches
    if (reduce || !hasHover) return

    const targetPx = { x: 0, y: 0 }
    const currentPx = { x: 0, y: 0 }

    const planeT = {
      x: -300, y: -300,
      facing: 1,
      pitch: 0,
      visible: false,
      lastMx: -1, lastMy: -1,
    }
    const planeC = { x: -300, y: -300, facing: 1, pitch: 0, alpha: 0 }

    let raf = 0
    let active = true

    function onMove(e: MouseEvent) {
      targetPx.x = (e.clientX / window.innerWidth - 0.5) * 2
      targetPx.y = (e.clientY / window.innerHeight - 0.5) * 2

      if (planeT.lastMx < 0) {
        planeT.lastMx = e.clientX
        planeT.lastMy = e.clientY
      }
      const dx = e.clientX - planeT.lastMx
      const dy = e.clientY - planeT.lastMy
      planeT.lastMx = e.clientX
      planeT.lastMy = e.clientY

      planeT.x = e.clientX
      planeT.y = e.clientY

      if (Math.abs(dx) > 1.5) {
        planeT.facing = dx > 0 ? 1 : -1
      }
      planeT.pitch = Math.max(-22, Math.min(22, dy * 1.5))

      const zone = rightZoneRef.current
      if (zone) {
        const r = zone.getBoundingClientRect()
        planeT.visible =
          e.clientX >= r.left && e.clientX <= r.right &&
          e.clientY >= r.top && e.clientY <= r.bottom
      }
    }
    function onLeave() {
      targetPx.x = 0
      targetPx.y = 0
      planeT.visible = false
    }
    function tick() {
      if (!active) return

      currentPx.x += (targetPx.x - currentPx.x) * 0.11
      currentPx.y += (targetPx.y - currentPx.y) * 0.11
      const el = rootRef.current
      if (el) {
        el.style.setProperty('--mx', currentPx.x.toFixed(3))
        el.style.setProperty('--my', currentPx.y.toFixed(3))
      }

      planeC.x += (planeT.x - planeC.x) * 0.18
      planeC.y += (planeT.y - planeC.y) * 0.18

      planeC.facing += (planeT.facing - planeC.facing) * 0.10

      const speed = Math.hypot(planeT.x - planeC.x, planeT.y - planeC.y)
      if (speed < 0.5) {
        planeT.pitch *= 0.9
      }
      planeC.pitch += (planeT.pitch - planeC.pitch) * 0.15

      const targetAlpha = planeT.visible ? 1 : 0
      planeC.alpha += (targetAlpha - planeC.alpha) * 0.12

      const plane = planeRef.current
      const flip = planeFlipRef.current
      if (plane && flip) {
        const facingSign = planeC.facing >= 0 ? 1 : -1
        plane.style.transform = `translate3d(${(planeC.x - 30).toFixed(2)}px, ${(planeC.y - 10).toFixed(2)}px, 0) rotate(${(planeC.pitch * facingSign).toFixed(2)}deg)`
        plane.style.opacity = planeC.alpha.toFixed(3)
        flip.style.transform = `scaleX(${planeC.facing.toFixed(3)})`
      }

      raf = requestAnimationFrame(tick)
    }
    window.addEventListener('mousemove', onMove)
    document.addEventListener('mouseleave', onLeave)
    raf = requestAnimationFrame(tick)
    return () => {
      active = false
      cancelAnimationFrame(raf)
      window.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseleave', onLeave)
    }
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
    <div ref={rootRef} className="relative min-h-screen overflow-hidden bg-[#070713] text-white">
      <style>{`
        @keyframes float-orb-1 {
          0%, 100% { transform: translate3d(calc(var(--mx, 0) * 80px), calc(var(--my, 0) * 80px), 0) scale(1); }
          50% { transform: translate3d(calc(60px + var(--mx, 0) * 80px), calc(80px + var(--my, 0) * 80px), 0) scale(1.1); }
        }
        @keyframes float-orb-2 {
          0%, 100% { transform: translate3d(calc(var(--mx, 0) * -80px), calc(var(--my, 0) * -80px), 0) scale(1); }
          50% { transform: translate3d(calc(-80px + var(--mx, 0) * -80px), calc(-60px + var(--my, 0) * -80px), 0) scale(1.15); }
        }
        @keyframes breathe-ring {
          0%, 100% { opacity: 0.55; transform: scale(1); }
          50% { opacity: 0.95; transform: scale(1.05); }
        }
        @keyframes rise-in {
          from { opacity: 0; transform: translateY(14px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .rise-in { animation: rise-in 0.7s cubic-bezier(0.16, 1, 0.3, 1) both; }
        .rise-d1 { animation-delay: 0.08s; }
        .rise-d2 { animation-delay: 0.16s; }
        .rise-d3 { animation-delay: 0.24s; }

        .tilt-logo {
          transform: perspective(1200px)
                     rotateY(calc(var(--mx, 0) * 13deg))
                     rotateX(calc(var(--my, 0) * -13deg))
                     translate3d(calc(var(--mx, 0) * 20px), calc(var(--my, 0) * 20px), 0);
          transform-style: preserve-3d;
          transition: transform 0.05s linear;
          will-change: transform;
        }
        .tilt-logo .specular {
          position: absolute;
          inset: 0;
          pointer-events: none;
          background: radial-gradient(
            ellipse 70% 70% at
              calc(50% + var(--mx, 0) * 45%)
              calc(50% + var(--my, 0) * 45%),
            rgba(255,255,255,0.75) 0%,
            rgba(255,255,255,0.12) 30%,
            transparent 60%
          );
          mix-blend-mode: overlay;
        }
        .tilt-reflection {
          position: absolute;
          left: 50%;
          top: 100%;
          width: 80%;
          height: 30%;
          transform: translate3d(-50%, 0, 0) scaleY(-1);
          opacity: 0.18;
          filter: blur(2px);
          mask-image: linear-gradient(to bottom, black, transparent 75%);
          -webkit-mask-image: linear-gradient(to bottom, black, transparent 75%);
          pointer-events: none;
        }
        .parallax-counter {
          transform: translate3d(calc(var(--mx, 0) * -16px), calc(var(--my, 0) * -16px), 0);
          will-change: transform;
        }
        .parallax-soft {
          transform: translate3d(calc(var(--mx, 0) * -10px), calc(var(--my, 0) * -10px), 0);
          will-change: transform;
        }
        @media (prefers-reduced-motion: reduce) {
          .tilt-logo, .parallax-counter, .parallax-soft { transform: none !important; }
        }
      `}</style>

      {/* ── 国航客机鼠标光标（侧视 747-style，机头朝右） ── */}
      <div
        ref={planeRef}
        aria-hidden
        className="hidden lg:block fixed left-0 top-0 pointer-events-none z-[60]"
        style={{ width: 60, height: 20, opacity: 0, willChange: 'transform, opacity' }}
      >
        <div
          ref={planeFlipRef}
          className="relative w-full h-full"
          style={{ willChange: 'transform', transformOrigin: 'center' }}
        >
          <div
            className="absolute"
            style={{
              right: '92%',
              top: '50%',
              transform: 'translateY(-50%)',
              width: 75,
              height: 2,
              background:
                'linear-gradient(to left, rgba(255,255,255,0.65), rgba(255,255,255,0.18) 45%, rgba(255,255,255,0) 100%)',
              filter: 'blur(3.5px)',
              borderRadius: 9999,
            }}
          />
          <svg viewBox="0 0 180 60" width="60" height="20" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="ac-body" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ffffff" />
                <stop offset="55%" stopColor="#f5f7fa" />
                <stop offset="100%" stopColor="#b3bcc8" />
              </linearGradient>
              <linearGradient id="ac-wing-g" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#dde2e8" />
                <stop offset="100%" stopColor="#8a93a3" />
              </linearGradient>
            </defs>

            <path d="M 14 30 L 0 35 L 10 36 L 22 32 Z" fill="url(#ac-wing-g)" stroke="rgba(15,15,35,0.4)" strokeWidth="0.3" />
            <path d="M 10 30 L 18 6 L 30 28 L 30 30 Z" fill="white" stroke="rgba(15,15,35,0.4)" strokeWidth="0.4" />
            <path d="M 13 24 Q 16 13 21 16 Q 18 18 17 22 Q 20 20 22 23 Q 17 26 13 24 Z" fill="#dc1820" />

            <path d="M 12 30
                     Q 11 33 17 33.3
                     L 158 32
                     Q 168 31.5 173 29
                     Q 178 26 178 25
                     Q 175 21 168 20.5
                     L 18 25
                     Q 11 25.5 12 30 Z"
                  fill="url(#ac-body)" stroke="rgba(15,15,35,0.4)" strokeWidth="0.5" />

            <path d="M 68 32 L 50 46 L 100 38 L 110 32 Z" fill="url(#ac-wing-g)" stroke="rgba(15,15,35,0.4)" strokeWidth="0.4" />

            <ellipse cx="60" cy="41" rx="7" ry="2.6" fill="#374151" stroke="rgba(0,0,0,0.4)" strokeWidth="0.3" />
            <ellipse cx="80" cy="39" rx="6" ry="2.3" fill="#374151" stroke="rgba(0,0,0,0.4)" strokeWidth="0.3" />

            <path d="M 20 28 L 162 26.5" stroke="#1e40af" strokeWidth="0.7" opacity="0.7" fill="none" />

            <g fill="#1e293b" opacity="0.45">
              {Array.from({ length: 22 }, (_, i) => (
                <circle key={i} cx={26 + i * 6} cy="27" r="0.5" />
              ))}
            </g>

            <path d="M 165 23 L 174 25 L 173 27.5 L 165 26.5 Z" fill="#0f172a" />
          </svg>
        </div>
      </div>

      {/* ── 背景层 ── */}
      <div className="absolute inset-0 pointer-events-none">
        <div
          className="absolute inset-0"
          style={{
            backgroundImage:
              'radial-gradient(circle at 1px 1px, rgba(148, 163, 184, 0.08) 1px, transparent 0)',
            backgroundSize: '36px 36px',
          }}
        />
        <div
          className="absolute -top-48 -left-32 w-[680px] h-[680px] rounded-full"
          style={{
            background:
              'radial-gradient(circle, rgba(99,102,241,0.28), rgba(99,102,241,0) 70%)',
            animation: 'float-orb-1 26s ease-in-out infinite',
          }}
        />
        <div
          className="absolute -bottom-48 -right-32 w-[760px] h-[760px] rounded-full"
          style={{
            background:
              'radial-gradient(circle, rgba(168,85,247,0.22), rgba(168,85,247,0) 70%)',
            animation: 'float-orb-2 32s ease-in-out infinite',
          }}
        />
        <div className="absolute top-0 inset-x-0 h-px bg-gradient-to-r from-transparent via-indigo-400/50 to-transparent" />
      </div>

      {/* ── 内容层（左右分屏） ── */}
      <div className="relative grid lg:grid-cols-[440px_minmax(0,1fr)] min-h-screen">
        {/* 左侧：登录区 */}
        <div className="flex items-center justify-center p-6 lg:p-12">
          <div className="w-full max-w-md">
            {/* 顶部品牌 */}
            <div className="flex items-center gap-3 mb-10 rise-in">
              <div className="relative shrink-0">
                <div className="absolute -inset-2 rounded-2xl bg-white/10 blur-xl" />
                <div className="relative w-14 h-14 rounded-xl bg-white p-0.5 shadow-lg shadow-black/40">
                  <img
                    src="/airchina-logo.png"
                    alt="Air China"
                    className="w-full h-full object-contain"
                  />
                </div>
              </div>
              <div className="min-w-0">
                <h1 className="text-lg font-semibold tracking-tight leading-tight truncate">
                  {APP_TITLE}
                </h1>
                <p className="text-xs text-slate-400 mt-0.5">
                  部门内部工具 · 请确认当前使用人
                </p>
              </div>
            </div>

            {/* 玻璃登录卡 */}
            <div
              className="relative rounded-3xl border border-white/10 bg-white/[0.03] backdrop-blur-2xl p-7 rise-in rise-d1"
              style={{
                boxShadow:
                  '0 24px 64px -16px rgba(15, 15, 35, 0.85), 0 8px 32px -8px rgba(99, 102, 241, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.06)',
              }}
            >
              {ssoHint && (
                <div className="text-xs text-sky-300 bg-sky-500/10 border border-sky-500/20 rounded-lg px-3 py-2 mb-4">
                  {ssoHint}
                </div>
              )}
              {!selected ? (
                /* ── Step 1：选择姓名 ── */
                <>
                  <div className="text-[11px] font-medium text-slate-400 mb-3 uppercase tracking-[0.18em]">
                    选择您的姓名
                  </div>
                  <input
                    type="text"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="搜索姓名或部门…"
                    className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-400/60 focus:bg-black/40 focus:shadow-[0_0_0_4px_rgba(99,102,241,0.12)] transition-all mb-3"
                  />
                  {users.length === 0 ? (
                    <div className="text-center py-8 text-slate-500 text-sm">加载成员列表中…</div>
                  ) : filtered.length === 0 ? (
                    <div className="text-center py-8 text-slate-500 text-sm">未找到匹配成员</div>
                  ) : (
                    <div className="grid grid-cols-3 gap-2 max-h-60 overflow-y-auto pr-1 -mr-1">
                      {filtered.map(u => (
                        <button
                          key={u.id}
                          onClick={() => { setSelected(u); setCode(''); setError('') }}
                          className="group text-left px-3 py-2.5 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:border-indigo-400/40 hover:bg-indigo-500/[0.08] transition-all"
                        >
                          <div className="text-sm font-medium text-slate-100 group-hover:text-white">
                            {u.name}
                          </div>
                          <div className="text-xs text-slate-500 mt-0.5 truncate">
                            {u.department}
                          </div>
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
                    className="text-xs text-slate-500 hover:text-slate-200 mb-4 flex items-center gap-1 transition-colors"
                  >
                    ← 重新选择
                  </button>

                  <div className="bg-black/30 border border-white/[0.06] rounded-xl px-4 py-3 mb-4 flex items-center gap-3">
                    <div className="w-9 h-9 rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center text-base font-medium text-white flex-shrink-0 shadow-lg shadow-indigo-500/30">
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
                    className="w-full bg-black/30 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-400/60 focus:bg-black/40 focus:shadow-[0_0_0_4px_rgba(99,102,241,0.12)] transition-all mb-3 tracking-[0.3em]"
                  />

                  {error && (
                    <div className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 mb-3">
                      {error}
                    </div>
                  )}

                  <button
                    onClick={handleLogin}
                    disabled={loading || !code.trim()}
                    className="group relative w-full py-2.5 rounded-xl overflow-hidden disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-transform active:scale-[0.99]"
                  >
                    <span className="absolute inset-0 bg-gradient-to-r from-indigo-500 to-violet-500" />
                    <span className="absolute inset-0 bg-gradient-to-r from-indigo-400 to-violet-400 opacity-0 group-hover:opacity-100 transition-opacity" />
                    <span
                      className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
                      style={{ boxShadow: '0 8px 32px -4px rgba(139, 92, 246, 0.55)' }}
                    />
                    <span className="relative">{loading ? '验证中…' : '进入系统'}</span>
                  </button>
                </>
              )}
            </div>

            <p className="text-center text-xs text-slate-500 mt-6 rise-in rise-d2">
              验证成功后，本设备 30 天内无需重复确认
            </p>
          </div>
        </div>

        {/* 右侧：品牌主视觉（鼠标变国航客机） */}
        <div ref={rightZoneRef} className="hidden lg:flex relative items-center justify-center border-l border-white/[0.06] lg:cursor-none">
          <div className="absolute inset-0 pointer-events-none overflow-hidden">
            <div
              className="absolute top-1/2 left-1/2 w-[560px] h-[560px] rounded-full"
              style={{
                background:
                  'radial-gradient(circle, rgba(99,102,241,0.18), rgba(99,102,241,0) 65%)',
                transform:
                  'translate3d(calc(-50% + var(--mx, 0) * 30px), calc(-50% + var(--my, 0) * 30px), 0)',
              }}
            />
          </div>

          <div className="relative text-center px-12 w-full">
            <div className="relative mx-auto mb-14 rise-in" style={{ width: 'min(820px, 78%)' }}>
              <div
                className="absolute parallax-soft pointer-events-none"
                style={{
                  inset: '-380px -320px',
                  background:
                    'radial-gradient(ellipse 38% 32% at center, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.04) 30%, rgba(180,195,255,0.025) 55%, rgba(99,102,241,0.015) 75%, transparent 100%)',
                  filter: 'blur(48px)',
                }}
              />
              <div
                className="absolute parallax-soft pointer-events-none"
                style={{
                  inset: '-220px -180px',
                  background:
                    'radial-gradient(ellipse 42% 38% at center, rgba(255,255,255,0.82) 0%, rgba(255,255,255,0.6) 10%, rgba(245,248,255,0.42) 22%, rgba(220,230,255,0.26) 36%, rgba(180,195,255,0.14) 52%, rgba(99,102,241,0.07) 70%, rgba(99,102,241,0.025) 85%, transparent 100%)',
                  filter: 'blur(36px)',
                  animation: 'breathe-ring 6s ease-in-out infinite',
                }}
              />
              <div className="tilt-logo relative">
                <img
                  src="/airchina-corp-logo.png"
                  alt="中国航空集团建设开发有限公司"
                  className="relative w-full h-auto object-contain"
                  draggable={false}
                />
                <div className="specular" aria-hidden />
                <img
                  src="/airchina-corp-logo.png"
                  alt=""
                  aria-hidden
                  className="tilt-reflection"
                  draggable={false}
                />
              </div>
            </div>

            <h2 className="text-7xl xl:text-8xl font-bold tracking-tight rise-in rise-d1 parallax-counter bg-gradient-to-r from-white via-indigo-100 to-violet-200 bg-clip-text text-transparent">
              {APP_NAME}
            </h2>
            <p className="text-base text-slate-400 mt-5 rise-in rise-d2 parallax-soft tracking-[0.45em] pl-[0.45em]">
              法务智能工具集
            </p>

            <div className="mt-12 flex items-center justify-center gap-3 rise-in rise-d3">
              <span className="h-px w-12 bg-gradient-to-r from-transparent to-white/20" />
              <span className="text-[11px] text-slate-500 tracking-[0.3em]">{APP_VERSION}</span>
              <span className="h-px w-12 bg-gradient-to-l from-transparent to-white/20" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ensureDingTalkJsApi(): Promise<void> {
  if (window.dd) return Promise.resolve()
  const existing = document.querySelector<HTMLScriptElement>('script[data-dingtalk-jsapi]')
  if (existing) {
    return new Promise((resolve, reject) => {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('dingtalk jsapi load failed')), { once: true })
    })
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://g.alicdn.com/dingding/dingtalk-jsapi/3.0.41/dingtalk.open.js'
    script.async = true
    script.dataset.dingtalkJsapi = 'true'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('dingtalk jsapi load failed'))
    document.head.appendChild(script)
  })
}
