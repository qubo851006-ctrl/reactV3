import type { TrainingResult, LedgerPreview, LedgerCaseData, SessionMeta } from './types'
import type { ModelRoutes } from './modelOptions'

const BASE = '/api'

export function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

/** 当前 session ID，由 App.tsx 在切换/新建时更新 */
let _sid = ''
export function setCurrentSessionId(id: string) { _sid = id }
export function getCurrentSessionId() { return _sid }

/** 统一 fetch 封装：自动带 Cookie，401/403 派发全局登出事件 */
async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(url, { ...init, credentials: 'include' })
  if (r.status === 401 || r.status === 403) {
    window.dispatchEvent(new Event('auth:unauthorized'))
    throw new Error('unauthorized')
  }
  return r
}

// ── Session 管理 ──────────────────────────────────────────────

export async function getSessions(): Promise<SessionMeta[]> {
  const r = await apiFetch(`${BASE}/chat/sessions`)
  const d = await r.json()
  return d.sessions ?? []
}

export async function createSession(): Promise<{ session_id: string; title: string }> {
  const r = await apiFetch(`${BASE}/chat/sessions`, { method: 'POST' })
  return r.json()
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiFetch(`${BASE}/chat/sessions/${sessionId}`, { method: 'DELETE' })
}

export async function renameSession(sessionId: string, title: string): Promise<void> {
  await apiFetch(`${BASE}/chat/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
}

export async function getHistory(sessionId: string) {
  const r = await apiFetch(`${BASE}/chat/history?session_id=${encodeURIComponent(sessionId)}`)
  return r.json()
}

export async function clearHistory(sessionId: string) {
  await apiFetch(`${BASE}/chat/history?session_id=${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

export async function getModelRoutes(): Promise<ModelRoutes> {
  const r = await apiFetch(`${BASE}/model-routes`)
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function sendChat(
  message: string,
  useKb: boolean,
  kbConvId: string,
  model: string,
  visionModel: string,
  onChunk: (text: string) => void,
): Promise<{ reply: string; next_stage: string; kb_conversation_id: string }> {
  const resp = await apiFetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      use_kb: useKb,
      kb_conversation_id: kbConvId,
      session_id: _sid,
      model,
      vision_model: visionModel,
    }),
  })
  if (!resp.ok) throw new Error(await resp.text())

  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result = { reply: '', next_stage: 'idle', kb_conversation_id: '' }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()!
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6))
        if (data.type === 'chunk') onChunk(data.text)
        else if (data.type === 'done') result = {
          reply: data.reply ?? '',
          next_stage: data.next_stage ?? 'idle',
          kb_conversation_id: data.kb_conversation_id ?? '',
        }
      } catch { /* ignore malformed */ }
    }
  }
  return result
}

// ── 培训统计 ──────────────────────────────────────────────────

export async function extractTraining(
  noticePdf: File,
  signinImg: File,
  department: string,
  visionModel: string,
): Promise<TrainingResult> {
  const form = new FormData()
  form.append('notice_pdf', noticePdf)
  form.append('signin_img', signinImg)
  form.append('department', department)
  form.append('vision_model', visionModel)
  const r = await apiFetch(`${BASE}/training/extract`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function writeTraining(data: Omit<TrainingResult, 'excel_path' | 'confidence' | 'reflection_note'>) {
  const r = await apiFetch(`${BASE}/training/write`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...data, session_id: _sid }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export function downloadTrainingExcel() {
  window.open(`${BASE}/training/download-excel`, '_blank')
}

// ── 案件台账 ──────────────────────────────────────────────────

export async function extractLedger(
  files: File[],
  visionModel: string,
  onLog: (log: string) => void,
): Promise<LedgerPreview> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  form.append('vision_model', visionModel)

  const resp = await apiFetch(`${BASE}/ledger/extract`, { method: 'POST', body: form })
  if (!resp.ok) throw new Error(await resp.text())

  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let previewData: LedgerPreview | null = null
  let streamError = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()!
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6)) as Partial<LedgerPreview> & {
          log?: string
          error?: string
          preview?: boolean
        }
        if (typeof data.log === 'string') onLog(data.log)
        if (typeof data.error === 'string') streamError = data.error
        if (data.preview && data.case_data) previewData = data as LedgerPreview
      } catch { /* ignore */ }
    }
  }
  if (streamError) throw new Error(streamError)
  if (!previewData) throw new Error('未收到案件预览数据')
  return previewData
}

