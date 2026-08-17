import type { Config, UseCase, Resolution, Prefs } from '../types'
import { MOCK_CONFIGS, MOCK_REPLY } from './mock'

// 默认后端地址 8766：本机 IDE 面板进程常驻占用 8765（启动后端请用默认端口，
// 或 CPAGENT_PORT 指定后同步修改这里；前端 main 进程支持 CPAGENT_BACKEND_URL 覆盖）
const BACKEND = 'http://127.0.0.1:8766'

// SSE 事件类型（对齐后端 server.py）
export type ChatEvent =
  | { type: 'status'; session_id: string; routing: unknown }
  | { type: 'delta'; text: string }
  | { type: 'config'; config: Config }
  | { type: 'done'; session_id: string; turn_id: string; evidence_ids: string[]; timeout: boolean }
  | { type: 'warn'; text: string }

export interface ChatHandlers {
  onDelta: (text: string) => void
  onConfig: (config: Config) => void
  onDone: () => void
}

/** 后端是否可达 */
export async function backendAlive(): Promise<boolean> {
  try {
    const resp = await fetch(`${BACKEND}/health`, { signal: AbortSignal.timeout(1500) })
    return resp.ok
  } catch {
    return false
  }
}

/** 直接生成配置单（非流式） */
export async function generateConfig(
  budget: number,
  use_case: UseCase,
  resolution: Resolution | ''
): Promise<Config> {
  const resp = await fetch(`${BACKEND}/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ budget, use_case, resolution: resolution || null, top_k: 1 })
  })
  if (!resp.ok) {
    const err = await resp.text().catch(() => '')
    throw new Error(`配置生成失败 (${resp.status})${err ? ': ' + err.slice(0, 200) : ''}`)
  }
  const data = await resp.json()
  return data.configs[0] as Config
}

/** SSE 流式对话 */
export async function chatSSE(
  message: string,
  sessionId: string,
  handlers: ChatHandlers,
  prefs?: Prefs
): Promise<void> {
  const resp = await fetch(`${BACKEND}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, prefs })
  })
  if (!resp.ok || !resp.body) throw new Error(`chat 请求失败 (${resp.status})`)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const processEvent = (data: string): void => {
    let evt: ChatEvent
    try {
      evt = JSON.parse(data)
    } catch {
      return
    }
    switch (evt.type) {
      case 'delta':
        handlers.onDelta(evt.text)
        break
      case 'config':
        handlers.onConfig(evt.config)
        break
      case 'done':
        handlers.onDone()
        break
    }
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''
    for (const chunk of chunks) {
      for (const line of chunk.split('\n')) {
        if (line.startsWith('data: ')) processEvent(line.slice(6))
      }
    }
  }
  if (buffer.trim()) {
    for (const line of buffer.split('\n')) {
      if (line.startsWith('data: ')) processEvent(line.slice(6))
    }
  }
}

/** 离线降级：用 Mock 数据模拟一次推荐 */
export async function chatMock(
  message: string,
  handlers: ChatHandlers
): Promise<void> {
  // 简单解析预算/用途选 Mock 配置
  const m = message.match(/\d{3,6}/)
  const budget = m ? parseInt(m[0], 10) : 8000
  const cfg = MOCK_CONFIGS.find((c) => c.budget >= budget) ?? MOCK_CONFIGS[0]

  const reply = MOCK_REPLY
  // 逐字模拟流式
  for (let i = 0; i < reply.length; i += 3) {
    handlers.onDelta(reply.slice(i, i + 3))
    await new Promise((r) => setTimeout(r, 8))
  }
  handlers.onConfig(cfg)
  handlers.onDone()
}

// ---------- key 状态 ----------
export interface KeyStatus {
  configured: boolean
  valid: boolean
  masked: string
}
export interface KeysStatus {
  deepseek: KeyStatus
  tavily: KeyStatus
}

export async function getKeysStatus(): Promise<KeysStatus> {
  const resp = await fetch(`${BACKEND}/keys/status`)
  return resp.json()
}

export async function saveKeys(keys: { deepseek_key?: string; tavily_key?: string }): Promise<{ ok: boolean }> {
  const resp = await fetch(`${BACKEND}/keys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(keys)
  })
  return resp.json()
}

