import type { SkillKey, Stage } from '../types'

export interface SkillDefinition {
  key: SkillKey
  icon: string
  label: string
  sidebarDesc: string
  welcomeLabel: string
  welcomeDesc: string
  welcomeColor: string
  iconBg: string
  iconText: string
  trigger: {
    msg: string
    reply: string
    stage: Stage
  }
}

export interface DownloadDefinition {
  stage: Stage
  label: string
}

export const SKILLS: SkillDefinition[] = [
  {
    key: 'training',
    icon: '📊',
    label: '培训统计及归档',
    sidebarDesc: '上传培训通知+签到表，自动统计归档',
    welcomeLabel: '培训统计',
    welcomeDesc: '培训通知 + 签到表归档',
    welcomeColor: 'border-blue-500/30 hover:border-blue-500/60 hover:bg-blue-500/5',
    iconBg: 'bg-blue-500/15',
    iconText: 'text-blue-400',
    trigger: {
      msg: '📊 培训统计及归档',
      reply: '好的！请上传以下两个文件：\n\n- 📄 **培训通知**（PDF 格式）\n- ✍️ **签到表**（图片格式：JPG / PNG）',
      stage: 'waiting_files',
    },
  },
  {
    key: 'ledger',
    icon: '⚖️',
    label: '案件台账生成',
    sidebarDesc: '上传法律文书，自动提取并更新台账',
    welcomeLabel: '案件台账',
    welcomeDesc: '法律文书 → 台账提取',
    welcomeColor: 'border-violet-500/30 hover:border-violet-500/60 hover:bg-violet-500/5',
    iconBg: 'bg-violet-500/15',
    iconText: 'text-violet-400',
    trigger: {
      msg: '⚖️ 案件台账生成',
      reply: '好的！请上传案件的法律文书文件（支持 **PDF / DOCX / DOC**，可多选）。\n\n系统会自动识别文书类型，并判断是否为台账中的已有案件。',
      stage: 'waiting_ledger_files',
    },
  },
  {
    key: 'auth',
    icon: '📝',
    label: '授权请示起草',
    sidebarDesc: '上传依据文件和授权委托书，起草授权请示Word',
    welcomeLabel: '授权请示',
    welcomeDesc: '依据文件 + 授权书 → 授权请示',
    welcomeColor: 'border-emerald-500/30 hover:border-emerald-500/60 hover:bg-emerald-500/5',
    iconBg: 'bg-emerald-500/15',
    iconText: 'text-emerald-400',
    trigger: {
      msg: '📝 授权请示起草',
      reply: '好的！请上传**依据文件 PDF**和**授权委托书**（支持 PDF / DOC / DOCX）。\n\n系统会先提取字段，再请你确认授权方式、份数、印章等信息，确认正文后生成授权请示 Word。',
      stage: 'waiting_auth_file',
    },
  },
  {
    key: 'merge',
    icon: '🔀',
    label: '三台账合并',
    sidebarDesc: '合并采购/合同/财务系统导出台账',
    welcomeLabel: '三台账合并',
    welcomeDesc: '合同/采购/财务合并',
    welcomeColor: 'border-amber-500/30 hover:border-amber-500/60 hover:bg-amber-500/5',
    iconBg: 'bg-amber-500/15',
    iconText: 'text-amber-400',
    trigger: {
      msg: '🔀 三台账合并',
      reply: '好的！请分别上传三个系统导出的 Excel 台账：\n\n- 📘 **合同系统台账**（必填，作为合并主键）\n- 📗 **采购系统台账**（可选）\n- 📙 **财务系统台账**（可选）\n\n系统将以合同编号为关键字段自动合并，支持大小写、全角括号等差异的模糊匹配。',
      stage: 'waiting_ledger_merge_files',
    },
  },
  {
    key: 'audit',
    icon: '🔍',
    label: '审计问题分析',
    sidebarDesc: '上传审计汇总表，AI分类并生成报告',
    welcomeLabel: '审计分析',
    welcomeDesc: 'AI分类审计问题',
    welcomeColor: 'border-red-500/30 hover:border-red-500/60 hover:bg-red-500/5',
    iconBg: 'bg-red-500/15',
    iconText: 'text-red-400',
    trigger: {
      msg: '🔍 审计问题分析',
      reply: '好的！请上传**审计发现问题汇总表**（Excel 格式），系统将自动识别问题列，通过 AI 对每条问题进行**双维度分类**：\n\n- 📌 **问题类别**（内控缺陷 / 制度执行 / 资金管理 / 采购管理）\n- 🏢 **业务领域**（工程业务 / 酒店业务 / 物业管理 / 资产管理）\n\n分类完成后可审查修改，并生成可视化分析报告。',
      stage: 'waiting_audit_file',
    },
  },
  {
    key: 'compliance',
    icon: '📑',
    label: '合规审查台账',
    sidebarDesc: '上传OA审批PDF，生成累计台账',
    welcomeLabel: '合规审查台账',
    welcomeDesc: 'OA审批PDF → 累计台账',
    welcomeColor: 'border-cyan-500/30 hover:border-cyan-500/60 hover:bg-cyan-500/5',
    iconBg: 'bg-cyan-500/15',
    iconText: 'text-cyan-400',
    trigger: {
      msg: '📑 合规审查工作台账生成',
      reply: '好的！请上传 OA 流程表单及审批记录 PDF，系统会提取重大事项、程序、审查意见、签署时间和背景材料，确认后写入长期累计合规审查工作台账。',
      stage: 'waiting_compliance_file',
    },
  },
]

export const SKILL_TRIGGERS = Object.fromEntries(
  SKILLS.map(skill => [skill.key, skill.trigger]),
) as Record<SkillKey, SkillDefinition['trigger']>

export const DOWNLOAD_DEFINITIONS: DownloadDefinition[] = [
  { stage: 'download_training_excel', label: '下载培训统计表 Excel' },
  { stage: 'download_ledger_excel', label: '下载案件台账 Excel' },
  { stage: 'download_compliance_excel', label: '下载合规审查工作台账 Excel' },
]
