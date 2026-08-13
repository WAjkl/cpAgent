import { useCallback, useEffect, useState } from 'react'
import { getKeysStatus, saveKeys, type KeysStatus } from '../lib/api'

type KeyStatus = KeysStatus['deepseek']

/** 红绿灯：未配置 ⚪ / 可用 🟢 / 不可用 🔴 */
function statusDot(s: KeyStatus | undefined): string {
  if (!s || !s.configured) return '⚪'
  return s.valid ? '🟢' : '🔴'
}

function statusText(s: KeyStatus | undefined): string {
  if (!s) return '读取中…'
  if (!s.configured) return '未配置'
  return s.valid ? '可用' : '不可用'
}

function KeyField({
  label,
  placeholder,
  status,
  value,
  onChange,
  onSave,
  saving,
}: {
  label: string
  placeholder: string
  status: KeyStatus | undefined
  value: string
  onChange: (v: string) => void
  onSave: () => void
  saving: boolean
}): JSX.Element {
  return (
    <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs text-gray-500">
          {statusDot(status)} {statusText(status)}
        </span>
      </div>
      <div className="mt-1 font-mono text-xs text-gray-500">
        {status?.configured ? status.masked : '未配置'}
      </div>
      <div className="mt-2 flex gap-2">
        <input
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="min-w-0 flex-1 rounded border border-gray-200 px-2 py-1.5 text-xs outline-none focus:border-primary dark:border-gray-700 dark:bg-gray-950"
        />
        <button
          onClick={onSave}
          disabled={!value.trim() || saving}
          className="shrink-0 rounded bg-primary px-3 py-1.5 text-xs text-white disabled:opacity-40"
        >
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
    </div>
  )
}

export default function KeySettingsModal({ onClose }: { onClose: () => void }): JSX.Element {
  const [keys, setKeys] = useState<KeysStatus | null>(null)
  const [checking, setChecking] = useState(false)
  const [dsVal, setDsVal] = useState('')
  const [tvVal, setTvVal] = useState('')
  const [saving, setSaving] = useState<null | 'deepseek' | 'tavily'>(null)
  const [error, setError] = useState('')

  const refresh = useCallback(async (): Promise<void> => {
    setChecking(true)
    setError('')
    try {
      const k = await getKeysStatus()
      setKeys(k)
    } catch {
      setKeys(null)
      setError('无法连接后端，请确认已运行 `python -m backend.server`')
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const save = async (which: 'deepseek' | 'tavily'): Promise<void> => {
    const val = (which === 'deepseek' ? dsVal : tvVal).trim()
    if (!val || saving) return
    setSaving(which)
    setError('')
    try {
      await saveKeys(which === 'deepseek' ? { deepseek_key: val } : { tavily_key: val })
      if (which === 'deepseek') {
        setDsVal('')
      } else {
        setTvVal('')
      }
      await refresh()
    } catch (e) {
      setError('保存失败：' + (e instanceof Error ? e.message : String(e)))
    } finally {
      setSaving(null)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-5 shadow-xl dark:border-gray-800 dark:bg-gray-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">API Key 设置</h2>
          <button
            onClick={onClose}
            className="rounded px-2 py-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800"
            title="关闭"
          >
            ✕
          </button>
        </div>

        {checking && !keys ? (
          <p className="py-6 text-center text-sm text-gray-400">正在读取 Key 状态…</p>
        ) : (
          <div className="space-y-3">
            <KeyField
              label="DeepSeek"
              placeholder="sk-...（LLM 对话用）"
              status={keys?.deepseek}
              value={dsVal}
              onChange={setDsVal}
              onSave={() => void save('deepseek')}
              saving={saving !== null}
            />
            <KeyField
              label="Tavily"
              placeholder="tvly-...（联网搜索用）"
              status={keys?.tavily}
              value={tvVal}
              onChange={setTvVal}
              onSave={() => void save('tavily')}
              saving={saving !== null}
            />

            <button
              onClick={() => void refresh()}
              disabled={checking}
              className="w-full rounded-lg border border-gray-300 px-3 py-1.5 text-xs text-gray-500 hover:bg-gray-100 disabled:opacity-50 dark:border-gray-700 dark:hover:bg-gray-800"
            >
              {checking ? '校验中…' : '重新校验'}
            </button>
          </div>
        )}

        {error && <p className="mt-3 text-xs text-red-500">{error}</p>}

        <p className="mt-4 text-xs text-gray-400">
          Key 保存在本地 <code className="font-mono">.env</code>，仅本地使用、不会上传；保存后后端自动重连生效。
        </p>
      </div>
    </div>
  )
}
