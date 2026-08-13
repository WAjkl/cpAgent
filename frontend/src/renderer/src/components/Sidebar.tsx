import { useState } from 'react'
import { useChatStore } from '../store/chatStore'
import { cn } from '../lib/utils'
import type { Conversation } from '../types'

export default function Sidebar({ onOpenSettings }: { onOpenSettings: () => void }): JSX.Element {
  const conversations = useChatStore((s) => s.conversations)
  const activeId = useChatStore((s) => s.activeId)
  const newConversation = useChatStore((s) => s.newConversation)
  const setActive = useChatStore((s) => s.setActive)
  const pinConversation = useChatStore((s) => s.pinConversation)
  const renameConversation = useChatStore((s) => s.renameConversation)
  const deleteConversation = useChatStore((s) => s.deleteConversation)
  const toggleSidebar = useChatStore((s) => s.toggleSidebar)

  const [search, setSearch] = useState('')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameVal, setRenameVal] = useState('')

  const filtered = conversations.filter((c) => c.title.toLowerCase().includes(search.toLowerCase()))
  const sorted = [...filtered].sort((a, b) => {
    if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1
    return b.updatedAt - a.updatedAt
  })

  const startRename = (c: Conversation): void => {
    setRenamingId(c.id)
    setRenameVal(c.title)
  }
  const commitRename = (): void => {
    if (renamingId && renameVal.trim()) renameConversation(renamingId, renameVal.trim())
    setRenamingId(null)
  }

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-950">
      {/* 顶部 */}
      <div className="flex items-center gap-2 p-3">
        <button
          onClick={newConversation}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          <span className="text-base leading-none">＋</span> 新建对话
        </button>
        <button
          onClick={toggleSidebar}
          className="rounded-lg px-2 py-2 text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-800"
          title="折叠侧边栏"
        >
          ⟨
        </button>
      </div>

      {/* 搜索 */}
      <div className="px-3 pb-2">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索对话…"
          className="w-full rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm outline-none focus:border-primary dark:border-gray-700 dark:bg-gray-900"
        />
      </div>

      {/* 历史列表 */}
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {sorted.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-gray-400">暂无对话</p>
        ) : (
          <ul className="space-y-1">
            {sorted.map((c) => (
              <li key={c.id}>
                {renamingId === c.id ? (
                  <input
                    autoFocus
                    value={renameVal}
                    onChange={(e) => setRenameVal(e.target.value)}
                    onBlur={commitRename}
                    onKeyDown={(e) => e.key === 'Enter' && commitRename()}
                    className="w-full rounded-lg border border-primary bg-white px-2 py-1.5 text-sm outline-none dark:bg-gray-900"
                  />
                ) : (
                  <div
                    onClick={() => setActive(c.id)}
                    className={cn(
                      'group flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-2 text-sm',
                      activeId === c.id
                        ? 'bg-primary-light text-primary dark:bg-gray-800'
                        : 'hover:bg-gray-200 dark:hover:bg-gray-800'
                    )}
                  >
                    {c.pinned && <span className="text-xs">📌</span>}
                    <span
                      className="flex-1 truncate"
                      onDoubleClick={() => startRename(c)}
                      title="双击重命名"
                    >
                      {c.title}
                    </span>
                    <span className="hidden items-center gap-0.5 group-hover:flex">
                      <button
                        onClick={(e) => { e.stopPropagation(); pinConversation(c.id) }}
                        className="rounded px-1 text-xs text-gray-400 hover:text-primary"
                        title="置顶"
                      >
                        📌
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); startRename(c) }}
                        className="rounded px-1 text-xs text-gray-400 hover:text-primary"
                        title="重命名"
                      >
                        ✎
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); if (confirm('删除该对话？')) deleteConversation(c.id) }}
                        className="rounded px-1 text-xs text-gray-400 hover:text-red-500"
                        title="删除"
                      >
                        ✕
                      </button>
                    </span>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 底部：API Key 设置 / 配置库入口 */}
      <div className="space-y-2 border-t border-gray-200 p-3 dark:border-gray-800">
        <button
          onClick={onOpenSettings}
          className="w-full rounded-lg border border-primary/40 bg-primary/5 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/10"
          title="配置 DeepSeek / Tavily API Key"
        >
          ⚙️ API Key 设置
        </button>
        <button
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
          title="历史配置库（后续版本）"
        >
          📚 配置库
        </button>
      </div>
    </aside>
  )
}
