import { useEffect, useState, useRef } from 'react'
import { getBackgroundTask, startAuthRequestProcessTask, recordAuthRequestLedger, downloadDocx, getErrorMessage, submitLlmFeedback } from '../api'
import { useNotifier } from './NotificationContext'

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
import ReactMarkdown from 'react-markdown'

function sleep(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

interface Props {
  onComplete: (reply: string) => void
  onCancel: () => void
  visionModel?: string
}

interface AuthResult {
  content: string
  docx_base64: string
  filename: string
  letter_content: string
  letter_base64: string
  letter_filename: string
  ledger_updated: boolean
  ledger_base64: string | null
  ledger_filename: string | null
  title: string
  info: unknown
  llm_trace_ids?: string[]
}

export default function AuthFlow({ onComplete, onCancel, visionModel = '' }: Props) {
  const { notifySuccess, notifyError } = useNotifier()
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [processing, setProcessing] = useState(false)
  const [result, setResult] = useState<AuthResult | null>(null)
  const [error, setError] = useState('')
  const [drag, setDrag] = useState(false)
  const [activeTab, setActiveTab] = useState<'request' | 'letter'>('request')
  const [recordingLedger, setRecordingLedger] = useState(false)
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

  async function waitForTask(id: string) {
    while (mountedRef.current) {
      const task = await getBackgroundTask<AuthResult>(id)
      if (!mountedRef.current) return
      setTaskProgress(task.progress ?? 0)
      setTaskMessage(task.message || '???????')

      if (task.status === 'succeeded') {
        if (!task.result) throw new Error('????????????????')
        setResult(task.result)
        notifySuccess('????????', '????????????????????')
        return
      }
      if (task.status === 'failed' || task.status === 'cancelled') {
        throw new Error(task.error || task.message || '????')
      }
      await sleep(1000)
    }
  }

  async function handleProcess() {
    if (!pdfFile) return
    setProcessing(true)
    setError('')
    setTaskId('')
    setTaskProgress(0)
    setTaskMessage('????????')
    try {
      const started = await startAuthRequestProcessTask(pdfFile, visionModel)
      setTaskId(started.task_id)
      await waitForTask(started.task_id)
    } catch (e: unknown) {
      let message = getErrorMessage(e, '????')
      try {
        const json = JSON.parse(message) as { detail?: unknown }
        message = typeof json.detail === 'string' ? json.detail : message
      } catch { /* keep original */ }
      setError(message)
      notifyError('????????', message)
    } finally {
      if (mountedRef.current) setProcessing(false)
    }
  }

  async function handleRecordLedger() {
    if (!result) return
    setRecordingLedger(true)
    setError('')
    try {
      const ledger = await recordAuthRequestLedger(result.info, result.title)
      setResult({
        ...result,
        ledger_updated: ledger.ledger_updated,
        ledger_base64: ledger.ledger_base64,
        ledger_filename: ledger.ledger_filename,
      })
      notifySuccess('授权台账记录完成', '授权委托台账已更新，可以下载查看。')
    } catch (e: unknown) {
      const message = getErrorMessage(e, '台账记录失败')
      setError(message)
      notifyError('授权台账记录失败', message)
    } finally {
      setRecordingLedger(false)
    }
  }

  if (processing && !result) {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="flex items-center gap-3 text-slate-300 mb-3">
          <div className="animate-spin w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full" />
          <div>
            <div className="text-sm">{taskMessage || '????????????'}</div>
            <div className="text-xs text-slate-500 mt-0.5">???? / AI ?? / ?? Word ??</div>
          </div>
        </div>
        <div className="h-2 rounded-full bg-slate-700 overflow-hidden">
          <div
            className="h-full rounded-full bg-indigo-500 transition-all duration-300"
            style={{ width: `${Math.max(5, taskProgress)}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-[11px] text-slate-500 mt-1">
          <span>{taskId ? `?????${taskId}` : '?????'}</span>
          <span>{taskProgress}%</span>
        </div>
      </div>
    )
  }

  if (result) {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="text-green-400 font-medium mb-4">
          ✅ 授权请示及授权书已生成
          {result.ledger_updated && (
            <span className="ml-2 text-xs text-slate-400">（已记录台账）</span>
          )}
        </div>
        {error && <div className="text-red-400 text-sm mb-3">❌ {error}</div>}

        {/* 标签切换 */}
        <div className="flex gap-1 mb-3 border-b border-slate-700">
          <button
            onClick={() => setActiveTab('request')}
            className={`px-3 py-1.5 text-sm rounded-t transition-colors ${
              activeTab === 'request'
                ? 'text-indigo-400 border-b-2 border-indigo-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            授权请示
          </button>
          <button
            onClick={() => setActiveTab('letter')}
            className={`px-3 py-1.5 text-sm rounded-t transition-colors ${
              activeTab === 'letter'
                ? 'text-indigo-400 border-b-2 border-indigo-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            授权书
          </button>
        </div>

        {/* 内容预览 */}
        <div className="bg-slate-900/60 rounded-xl p-4 max-h-80 overflow-y-auto mb-4">
          <div className="prose prose-sm prose-invert max-w-none prose-p:my-1">
            {activeTab === 'request' ? (
              <ReactMarkdown>{result.content}</ReactMarkdown>
            ) : (
              <pre className="text-xs text-slate-300 whitespace-pre-wrap font-sans">{result.letter_content}</pre>
            )}
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => downloadDocx(result.docx_base64, result.filename)}
            className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition-colors"
          >
            📥 下载授权请示
          </button>
          <button
            onClick={() => downloadDocx(result.letter_base64, result.letter_filename)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors"
          >
            📥 下载授权书
          </button>
          {!result.ledger_updated && (
            <button
              onClick={handleRecordLedger}
              disabled={recordingLedger}
              className="flex items-center gap-2 px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
            >
              {recordingLedger ? '记录中…' : '📊 记录授权台账'}
            </button>
          )}
          {result.ledger_updated && result.ledger_base64 && result.ledger_filename && (
            <button
              onClick={() => downloadXlsx(result.ledger_base64!, result.ledger_filename!)}
              className="flex items-center gap-2 px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white text-sm rounded-lg transition-colors"
            >
              📊 下载台账
            </button>
          )}
          <button
            onClick={() => {
              // User confirmed the generated docs are useful — record positive
              // feedback so the few-shot pool grows.
              submitLlmFeedback(result.llm_trace_ids ?? [], true, null)
              onComplete(`✅ 授权请示及授权书已生成：${result.filename}、${result.letter_filename}`)
            }}
            className="px-4 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors"
          >
            完成
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
      <div className="text-sm font-medium text-slate-300 mb-3">请上传呈批件（PDF 格式）</div>
      {error && <div className="text-red-400 text-sm mb-3">❌ {error}</div>}

      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) setPdfFile(f) }}
        className={`
          border-2 border-dashed rounded-xl p-8 cursor-pointer text-center transition-all mb-4
          ${drag ? 'border-indigo-400 bg-indigo-500/10' : 'border-slate-600 hover:border-slate-500'}
          ${pdfFile ? 'border-green-500/50 bg-green-500/5' : ''}
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={e => e.target.files?.[0] && setPdfFile(e.target.files[0])}
        />
        {pdfFile ? (
          <>
            <div className="text-green-400 text-2xl mb-2">✓</div>
            <div className="text-sm text-slate-300">{pdfFile.name}</div>
            <div className="text-xs text-slate-500 mt-1">{(pdfFile.size / 1024).toFixed(0)} KB</div>
          </>
        ) : (
          <>
            <div className="text-3xl mb-2">📄</div>
            <div className="text-sm text-slate-400">点击或拖拽上传 PDF</div>
            <div className="text-xs text-slate-500 mt-1">支持文字版和扫描版（自动 OCR）</div>
          </>
        )}
      </div>

      <div className="flex gap-2">
        <button
          onClick={handleProcess}
          disabled={!pdfFile}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
        >
          开始生成
        </button>
        <button
          onClick={() => {
            // No result yet → nothing to report; just cancel.
            if (result) submitLlmFeedback((result as AuthResult).llm_trace_ids ?? [], false, null)
            onCancel()
          }}
          className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors"
        >
          取消
        </button>
      </div>
    </div>
  )
}
