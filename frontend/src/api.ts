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

export async function extractComplianceLedger(pdfFile: File, visionModel: string): Promise<ComplianceItem> {
  const form = new FormData()
  form.append('pdf_file', pdfFile)
  form.append('vision_model', visionModel)
  const r = await apiFetch(`${BASE}/compliance/extract`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(await r.text())
  const d = await r.json() as { item: ComplianceItem }
  return d.item
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
