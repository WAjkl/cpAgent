import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Config, Conversation, Message, Prefs, Theme, UseCase, Resolution } from '../types'
import { chatSSE, chatMock, backendAlive } from '../lib/api'
import { uid } from '../lib/utils'

const DEFAULT_PREFS: Prefs = { budget: 8000, use_case: 'gaming', resolution: '2K', exclude: [], mode: 'snapshot' }

// 从自然语言提取需求要素（与后端 memory.py 对应）
function parsePrefsFromText(text: string, base: Prefs): Prefs {
  const t = text.toLowerCase()
  const out: Prefs = { ...base }
  const m = t.match(/(\d{3,6})\s*(?:元|块|k\b|预算)/) ?? t.match(/(?:预算|不超过|以内|以下)\s*(\d{3,6})/) ?? t.match(/^\s*(\d{3,6})(?![0-9])/)
  if (m) {
    let v = parseInt(m[1], 10)
    if (v < 100) v *= 1000
    out.budget = v
  }
  if (/(游戏|打游戏|gaming)/.test(t)) out.use_case = 'gaming'
  else if (/(生产力|设计|剪辑|渲染|编程|production)/.test(t)) out.use_case = 'productivity'
  else if (/均衡/.test(t)) out.use_case = 'balanced'
  if (/4k/.test(t)) out.resolution = '4K'
  else if (/2k/.test(t)) out.resolution = '2K'
  else if (/1080/.test(t)) out.resolution = '1080p'
  if (/(不要显示器|不含显示器|无显示器|不要屏幕)/.test(t)) {
    if (!out.exclude.includes('monitor')) out.exclude = [...out.exclude, 'monitor']
  }
  if (/(不要外设|不要键鼠|无外设)/.test(t)) {
    if (!out.exclude.includes('peripherals')) out.exclude = [...out.exclude, 'peripherals']
  }
  return out
}

function autoTitle(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length > 16 ? clean.slice(0, 16) + '…' : clean || '新对话'
}

interface ChatState {
  conversations: Conversation[]
  activeId: string | null
  theme: Theme
  sidebarCollapsed: boolean
  // 双向联动：记录最后操作来源（panel=面板控件，input=自然语言）
  lastTouch: 'panel' | 'input'

  newConversation: () => void
  setActive: (id: string) => void
  setPrefs: (prefs: Partial<Prefs>, touch?: 'panel' | 'input') => void
  sendMessage: (text: string) => Promise<void>
  regenerate: () => Promise<void>
  setFeedback: (msgId: string, fb: 'up' | 'down' | null) => void
  pinConversation: (id: string) => void
  renameConversation: (id: string, title: string) => void
  deleteConversation: (id: string) => void
  toggleTheme: () => void
  toggleSidebar: () => void
}

const activeConv = (s: ChatState): Conversation | undefined =>
  s.conversations.find((c) => c.id === s.activeId)

