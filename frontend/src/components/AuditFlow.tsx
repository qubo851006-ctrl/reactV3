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
import type { AuditRow } from '../api'
import { analyzeAudit, downloadAuditExcel, getErrorMessage, submitLlmFeedback } from '../api'

interface Props {
  onComplete: (reply: string) => void
  onCancel: () => void
}

type Phase = 'upload' | 'analyzing' | 'review' | 'report'

// ── 分类体系常量（与后端 CATEGORY_TAXONOMY 保持一致）────────────

const CATEGORY_TAXONOMY: Record<string, string[]> = {
  '公司治理': ['三重一大决策', '董事会管理', '股东会管理', '会议管理', '其他'],
  '合同及法律合规管理': ['合同审核及签署', '合同执行', '诉讼管理', '授权管理', '知识产权管理', '其他'],
  '采购管理': ['采购方式', '采购评审', '供应商管理', '采购文档管理', '其他'],
  '营销管理': ['代理人管理', '销售管理', '大客户管理', '团队管理', '常旅客管理', '知音商城管理', '品牌管理', '其他'],
  '人力资源管理': ['人员招聘', '绩效考核', '薪酬福利', '考勤管理', '培训管理', '岗位与人员配置', '离职管理', '领导人员履职待遇', '其他'],
  '财务管理': ['预算管理', '银行账户管理', '成本费用管理', '资金管理', '往来账款管理', '会计核算管理', '保险及索赔管理', '担保管理', '税务管理', '优惠政策使用管理', '其他'],
  '资产管理': ['固定资产管理', '存货管理', '低值易耗品管理', '无形资产管理', '资产权证管理', '其他'],
  '信息系统管理': ['系统功能开发管理', '系统账号管理', '系统安全管理', '系统应用管理', '其他'],
  '工程项目管理': ['工程项目工期管理', '工程项目招标管理', '工程项目洽商变更', '施工过程管理', '工程项目验收', '工程项目竣工结决算', '其他'],
  '安全管理': ['安全事件', '安全与质量考核', '空防、消防、地面安全管理', '应急管理', '其他'],
  '内部控制管理': ['评价管理', '内部控制手册建设', '风险识别与管理', '规章制度审核', '其他'],
  '行政管理（其他）': ['中央八项规定精神', '档案管理', '证照管理', '礼品管理', '印章管理', '免折票管理', '审计整改', '对外捐赠', '企业文化'],
  '其他': ['其他'],
}

const L1_CATEGORIES = Object.keys(CATEGORY_TAXONOMY)

const DEFAULT_DOMAINS = ['物业租赁', '酒店公寓', '工程领域', '资产处置', '历史遗留问题']
const COLORS = ['#6366f1', '#22d3ee', '#f59e0b', '#10b981', '#f43f5e', '#a78bfa']

interface PieLabelProps {
  name?: string
  percent?: number
}

// ── 可编辑标签组 ────────────────────────────────────────────────

