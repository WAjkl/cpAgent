import { useChatStore } from '../store/chatStore'
import MessageBubble from './MessageBubble'

export default function MessageList(): JSX.Element {
  const conv = useChatStore((s) => s.conversations.find((c) => c.id === s.activeId))
  const messages = conv?.messages ?? []

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-4 p-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="mb-3 text-4xl">🖥️</div>
            <h2 className="mb-1 text-lg font-semibold">装机顾问</h2>
            <p className="text-sm text-gray-400">
              描述你的需求，例如「8000 打游戏 2K 不要显示器」
              <br />
              或在上方面板调整预算与用途
            </p>
          </div>
        ) : (
          messages.map((m) => <MessageBubble key={m.id} msg={m} />)
        )}
      </div>
    </div>
  )
}
