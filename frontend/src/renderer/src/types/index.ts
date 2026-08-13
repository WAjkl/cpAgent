// 需求偏好（对齐后端 WorkingMemory prefs）
export type UseCase = 'gaming' | 'productivity' | 'balanced'
export type Resolution = '1080p' | '2K' | '4K'

export type SearchMode = 'snapshot' | 'online'

export interface Prefs {
  budget: number
  use_case: UseCase
  resolution: Resolution | ''
  exclude: string[]
  mode: SearchMode
}

// 配件明细（对齐后端 config_gen 的 part 对象）
export interface PartInfo {
  model: string
  brand?: string
  price_cny: number | string
  price_low?: number | null
  price_high?: number | null
  price_source: 'live' | 'estimate'
  confidence?: number
  fetched_at?: string
  level?: 'fresh' | 'stale' | 'expired'
  price?: number
  // 各配件规格（可选）
  socket?: string
  cores_threads?: string
  vram_gb?: number
  vram_type?: string
  wattage_w?: number
  type?: string
  kit?: string
  capacity_gb?: number
  interface?: string
  chipset?: string
  form?: string
  tier?: string
  [key: string]: unknown
}

// 配置单（对齐后端 config_gen 输出）
export interface Config {
  id: string
  total_price: number
  use_case: UseCase
  resolution?: string
  budget: number
  score: { gaming: number; productivity: number }
  parts: {
    cpu: PartInfo
    gpu: PartInfo
    memory: PartInfo
    ssd: PartInfo
    psu: PartInfo
    motherboard: PartInfo
  }
  compatibility: { ok: boolean; problems: string[] }
  price_freshness: Record<string, number>
  warnings: string[]
  generated_at: string
}

// 消息
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  config?: Config
  status: 'streaming' | 'done' | 'error'
  feedback?: 'up' | 'down' | null
  createdAt: number
}

// 会话
export interface Conversation {
  id: string
  title: string
  messages: Message[]
  prefs: Prefs
  pinned?: boolean
  updatedAt: number
}

export type Theme = 'light' | 'dark'

// 前端全局 electronAPI（preload 暴露）
export interface ElectronAPI {
  platform: string
  versions: { electron: string; chrome: string; node: string }
  backendUrl: () => Promise<string>
  proxy: (method: string, path: string, body?: unknown) => Promise<{ status: number; body: string }>
  on: (channel: string, cb: (...args: unknown[]) => void) => () => void
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}