function TagGroup({
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

// ── 饼图 + 文字说明 + 复制按钮 ─────────────────────────────────

function PieSection({
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

// ── 主组件 ──────────────────────────────────────────────────────

export default function AuditFlow({ onComplete, onCancel }: Props) {
  const [phase, setPhase] = useState<Phase>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [domains, setDomains] = useState<string[]>(DEFAULT_DOMAINS)
  const [rows, setRows] = useState<AuditRow[]>([])
  const [originalRows, setOriginalRows] = useState<AuditRow[]>([])
  const [traceIds, setTraceIds] = useState<string[]>([])
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function handleCancel() {
    if (traceIds.length > 0) submitLlmFeedback(traceIds, false, null)
    onCancel()
  }

  // ── 文件选择 ──

  function handleFileSelect(f: File) {
    if (!f.name.match(/\.(xlsx|xls)$/i)) {
      setError('请上传 Excel 文件（.xlsx 或 .xls）')
      return
    }
    setFile(f)
    setError('')
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFileSelect(f)
  }

  // ── 开始分析 ──

  async function startAnalyze() {
    if (!file) { setError('请先上传 Excel 文件'); return }
    if (domains.length === 0) { setError('请至少配置一个业务领域'); return }
    setError('')
    setPhase('analyzing')
    try {
      const result = await analyzeAudit(file, domains)
      setRows(result.rows)
      setOriginalRows(result.rows.map(r => ({ ...r })))
      setTraceIds(result.llm_trace_ids ?? [])
      setPhase('review')
    } catch (e: unknown) {
      setError(getErrorMessage(e, '分析失败，请重试'))
      setPhase('upload')
    }
  }

  // ── 行更新 ──

  function updateRow(i: number, patch: Partial<AuditRow>) {
    setRows(prev => {
      const updated = [...prev]
      updated[i] = { ...updated[i], ...patch }
      return updated
    })
  }

  // 采纳 A 的分类（清除分歧标记）
  function acceptA(i: number) {
    updateRow(i, { disagreement: undefined })
  }

  // 采纳 B 的分类（用 B 覆盖 A，清除分歧标记）
  function acceptB(i: number) {
    const d = rows[i].disagreement
    if (!d) return
    updateRow(i, {
      category_l1: d.category_l1,
      category_l2: d.category_l2,
      domain: d.domain,
      disagreement: undefined,
    })
  }

  // ── 下载 ──

  async function handleDownload() {
    setDownloading(true)
    try {
      const baseName = file?.name.replace(/\.(xlsx|xls)$/i, '') || '审计问题分析结果'
      await downloadAuditExcel(rows, baseName)
    } catch (e: unknown) {
      setError(getErrorMessage(e, '下载失败'))
    } finally {
      setDownloading(false)
    }
  }

  // ── 统计数据（report 阶段用）──

  function calcStats(key: 'category_l1' | 'domain') {
    const counts: Record<string, number> = {}
    for (const r of rows) {
      const val = r[key] || '未分类'
      counts[val] = (counts[val] || 0) + 1
    }
    return Object.entries(counts).map(([name, value]) => ({ name, value }))
  }

  const disagreementCount = rows.filter(r => r.disagreement).length

  // ════════════════════════════════════════════════════════════════
  // RENDER
  // ════════════════════════════════════════════════════════════════

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5 my-3 max-w-3xl">

      {/* ── Phase 1: 上传 + 配置 ── */}
      {phase === 'upload' && (
        <>
          <div className="text-sm font-semibold text-slate-200 mb-4">🔍 审计问题智能分析</div>

          {/* 文件上传区 */}
          <div
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`
              border-2 border-dashed rounded-xl p-6 mb-5 text-center cursor-pointer transition-colors
              ${dragging ? 'border-indigo-400 bg-indigo-900/20' : 'border-slate-600 hover:border-slate-500 hover:bg-slate-700/30'}
            `}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) handleFileSelect(f) }}
            />
            {file ? (
              <div>
                <div className="text-2xl mb-1">📄</div>
                <div className="text-sm text-indigo-300 font-medium">{file.name}</div>
                <div className="text-xs text-slate-500 mt-1">点击重新选择</div>
              </div>
            ) : (
              <div>
                <div className="text-2xl mb-1">📂</div>
                <div className="text-sm text-slate-400">点击或拖拽上传审计 Excel 文件</div>
                <div className="text-xs text-slate-600 mt-1">支持 .xlsx / .xls</div>
              </div>
            )}
          </div>

          {/* 问题类别说明（固定体系，不可编辑） */}
          <div className="bg-slate-700/30 rounded-xl p-4 mb-4">
            <div className="text-xs font-medium text-slate-400 mb-1">问题类别</div>
            <div className="text-xs text-slate-500">
              固定采用企业审计问题分类体系（13个一级大类，含对应二级子类），由 AI 自动匹配。
            </div>
          </div>

          {/* 业务领域配置 */}
          <div className="bg-slate-700/30 rounded-xl p-4 mb-4">
            <TagGroup label="业务领域（可增删）" tags={domains} onChange={setDomains} />
          </div>

          {error && <div className="text-xs text-red-400 mb-3">{error}</div>}

          <div className="flex gap-3">
            <button
              onClick={handleCancel}
              className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 border border-slate-600 rounded-lg transition-colors"
            >
              取消
            </button>
            <button
              onClick={startAnalyze}
              disabled={!file}
              className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
            >
              开始分析
            </button>
          </div>
        </>
      )}

      {/* ── Phase 2: 分析中 ── */}
      {phase === 'analyzing' && (
        <div className="py-8 text-center">
          <div className="text-3xl mb-3">⏳</div>
          <div className="text-sm font-medium text-slate-200 mb-1">双模型交叉分析中…</div>
          <div className="text-xs text-slate-500">模型A 初步分类 → 模型B 交叉校验，耗时约为单次的 2 倍，请稍候</div>
          <div className="flex justify-center gap-1 mt-5">
            {[0, 150, 300].map(delay => (
              <span
                key={delay}
                className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce"
                style={{ animationDelay: `${delay}ms` }}
              />
            ))}
          </div>
        </div>
      )}

      {/* ── Phase 3: 审查确认 ── */}
      {phase === 'review' && (
        <>
          <div className="text-sm font-semibold text-slate-200 mb-1">
            ✅ 分类完成，请审查确认（共 {rows.length} 条）
          </div>
          <div className="text-xs text-slate-500 mb-3">可修改下方下拉框中的分类结果；修改一级类别时二级自动切换</div>

          {/* 分歧汇总提示 */}
          {disagreementCount > 0 && (
            <div className="text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 mb-3">
              ⚠ 共 {disagreementCount} 条（橙色行）存在分类分歧，请选择「用A」或「用B」的分类后再生成报告
            </div>
          )}

          <div className="overflow-x-auto rounded-xl border border-slate-700 mb-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-700/60">
                  <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-12">序号</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-36">发现问题</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-36">问题类别一级</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-36">问题类别二级</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-28">业务领域</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => {
                  const hasDisagreement = !!row.disagreement
                  const rowBg = hasDisagreement
                    ? 'bg-amber-900/30'
                    : i % 2 === 0 ? 'bg-slate-800' : 'bg-slate-800/60'

                  return (
                    <tr key={row.seq} className={rowBg}>
                      {/* 序号 + 分歧标记 */}
                      <td className="px-3 py-2 text-slate-400 text-center">
                        <div className="flex flex-col items-center gap-1">
                          <span>{row.seq}</span>
                          {hasDisagreement && (
                            <span className="text-[10px] text-amber-400 font-medium">⚠ 分歧</span>
                          )}
                        </div>
                      </td>

                      {/* 发现问题 */}
                      <td
                        className="px-3 py-2 text-slate-200 text-xs max-w-[144px] truncate"
                        title={row.issue}
                      >
                        {row.issue}
                      </td>

                      {/* 一级类别 select */}
                      <td className="px-3 py-2">
                        <select
                          value={row.category_l1}
                          onChange={e => {
                            const l1 = e.target.value
                            updateRow(i, {
                              category_l1: l1,
                              category_l2: CATEGORY_TAXONOMY[l1]?.[0] ?? '',
                              disagreement: undefined,
                            })
                          }}
                          className="w-full bg-slate-700 border border-slate-600 text-slate-200 text-xs rounded px-2 py-1 outline-none focus:border-indigo-500"
                        >
                          {row.category_l1 === '' && <option value="">未分类</option>}
                          {L1_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                        </select>
                        {/* A/B 选择按钮（仅分歧行） */}
                        {hasDisagreement && (
                          <div className="flex gap-1 mt-1.5">
                            <button
                              onClick={() => acceptA(i)}
                              className="flex-1 text-[10px] px-1 py-0.5 bg-indigo-700/60 hover:bg-indigo-600/80 text-indigo-200 rounded transition-colors"
                              title={`模型A：${row.category_l1}`}
                            >
                              用A
                            </button>
                            <button
                              onClick={() => acceptB(i)}
                              className="flex-1 text-[10px] px-1 py-0.5 bg-amber-700/60 hover:bg-amber-600/80 text-amber-200 rounded transition-colors"
                              title={`模型B：${row.disagreement?.category_l1}`}
                            >
                              用B
                            </button>
                          </div>
                        )}
                      </td>

                      {/* 二级类别 select（随一级联动） */}
                      <td className="px-3 py-2">
                        <select
                          value={row.category_l2}
                          onChange={e => updateRow(i, { category_l2: e.target.value, disagreement: undefined })}
                          className="w-full bg-slate-700 border border-slate-600 text-slate-200 text-xs rounded px-2 py-1 outline-none focus:border-indigo-500"
                        >
                          {row.category_l2 === '' && <option value="">未分类</option>}
                          {(CATEGORY_TAXONOMY[row.category_l1] ?? []).map(c => (
                            <option key={c} value={c}>{c}</option>
                          ))}
                        </select>
                        {/* B 的建议值提示 */}
                        {hasDisagreement && row.disagreement?.category_l2 && (
                          <div className="text-[10px] text-amber-400/70 mt-1 truncate" title={`B建议：${row.disagreement.category_l2}`}>
                            B: {row.disagreement.category_l2}
                          </div>
                        )}
                      </td>

                      {/* 业务领域 select */}
                      <td className="px-3 py-2">
                        <select
                          value={row.domain}
                          onChange={e => updateRow(i, { domain: e.target.value, disagreement: undefined })}
                          className="w-full bg-slate-700 border border-slate-600 text-slate-200 text-xs rounded px-2 py-1 outline-none focus:border-indigo-500"
                        >
                          {row.domain === '' && <option value="">未分类</option>}
                          {domains.map(d => <option key={d} value={d}>{d}</option>)}
                        </select>
                        {/* B 的建议值提示 */}
                        {hasDisagreement && row.disagreement?.domain && (
                          <div className="text-[10px] text-amber-400/70 mt-1 truncate" title={`B建议：${row.disagreement.domain}`}>
                            B: {row.disagreement.domain}
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => setPhase('upload')}
              className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 border border-slate-600 rounded-lg transition-colors"
            >
              重新上传
            </button>
            <button
              onClick={() => setPhase('report')}
              className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg transition-colors"
            >
              生成报告
            </button>
          </div>
        </>
      )}

      {/* ── Phase 4: 可视化报告 ── */}
      {phase === 'report' && (
        <>
          <div className="text-sm font-semibold text-slate-200 mb-4">📊 审计发现问题分析报告</div>

          <PieSection
            title="问题类别分布（一级）"
            data={calcStats('category_l1')}
            total={rows.length}
            suffix="问题"
          />
          <PieSection
            title="业务领域风险分布"
            data={calcStats('domain')}
            total={rows.length}
            suffix="领域"
          />

          {error && <div className="text-xs text-red-400 mb-3">{error}</div>}

          <div className="flex gap-3 mt-2">
            <button
              onClick={() => setPhase('review')}
              className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 border border-slate-600 rounded-lg transition-colors"
            >
              返回修改
            </button>
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="flex items-center gap-2 px-5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
            >
              {downloading ? '下载中…' : '📥 下载 Excel'}
            </button>
            <button
              onClick={() => {
                const wasEdited = JSON.stringify(rows) !== JSON.stringify(originalRows)
                submitLlmFeedback(traceIds, true, wasEdited ? rows : null)
                onComplete(`✅ 审计分析完成！共分析 ${rows.length} 条问题，报告已生成。`)
              }}
              className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 border border-slate-600 rounded-lg transition-colors"
            >
              完成
            </button>
          </div>
        </>
      )}
    </div>
  )
}
