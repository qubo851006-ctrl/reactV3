export const DEFAULT_CHAT_MODEL = 'qwen2.5-72b'
export const DEFAULT_VISION_MODEL = 'qwen2.5-vl-72b'

export interface ModelOption {
  value: string
  label: string
  hint?: string
}

export interface ModelRoutes {
  default_chat_model: string
  default_vision_model: string
  chat_models: ModelOption[]
  vision_models: ModelOption[]
}

export const CHAT_MODEL_OPTIONS: ModelOption[] = [
  { value: 'qwen2.5-72b', label: 'Qwen2.5 72B', hint: '默认' },
  { value: 'DeepSeek-V3', label: 'DeepSeek V3', hint: '高速' },
  { value: 'glm-5-outside', label: 'GLM-5', hint: '集团' },
]

export const VISION_MODEL_OPTIONS: ModelOption[] = [
  { value: 'qwen2.5-vl-72b', label: 'Qwen2.5 VL 72B', hint: '默认' },
  { value: 'qwen3-vl:8b', label: 'Qwen3 VL 8B (本地)', hint: '本地' },
]

export type ChatModel = string
export type VisionModel = string

export function hasModel(value: string, options: ModelOption[]): boolean {
  return options.some(option => option.value === value)
}

export function isChatModel(value: string): value is ChatModel {
  return hasModel(value, CHAT_MODEL_OPTIONS)
}

export function isVisionModel(value: string): value is VisionModel {
  return hasModel(value, VISION_MODEL_OPTIONS)
}
