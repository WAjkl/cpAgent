import { useState } from 'react'
import { cn, formatPrice, freshnessMeta, useCaseLabel, parsePriceNumber } from '../lib/utils'
import type { Config, PartInfo } from '../types'

const PART_LABELS: Record<string, string> = {
  cpu: 'CPU',
  gpu: '显卡',
  motherboard: '主板',
  memory: '内存',
  ssd: '固态硬盘',
  psu: '电源'
}

const PART_ORDER = ['cpu', 'gpu', 'motherboard', 'memory', 'ssd', 'psu']

function PartRow({ k, part }: { k: string; part: PartInfo }): JSX.Element {
  const meta = freshnessMeta(part.level)
  return (
    <div className="flex items-center gap-2 py-1.5">
      <span className="w-14 shrink-0 text-xs text-gray-400">{PART_LABELS[k] ?? k}</span>
      <span className="flex-1 truncate text-sm">{part.model}</span>
      <span className="flex items-center gap-1 text-xs text-gray-400">
        <span className={cn('inline-block h-2 w-2 rounded-full', meta.color)} title={meta.label} />
        {part.price_source === 'estimate' ? '估算' : '实时'}
      </span>
      <span className="w-20 text-right font-mono text-sm">{formatPrice(part.price ?? part.price_cny)}</span>
    </div>
  )
}

function ScoreBar({ label, value }: { label: string; value: number }): JSX.Element {
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 text-xs text-gray-400">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
        <div
          className="h-full rounded-full bg-gradient-to-r from-primary to-teal-400"
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
      <span className="w-10 text-right font-mono text-xs">{value.toFixed(1)}</span>
    </div>
  )
}

export default function ConfigCard({ config }: { config: Config }): JSX.Element {
  const [exported, setExported] = useState(false)

  const exportJson = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(config, null, 2))
      setExported(true)
      setTimeout(() => setExported(false), 1200)
    } catch {
      /* ignore */
    }
  }

  const parts = config.parts

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-gray-200 dark:border-gray-700">
      {/* 头部 */}
      <div className="flex items-center justify-between bg-gradient-to-r from-primary to-teal-600 px-4 py-3 text-white">
        <div>
          <div className="text-xs opacity-80">配置总价</div>
          <div className="font-mono text-2xl font-bold">¥{config.total_price.toLocaleString()}</div>
        </div>
        <div className="text-right">
          <span className="rounded-full bg-white/20 px-2.5 py-1 text-xs">{useCaseLabel(config.use_case)}</span>
          {config.resolution && (
            <span className="ml-1 rounded-full bg-white/20 px-2.5 py-1 text-xs">{config.resolution}</span>
          )}
          <div className="mt-1 text-xs opacity-80">
            {config.compatibility.ok ? '✅ 兼容性通过' : '⚠️ 存在不兼容'}
          </div>
        </div>
      </div>

      <div className="space-y-2 bg-white px-4 py-3 dark:bg-gray-900">
        {/* 性能双进度条 */}
        <div className="space-y-1.5">
          <ScoreBar label="游戏性能" value={config.score.gaming} />
          <ScoreBar label="生产力" value={config.score.productivity} />
        </div>

        {/* 六大件明细 */}
        <div className="divide-y divide-gray-100 dark:divide-gray-800">
          {PART_ORDER.map((k) => {
            const part = parts[k as keyof typeof parts]
            return part ? <PartRow key={k} k={k} part={part} /> : null
          })}
        </div>

        {/* 兼容性 + 警告 */}
        {!config.compatibility.ok && config.compatibility.problems.length > 0 && (
          <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600 dark:bg-red-900/20 dark:text-red-400">
            {config.compatibility.problems.map((p, i) => (
              <div key={i}>• {p}</div>
            ))}
          </div>
        )}
        {config.warnings.length > 0 && (
          <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-600 dark:bg-amber-900/20 dark:text-amber-400">
            {config.warnings.map((w, i) => (
              <div key={i}>⚠️ {w}</div>
            ))}
          </div>
        )}

        {/* 价格来源时间戳 + 操作 */}
        <div className="flex items-center justify-between border-t border-gray-100 pt-2 text-xs text-gray-400 dark:border-gray-800">
          <span>价格快照：{config.generated_at}</span>
          <div className="flex gap-2">
            <button
              onClick={exportJson}
              className="rounded-md border border-gray-200 px-2 py-1 hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800"
              title="导出配置单 JSON"
            >
              {exported ? '已复制' : '导出'}
            </button>
            <button className="rounded-md border border-gray-200 px-2 py-1 hover:bg-gray-50 dark:border-gray-700 dark:hover:bg-gray-800" title="收藏（后续版本）">
              收藏
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// 供组件外计算用（保持类型一致）
export function configTotal(config: Config): number {
  return parsePriceNumber(config.total_price)
}