function patchMessage(s: ChatState, convId: string, msgId: string, patch: Partial<Message>): Conversation[] {
  return s.conversations.map((c) =>
    c.id === convId
      ? { ...c, messages: c.messages.map((m) => (m.id === msgId ? { ...m, ...patch } : m)), updatedAt: Date.now() }
      : c
  )
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
  conversations: [],
  activeId: null,
  theme: (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') as Theme,
  sidebarCollapsed: false,
  lastTouch: 'input',

  newConversation: () => {
    const conv: Conversation = {
      id: uid('sess-'),
      title: '新对话',
      messages: [],
      prefs: { ...DEFAULT_PREFS },
      updatedAt: Date.now()
    }
    set((s) => ({ conversations: [conv, ...s.conversations], activeId: conv.id }))
  },

  setActive: (id) => set({ activeId: id }),

  setPrefs: (prefs, touch = 'panel') => {
    const { activeId } = get()
    if (!activeId) return
    set((s) => ({
      lastTouch: touch,
      conversations: s.conversations.map((c) =>
        c.id === activeId ? { ...c, prefs: { ...c.prefs, ...prefs } } : c
      )
    }))
  },

  sendMessage: async (text) => {
    const trimmed = text.trim()
    if (!trimmed) return
    const { activeId, conversations } = get()
    if (!activeId) return

    // 融合规则：自然语言解析 prefs（以本次输入为准）
    const conv = conversations.find((c) => c.id === activeId)
    const newPrefs = parsePrefsFromText(trimmed, conv?.prefs ?? DEFAULT_PREFS)

    const userMsg: Message = { id: uid('m-'), role: 'user', content: trimmed, status: 'done', createdAt: Date.now() }
    const assistantMsg: Message = { id: uid('m-'), role: 'assistant', content: '', status: 'streaming', createdAt: Date.now() }

    set((s) => ({
      lastTouch: 'input',
      conversations: s.conversations.map((c) =>
        c.id === activeId
          ? {
              ...c,
              title: c.messages.length === 0 ? autoTitle(trimmed) : c.title,
              prefs: newPrefs,
              messages: [...c.messages, userMsg, assistantMsg],
              updatedAt: Date.now()
            }
          : c
      )
    }))

    const alive = await backendAlive()
    const handlers = {
      onDelta: (d: string) =>
        set((s) => ({ conversations: patchMessage(s, activeId, assistantMsg.id, { content: (s.conversations.find((c) => c.id === activeId)?.messages.find((m) => m.id === assistantMsg.id)?.content ?? '') + d }) })),
      onConfig: (cfg: Config) =>
        set((s) => ({ conversations: patchMessage(s, activeId, assistantMsg.id, { config: cfg }) })),
      onDone: () => set((s) => ({ conversations: patchMessage(s, activeId, assistantMsg.id, { status: 'done' }) }))
    }

    try {
      if (alive) {
        await chatSSE(trimmed, activeId, handlers, newPrefs)
      } else {
        await chatMock(trimmed, handlers)
      }
    } catch (e) {
      const errText = e instanceof Error ? e.message : String(e)
      set((s) => ({
        conversations: patchMessage(s, activeId, assistantMsg.id, {
          content: `请求失败：${errText}\n\n（请确认后端服务已启动：` + '`python -m backend.server`' + `）`,
          status: 'error'
        })
      }))
    }
  },

  regenerate: async () => {
    const { activeId } = get()
    if (!activeId) return
    const conv = get().conversations.find((c) => c.id === activeId)
    if (!conv) return
    // 找最后一条 user 消息
    const lastUser = [...conv.messages].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    // 移除最后一条 assistant 回复后重新发送
    set((s) => ({
      conversations: s.conversations.map((c) => {
        if (c.id !== activeId) return c
        const msgs = [...c.messages]
        while (msgs.length && msgs[msgs.length - 1].role === 'assistant') msgs.pop()
        return { ...c, messages: msgs }
      })
    }))
    await get().sendMessage(lastUser.content)
  },

  setFeedback: (msgId, fb) => {
    const { activeId } = get()
    if (!activeId) return
    set((s) => ({ conversations: patchMessage(s, activeId, msgId, { feedback: fb }) }))
  },

  pinConversation: (id) =>
    set((s) => ({ conversations: s.conversations.map((c) => (c.id === id ? { ...c, pinned: !c.pinned } : c)) })),

  renameConversation: (id, title) =>
    set((s) => ({ conversations: s.conversations.map((c) => (c.id === id ? { ...c, title } : c)) })),

  deleteConversation: (id) =>
    set((s) => {
      const rest = s.conversations.filter((c) => c.id !== id)
      return { conversations: rest, activeId: s.activeId === id ? (rest[0]?.id ?? null) : s.activeId }
    }),

  toggleTheme: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark'
    set({ theme: next })
    document.documentElement.classList.toggle('dark', next === 'dark')
  },

  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed }))
    }),
    {
      name: 'cpagent-chat-storage',
      partialize: (s) => ({
        conversations: s.conversations,
        activeId: s.activeId,
        theme: s.theme,
        sidebarCollapsed: s.sidebarCollapsed
      })
    }
  )
)
