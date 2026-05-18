import { useState, useRef } from 'react'
import { extractLedger, writeLedger, downloadLedgerExcel, getErrorMessage, submitLlmFeedback } from '../api'
import type { LedgerPreview, LedgerCaseData, LedgerStage } from '../types'

interface Props {
  onComplete: (reply: string) => void
  onCancel: () => void
  visionModel?: string
}

type Step = 'upload' | 'processing' | 'confirm' | 'done'

export default function LedgerFlow({ onComplete, onCancel, visionModel = '' }: Props) {
  const [files, setFiles] = useState<File[]>([])
  const [logs, setLogs] = useState<string[]>([])
  const [step, setStep] = useState<Step>('upload')
  const [preview, setPreview] = useState<LedgerPreview | null>(null)
  const [editedCase, setEditedCase] = useState<LedgerCaseData | null>(null)
  const [doneResult, setDoneResult] = useState<{ case_count: number; archive_dir: string } | null>(null)
  const [error, setError] = useState('')
  const [writing, setWriting] = useState(false)
  const [drag, setDrag] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const logRef = useRef<HTMLDivElement>(null)

  function addFiles(newFiles: FileList | null) {
    if (!newFiles) return
    const arr = Array.from(newFiles).filter(f => /\.(pdf|docx|doc)$/i.test(f.name))
    setFiles(prev => {
      const names = new Set(prev.map(f => f.name))
      return [...prev, ...arr.filter(f => !names.has(f.name))]
    })
  }

  async function handleExtract() {
    if (!files.length) return
    setStep('processing')
    setLogs([])
    setError('')
    try {
      const res = await extractLedger(files, visionModel, log => {
        setLogs(prev => [...prev, log])
        setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 50)
      })
      setPreview(res)
      setEditedCase({ ...res.case_data, stages: res.case_data.stages.map(s => ({ ...s })) })
      setStep('confirm')
    } catch (e: unknown) {
      setError(getErrorMessage(e, '处理失败'))
      setStep('upload')
    }
  }

  async function handleWrite() {
    if (!preview || !editedCase) return
    setWriting(true)
    try {
      const res = await writeLedger(editedCase, preview.match_idx, preview.archive_dir, preview.pending_archive_id ?? '', preview.existing_archive_name ?? '')
      setDoneResult({ case_count: res.case_count, archive_dir: res.archive_dir || preview.archive_dir })
      setStep('done')
      // Feedback: user accepted the extraction. `edited_to` carries the
      // user-confirmed payload so the few-shot engine can learn what they
      // actually wanted, even when the AI's first pass was edited.
      const wasEdited = JSON.stringify(editedCase) !== JSON.stringify(preview.case_data)
      submitLlmFeedback(
        preview.llm_trace_ids ?? [],
        true,
        wasEdited ? editedCase : null,
      )
      onComplete(res.reply)
    } catch (e: unknown) {
      setError(getErrorMessage(e, '写入失败'))
    } finally {
      setWriting(false)
    }
  }

  function handleCancel() {
    // User dismissed the extraction — record as not accepted so we don't
    // pollute the few-shot pool with abandoned outputs.
    if (preview?.llm_trace_ids?.length) {
      submitLlmFeedback(preview.llm_trace_ids, false, null)
    }
    onCancel()
  }

  function setField<K extends keyof LedgerCaseData>(key: K, value: LedgerCaseData[K]) {
    setEditedCase(prev => prev ? { ...prev, [key]: value } : prev)
  }

  function setStageField(idx: number, key: keyof LedgerStage, value: string) {
    setEditedCase(prev => {
      if (!prev) return prev
      const stages = prev.stages.map((s, i) => i === idx ? { ...s, [key]: value } : s)
      return { ...prev, stages }
    })
  }

  // ── 处理中（SSE 日志）────────────────────────────────────────
  if (step === 'processing') {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="flex items-center gap-2 text-slate-300 text-sm mb-3">
          <div className="animate-spin w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full flex-shrink-0" />
          正在提取文书信息…
        </div>
        <div
          ref={logRef}
          className="bg-slate-900/60 rounded-lg p-3 h-48 overflow-y-auto font-mono text-xs text-slate-400 space-y-1"
        >
          {logs.map((l, i) => (
            <div key={i} dangerouslySetInnerHTML={{
              __html: l
                .replace(/\*\*(.*?)\*\*/g, '<strong class="text-slate-200">$1</strong>')
                .replace(/`(.*?)`/g, '<code class="text-indigo-300">$1</code>')
            }} />
          ))}
          {!logs.length && <div className="text-slate-600">等待处理…</div>}
        </div>
      </div>
    )
  }

  // ── 确认步骤 ────────────────────────────────────────────────
  if (step === 'confirm' && preview && editedCase) {
    const actionColor = preview.is_new ? 'text-green-400' : 'text-yellow-400'
    const actionIcon = preview.is_new ? '🆕' : '🔄'

    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="flex items-start justify-between gap-3 mb-1">
          <div className="text-sm font-medium text-slate-200">请确认以下提取结果，可直接修改后写入台账：</div>
          <button onClick={downloadLedgerExcel} className="text-xs text-emerald-300 hover:text-emerald-200 whitespace-nowrap">
            下载已有台账
          </button>
        </div>
        <div className={`text-xs ${actionColor} mb-4`}>{actionIcon} {preview.action_text}</div>
        {error && <div className="text-red-400 text-sm mb-3">❌ {error}</div>}

        <div className="space-y-2 mb-4">
          {([
            ['案件名称', '案件名称', 'text'],
            ['案由', '案由', 'text'],
            ['诉讼主体', '诉讼主体', 'textarea'],
            ['主诉/被诉', '主诉被诉', 'text'],
            ['案件发生时间', '案件发生时间', 'text'],
            ['生效判决日期', '生效判决日期', 'text'],
            ['服务律所', '服务律所', 'text'],
          ] as [string, keyof LedgerCaseData, string][]).map(([label, key, type]) => (
            <div key={key} className="flex gap-3">
              <span className="text-slate-400 text-xs w-24 flex-shrink-0 pt-2">{label}</span>
              {type === 'textarea' ? (
                <textarea
                  rows={3}
                  value={String(editedCase[key] ?? '')}
                  onChange={e => setField(key, e.target.value)}
                  className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-indigo-500 resize-none"
                />
              ) : (
                <input
                  type="text"
                  value={String(editedCase[key] ?? '')}
                  onChange={e => setField(key, e.target.value)}
                  className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-indigo-500"
                />
              )}
            </div>
          ))}

          <div className="flex gap-3">
            <span className="text-slate-400 text-xs w-24 flex-shrink-0 pt-2">标的金额（万元）</span>
            <input
              type="number"
              step="0.01"
              value={editedCase.标的金额 ?? ''}
              onChange={e => setField('标的金额', e.target.value ? parseFloat(e.target.value) : null)}
              className="w-36 bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex gap-3">
            <span className="text-slate-400 text-xs w-24 flex-shrink-0 pt-2">基本情况</span>
            <textarea
              rows={4}
              value={editedCase.基本情况 ?? ''}
              onChange={e => setField('基本情况', e.target.value)}
              className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-indigo-500 resize-none"
            />
          </div>

          {/* 审级处理结果 */}
          {editedCase.stages.length > 0 && (
            <div className="flex gap-3">
              <span className="text-slate-400 text-xs w-24 flex-shrink-0 pt-2">审级结果</span>
              <div className="flex-1 space-y-2">
                {editedCase.stages.map((stage, idx) => (
                  <div key={idx} className="bg-slate-700/50 rounded-lg p-3 space-y-2">
                    <input
                      type="text"
                      value={stage.审级}
                      onChange={e => setStageField(idx, '审级', e.target.value)}
                      placeholder="审级（一审/二审/再审）"
                      className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-white outline-none focus:border-indigo-500"
                    />
                    <textarea
                      rows={3}
                      value={stage.处理结果}
                      onChange={e => setStageField(idx, '处理结果', e.target.value)}
                      placeholder="处理结果"
                      className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-white outline-none focus:border-indigo-500 resize-none"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="flex gap-2">
          <button
            onClick={handleWrite}
            disabled={writing}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
          >
            {writing ? '写入中…' : '✅ 确认写入台账'}
          </button>
          <button
            onClick={handleCancel}
            className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors"
          >
            取消
          </button>
        </div>
      </div>
    )
  }

  // ── 完成 ────────────────────────────────────────────────────
  if (step === 'done' && doneResult) {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="text-green-400 font-medium mb-3">✅ 台账更新完成</div>
        <div className="text-sm text-slate-300 mb-1">
          共 <span className="text-white font-bold">{doneResult.case_count}</span> 个案件
        </div>
        <div className="text-xs text-slate-500 mb-4">📁 文书已归档至：{doneResult.archive_dir}</div>
        <button
          onClick={downloadLedgerExcel}
          className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition-colors"
        >
          📥 下载案件台账 Excel
        </button>
      </div>
    )
  }

  // ── 上传文件 ────────────────────────────────────────────────
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="text-sm font-medium text-slate-300">请上传案件法律文书（PDF / DOCX / DOC，可多选）</div>
        <button onClick={downloadLedgerExcel} className="text-xs text-emerald-300 hover:text-emerald-200 whitespace-nowrap">
          下载已有台账
        </button>
      </div>
      {error && <div className="text-red-400 text-sm mb-3">❌ {error}</div>}

      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files) }}
        className={`
          border-2 border-dashed rounded-xl p-6 cursor-pointer text-center transition-all mb-3
          ${drag ? 'border-indigo-400 bg-indigo-500/10' : 'border-slate-600 hover:border-slate-500'}
        `}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.doc"
          multiple
          className="hidden"
          onChange={e => addFiles(e.target.files)}
        />
        <div className="text-slate-400 text-sm mb-1">📂 点击或拖拽上传文书文件</div>
        <div className="text-slate-500 text-xs">支持 PDF / DOCX / DOC，可多选</div>
      </div>

      {files.length > 0 && (
        <div className="space-y-1 mb-4">
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-slate-400 bg-slate-700/40 rounded-lg px-3 py-2">
              <span className="text-green-400">✓</span>
              <span className="flex-1 truncate">{f.name}</span>
              <span className="text-slate-500">{(f.size / 1024).toFixed(0)} KB</span>
              <button
                onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}
                className="text-slate-500 hover:text-red-400 transition-colors"
              >✕</button>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={handleExtract}
          disabled={!files.length}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
        >
          开始处理 {files.length > 0 && `（${files.length} 个文件）`}
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors"
        >
          取消
        </button>
      </div>
    </div>
  )
}
