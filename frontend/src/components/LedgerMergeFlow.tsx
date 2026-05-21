import { useEffect, useRef, useState } from 'react'
import {
  downloadMergedExcel,
  getBackgroundTask,
  getErrorMessage,
  startLedgerMergeTask,
  type MergeStats,
} from '../api'
import { useNotifier } from './NotificationContext'

interface Props {
  onComplete: (reply: string) => void
  onCancel: () => void
}

interface FileZoneProps {
  label: string
  badge: string
  badgeColor: string
  required?: boolean
  file: File | null
  onChange: (f: File | null) => void
  disabled: boolean
}

function sleep(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

function FileZone({ label, badge, badgeColor, required, file, onChange, disabled }: FileZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) onChange(f)
  }

  return (
    <div
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`
        relative flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed
        px-4 py-5 cursor-pointer transition-all select-none min-h-[100px]
        ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        ${dragging ? 'border-indigo-400 bg-indigo-500/10' : file ? 'border-emerald-500/60 bg-emerald-500/5' : 'border-slate-600 bg-slate-800/50 hover:border-slate-500'}
      `}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".xlsx,.xls"
        className="hidden"
        disabled={disabled}
        onChange={e => { const f = e.target.files?.[0]; if (f) onChange(f); e.target.value = '' }}
      />
      <div className="flex items-center gap-2">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${badgeColor}`}>
          {badge}
        </span>
        {required && <span className="text-xs text-red-400">必填</span>}
      </div>
      <div className="text-sm font-medium text-slate-200">{label}</div>
      {file ? (
        <div className="flex items-center gap-2 mt-1">
          <span className="text-emerald-400 text-xs">已选</span>
          <span className="text-xs text-emerald-400 truncate max-w-[180px]">{file.name}</span>
          <button
            onClick={e => { e.stopPropagation(); onChange(null) }}
            className="text-slate-500 hover:text-red-400 text-xs transition-colors"
          >
            移除
          </button>
        </div>
      ) : (
        <div className="text-xs text-slate-500">点击或拖拽上传 Excel 文件</div>
      )}
    </div>
  )
}

export default function LedgerMergeFlow({ onComplete, onCancel }: Props) {
  const { notifySuccess, notifyError } = useNotifier()
  const [contractFile, setContractFile] = useState<File | null>(null)
  const [purchaseFile, setPurchaseFile] = useState<File | null>(null)
  const [financeFile, setFinanceFile] = useState<File | null>(null)
  const [processing, setProcessing] = useState(false)
  const [taskId, setTaskId] = useState('')
  const [taskMessage, setTaskMessage] = useState('')
  const [taskProgress, setTaskProgress] = useState(0)
  const [stats, setStats] = useState<MergeStats | null>(null)
  const [error, setError] = useState('')
  const mountedRef = useRef(true)

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  const canSubmit = !!contractFile && !processing

  async function waitForTask(id: string) {
    while (mountedRef.current) {
      const task = await getBackgroundTask<MergeStats>(id)
      if (!mountedRef.current) return
      setTaskProgress(task.progress ?? 0)
      setTaskMessage(task.message || '任务处理中')

      if (task.status === 'succeeded') {
        if (!task.result) throw new Error('任务完成，但没有返回合并结果')
        setStats(task.result)
        notifySuccess('三台账合并完成', `合同系统 ${task.result.total_contract} 条，全部匹配 ${task.result.fully_matched} 条。`)
        return
      }
      if (task.status === 'failed' || task.status === 'cancelled') {
        throw new Error(task.error || task.message || '合并失败')
      }
      await sleep(1000)
    }
  }

  async function handleMerge() {
    if (!contractFile) return
    setProcessing(true)
    setError('')
    setStats(null)
    setTaskProgress(0)
    setTaskMessage('正在提交任务')
    try {
      const started = await startLedgerMergeTask(contractFile, purchaseFile, financeFile)
      setTaskId(started.task_id)
      await waitForTask(started.task_id)
    } catch (e: unknown) {
      let msg = getErrorMessage(e, '合并失败')
      try {
        const json = JSON.parse(msg) as { detail?: unknown }
        msg = typeof json.detail === 'string' ? json.detail : msg
      } catch { /* keep original */ }
      setError(msg)
      notifyError('三台账合并失败', msg)
    } finally {
      if (mountedRef.current) setProcessing(false)
    }
  }

  function handleDownload() {
    downloadMergedExcel(stats?.result_id ?? '')
    const hasPurchase = !!purchaseFile
    const hasFinance = !!financeFile
    onComplete(
      `三台账合并完成。\n\n` +
      `- 合同系统台账：${stats!.total_contract} 条记录\n` +
      (hasPurchase ? `- 采购系统匹配：${stats!.matched_purchase} 条\n` : '') +
      (hasFinance ? `- 财务系统匹配：${stats!.matched_finance} 条\n` : '') +
      `- 全部匹配：${stats!.fully_matched} 条\n` +
      (stats!.partial_matched > 0 ? `- 部分匹配：${stats!.partial_matched} 条\n` : '') +
      (stats!.unmatched > 0 ? `- 未匹配：${stats!.unmatched} 条\n` : '') +
      `\n合并台账已下载。`
    )
  }

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5 my-3 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">合</span>
          <span className="text-sm font-semibold text-white">三台账合并</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => downloadMergedExcel()}
            className="text-xs text-emerald-300 hover:text-emerald-200 whitespace-nowrap"
          >
            下载已有台账
          </button>
          {!stats && (
            <button
              onClick={onCancel}
              disabled={processing}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors disabled:opacity-40"
            >
              取消
            </button>
          )}
        </div>
      </div>

      <p className="text-xs text-slate-400">
        以合同系统台账为主键，将采购和财务台账按合同编号合并。任务提交后会在后台处理，完成后可下载结果。
      </p>

      {!stats && (
        <div className="space-y-3">
          <FileZone
            label="合同系统台账"
            badge="合同"
            badgeColor="bg-blue-900/60 text-blue-300"
            required
            file={contractFile}
            onChange={setContractFile}
            disabled={processing}
          />
          <FileZone
            label="采购系统台账"
            badge="采购"
            badgeColor="bg-green-900/60 text-green-300"
            file={purchaseFile}
            onChange={setPurchaseFile}
            disabled={processing}
          />
          <FileZone
            label="财务系统台账"
            badge="财务"
            badgeColor="bg-orange-900/60 text-orange-300"
            file={financeFile}
            onChange={setFinanceFile}
            disabled={processing}
          />
        </div>
      )}

      {error && (
        <div className="text-xs text-red-400 bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {processing && (
        <div className="space-y-2 text-sm text-slate-400 py-2">
          <div className="flex items-center justify-between gap-3">
            <span>{taskMessage || '后台任务处理中'}</span>
            <span className="text-xs text-slate-500">{taskProgress}%</span>
          </div>
          <div className="h-2 rounded-full bg-slate-700 overflow-hidden">
            <div
              className="h-full rounded-full bg-indigo-500 transition-all duration-300"
              style={{ width: `${Math.max(5, taskProgress)}%` }}
            />
          </div>
          {taskId && <div className="text-[11px] text-slate-500">任务编号：{taskId}</div>}
        </div>
      )}

      {stats && (
        <div className="space-y-3">
          <div className="bg-slate-900/60 rounded-xl p-4 space-y-2">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">合并结果</div>
            <StatRow label="合同系统台账" value={`${stats.total_contract} 条`} color="text-blue-300" />
            {purchaseFile && (
              <StatRow
                label="采购系统匹配"
                value={`${stats.matched_purchase} / ${stats.total_contract} 条`}
                color="text-green-300"
              />
            )}
            {financeFile && (
              <StatRow
                label="财务系统匹配"
                value={`${stats.matched_finance} / ${stats.total_contract} 条`}
                color="text-orange-300"
              />
            )}
            <div className="border-t border-slate-700/50 my-2" />
            <StatRow label="全部匹配" value={`${stats.fully_matched} 条`} color="text-emerald-400" />
            {stats.partial_matched > 0 && (
              <StatRow label="部分匹配" value={`${stats.partial_matched} 条`} color="text-yellow-400" />
            )}
            {stats.unmatched > 0 && (
              <StatRow label="未匹配" value={`${stats.unmatched} 条`} color="text-red-400" />
            )}
          </div>

          <button
            onClick={handleDownload}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-xl transition-colors font-medium"
          >
            下载合并台账 Excel
          </button>
        </div>
      )}

      {!stats && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={handleMerge}
            disabled={!canSubmit}
            className="flex-1 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-xl transition-colors font-medium"
          >
            {processing ? '后台合并中' : '开始合并'}
          </button>
        </div>
      )}
    </div>
  )
}

function StatRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-slate-400">{label}</span>
      <span className={`font-semibold ${color}`}>{value}</span>
    </div>
  )
}
