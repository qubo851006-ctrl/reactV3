import html2canvas from 'html2canvas'
import { useRef, useState } from 'react'
import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'

interface PieLabelProps {
  name?: string
  percent?: number
}

const COLORS = ['#6366f1', '#22d3ee', '#f59e0b', '#10b981', '#f43f5e', '#a78bfa']
const CHART_CAPTURE_TIMEOUT_MS = 10000
const CLIPBOARD_WRITE_TIMEOUT_MS = 6000
const BLOB_CREATE_TIMEOUT_MS = 4000

type CopyState = 'idle' | 'copying' | 'failed' | 'downloaded'

/**
 * Wrap a promise with a timeout so html2canvas / clipboard.write can't
 * hang the UI forever (seen in V2 on flaky browsers — the operation
 * succeeded but never resolved, leaving the button stuck on '复制中…').
 */
function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(message)), timeoutMs)
    promise.then(
      value => { window.clearTimeout(timer); resolve(value) },
      error => { window.clearTimeout(timer); reject(error) },
    )
  })
}

function canvasToPngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error('图片生成失败'))
    }, 'image/png')
  })
}

function canWriteImageToClipboard() {
  return typeof ClipboardItem !== 'undefined' && !!navigator.clipboard?.write
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/**
 * Pie chart + auto-generated breakdown sentence + "copy as image" button.
 *
 * Copy strategy (ported from V2 commits 27c2203 + aec04a6):
 * 1. Render the chart into a canvas via html2canvas (timeout-guarded).
 * 2. Convert canvas → PNG blob (timeout-guarded).
 * 3. If the browser exposes ClipboardItem + clipboard.write, try copying.
 *    Otherwise (Firefox before 127, Safari without HTTPS, etc.) skip
 *    straight to download.
 * 4. If clipboard.write fails (e.g. user denied permission), fall back
 *    to downloading the blob as <title>.png so the user still gets
 *    something useful.
 *
 * Lifted out of AuditFlow.tsx as part of file-size cleanup.
 */
export default function PieSection({
  title,
  data,
  total,
  suffix,
}: {
  title: string
  data: { name: string; value: number }[]
  total: number
  suffix: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [copyState, setCopyState] = useState<CopyState>('idle')

  const sorted = [...data].sort((a, b) => b.value - a.value)
  const top = sorted[0]

  const description = [
    `共发现问题 ${total} 项。${top ? `其中${top.name}${suffix}最多，占比 ${Math.round((top.value / total) * 100)}%（${top.value}项）。` : ''}`,
    sorted.map(d => `${d.name}${suffix}占比 ${Math.round((d.value / total) * 100)}%（${d.value}项）`).join('，') + '。',
  ].join('')

  async function copyChart() {
    const el = containerRef.current
    if (!el) return
    let fallbackBlob: Blob | null = null
    setCopyState('copying')
    el.style.backgroundColor = 'white'
    try {
      const canvas = await withTimeout(html2canvas(el, {
        backgroundColor: '#ffffff',
        scale: 2,
        useCORS: true,
        imageTimeout: 5000,
        logging: false,
        width: el.scrollWidth,
        height: el.scrollHeight,
        windowWidth: el.scrollWidth,
        windowHeight: el.scrollHeight,
      }), CHART_CAPTURE_TIMEOUT_MS, '图表截图超时')
      const blob = await withTimeout(canvasToPngBlob(canvas), BLOB_CREATE_TIMEOUT_MS, '图片生成超时')
      fallbackBlob = blob
      if (!canWriteImageToClipboard()) {
        downloadBlob(blob, `${title}.png`)
        setCopyState('downloaded')
        window.setTimeout(() => setCopyState('idle'), 3000)
        return
      }
      await withTimeout(
        navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]),
        CLIPBOARD_WRITE_TIMEOUT_MS,
        '剪贴板写入超时',
      )
      setCopyState('idle')
    } catch (e) {
      // eslint-disable-next-line no-console -- intentional warn so users can
      // open devtools and report the cause if all paths fail.
      console.warn('Copy audit chart failed:', e)
      if (fallbackBlob) {
        downloadBlob(fallbackBlob, `${title}.png`)
        setCopyState('downloaded')
        window.setTimeout(() => setCopyState('idle'), 3000)
      } else {
        setCopyState('failed')
        window.setTimeout(() => setCopyState('idle'), 3000)
      }
    } finally {
      el.style.backgroundColor = ''
    }
  }

  const copying = copyState === 'copying'
  const copyFailed = copyState === 'failed'
  const copiedToDownload = copyState === 'downloaded'
  const buttonText = copying
    ? '复制中…'
    : copiedToDownload
      ? '已下载PNG'
      : copyFailed
        ? '复制失败'
        : '⬜ 复制图片'

  return (
    <div className="relative bg-slate-800/60 border border-slate-700 rounded-2xl p-5 mb-4">
      {/* 复制按钮：绝对定位在外层容器右上角，不在截图范围内 */}
      <button
        onClick={copyChart}
        disabled={copying}
        className={`absolute top-3 right-3 z-10 text-xs px-2.5 py-1 rounded-md transition-colors disabled:opacity-50 ${
          copiedToDownload
            ? 'bg-amber-700/60 text-amber-100'
            : copyFailed
              ? 'bg-red-700/60 text-red-200'
              : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
        }`}
        title={
          copiedToDownload
            ? '剪贴板不可用，已自动下载为 PNG'
            : copyFailed
              ? '复制失败，请截图保存'
              : '复制图片到剪贴板（剪贴板不可用时自动下载）'
        }
      >
        {buttonText}
      </button>
      {/* 截图区域：不含按钮 */}
      <div ref={containerRef}>
        <div className="text-sm font-semibold text-slate-200 mb-3 pr-20">{title}</div>
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              outerRadius={90}
              dataKey="value"
              label={({ name, percent }: PieLabelProps) =>
                `${name ?? ''} ${((percent ?? 0) * 100).toFixed(0)}%`
              }
              labelLine={true}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value) => [`${value}项`, '数量'] as [string, string]}
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0' }}
            />
            <Legend wrapperStyle={{ color: '#94a3b8', fontSize: 12 }} />
          </PieChart>
        </ResponsiveContainer>
        <p className="text-xs text-slate-400 mt-2 leading-relaxed">{description}</p>
      </div>
    </div>
  )
}
