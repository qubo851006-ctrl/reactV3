import { useRef, useState } from 'react'
import { getErrorMessage, type LedgerImportConfirmResult, type LedgerImportPreview } from '../api'
import { useNotifier } from './NotificationContext'

interface Props {
  title: string
  previewImport: (file: File) => Promise<LedgerImportPreview>
  confirmImport: (importToken: string) => Promise<LedgerImportConfirmResult>
  onImported: (reply: string) => void
}

export default function LedgerImportPanel({ title, previewImport, confirmImport, onImported }: Props) {
  const { notifySuccess, notifyError } = useNotifier()
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<LedgerImportPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handlePreview(nextFile = file) {
    if (!nextFile) return
    setBusy(true)
    setError('')
    try {
      const result = await previewImport(nextFile)
      setPreview(result)
      notifySuccess(`${title}预览完成`, `可导入 ${result.rows_valid} 条，新增 ${result.inserts} 条，更新 ${result.updates} 条。`)
    } catch (e: unknown) {
      const message = getErrorMessage(e, '导入预览失败')
      setError(message)
      notifyError(`${title}预览失败`, message)
    } finally {
      setBusy(false)
    }
  }

  async function handleConfirm() {
    if (!preview) return
    setBusy(true)
    setError('')
    try {
      const result = await confirmImport(preview.import_token)
      setPreview(null)
      setFile(null)
      notifySuccess(`${title}导入完成`, `新增 ${result.inserts} 条，更新 ${result.updates} 条。`)
      onImported(result.reply)
    } catch (e: unknown) {
      const message = getErrorMessage(e, '导入失败')
      setError(message)
      notifyError(`${title}导入失败`, message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border border-slate-700 bg-slate-900/40 rounded-xl p-3 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-200">导入历史台账</div>
          <div className="text-xs text-slate-500 mt-0.5">上传 .xlsx 后先预览差异，确认后写入当前累计台账。</div>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx"
          className="hidden"
          onChange={e => {
            const nextFile = e.target.files?.[0] ?? null
            setFile(nextFile)
            setPreview(null)
            if (nextFile) void handlePreview(nextFile)
          }}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="px-3 py-2 text-xs rounded-lg bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-100 whitespace-nowrap"
        >
          选择 Excel
        </button>
      </div>

      {file && (
        <div className="text-xs text-slate-400 truncate">已选择：{file.name}</div>
      )}

      {preview && (
        <div className="space-y-3">
          <div className="grid grid-cols-4 gap-2 text-center">
            <ImportStat label="有效" value={preview.rows_valid} />
            <ImportStat label="新增" value={preview.inserts} />
            <ImportStat label="更新" value={preview.updates} />
            <ImportStat label="无效" value={preview.rows_invalid} />
          </div>
          {preview.rows_invalid > 0 && (
            <div className="text-xs text-amber-300">
              有 {preview.rows_invalid} 行未导入，首条原因：{preview.invalid_rows[0]?.reason || '字段不完整'}
            </div>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleConfirm}
              disabled={busy || preview.rows_valid === 0}
              className="px-3 py-2 text-xs rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white"
            >
              {busy ? '导入中…' : '确认导入'}
            </button>
            <button
              type="button"
              onClick={() => {
                setPreview(null)
                setFile(null)
              }}
              disabled={busy}
              className="px-3 py-2 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {error && <div className="text-xs text-red-300 break-words">{error}</div>}
    </div>
  )
}

function ImportStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-950/50 py-2">
      <div className="text-base font-semibold text-slate-100">{value}</div>
      <div className="text-[11px] text-slate-500">{label}</div>
    </div>
  )
}
