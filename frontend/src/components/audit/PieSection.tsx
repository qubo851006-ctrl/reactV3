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

/**
 * Pie chart + auto-generated breakdown sentence + "copy as image"
 * button (uses html2canvas → clipboard).
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
  const [copying, setCopying] = useState(false)
  const [copyError, setCopyError] = useState(false)

  const sorted = [...data].sort((a, b) => b.value - a.value)
  const top = sorted[0]

  const description = [
    `共发现问题 ${total} 项。${top ? `其中${top.name}${suffix}最多，占比 ${Math.round((top.value / total) * 100)}%（${top.value}项）。` : ''}`,
    sorted.map(d => `${d.name}${suffix}占比 ${Math.round((d.value / total) * 100)}%（${d.value}项）`).join('，') + '。',
  ].join('')

  async function copyChart() {
    const el = containerRef.current
    if (!el) return
    setCopying(true)
    el.style.backgroundColor = 'white'
    try {
      const canvas = await html2canvas(el, {
        backgroundColor: '#ffffff',
        scale: 2,
        useCORS: true,
        width: el.scrollWidth,
        height: el.scrollHeight,
        windowWidth: el.scrollWidth,
        windowHeight: el.scrollHeight,
      })
      await new Promise<void>((resolve, reject) => {
        canvas.toBlob(async (blob) => {
          if (!blob) { reject(new Error('截图失败')); return }
          navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
            .then(resolve).catch(reject)
        })
      })
    } catch {
      setCopyError(true)
      setTimeout(() => setCopyError(false), 3000)
    } finally {
      el.style.backgroundColor = ''
      setCopying(false)
    }
  }

  return (
    <div className="relative bg-slate-800/60 border border-slate-700 rounded-2xl p-5 mb-4">
      {/* 复制按钮：绝对定位在外层容器右上角，不在截图范围内 */}
      <button
        onClick={copyChart}
        disabled={copying}
        className={`absolute top-3 right-3 z-10 text-xs px-2.5 py-1 rounded-md transition-colors disabled:opacity-50 ${
          copyError
            ? 'bg-red-700/60 text-red-200'
            : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
        }`}
        title={copyError ? '复制失败，请截图保存' : '复制图片到剪贴板'}
      >
        {copying ? '复制中…' : copyError ? '复制失败' : '⬜ 复制图片'}
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
