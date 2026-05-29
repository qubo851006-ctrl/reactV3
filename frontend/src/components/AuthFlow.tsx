import { useEffect, useRef, useState } from 'react'
import {
  type AuthGeneratedDoc,
  type AuthUserInputs,
  downloadDocx,
  generateAuthRequestDocx,
  getBackgroundTask,
  getErrorMessage,
  previewAuthRequest,
  recordAuthRequestLedgerV2,
  startAuthRequestExtractTask,
} from '../api'
import { useNotifier } from './NotificationContext'

function sleep(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function downloadXlsx(base64: string, filename: string) {
  const bytes = atob(base64)
  const arr = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
  const blob = new Blob([arr], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function friendlyError(error: unknown, fallback: string) {
  let message = getErrorMessage(error, fallback)
  try {
    const json = JSON.parse(message) as { detail?: unknown }
    if (typeof json.detail === 'string') message = json.detail
  } catch {
    // keep original message
  }
  return message
}

interface Props {
  onComplete: (reply: string) => void
  onCancel: () => void
  visionModel?: string
}

type Step = 'upload' | 'review' | 'preview' | 'done'

type ExtractedFields = Record<string, Record<string, string | null | undefined>>

interface ExtractTaskResult {
  extracted: ExtractedFields
}

const fieldGroups = [
  {
    title: '依据文件',
    key: 'attachment1',
    fields: [
      ['title', '文件标题'],
      ['document_no', '发文字号'],
      ['project_name', '项目名称'],
      ['undertaking_unit', '前期工作单位'],
      ['undertaking_short', '单位简称'],
    ],
  },
  {
    title: '授权委托书',
    key: 'attachment2',
    fields: [
      ['authorization_no', '授权编号'],
      ['principal_unit', '委托单位'],
      ['legal_representative', '授权人'],
      ['trustee_name', '代理人'],
      ['trustee_work_unit', '代理人工作单位'],
      ['trustee_position', '代理人职务'],
      ['permission_type', '权限类型'],
      ['permission_detail', '具体权限'],
      ['authorization_term', '授权期限'],
    ],
  },
] as const

export default function AuthFlow({ onComplete, onCancel, visionModel = '' }: Props) {
  const { notifySuccess, notifyError } = useNotifier()
  const [attachment1, setAttachment1] = useState<File | null>(null)
  const [attachment2, setAttachment2] = useState<File | null>(null)
  const [step, setStep] = useState<Step>('upload')
  const [processing, setProcessing] = useState(false)
  const [taskId, setTaskId] = useState('')
  const [taskProgress, setTaskProgress] = useState(0)
  const [taskMessage, setTaskMessage] = useState('')
  const [error, setError] = useState('')
  const [extracted, setExtracted] = useState<ExtractedFields | null>(null)
  const [content, setContent] = useState('')
  const [generated, setGenerated] = useState<AuthGeneratedDoc | null>(null)
  const [ledgerBase64, setLedgerBase64] = useState<string | null>(null)
  const [ledgerFilename, setLedgerFilename] = useState<string | null>(null)
  const [recordingLedger, setRecordingLedger] = useState(false)
  const [dragTarget, setDragTarget] = useState<'basis' | 'auth' | null>(null)
  const [inputs, setInputs] = useState<AuthUserInputs>({
    auth_mode: 'direct',
    transfer_subject: '',
    copies: '',
    seal: '',
    handler: '',
  })
  const input1Ref = useRef<HTMLInputElement>(null)
  const input2Ref = useRef<HTMLInputElement>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  async function waitForTask(id: string) {
    while (mountedRef.current) {
      const task = await getBackgroundTask<ExtractTaskResult>(id)
      if (!mountedRef.current) return
      setTaskProgress(task.progress ?? 0)
      setTaskMessage(task.message || '正在处理附件')
      if (task.status === 'succeeded') {
        if (!task.result?.extracted) throw new Error('任务完成，但没有返回提取结果')
        setExtracted(task.result.extracted)
        setStep('review')
        notifySuccess('授权字段提取完成', '请补充授权方式、份数、印章等信息。')
        return
      }
      if (task.status === 'failed' || task.status === 'cancelled') {
        throw new Error(task.error || task.message || '处理失败')
      }
      await sleep(1000)
    }
  }

  async function handleExtract() {
    if (!attachment1 || !attachment2) return
    setProcessing(true)
    setError('')
    setTaskId('')
    setTaskProgress(0)
    setTaskMessage('正在提交提取任务')
    try {
      const started = await startAuthRequestExtractTask(attachment1, attachment2, visionModel)
      setTaskId(started.task_id)
      await waitForTask(started.task_id)
    } catch (e: unknown) {
      const message = friendlyError(e, '字段提取失败')
      setError(message)
      notifyError('授权字段提取失败', message)
    } finally {
      if (mountedRef.current) setProcessing(false)
    }
  }

  async function handlePreview() {
    if (!extracted) return
    setProcessing(true)
    setError('')
    try {
      const res = await previewAuthRequest(extracted, inputs)
      setContent(res.content)
      setStep('preview')
    } catch (e: unknown) {
      const message = friendlyError(e, '正文生成失败')
      setError(message)
      notifyError('正文生成失败', message)
    } finally {
      setProcessing(false)
    }
  }

  async function handleGenerate() {
    if (!extracted || !content) return
    setProcessing(true)
    setError('')
    try {
      const doc = await generateAuthRequestDocx(extracted, inputs, content)
      setGenerated(doc)
      setStep('done')
      notifySuccess('授权请示已生成', '请下载 DOCX，下载动作触发后系统会写入授权台账。')
    } catch (e: unknown) {
      const message = friendlyError(e, 'DOCX 生成失败')
      setError(message)
      notifyError('DOCX 生成失败', message)
    } finally {
      setProcessing(false)
    }
  }

  async function handleDownloadAndLedger() {
    if (!generated || !extracted) return
    downloadDocx(generated.docx_base64, generated.filename)
    if (generated.ledger_updated || recordingLedger) return
    setRecordingLedger(true)
    setError('')
    try {
      const ledger = await recordAuthRequestLedgerV2(extracted, inputs, generated.title)
      setGenerated({ ...generated, ledger_updated: ledger.ledger_updated })
      setLedgerBase64(ledger.ledger_base64)
      setLedgerFilename(ledger.ledger_filename)
      notifySuccess('授权台账已记录', '请示下载已触发，授权委托台账已更新。')
    } catch (e: unknown) {
      const message = friendlyError(e, '台账记录失败')
      setError(message)
      notifyError('授权台账记录失败', message)
    } finally {
      setRecordingLedger(false)
    }
  }

  function updateInput<K extends keyof AuthUserInputs>(key: K, value: AuthUserInputs[K]) {
    setInputs(prev => ({ ...prev, [key]: value }))
  }

  const canExtract = Boolean(attachment1 && attachment2 && !processing)
  const canPreview = Boolean(extracted && inputs.copies.trim() && inputs.seal.trim() && inputs.handler.trim() && (inputs.auth_mode === 'direct' || inputs.transfer_subject.trim()))

  if (processing && step === 'upload') {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="flex items-center gap-3 text-slate-300 mb-3">
          <div className="animate-spin w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full" />
          <div>
            <div className="text-sm">{taskMessage || '正在提取材料字段'}</div>
            <div className="text-xs text-slate-500 mt-0.5">依据文件 / 授权委托书 / OCR 兜底</div>
          </div>
        </div>
        <div className="h-2 rounded-full bg-slate-700 overflow-hidden">
          <div className="h-full rounded-full bg-indigo-500 transition-all duration-300" style={{ width: `${Math.max(5, taskProgress)}%` }} />
        </div>
        <div className="flex items-center justify-between text-[11px] text-slate-500 mt-1">
          <span>{taskId ? `任务编号：${taskId}` : '任务提交中'}</span>
          <span>{taskProgress}%</span>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
      <div className="flex items-center justify-between gap-3 mb-5">
        <div>
          <div className="text-sm font-semibold text-slate-200">授权请示起草</div>
          <div className="text-xs text-slate-500 mt-0.5">材料提取、人工补填、正文确认、下载后自动写台账</div>
        </div>
        <div className="text-xs text-slate-500">步骤 {step === 'upload' ? 1 : step === 'review' ? 2 : step === 'preview' ? 3 : 4}/4</div>
      </div>

      {error && <div className="text-red-400 text-sm mb-3">✕ {error}</div>}

      {step === 'upload' && (
        <>
          <div className="grid md:grid-cols-2 gap-3 mb-4">
            <button
              type="button"
              onClick={() => input1Ref.current?.click()}
              onDragOver={e => { e.preventDefault(); setDragTarget('basis') }}
              onDragLeave={() => setDragTarget(null)}
              onDrop={e => {
                e.preventDefault()
                setDragTarget(null)
                const file = e.dataTransfer.files?.[0]
                if (file) setAttachment1(file)
              }}
              className={`text-left border border-dashed rounded-xl p-4 transition-colors ${dragTarget === 'basis' ? 'border-indigo-400 bg-indigo-500/10' : 'border-slate-600 hover:border-slate-500'}`}
            >
              <input ref={input1Ref} type="file" accept=".pdf" className="hidden" onChange={e => e.target.files?.[0] && setAttachment1(e.target.files[0])} />
              <div className="text-sm text-slate-300">依据文件 PDF</div>
              <div className="text-xs text-slate-500 mt-2 truncate">{attachment1 ? attachment1.name : '点击选择或拖拽 PDF'}</div>
            </button>
            <button
              type="button"
              onClick={() => input2Ref.current?.click()}
              onDragOver={e => { e.preventDefault(); setDragTarget('auth') }}
              onDragLeave={() => setDragTarget(null)}
              onDrop={e => {
                e.preventDefault()
                setDragTarget(null)
                const file = e.dataTransfer.files?.[0]
                if (file) setAttachment2(file)
              }}
              className={`text-left border border-dashed rounded-xl p-4 transition-colors ${dragTarget === 'auth' ? 'border-indigo-400 bg-indigo-500/10' : 'border-slate-600 hover:border-slate-500'}`}
            >
              <input ref={input2Ref} type="file" accept=".pdf,.doc,.docx" className="hidden" onChange={e => e.target.files?.[0] && setAttachment2(e.target.files[0])} />
              <div className="text-sm text-slate-300">授权委托书</div>
              <div className="text-xs text-slate-500 mt-2 truncate">{attachment2 ? attachment2.name : '点击选择或拖拽 PDF / DOC / DOCX'}</div>
            </button>
          </div>
          <div className="flex gap-2">
            <button onClick={handleExtract} disabled={!canExtract} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors">
              开始提取
            </button>
            <button onClick={onCancel} className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors">取消</button>
          </div>
        </>
      )}

      {step === 'review' && extracted && (
        <>
          <div className="grid lg:grid-cols-2 gap-4 mb-5">
            {fieldGroups.map(group => (
              <div key={group.key} className="bg-slate-900/50 rounded-xl p-4">
                <div className="text-sm font-medium text-slate-200 mb-3">{group.title}提取结果</div>
                <div className="space-y-2">
                  {group.fields.map(([key, label]) => (
                    <div key={key} className="grid grid-cols-[96px_1fr] gap-2 text-xs">
                      <div className="text-slate-500">{label}</div>
                      <div className="text-slate-300 break-words">{extracted[group.key]?.[key] || <span className="text-amber-400">未提取到</span>}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="bg-slate-900/50 rounded-xl p-4 mb-4">
            <div className="text-sm font-medium text-slate-200 mb-3">请补充生成信息</div>
            <div className="grid md:grid-cols-2 gap-3">
              <label className="text-xs text-slate-400">
                授权方式
                <select
                  value={inputs.auth_mode}
                  onChange={e => updateInput('auth_mode', e.target.value as AuthUserInputs['auth_mode'])}
                  className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200"
                >
                  <option value="direct">直接授权</option>
                  <option value="transfer">转授权</option>
                </select>
              </label>
              <label className="text-xs text-slate-400">
                转授权委托主体
                <input
                  value={inputs.transfer_subject}
                  onChange={e => updateInput('transfer_subject', e.target.value)}
                  disabled={inputs.auth_mode === 'direct'}
                  placeholder={inputs.auth_mode === 'transfer' ? '例如：国航股份' : '直接授权无需填写'}
                  className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
                />
              </label>
              <label className="text-xs text-slate-400">
                经办人
                <input value={inputs.handler} onChange={e => updateInput('handler', e.target.value)} className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200" />
              </label>
              <label className="text-xs text-slate-400">
                授权办理份数
                <input value={inputs.copies} onChange={e => updateInput('copies', e.target.value)} placeholder="例如：建开公司3份；国航股份1份" className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200" />
              </label>
              <label className="text-xs text-slate-400 md:col-span-2">
                办理授权使用的章
                <input value={inputs.seal} onChange={e => updateInput('seal', e.target.value)} placeholder="例如：建开公章及法定代表人签字章" className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200" />
              </label>
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={handlePreview} disabled={!canPreview || processing} className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors">
              {processing ? '生成中…' : '生成正文预览'}
            </button>
            <button onClick={() => setStep('upload')} className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors">返回</button>
          </div>
        </>
      )}

      {step === 'preview' && (
        <>
          <div className="bg-slate-950/70 border border-slate-700 rounded-xl p-4 max-h-96 overflow-y-auto mb-4">
            <pre className="text-sm leading-7 text-slate-200 whitespace-pre-wrap font-sans">{content}</pre>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={handleGenerate} disabled={processing} className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors">
              {processing ? '生成中…' : '确认生成 DOCX'}
            </button>
            <button onClick={() => setStep('review')} className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors">返回修改</button>
          </div>
        </>
      )}

      {step === 'done' && generated && (
        <>
          <div className="text-green-400 font-medium mb-4">
            ✓ 授权请示已生成
            {generated.ledger_updated && <span className="ml-2 text-xs text-slate-400">（已记录台账）</span>}
          </div>
          <div className="bg-slate-950/70 border border-slate-700 rounded-xl p-4 max-h-72 overflow-y-auto mb-4">
            <pre className="text-sm leading-7 text-slate-200 whitespace-pre-wrap font-sans">{generated.content}</pre>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={handleDownloadAndLedger} disabled={recordingLedger} className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors">
              {recordingLedger ? '写入台账中…' : '下载请示并写入台账'}
            </button>
            {ledgerBase64 && ledgerFilename && (
              <button onClick={() => downloadXlsx(ledgerBase64, ledgerFilename)} className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white text-sm rounded-lg transition-colors">
                下载授权台账
              </button>
            )}
            <button onClick={() => onComplete(`✅ 授权请示已生成：${generated.filename}`)} className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors">
              完成
            </button>
          </div>
        </>
      )}
    </div>
  )
}