export async function writeLedger(
  caseData: LedgerCaseData,
  matchIdx: number | null,
  archiveDir: string,
  pendingArchiveId = '',
  existingArchiveName = '',
): Promise<{ ok: boolean; case_count: number; reply: string; archive_dir: string }> {
  const r = await apiFetch(`${BASE}/ledger/write`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      case_data: caseData,
      match_idx: matchIdx,
      archive_dir: archiveDir,
      existing_archive_name: existingArchiveName,
      pending_archive_id: pendingArchiveId,
      session_id: _sid,
    }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function clearLedger() {
  const r = await apiFetch(`${BASE}/ledger/clear`, { method: 'POST' })
  return r.json()
}

export function downloadLedgerExcel() {
  window.open(`${BASE}/ledger/download-excel`, '_blank')
}

// ── 合规审查工作台账 ───────────────────────────────────────────

export interface ComplianceReviewRow {
  review_time: string
  review_unit: string
  review_opinion: '同意' | '不予同意' | '建议补充完善'
  detail: string
  implementation: '/' | '已按要求补充完善' | '未见落实' | '不涉及'
}

export interface ComplianceItem {
  title: string
  procedure: '董事会审议' | '总办会审议'
  undertaking_department: string
  background_materials: string[]
  review_rows: ComplianceReviewRow[]
  warnings?: string[]
}

export async function extractComplianceLedger(
  pdfFile: File,
  visionModel: string,
): Promise<{ item: ComplianceItem; llm_trace_ids: string[] }> {
  const form = new FormData()
  form.append('pdf_file', pdfFile)
  form.append('vision_model', visionModel)
  const r = await apiFetch(`${BASE}/compliance/extract`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(await r.text())
  const d = await r.json() as { item: ComplianceItem; llm_trace_ids?: string[] }
  return { item: d.item, llm_trace_ids: d.llm_trace_ids ?? [] }
}

export async function writeComplianceLedger(item: ComplianceItem): Promise<{ ok: boolean; count: number; sequence: number; reply: string }> {
  const r = await apiFetch(`${BASE}/compliance/write`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...item, session_id: _sid }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export function downloadComplianceLedger() {
  window.open(`${BASE}/compliance/download`, '_blank')
}

export async function getComplianceResponsiblePersons(): Promise<Record<string, string>> {
  const r = await apiFetch(`${BASE}/compliance/responsible-persons`)
  if (!r.ok) throw new Error(await r.text())
  const d = await r.json() as { persons: Record<string, string> }
  return d.persons
}

export async function updateComplianceResponsiblePersons(persons: Record<string, string>): Promise<Record<string, string>> {
  const r = await apiFetch(`${BASE}/compliance/responsible-persons`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ persons }),
  })
  if (!r.ok) throw new Error(await r.text())
  const d = await r.json() as { persons: Record<string, string> }
  return d.persons
}

// ── 三台账合并 ────────────────────────────────────────────────

export interface MergeStats {
  result_id?: string
  total_contract: number
  matched_purchase: number
  matched_finance: number
  fully_matched: number
  partial_matched: number
  unmatched: number
}

export type BackgroundTaskStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface BackgroundTask<T = unknown> {
  task_id: string
  type: string
  status: BackgroundTaskStatus
  progress: number
  message: string
  result: T | null
  error: string | null
  created_by: number | null
  created_at: string | null
  updated_at: string | null
  started_at: string | null
  finished_at: string | null
}

