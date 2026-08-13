import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChatStore } from '../store/chatStore'
import ConfigCard from './ConfigCard'
import { cn } from '../lib/utils'
import type { Message } from '../types'

export default function MessageBubble({ msg }: { msg: Message }): JSX.Element {
  const setFeedback = useChatStore((s) => s.setFeedback)
  const regenerate = useChatStore((s) => s.regenerate)
  const [copied, setCopied] = useState(false)

  const isUser = msg.role === 'user'

  const copy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(msg.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      /* ignore */
    }
  }

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-white">
          <p className="whitespace-pre-wrap">{msg.content}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[88%]">
        <div className="rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-4 py-3 text-sm shadow-sm dark:border-gray-800 dark:bg-gray-900">
          <div className="markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
          </div>

          {msg.config && <ConfigCard config={msg.config} />}

          {msg.status === 'streaming' && (
            <span className="mt-1 inline-block h-4 w-1.5 animate-pulse bg-primary" />
          )}

          {msg.status === 'error' && (
            <p className="mt-1 text-xs text-red-500">⚠️ {msg.content}</p>
          )}
        </div>

        {/* 快捷操作 */}
        {msg.status === 'done' && msg.content && (
          <div className="mt-1 flex items-center gap-1 px-1 text-xs text-gray-400">
            <button onClick={copy} className="rounded px-1.5 py-0.5 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800">
              {copied ? '已复制' : '复制'}
            </button>
            <button onClick={regenerate} className="rounded px-1.5 py-0.5 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800">
              重新生成
            </button>
            <span className="mx-1">|</span>
            <button
              onClick={() => setFeedback(msg.id, msg.feedback === 'up' ? null : 'up')}
              className={cn('rounded px-1.5 py-0.5', msg.feedback === 'up' ? 'text-primary' : 'hover:text-gray-600')}
              title="有帮助"
            >
              👍
            </button>
            <button
              onClick={() => setFeedback(msg.id, msg.feedback === 'down' ? null : 'down')}
              className={cn('rounded px-1.5 py-0.5', msg.feedback === 'down' ? 'text-red-500' : 'hover:text-gray-600')}
              title="无帮助"
            >
              👎
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
