import { useEffect, useState } from 'react'
import {
  getLlmSceneStats,
  getLlmTraceDetail,
  listLlmTraces,
  type LlmSceneStats,
  type LlmTraceDetail,
  type LlmTraceSummary,
} from '../api'

interface Props {
  open: boolean
  onClose: () => void
}

/**
 * Admin-only quality dashboard for LLM calls.
 *
 * Two levels:
 * - Top: per-scene aggregate (total, acceptance, edit rate, tokens, latency)
 * - Drill-in: click a scene row → table of last 20 traces → click a trace
 *   row → modal with full input / output / edited_to
 *
 * Data comes from the audit DB via /api/llm-traces/*. All endpoints require
 * the admin role.
 */
export default function AdminLLMDashboard({ open, onClose }: Props) {
  const [scenes, setScenes] = useState<LlmSceneStats[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Drill-in state
  const [activeScene, setActiveScene] = useState<string | null>(null)
  const [traces, setTraces] = useState<LlmTraceSummary[]>([])
  const [tracesLoading, setTracesLoading] = useState(false)
  const [activeTraceId, setActiveTraceId] = useState<string | null>(null)
  const [detail, setDetail] = useState<LlmTraceDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError('')
    getLlmSceneStats()
      .then(setScenes)
      .catch(e => setError(e instanceof Error ? e.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [open])

  function openSceneDrillin(scene: string) {
    setActiveScene(scene)
    setTracesLoading(true)
    setTraces([])
    listLlmTraces({ scene, limit: 20 })
      .then(setTraces)
      .catch(e => setError(e instanceof Error ? e.message : '加载追溯列表失败'))
      .finally(() => setTracesLoading(false))
  }

  function closeDrillin() {
    setActiveScene(null)
    setTraces([])
  }

  function openTraceDetail(traceId: string) {
    setActiveTraceId(traceId)
    setDetailLoading(true)
    setDetail(null)
    getLlmTraceDetail(traceId)
      .then(setDetail)
      .catch(e => setError(e instanceof Error ? e.message : '加载详情失败'))
      .finally(() => setDetailLoading(false))
  }

  function closeDetail() {
    setActiveTraceId(null)
    setDetail(null)
  }

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
            <h2 className="text-lg font-semibold text-white">
              {activeScene ? `场景明细: ${activeScene}` : 'LLM 调用质量仪表盘'}
            </h2>
            <div className="text-xs text-slate-500 mt-0.5">
              {activeScene
                ? '最近 20 次调用，点击行查看完整输入/输出'
                : '基于历史 LLM 追溯。反馈率 = 用户点确认/取消的占比；接受率 = 在已反馈中被接受的比例'}
            </div>
          </div>
          <div className="flex gap-2">
            {activeScene && (
              <button onClick={closeDrillin} className="text-slate-400 hover:text-slate-200 text-sm">
                ← 返回汇总
              </button>
            )}
            <button onClick={onClose} className="text-slate-500 hover:text-slate-200 text-xl leading-none">
              ✕
            </button>
          </div>
        </header>

        {!activeScene && (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-4 gap-3 p-5 border-b border-slate-800">
              <SummaryCard label="总调用次数" value={totalCalls.toLocaleString()} />
              <SummaryCard
                label="已反馈次数"
                value={totalFeedback.toLocaleString()}
                sub={totalCalls > 0 ? `${((totalFeedback / totalCalls) * 100).toFixed(0)}%` : '—'}
              />
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
                      <SceneRow key={s.scene} s={s} onClick={() => openSceneDrillin(s.scene)} />
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}

        {activeScene && (
          <div className="flex-1 overflow-y-auto p-5">
            {tracesLoading && <div className="text-slate-400 text-sm">加载中…</div>}
            {!tracesLoading && traces.length === 0 && (
              <div className="text-slate-500 text-sm">该场景暂无 trace 记录。</div>
            )}
            {!tracesLoading && traces.length > 0 && (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-400 uppercase border-b border-slate-700">
                    <th className="text-left py-2 px-2 font-medium">时间</th>
                    <th className="text-left py-2 px-2 font-medium">trace_id</th>
                    <th className="text-left py-2 px-2 font-medium">model</th>
                    <th className="text-right py-2 px-2 font-medium">tokens</th>
                    <th className="text-right py-2 px-2 font-medium">耗时</th>
                    <th className="text-center py-2 px-2 font-medium">反馈</th>
                    <th className="text-left py-2 px-2 font-medium">输入预览</th>
                  </tr>
                </thead>
                <tbody>
                  {traces.map(t => (
                    <TraceRow key={t.trace_id} t={t} onClick={() => openTraceDetail(t.trace_id)} />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Trace detail modal — second layer on top of dashboard */}
        {activeTraceId && (
          <TraceDetailModal
            loading={detailLoading}
            detail={detail}
            onClose={closeDetail}
          />
        )}
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

function SceneRow({ s, onClick }: { s: LlmSceneStats; onClick: () => void }) {
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
    <tr onClick={onClick} className="border-b border-slate-800 hover:bg-slate-800/60 cursor-pointer">
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

function TraceRow({ t, onClick }: { t: LlmTraceSummary; onClick: () => void }) {
  const feedbackBadge = t.accepted === null
    ? <span className="text-slate-600">—</span>
    : t.accepted
      ? <span className="text-emerald-400">✓</span>
      : <span className="text-red-400">✗</span>
  const time = t.created_at ? new Date(t.created_at).toLocaleString('zh-CN', { hour12: false }) : '—'
  return (
    <tr onClick={onClick} className="border-b border-slate-800 hover:bg-slate-800/60 cursor-pointer">
      <td className="py-2 px-2 text-slate-400 text-xs whitespace-nowrap">{time}</td>
      <td className="py-2 px-2 text-slate-300 font-mono text-[11px]">{t.trace_id.slice(0, 12)}…</td>
      <td className="py-2 px-2 text-slate-300 text-xs">{t.model ?? '—'}</td>
      <td className="py-2 px-2 text-right text-slate-400 text-xs">{t.tokens_in}/{t.tokens_out}</td>
      <td className="py-2 px-2 text-right text-slate-400 text-xs">{t.duration_ms}ms</td>
      <td className="py-2 px-2 text-center">{feedbackBadge}</td>
      <td className="py-2 px-2 text-slate-400 text-xs max-w-md truncate" title={t.input_preview ?? ''}>
        {t.input_preview ? t.input_preview.slice(0, 80) : '—'}
        {t.has_error && <span className="ml-2 text-red-400">⚠ 错误</span>}
      </td>
    </tr>
  )
}

function TraceDetailModal({
  loading, detail, onClose,
}: {
  loading: boolean
  detail: LlmTraceDetail | null
  onClose: () => void
}) {
  return (
    <div onClick={onClose} className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4">
      <div onClick={e => e.stopPropagation()} className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col">
        <header className="flex items-center justify-between p-4 border-b border-slate-700">
          <h3 className="text-sm font-semibold text-white">Trace 详情</h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-200 text-xl leading-none">✕</button>
        </header>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading && <div className="text-slate-400 text-sm">加载中…</div>}
          {!loading && detail && (
            <>
              <Field label="trace_id" value={detail.trace_id} mono />
              <Field label="scene" value={detail.scene} mono />
              <Field label="model" value={detail.model ?? '—'} />
              <Field label="prompt_template_id" value={detail.prompt_template_id ?? '—'} mono />
              <Field label="tokens" value={`${detail.tokens_in} in / ${detail.tokens_out} out · ${detail.duration_ms}ms`} />
              <Field
                label="feedback"
                value={detail.accepted === null
                  ? '未反馈'
                  : detail.accepted
                    ? `已接受${detail.edited_to ? '（含修改）' : ''}`
                    : '已拒绝'}
              />
              {detail.error && (
                <div>
                  <div className="text-[11px] text-red-400 uppercase tracking-wide mb-1">错误</div>
                  <pre className="bg-red-950/40 border border-red-900/60 rounded p-3 text-xs text-red-300 whitespace-pre-wrap">{detail.error}</pre>
                </div>
              )}
              <LongTextBlock label="完整输入 (messages JSON)" text={detail.input_text} />
              <LongTextBlock label="LLM 输出" text={detail.output_text} />
              {detail.edited_to && (
                <LongTextBlock label="用户最终采纳的版本 (edited_to)" text={detail.edited_to} highlight />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-3">
      <div className="text-[11px] text-slate-500 uppercase tracking-wide w-40 flex-shrink-0 pt-0.5">{label}</div>
      <div className={`text-sm text-slate-200 break-all ${mono ? 'font-mono text-xs' : ''}`}>{value}</div>
    </div>
  )
}

function LongTextBlock({ label, text, highlight = false }: { label: string; text: string | null; highlight?: boolean }) {
  if (!text) return null
  const ringClass = highlight ? 'border-emerald-700/60 bg-emerald-950/30' : 'border-slate-700 bg-slate-800/60'
  return (
    <div>
      <div className="text-[11px] text-slate-500 uppercase tracking-wide mb-1">{label}</div>
      <pre className={`border rounded p-3 text-xs text-slate-300 whitespace-pre-wrap max-h-64 overflow-y-auto ${ringClass}`}>{text}</pre>
    </div>
  )
}
