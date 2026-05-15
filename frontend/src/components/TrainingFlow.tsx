import { useState, useRef } from 'react'
import { extractTraining, writeTraining, downloadTrainingExcel, getErrorMessage } from '../api'
import type { TrainingResult } from '../types'

interface Props {
  onComplete: (reply: string) => void
  onCancel: () => void
  visionModel?: string
}

type Step = 'upload' | 'dept' | 'processing' | 'confirm' | 'done'

export default function TrainingFlow({ onComplete, onCancel, visionModel = '' }: Props) {
  const [step, setStep] = useState<Step>('upload')
  const [noticePdf, setNoticePdf] = useState<File | null>(null)
  const [signinImg, setSigninImg] = useState<File | null>(null)
  const [department, setDepartment] = useState('')
  const [extracted, setExtracted] = useState<TrainingResult | null>(null)
  const [edited, setEdited] = useState<TrainingResult | null>(null)
  const [error, setError] = useState('')
  const [writing, setWriting] = useState(false)
  const deptRef = useRef<HTMLInputElement>(null)

  const canUpload = noticePdf && signinImg

  async function handleExtract() {
    if (!noticePdf || !signinImg) return
    setStep('processing')
    setError('')
    try {
      const res = await extractTraining(noticePdf, signinImg, department, visionModel)
      setExtracted(res)
      setEdited({ ...res })
      setStep('confirm')
    } catch (e: unknown) {
      setError(getErrorMessage(e, '处理失败'))
      setStep('upload')
    }
  }

  async function handleWrite() {
    if (!edited) return
    setWriting(true)
    try {
      await writeTraining({
        topic: edited.topic,
        location: edited.location,
        date: edited.date,
        department: edited.department,
        count: edited.count,
        category: edited.category,
        archive_path: edited.archive_path,
        pending_upload_id: edited.pending_upload_id,
        start_time: edited.start_time,
        end_time: edited.end_time,
        duration_hours: edited.duration_hours,
      })
      setStep('done')
      const durationText = edited.duration_hours > 0 ? `，培训时长：${edited.duration_hours} 课时` : ''
      onComplete(`✅ 培训记录已写入台账！主题：${edited.topic}，参与人数：${edited.count} 人${durationText}`)
    } catch (e: unknown) {
      setError(getErrorMessage(e, '写入失败'))
    } finally {
      setWriting(false)
    }
  }

  function setField(key: keyof TrainingResult, value: string | number) {
    setEdited(prev => prev ? { ...prev, [key]: value } : prev)
  }

  // ── 处理中 ──────────────────────────────────────────────────
  if (step === 'processing') {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="flex items-center gap-3 text-slate-300">
          <div className="animate-spin w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full" />
          <span>正在识别处理，请稍候…</span>
        </div>
      </div>
    )
  }

  // ── 确认步骤 ────────────────────────────────────────────────
  if (step === 'confirm' && extracted && edited) {
    const confidenceLabel = extracted.confidence === 'high'
      ? <span className="text-green-400 text-xs">🟢 高置信度</span>
      : <span className="text-yellow-400 text-xs">🟡 低置信度（建议核对）</span>

    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="flex items-start justify-between gap-3 mb-1">
          <div className="text-sm font-medium text-slate-200">请确认以下识别结果，可直接修改后再写入台账：</div>
          <button onClick={downloadTrainingExcel} className="text-xs text-emerald-300 hover:text-emerald-200 whitespace-nowrap">
            下载已有台账
          </button>
        </div>
        {extracted.reflection_note && (
          <div className="text-xs text-slate-400 bg-slate-700/50 rounded-lg px-3 py-2 mb-4">
            🔍 {extracted.reflection_note}
          </div>
        )}
        {error && <div className="text-red-400 text-sm mb-3">❌ {error}</div>}

        <div className="space-y-2 mb-5">
          {([
            ['培训主题', 'topic', 'text'],
            ['培训地点', 'location', 'text'],
            ['培训日期', 'date', 'text'],
            ['主办部门', 'department', 'text'],
            ['培训类别', 'category', 'text'],
          ] as [string, keyof TrainingResult, string][]).map(([label, key, type]) => (
            <div key={key} className="flex items-center gap-3">
              <span className="text-slate-400 text-sm w-20 flex-shrink-0">{label}</span>
              <input
                type={type}
                value={String(edited[key] ?? '')}
                onChange={e => setField(key, e.target.value)}
                className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-indigo-500"
              />
            </div>
          ))}
          <div className="flex items-center gap-3">
            <span className="text-slate-400 text-sm w-20 flex-shrink-0">参与人数</span>
            <div className="flex items-center gap-2 flex-1">
              <input
                type="number"
                min={0}
                value={edited.count}
                onChange={e => setField('count', parseInt(e.target.value) || 0)}
                className="w-24 bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-indigo-500"
              />
              <span className="text-slate-400 text-sm">人</span>
              {confidenceLabel}
            </div>
          </div>
          {([
            ['培训开始时间', 'start_time', 'text'],
            ['培训结束时间', 'end_time', 'text'],
          ] as [string, keyof TrainingResult, string][]).map(([label, key, type]) => (
            <div key={key} className="flex items-center gap-3">
              <span className="text-slate-400 text-sm w-20 flex-shrink-0">{label}</span>
              <input
                type={type}
                placeholder="HH:MM"
                value={String(edited[key] ?? '')}
                onChange={e => setField(key, e.target.value)}
                className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-indigo-500"
              />
            </div>
          ))}
          <div className="flex items-center gap-3">
            <span className="text-slate-400 text-sm w-20 flex-shrink-0">培训时长</span>
            <div className="flex items-center gap-2 flex-1">
              <input
                type="number"
                min={0}
                step={0.5}
                value={edited.duration_hours}
                onChange={e => setField('duration_hours', parseFloat(e.target.value) || 0)}
                className="w-24 bg-slate-700 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-white outline-none focus:border-indigo-500"
              />
              <span className="text-slate-400 text-sm">课时（1课时=40分钟）</span>
            </div>
          </div>
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
            onClick={onCancel}
            className="px-3 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors"
          >
            取消
          </button>
        </div>
      </div>
    )
  }

  // ── 完成 ────────────────────────────────────────────────────
  if (step === 'done' && edited) {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="text-green-400 font-medium mb-4">✅ 已写入台账</div>
        <table className="w-full text-sm mb-4">
          <tbody>
            {([
              ['培训主题', edited.topic],
              ['培训地点', edited.location],
              ['培训日期', edited.date],
              ['主办部门', edited.department || '未填写'],
              ['参与人数', `${edited.count} 人`],
              ['培训时长', edited.duration_hours > 0 ? `${edited.duration_hours} 课时` : '未填写'],
              ['培训类别', edited.category],
            ] as [string, string][]).map(([k, v]) => (
              <tr key={k} className="border-b border-slate-700/50">
                <td className="py-2 pr-4 text-slate-400 w-24">{k}</td>
                <td className="py-2 text-slate-200 font-medium">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          onClick={downloadTrainingExcel}
          className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition-colors"
        >
          📥 下载培训统计表 Excel
        </button>
      </div>
    )
  }

  // ── 填写部门 ────────────────────────────────────────────────
  if (step === 'dept') {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="text-sm text-slate-300">
            文件已收到：<span className="text-indigo-400">{noticePdf?.name}</span>、
            <span className="text-indigo-400">{signinImg?.name}</span>
            <br />请填写主办部门（可留空跳过）：
          </div>
          <button onClick={downloadTrainingExcel} className="text-xs text-emerald-300 hover:text-emerald-200 whitespace-nowrap">
            下载已有台账
          </button>
        </div>
        <div className="flex gap-2">
          <input
            ref={deptRef}
            type="text"
            placeholder="主办部门（可选）"
            value={department}
            onChange={e => setDepartment(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleExtract()}
            className="flex-1 bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-indigo-500"
            autoFocus
          />
          <button
            onClick={handleExtract}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg transition-colors"
          >
            开始处理
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

  // ── 上传文件 ────────────────────────────────────────────────
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 my-3">
      <div className="flex items-center justify-between gap-3 mb-4">
        <div className="text-sm font-medium text-slate-300">请上传以下两个文件：</div>
        <button onClick={downloadTrainingExcel} className="text-xs text-emerald-300 hover:text-emerald-200 whitespace-nowrap">
          下载已有台账
        </button>
      </div>
      {error && <div className="text-red-400 text-sm mb-3">❌ {error}</div>}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <FileDropZone
          label="📄 培训通知（PDF）"
          accept=".pdf"
          file={noticePdf}
          onFile={setNoticePdf}
        />
        <FileDropZone
          label="✍️ 签到表（图片）"
          accept=".jpg,.jpeg,.png"
          file={signinImg}
          onFile={setSigninImg}
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => setStep('dept')}
          disabled={!canUpload}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
        >
          下一步
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

function FileDropZone({
  label, accept, file, onFile,
}: { label: string; accept: string; file: File | null; onFile: (f: File) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDrag(false)
    const f = e.dataTransfer.files[0]
    if (f) onFile(f)
  }

  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={e => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={handleDrop}
      className={`
        border-2 border-dashed rounded-xl p-4 cursor-pointer transition-all text-center
        ${drag ? 'border-indigo-400 bg-indigo-500/10' : 'border-slate-600 hover:border-slate-500'}
        ${file ? 'border-green-500/50 bg-green-500/5' : ''}
      `}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={e => e.target.files?.[0] && onFile(e.target.files[0])}
      />
      <div className="text-sm text-slate-400 mb-1">{label}</div>
      {file ? (
        <div className="text-xs text-green-400">✓ {file.name}</div>
      ) : (
        <div className="text-xs text-slate-500">点击或拖拽上传</div>
      )}
    </div>
  )
}
