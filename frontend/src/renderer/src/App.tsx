import { useEffect, useState } from 'react'
import { useChatStore } from './store/chatStore'
import Sidebar from './components/Sidebar'
import RequirementsPanel from './components/RequirementsPanel'
import MessageList from './components/MessageList'
import ChatInput from './components/ChatInput'
import ContextPanel from './components/ContextPanel'
import KeySettingsModal from './components/KeySettingsModal'

export default function App(): JSX.Element {
  const theme = useChatStore((s) => s.theme)
  const conversations = useChatStore((s) => s.conversations)
  const newConversation = useChatStore((s) => s.newConversation)
  const sidebarCollapsed = useChatStore((s) => s.sidebarCollapsed)
  const [settingsOpen, setSettingsOpen] = useState(false)

  // 主题应用到根元素
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])

  // 首次启动自动新建一个对话
  useEffect(() => {
    if (conversations.length === 0) newConversation()
  }, [conversations.length, newConversation])

  return (
    <div className="flex h-screen overflow-hidden bg-white text-gray-900 dark:bg-gray-900 dark:text-gray-100">
      {/* 左栏：对话管理 */}
      <Sidebar onOpenSettings={() => setSettingsOpen(true)} />

      {/* 中栏：对话主区（需求面板 + 消息流 + 输入） */}
      <main className="flex min-w-0 flex-1 flex-col border-x border-gray-200 dark:border-gray-800">
        {!sidebarCollapsed && <RequirementsPanel />}
        <MessageList />
        <ChatInput />
      </main>

      {/* 右栏：上下文栏 */}
      <ContextPanel />

      {/* API Key 设置弹窗 */}
      {settingsOpen && <KeySettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  )
}
