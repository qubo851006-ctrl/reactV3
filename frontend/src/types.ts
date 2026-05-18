export type Stage =
  | 'idle'
  | 'thinking'
  | 'waiting_files'
  | 'waiting_dept'
  | 'processing'
  | 'waiting_ledger_files'
  | 'processing_ledger'
  | 'waiting_auth_file'
  | 'processing_auth'
  | 'download_training_excel'
  | 'download_ledger_excel'
  | 'download_compliance_excel'
  | 'waiting_ledger_merge_files'
  | 'waiting_audit_file'
  | 'waiting_compliance_file'

export interface Message {
  role: 'user' | 'assistant'
  content: string
}

/** 所有 Flow 组件共享的 props 接口 */
export interface FlowProps {
  onComplete: (reply: string) => void
  onCancel: () => void
  visionModel?: string
  canManageResponsiblePersons?: boolean
}

/** 侧边栏技能按钮的 key，新增技能在此加一个联合类型成员 */
export type SkillKey = 'training' | 'ledger' | 'auth' | 'merge' | 'audit' | 'compliance'

export interface SessionMeta {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface TrainingResult {
  topic: string
  location: string
  date: string
  department: string
  count: number
  category: string
  archive_path: string
  pending_upload_id?: string
  excel_path: string
  confidence: 'high' | 'low'
  reflection_note: string
  start_time: string
  end_time: string
  duration_hours: number
  /** trace ids from the audit DB, for P1-2 feedback */
  llm_trace_ids?: string[]
}

export interface LedgerStage {
  审级: string
  处理结果: string
}

export interface LedgerCaseData {
  案件名称: string
  案件发生时间: string | null
  案由: string
  诉讼主体: string
  主诉被诉: string
  标的金额: number | null
  基本情况: string
  生效判决日期: string | null
  强制执行时间: string | null
  服务律所: string | null
  stages: LedgerStage[]
  案号列表: string[]
}

export interface LedgerPreview {
  case_data: LedgerCaseData
  match_idx: number | null
  is_new: boolean
  action_text: string
  archive_dir: string
  existing_archive_name?: string
  pending_archive_id?: string
  existing_count: number
  /** trace ids from the audit DB, for P1-2 feedback */
  llm_trace_ids?: string[]
}