export async function mergeLedgers(
  contractFile: File,
  purchaseFile: File | null,
  financeFile: File | null,
): Promise<MergeStats> {
  const form = new FormData()
  form.append('contract_file', contractFile)
  if (purchaseFile) form.append('purchase_file', purchaseFile)
  if (financeFile) form.append('finance_file', financeFile)
  const r = await apiFetch(`${BASE}/ledger-merge/merge`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function startLedgerMergeTask(
  contractFile: File,
  purchaseFile: File | null,
  financeFile: File | null,
): Promise<{ ok: boolean; task_id: string }> {
  const form = new FormData()
  form.append('contract_file', contractFile)
  if (purchaseFile) form.append('purchase_file', purchaseFile)
  if (financeFile) form.append('finance_file', financeFile)
  const r = await apiFetch(`${BASE}/ledger-merge/merge-task`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function getBackgroundTask<T = unknown>(taskId: string): Promise<BackgroundTask<T>> {
  const r = await apiFetch(`${BASE}/tasks/${encodeURIComponent(taskId)}`)
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export function downloadMergedExcel(resultId = '') {
  const suffix = resultId ? `?result_id=${encodeURIComponent(resultId)}` : ''
  window.open(`${BASE}/ledger-merge/download${suffix}`, '_blank')
}

// ── 审计分析 ──────────────────────────────────────────────────

export interface AuditRow {
  seq: number
  issue: string
  description: string
  category_l1: string
  category_l2: string
  domain: string
  disagreement?: {           // B 模型的修正建议，undefined 表示 A/B 一致
    category_l1: string
    category_l2: string
    domain: string
  }
}

export interface AuditAnalysisResult {
  rows: AuditRow[]
  total: number
  /** trace ids from the audit DB, for P1-2 feedback */
  llm_trace_ids?: string[]
}

export async function analyzeAudit(
  file: File,
  domains: string[],
): Promise<AuditAnalysisResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('domains', JSON.stringify(domains))
  const r = await apiFetch(`${BASE}/audit/analyze`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function downloadAuditExcel(rows: AuditRow[], originalFilename: string) {
  const r = await apiFetch(`${BASE}/audit/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows, original_filename: originalFilename }),
  })
  if (!r.ok) throw new Error(await r.text())
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${originalFilename}_分类结果.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}

// ── 授权请示 ──────────────────────────────────────────────────

export async function processAuthRequest(pdfFile: File, visionModel: string) {
  const form = new FormData()
  form.append('pdf_file', pdfFile)
  form.append('session_id', _sid)
  form.append('vision_model', visionModel)
  const r = await apiFetch(`${BASE}/auth-request/process`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function recordAuthRequestLedger(info: unknown, title: string) {
  const r = await apiFetch(`${BASE}/auth-request/record-ledger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ info, title, session_id: _sid }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export function downloadDocx(base64: string, filename: string) {
  const bytes = atob(base64)
  const arr = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
  const blob = new Blob([arr], {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── LLM 调用反馈（P1-2 反馈学习闭环） ──────────────────────────

/**
 * Tell the audit DB whether the user kept the LLM's extracted output
 * and what they changed it to. Drives the few-shot learning loop.
 *
 * Fail-quietly: feedback is a quality booster, not core flow — a network
 * error here should not surface to the user.
 */
export async function submitLlmFeedback(
  traceIds: string[],
  accepted: boolean,
  editedTo: unknown | null = null,
): Promise<void> {
  if (!traceIds || traceIds.length === 0) return
  const editedPayload = editedTo === null
    ? null
    : (typeof editedTo === 'string' ? editedTo : JSON.stringify(editedTo, null, 2))
  await Promise.allSettled(traceIds.map(traceId =>
    apiFetch(`${BASE}/llm-traces/${encodeURIComponent(traceId)}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ accepted, edited_to: editedPayload }),
    }).catch(() => { /* swallow — feedback must not break the flow */ })
  ))
}

// ── LLM 追溯仪表盘 (admin) ────────────────────────────────────────

export interface LlmSceneStats {
  scene: string
  total: number
  feedback_count: number
  accepted_count: number
  edited_count: number
  error_count: number
  acceptance_rate: number | null
  edit_rate: number | null
  avg_tokens_in: number
  avg_tokens_out: number
  avg_duration_ms: number
}

export async function getLlmSceneStats(): Promise<LlmSceneStats[]> {
  const r = await apiFetch(`${BASE}/llm-traces/scenes/stats`)
  if (!r.ok) throw new Error(await r.text())
  const d = await r.json() as { scenes: LlmSceneStats[] }
  return d.scenes ?? []
}

export interface LlmTraceSummary {
  trace_id: string
  scene: string
  model: string | null
  prompt_template_id: string | null
  tokens_in: number
  tokens_out: number
  duration_ms: number
  user_id: number | null
  session_id: string | null
  input_preview: string | null
  accepted: boolean | null
  has_error: boolean
  created_at: string | null
}

export interface LlmTraceDetail extends LlmTraceSummary {
  input_text: string | null
  output_text: string | null
  input_hash: string
  edited_to: string | null
  error: string | null
}

export async function listLlmTraces(params: {
  scene?: string
  hasError?: boolean
  limit?: number
} = {}): Promise<LlmTraceSummary[]> {
  const qs = new URLSearchParams()
  if (params.scene) qs.set('scene', params.scene)
  if (params.hasError !== undefined) qs.set('has_error', String(params.hasError))
  qs.set('limit', String(params.limit ?? 20))
  const r = await apiFetch(`${BASE}/llm-traces?${qs.toString()}`)
  if (!r.ok) throw new Error(await r.text())
  const d = await r.json() as { traces: LlmTraceSummary[] }
  return d.traces ?? []
}

export async function getLlmTraceDetail(traceId: string): Promise<LlmTraceDetail> {
  const r = await apiFetch(`${BASE}/llm-traces/${encodeURIComponent(traceId)}`)
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}
