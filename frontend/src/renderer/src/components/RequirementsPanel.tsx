import { useChatStore } from '../store/chatStore'
import { cn } from '../lib/utils'
import type { Prefs, Resolution, UseCase } from '../types'

const BUDGET_PRESETS = [5000, 8000, 12000, 20000, 30000]
const USE_CASES: Array<{ key: UseCase; label: string }> = [
  { key: 'gaming', label: '🎮 游戏' },
  { key: 'balanced', label: '⚖️ 均衡' },
  { key: 'productivity', label: '💼 生产力' }
]
const RESOLUTIONS: Array<{ key: Resolution | ''; label: string }> = [
  { key: '', label: '不限' },
  { key: '1080p', label: '1080p' },
  { key: '2K', label: '2K' },
  { key: '4K', label: '4K' }
]
const EXCLUDES: Array<{ key: string; label: string }> = [
  { key: 'monitor', label: '不要显示器' },
  { key: 'peripherals', label: '不要外设' }
]

export default function RequirementsPanel(): JSX.Element {
  const activeId = useChatStore((s) => s.activeId)
  const prefs = useChatStore((s) => s.conversations.find((c) => c.id === s.activeId)?.prefs)
  const setPrefs = useChatStore((s) => s.setPrefs)

  if (!activeId || !prefs) return <></>

  const update = (p: Partial<Prefs>): void => setPrefs(p, 'panel')

  const toggleExclude = (key: string): void => {
    const has = prefs.exclude.includes(key)
    update({ exclude: has ? prefs.exclude.filter((x) => x !== key) : [...prefs.exclude, key] })
  }

  return (
    <div className="border-b border-gray-200 bg-gray-50/60 px-4 py-3 dark:border-gray-800 dark:bg-gray-900/60">
      {/* 预算行 */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">预算</span>
        <input
          type="range"
          min={2000}
          max={30000}
          step={500}
          value={prefs.budget}
          onChange={(e) => update({ budget: parseInt(e.target.value, 10) })}
          className="w-40 accent-primary"
        />
        <span className="min-w-16 font-mono text-sm font-semibold text-primary">¥{prefs.budget.toLocaleString()}</span>
        <div className="flex gap-1">
          {BUDGET_PRESETS.map((p) => (
            <button
              key={p}
              onClick={() => update({ budget: p })}
              className={cn(
                'rounded-full px-2.5 py-0.5 text-xs',
                prefs.budget === p
                  ? 'bg-primary text-white'
                  : 'bg-gray-200 text-gray-600 hover:bg-gray-300 dark:bg-gray-800 dark:text-gray-300'
              )}
            >
              {p >= 10000 ? `${p / 10000}万` : p}
            </button>
          ))}
        </div>
      </div>

      {/* 用途 + 分辨率 + 排除 */}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">用途</span>
          <div className="flex rounded-lg bg-gray-200 p-0.5 dark:bg-gray-800">
            {USE_CASES.map((uc) => (
              <button
                key={uc.key}
                onClick={() => update({ use_case: uc.key })}
                className={cn(
                  'rounded-md px-2.5 py-1 text-xs',
                  prefs.use_case === uc.key
                    ? 'bg-white text-primary shadow dark:bg-gray-700'
                    : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
                )}
              >
                {uc.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">分辨率</span>
          <div className="flex gap-1">
            {RESOLUTIONS.map((r) => (
              <button
                key={r.key}
                onClick={() => update({ resolution: r.key })}
                className={cn(
                  'rounded-full px-2.5 py-0.5 text-xs',
                  prefs.resolution === r.key
                    ? 'bg-primary text-white'
                    : 'bg-gray-200 text-gray-600 hover:bg-gray-300 dark:bg-gray-800 dark:text-gray-300'
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">排除</span>
          {EXCLUDES.map((e) => (
            <label key={e.key} className="flex cursor-pointer items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={prefs.exclude.includes(e.key)}
                onChange={() => toggleExclude(e.key)}
                className="accent-primary"
              />
              {e.label}
            </label>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">搜索</span>
          <div className="flex rounded-lg bg-gray-200 p-0.5 dark:bg-gray-800">
            <button
              onClick={() => update({ mode: 'snapshot' })}
              className={cn(
                'rounded-md px-2.5 py-1 text-xs',
                prefs.mode === 'snapshot'
                  ? 'bg-white text-primary shadow dark:bg-gray-700'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              )}
              title="快照模式：只用本地硬件库，不联网"
            >
              快照
            </button>
            <button
              onClick={() => update({ mode: 'online' })}
              className={cn(
                'rounded-md px-2.5 py-1 text-xs',
                prefs.mode === 'online'
                  ? 'bg-white text-primary shadow dark:bg-gray-700'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              )}
              title="联网模式：实时搜索最新行情/新闻"
            >
              联网
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
