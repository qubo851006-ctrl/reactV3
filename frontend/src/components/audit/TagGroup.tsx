import { useState } from 'react'

/**
 * Editable pill-shaped tag list. Used by AuditFlow to let the user
 * adjust the business-domain list before running classification.
 *
 * Lifted out of AuditFlow.tsx as part of file-size cleanup.
 */
export default function TagGroup({
  label,
  tags,
  onChange,
}: {
  label: string
  tags: string[]
  onChange: (tags: string[]) => void
}) {
  const [adding, setAdding] = useState(false)
  const [input, setInput] = useState('')

  function remove(tag: string) {
    onChange(tags.filter(t => t !== tag))
  }

  function confirm() {
    const trimmed = input.trim()
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed])
    }
    setInput('')
    setAdding(false)
  }

  return (
    <div className="mb-4">
      <div className="text-xs font-medium text-slate-400 mb-2">{label}</div>
      <div className="flex flex-wrap gap-2 items-center">
        {tags.map(tag => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 px-3 py-1 bg-slate-700 text-slate-200 text-sm rounded-full"
          >
            {tag}
            <button
              onClick={() => remove(tag)}
              className="text-slate-400 hover:text-red-400 transition-colors leading-none ml-0.5"
              title="删除"
            >
              ×
            </button>
          </span>
        ))}
        {adding ? (
          <input
            autoFocus
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') confirm()
              if (e.key === 'Escape') { setAdding(false); setInput('') }
            }}
            onBlur={confirm}
            placeholder="输入后回车确认"
            className="px-3 py-1 bg-slate-700 border border-indigo-500 text-slate-200 text-sm rounded-full outline-none w-36"
          />
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="px-3 py-1 border border-dashed border-slate-600 text-slate-500 hover:text-slate-300 hover:border-slate-400 text-sm rounded-full transition-colors"
          >
            + 添加
          </button>
        )}
      </div>
    </div>
  )
}
