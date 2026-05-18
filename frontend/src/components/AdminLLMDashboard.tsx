import { useEffect, useState } from 'react'
import { getLlmSceneStats, type LlmSceneStats } from '../api'

interface Props {
  open: boolean
  onClose: () => void
}

/**
 * Admin-only quality dashboard for LLM calls.
 *
 * Surfaces per-scene total / acceptance rate / edit rate / token cost / latency.
 * Data comes from the audit DB via /api/llm-traces/scenes/stats. Calls without
 * user feedback are excluded from the rate columns so they don't drag numbers
 * down — only feedback_count denominates acceptance_rate / edit_rate.
 *
 * Read-only by design: writes (e.g. prompt rollback) belong to a separate
 * mutation endpoint and aren't in P1-2 scope.
 */
export default function AdminLLMDashboard({ open, onClose }: Props) {
  const [scenes, setScenes] = useState<LlmSceneStats[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError('')
    getLlmSceneStats()
      .then(setScenes)
      .catch(e => setError(e instanceof Error ? e.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [open])

  if (!open) return null

  const totalCalls = scenes.reduce((s, x) => s + x.total, 0)
  const totalFeedback = scenes.reduce((s, x) => s + x.feedback_count, 0)
  const totalAccepted = scenes.reduce((s, x) => s + x.accepted_count, 0)
  const overallAcceptance = totalFeedback > 0 ? totalAccepted / totalFeedback : null
  const totalErrors = scenes.reduce((s, x) => s + x.error_count, 0)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-6xl max-h-[90vh] flex flex-col">
        <header className="flex items-center justify-between p-5 border-b border-slate-700">
          <div>
            <h2 className="text-lg font-semibold text-white">LLM 调用质量仪表盘</h2>
            <div className="text-xs text-slate-500 mt-0.5">
              基于历史 LLM 追溯，反馈率 = 用户点确认/取消的占比；接受率 = 在已反馈中被接受的比例
            </div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-200 text-xl leading-none">
            ✕
          </button>
        </header>

        {/* Summary cards */}
        <div className="grid grid-cols-4 gap-3 p-5 border-b border-slate-800">
          <SummaryCard label="总调用次数" value={totalCalls.toLocaleString()} />
          <SummaryCard label="已反馈次数" value={totalFeedback.toLocaleString()} sub={totalCalls > 0 ? `${((totalFeedback / totalCalls) * 100).toFixed(0)}%` : '—'} />
          <SummaryCard
            label="总接受率"
            value={overallAcceptance === null ? '—' : `${(overallAcceptance * 100).toFixed(1)}%`}
            tone={overallAcceptance !== null && overallAcceptance >= 0.7 ? 'good' : overallAcceptance !== null && overallAcceptance < 0.5 ? 'bad' : 'neutral'}
          />
          <SummaryCard label="累计错误" value={totalErrors.toLocaleString()} tone={totalErrors > 0 ? 'bad' : 'neutral'} />
        </div>

        {/* Scene table */}
        <div className="flex-1 overflow-y-auto p-5">
          {loading && <div className="text-slate-400 text-sm">加载中…</div>}
          {error && <div className="text-red-400 text-sm">❌ {error}</div>}
          {!loading && !error && scenes.length === 0 && (
            <div className="text-slate-500 text-sm">暂无追溯数据。让用户在 Ledger / Compliance / Auth / Training / Audit 任一流程里走一次,数据会自动出现。</div>
          )}
          {!loading && scenes.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-400 uppercase border-b border-slate-700">
                  <th className="text-left py-2 px-2 font-medium">Scene</th>
                  <th className="text-right py-2 px-2 font-medium">调用</th>
                  <th className="text-right py-2 px-2 font-medium">反馈</th>
                  <th className="text-right py-2 px-2 font-medium">接受率</th>
                  <th className="text-right py-2 px-2 font-medium">修改率</th>
                  <th className="text-right py-2 px-2 font-medium">错误</th>
                  <th className="text-right py-2 px-2 font-medium">平均 tokens (in/out)</th>
                  <th className="text-right py-2 px-2 font-medium">平均延迟</th>
                </tr>
              </thead>
              <tbody>
                {scenes.map(s => (
                  <SceneRow key={s.scene} s={s} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

function SummaryCard({
  label, value, sub, tone = 'neutral',
}: {
  label: string
  value: string
  sub?: string
  tone?: 'good' | 'bad' | 'neutral'
}) {
  const toneClass = tone === 'good'
    ? 'text-emerald-400'
    : tone === 'bad'
      ? 'text-red-400'
      : 'text-white'
  return (
    <div className="bg-slate-800/60 border border-slate-700 rounded-lg p-3">
      <div className="text-[11px] text-slate-500 uppercase tracking-wide mb-1">{label}</div>
      <div className={`text-xl font-semibold ${toneClass}`}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}

function SceneRow({ s }: { s: LlmSceneStats }) {
  const rateText = (r: number | null) => r === null ? '—' : `${(r * 100).toFixed(1)}%`
  const acceptanceColor = s.acceptance_rate === null
    ? 'text-slate-500'
    : s.acceptance_rate >= 0.7
      ? 'text-emerald-400'
      : s.acceptance_rate < 0.5
        ? 'text-red-400'
        : 'text-amber-400'
  const editColor = s.edit_rate !== null && s.edit_rate > 0.5 ? 'text-amber-400' : 'text-slate-300'
  const errColor = s.error_count > 0 ? 'text-red-400' : 'text-slate-500'
  return (
    <tr className="border-b border-slate-800 hover:bg-slate-800/40">
      <td className="py-2 px-2 text-slate-200 font-mono text-xs">{s.scene}</td>
      <td className="py-2 px-2 text-right text-slate-300">{s.total.toLocaleString()}</td>
      <td className="py-2 px-2 text-right text-slate-400">{s.feedback_count.toLocaleString()}</td>
      <td className={`py-2 px-2 text-right font-medium ${acceptanceColor}`}>{rateText(s.acceptance_rate)}</td>
      <td className={`py-2 px-2 text-right ${editColor}`}>{rateText(s.edit_rate)}</td>
      <td className={`py-2 px-2 text-right ${errColor}`}>{s.error_count.toLocaleString()}</td>
      <td className="py-2 px-2 text-right text-slate-400 text-xs">
        {Math.round(s.avg_tokens_in)} / {Math.round(s.avg_tokens_out)}
      </td>
      <td className="py-2 px-2 text-right text-slate-400 text-xs">{Math.round(s.avg_duration_ms)}ms</td>
    </tr>
  )
}
