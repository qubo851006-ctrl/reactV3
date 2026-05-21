import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  downloadComplianceLedger,
  getBackgroundTask,
  getComplianceResponsiblePersons,
  getErrorMessage,
  startComplianceExtractTask,
  submitLlmFeedback,
  updateComplianceResponsiblePersons,
  writeComplianceLedger,
  type ComplianceItem,
  type ComplianceReviewRow,
} from '../api'
import { useNotifier } from './NotificationContext'

interface Props {
  onComplete: (reply: string) => void
  onCancel: () => void
  visionModel?: string
  canManageResponsiblePersons?: boolean
}

type Step = 'upload' | 'processing' | 'review' | 'done'
type Opinion = ComplianceReviewRow['review_opinion']
type Implementation = ComplianceReviewRow['implementation']

function sleep(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

const OPINIONS: Opinion[] = ['同意', '不予同意', '建议补充完善']
const IMPLEMENTATIONS: Implementation[] = ['/', '已按要求补充完善', '未见落实', '不涉及']

const EMPTY_ROW: ComplianceReviewRow = {
  review_time: '',
  review_unit: '会签单位',
  review_opinion: '同意',
  detail: '/',
  implementation: '/',
}

export default function ComplianceFlow({
  onComplete,
  onCancel,
  visionModel = '',
  canManageResponsiblePersons = false,
}: Props) {
  const { notifySuccess, notifyError } = useNotifier()
  const [step, setStep] = useState<Step>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [drag, setDrag] = useState(false)
  const [item, setItem] = useState<ComplianceItem | null>(null)
  const [originalItem, setOriginalItem] = useState<ComplianceItem | null>(null)
  const [traceIds, setTraceIds] = useState<string[]>([])
  const [error, setError] = useState('')
  const [writing, setWriting] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [taskId, setTaskId] = useState('')
  const [taskProgress, setTaskProgress] = useState(0)
  const [taskMessage, setTaskMessage] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  function applyExtractResult(result: ComplianceItem, llmTraceIds: string[]) {
    const normalised: ComplianceItem = {
      ...result,
      undertaking_department: result.undertaking_department || '法务合规部',
      background_materials: result.background_materials ?? [],
      review_rows: result.review_rows?.length ? result.review_rows : [{ ...EMPTY_ROW }],
    }
    setItem(normalised)
    setOriginalItem(normalised)
    setTraceIds(llmTraceIds)
    setStep('review')
    notifySuccess('合规审查台账提取完成', '已生成预览结果，请核对后写入累计台账。')
  }

  async function waitForTask(id: string) {
    while (mountedRef.current) {
      const task = await getBackgroundTask<{ item: ComplianceItem; llm_trace_ids?: string[] }>(id)
      if (!mountedRef.current) return
      setTaskProgress(task.progress ?? 0)
      setTaskMessage(task.message || '后台任务处理中')

      if (task.status === 'succeeded') {
        if (!task.result?.item) throw new Error('任务完成，但没有返回合规审查预览数据')
        applyExtractResult(task.result.item, task.result.llm_trace_ids ?? [])
        return
      }
      if (task.status === 'failed' || task.status === 'cancelled') {
        throw new Error(task.error || task.message || '提取失败')
      }
      await sleep(1000)
    }
  }

  async function handleExtract() {
    if (!file) return
    setStep('processing')
    setError('')
    setTaskId('')
    setTaskProgress(0)
    setTaskMessage('正在提交识别任务')
    try {
      const started = await startComplianceExtractTask(file, visionModel)
      setTaskId(started.task_id)
      await waitForTask(started.task_id)
    } catch (e: unknown) {
      let message = getErrorMessage(e, '提取失败')
      try {
        const json = JSON.parse(message) as { detail?: unknown }
        message = typeof json.detail === 'string' ? json.detail : message
      } catch { /* keep original */ }
      setError(message)
      setStep('upload')
      notifyError('合规审查台账提取失败', message)
    }
  }

  async function handleWrite() {
    if (!item) return
    setWriting(true)
    setError('')
    try {
      const res = await writeComplianceLedger(item)
      setStep('done')
      const wasEdited = originalItem !== null
        && JSON.stringify(item) !== JSON.stringify(originalItem)
      submitLlmFeedback(traceIds, true, wasEdited ? item : null)
      notifySuccess('合规审查台账写入完成', '累计台账已更新，可以直接下载查看。')
      onComplete(res.reply)
    } catch (e: unknown) {
      const message = getErrorMessage(e, '写入失败')
      setError(message)
      notifyError('合规审查台账写入失败', message)
    } finally {
      setWriting(false)
    }
  }

  function handleCancel() {
    if (traceIds.length > 0) submitLlmFeedback(traceIds, false, null)
    onCancel()
  }

  function setField<K extends keyof ComplianceItem>(key: K, value: ComplianceItem[K]) {
    setItem(prev => prev ? { ...prev, [key]: value } : prev)
  }

  function setRow(index: number, patch: Partial<ComplianceReviewRow>) {
    setItem(prev => {
      if (!prev) return prev
      const rows = prev.review_rows.map((row, i) => i === index ? { ...row, ...patch } : row)
      return { ...prev, review_rows: rows }
    })
  }

  function addRow() {
    setItem(prev => prev ? { ...prev, review_rows: [...prev.review_rows, { ...EMPTY_ROW }] } : prev)
  }

  function removeRow(index: number) {
    setItem(prev => {
      if (!prev || prev.review_rows.length <= 1) return prev
      return { ...prev, review_rows: prev.review_rows.filter((_, i) => i !== index) }
    })
  }

  if (step === 'processing') {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="flex items-center gap-3 text-slate-300 mb-3">
          <div className="animate-spin w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full" />
          <div>
            <div className="text-sm">{taskMessage || '正在提取合规审查台账信息'}</div>
            <div className="text-xs text-slate-500 mt-0.5">OA PDF 解析 / OCR / AI 抽取 / 生成预览</div>
          </div>
        </div>
        <div className="h-2 rounded-full bg-slate-700 overflow-hidden">
          <div
            className="h-full rounded-full bg-indigo-500 transition-all duration-300"
            style={{ width: `${Math.max(5, taskProgress)}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-[11px] text-slate-500 mt-1">
          <span>{taskId ? `任务编号：${taskId}` : '任务提交中'}</span>
          <span>{taskProgress}%</span>
        </div>
      </div>
    )
  }

  if (step === 'done') {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="text-green-400 font-medium mb-4">✅ 合规审查工作台账已更新</div>
        <button
          onClick={downloadComplianceLedger}
          className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition-colors"
        >
          📥 下载合规审查工作台账
        </button>
      </div>
    )
  }

  if (step === 'review' && item) {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5 my-3 max-w-5xl">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-sm font-semibold text-slate-200">请确认合规审查台账预览</div>
            <div className="text-xs text-slate-500 mt-0.5">确认后写入长期累计台账</div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={downloadComplianceLedger} className="text-xs text-emerald-300 hover:text-emerald-200">
              下载已有台账
            </button>
            <button onClick={() => setConfigOpen(true)} className="text-xs text-indigo-300 hover:text-indigo-200">
              部门负责人配置
            </button>
          </div>
        </div>

        {error && <div className="text-red-400 text-xs mb-3">{error}</div>}
        {item.warnings?.length ? (
          <div className="bg-amber-500/10 border border-amber-500/20 text-amber-200 text-xs rounded-lg px-3 py-2 mb-3">
            {item.warnings.join('；')}
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-3 mb-4">
          <Field label="重大事项">
            <textarea
              rows={3}
              value={item.title}
              onChange={e => setField('title', e.target.value)}
              className="field-textarea"
            />
          </Field>
          <Field label="程序">
            <select
              value={item.procedure}
              onChange={e => setField('procedure', e.target.value as ComplianceItem['procedure'])}
              className="field-input"
            >
              <option value="董事会审议">董事会审议</option>
              <option value="总办会审议">总办会审议</option>
            </select>
          </Field>
          <Field label="承办单位">
            <input
              value={item.undertaking_department}
              onChange={e => setField('undertaking_department', e.target.value)}
              className="field-input"
            />
          </Field>
          <Field label="背景材料">
            <textarea
              rows={3}
              value={item.background_materials.join('、')}
              onChange={e => setField('background_materials', e.target.value.split(/[、,，\n]/).map(x => x.trim()).filter(Boolean))}
              className="field-textarea"
            />
          </Field>
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-700 mb-4">
          <table className="w-full min-w-[920px] text-xs">
            <thead className="bg-slate-700/60 text-slate-400">
              <tr>
                <th className="px-2 py-2 text-left w-28">审查时间</th>
                <th className="px-2 py-2 text-left w-52">审查单位</th>
                <th className="px-2 py-2 text-left w-32">合规审查意见</th>
                <th className="px-2 py-2 text-left">具体意见描述</th>
                <th className="px-2 py-2 text-left w-36">落实情况</th>
                <th className="px-2 py-2 w-12"></th>
              </tr>
            </thead>
            <tbody>
              {item.review_rows.map((row, index) => (
                <tr key={index} className="border-t border-slate-700/60">
                  <td className="px-2 py-2 align-top">
                    <input value={row.review_time} onChange={e => setRow(index, { review_time: e.target.value })} className="table-input" />
                  </td>
                  <td className="px-2 py-2 align-top">
                    <input value={row.review_unit} onChange={e => setRow(index, { review_unit: e.target.value })} className="table-input" />
                  </td>
                  <td className="px-2 py-2 align-top">
                    <select value={row.review_opinion} onChange={e => setRow(index, { review_opinion: e.target.value as Opinion })} className="table-input">
                      {OPINIONS.map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </td>
                  <td className="px-2 py-2 align-top">
                    <textarea rows={2} value={row.detail} onChange={e => setRow(index, { detail: e.target.value })} className="table-textarea" />
                  </td>
                  <td className="px-2 py-2 align-top">
                    <select value={row.implementation} onChange={e => setRow(index, { implementation: e.target.value as Implementation })} className="table-input">
                      {IMPLEMENTATIONS.map(v => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </td>
                  <td className="px-2 py-2 align-top text-center">
                    <button onClick={() => removeRow(index)} className="text-slate-500 hover:text-red-400">删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap gap-2">
          <button onClick={addRow} className="px-3 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm rounded-lg">
            + 增加审查单位
          </button>
          <button
            onClick={handleWrite}
            disabled={writing}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm rounded-lg"
          >
            {writing ? '写入中…' : '确认写入累计台账'}
          </button>
          <button onClick={() => setStep('upload')} className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm">
            重新上传
          </button>
        </div>

        <ResponsiblePersonsPanel
          open={configOpen}
          canManage={canManageResponsiblePersons}
          onClose={() => setConfigOpen(false)}
        />
      </div>
    )
  }

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-medium text-slate-300">请上传 OA 流程表单及审批记录 PDF</div>
        <div className="flex items-center gap-3">
          <button onClick={downloadComplianceLedger} className="text-xs text-emerald-300 hover:text-emerald-200">
            下载已有台账
          </button>
          <button onClick={() => setConfigOpen(true)} className="text-xs text-indigo-300 hover:text-indigo-200">
            部门负责人配置
          </button>
        </div>
      </div>
      {error && <div className="text-red-400 text-sm mb-3">❌ {error}</div>}

      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) setFile(f) }}
        className={`border-2 border-dashed rounded-xl p-8 cursor-pointer text-center transition-all mb-4 ${
          drag ? 'border-indigo-400 bg-indigo-500/10' : file ? 'border-green-500/50 bg-green-500/5' : 'border-slate-600 hover:border-slate-500'
        }`}
      >
        <input ref={inputRef} type="file" accept=".pdf" className="hidden" onChange={e => e.target.files?.[0] && setFile(e.target.files[0])} />
        {file ? (
          <>
            <div className="text-green-400 text-2xl mb-2">✓</div>
            <div className="text-sm text-slate-300">{file.name}</div>
            <div className="text-xs text-slate-500 mt-1">{(file.size / 1024).toFixed(0)} KB</div>
          </>
        ) : (
          <>
            <div className="text-3xl mb-2">📄</div>
            <div className="text-sm text-slate-400">点击或拖拽上传 PDF</div>
            <div className="text-xs text-slate-500 mt-1">支持 OA 网页导出件，文本异常时自动走 OCR/视觉模型</div>
          </>
        )}
      </div>

      <div className="flex gap-2">
        <button onClick={handleExtract} disabled={!file} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg">
          开始提取
        </button>
        <button onClick={handleCancel} className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm">
          取消
        </button>
      </div>

      <ResponsiblePersonsPanel
        open={configOpen}
        canManage={canManageResponsiblePersons}
        onClose={() => setConfigOpen(false)}
      />
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <div className="text-xs text-slate-500 mb-1">{label}</div>
      {children}
    </label>
  )
}

function ResponsiblePersonsPanel({
  open,
  canManage,
  onClose,
}: {
  open: boolean
  canManage: boolean
  onClose: () => void
}) {
  const [persons, setPersons] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    getComplianceResponsiblePersons()
      .then(setPersons)
      .catch(() => setNotice('负责人配置加载失败'))
  }, [open])

  function updateDept(oldDept: string, newDept: string) {
    setPersons(prev => {
      const next: Record<string, string> = {}
      for (const [dept, person] of Object.entries(prev)) {
        next[dept === oldDept ? newDept : dept] = person
      }
      return next
    })
  }

  async function save() {
    setLoading(true)
    setNotice('')
    try {
      const saved = await updateComplianceResponsiblePersons(persons)
      setPersons(saved)
      setNotice('已保存')
    } catch (e: unknown) {
      setNotice(getErrorMessage(e, '保存失败'))
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed top-0 right-0 z-50 h-full w-[520px] max-w-full bg-slate-900 border-l border-slate-700/60 shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/60">
          <div>
            <div className="text-sm font-semibold text-white">部门负责人配置</div>
            <div className="text-xs text-slate-500 mt-0.5">{canManage ? '管理员可修改' : '当前仅可查看'}</div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300">×</button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {Object.entries(persons).map(([dept, person]) => (
            <div key={dept} className="grid grid-cols-[1fr_96px] gap-2">
              <input
                value={dept}
                disabled={!canManage}
                onChange={e => updateDept(dept, e.target.value)}
                className="field-input disabled:opacity-60"
              />
              <input
                value={person}
                disabled={!canManage}
                onChange={e => setPersons(prev => ({ ...prev, [dept]: e.target.value }))}
                className="field-input disabled:opacity-60"
              />
            </div>
          ))}
          {canManage && (
            <button onClick={() => setPersons(prev => ({ ...prev, 新部门: '' }))} className="mt-2 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm rounded-lg">
              + 新增部门
            </button>
          )}
        </div>

        {notice && <div className="px-5 py-2 text-xs text-slate-300">{notice}</div>}
        <div className="px-5 py-4 border-t border-slate-700/60 flex gap-2">
          {canManage && (
            <button onClick={save} disabled={loading} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm rounded-lg">
              {loading ? '保存中…' : '保存配置'}
            </button>
          )}
          <button onClick={onClose} className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm rounded-lg">
            关闭
          </button>
        </div>
      </div>
    </>
  )
}
