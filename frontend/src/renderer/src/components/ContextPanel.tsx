import { useChatStore } from '../store/chatStore'
import { useCaseLabel } from '../lib/utils'

// 右侧上下文栏（3.7 完整版含摘要/价格快照/推荐；此处 3.1-3.6 先做 prefs 快照）
export default function ContextPanel(): JSX.Element {
  const activeId = useChatStore((s) => s.activeId)
  const conv = useChatStore((s) => s.conversations.find((c) => c.id === s.activeId))
  const theme = useChatStore((s) => s.theme)
  const toggleTheme = useChatStore((s) => s.toggleTheme)

  return (
    <aside className="hidden w-64 shrink-0 flex-col md:flex">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-800">
        <span className="text-sm font-semibold">上下文</span>
        <button
          onClick={toggleTheme}
          className="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
          title="切换深浅主题"
        >
          {theme === 'dark' ? '🌙 深色' : '☀️ 浅色'}
        </button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
        <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">当前需求</div>
          {conv ? (
            <dl className="space-y-1.5">
              <div className="flex justify-between">
                <dt className="text-gray-500">预算</dt>
                <dd className="font-mono font-semibold">¥{conv.prefs.budget.toLocaleString()}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">用途</dt>
                <dd>{useCaseLabel(conv.prefs.use_case)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">分辨率</dt>
                <dd>{conv.prefs.resolution || '—'}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">排除</dt>
                <dd>{conv.prefs.exclude.length ? conv.prefs.exclude.join('、') : '无'}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-gray-400">暂无对话</p>
          )}
        </div>

        <div className="rounded-lg border border-dashed border-gray-300 p-3 text-xs text-gray-400 dark:border-gray-700">
          会话 {activeId?.slice(0, 8) ?? '—'}
          <br />
          摘要 / 价格快照 / 相关推荐将在后续版本完善
        </div>
      </div>
    </aside>
  )
}
