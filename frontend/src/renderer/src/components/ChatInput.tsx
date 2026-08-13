import { useState } from 'react'
import { useChatStore } from '../store/chatStore'

export default function ChatInput(): JSX.Element {
  const sendMessage = useChatStore((s) => s.sendMessage)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (): Promise<void> => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setText('')
    await sendMessage(trimmed)
    setBusy(false)
  }

  return (
    <div className="border-t border-gray-200 p-3 dark:border-gray-800">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          rows={1}
          placeholder="描述你的装机需求，Enter 发送，Shift+Enter 换行…"
          className="max-h-40 min-h-[42px] flex-1 resize-none rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm outline-none focus:border-primary dark:border-gray-700 dark:bg-gray-900"
        />
        <button
          onClick={submit}
          disabled={busy || !text.trim()}
          className="rounded-xl bg-primary px-5 py-2.5 text-sm font-medium text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? '…' : '发送'}
        </button>
      </div>
    </div>
  )
}
