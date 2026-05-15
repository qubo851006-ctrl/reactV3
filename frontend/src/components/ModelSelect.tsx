import type { ModelOption } from '../modelOptions'

interface Props {
  label: string
  title: string
  value: string
  options: ModelOption[]
  onChange: (value: string) => void
  disabled?: boolean
}

export default function ModelSelect({ label, title, value, options, onChange, disabled = false }: Props) {
  return (
    <label className="hidden sm:flex items-center gap-2 text-xs text-slate-400">
      <span className="whitespace-nowrap">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
        title={title}
        className="
          h-8 max-w-44 rounded-lg border border-slate-700/70 bg-slate-800/80
          px-2.5 text-xs font-medium text-slate-100 outline-none
          hover:border-slate-600 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30
          disabled:opacity-50 disabled:cursor-not-allowed
        "
      >
        {options.map(option => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}
