import type { UseCase } from '../types'

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

export function formatPrice(p: number | string | undefined | null): string {
  if (p == null) return '—'
  if (typeof p === 'number') return `¥${p.toLocaleString()}`
  const nums = p.replace(/,/g, '').split('-').map((x) => parseFloat(x)).filter((x) => !isNaN(x))
  if (nums.length === 0) return '—'
  return nums.length > 1 ? `¥${nums[0].toLocaleString()}~${nums[1].toLocaleString()}` : `¥${nums[0].toLocaleString()}`
}

export function useCaseLabel(uc: UseCase): string {
  return { gaming: '游戏', productivity: '生产力', balanced: '均衡' }[uc] ?? uc
}

export function freshnessMeta(level?: string): { label: string; color: string } {
  switch (level) {
    case 'fresh':
      return { label: '新鲜', color: 'bg-emerald-500' }
    case 'stale':
      return { label: '稍旧', color: 'bg-amber-500' }
    case 'expired':
      return { label: '需刷新', color: 'bg-gray-400' }
    default:
      return { label: '未知', color: 'bg-gray-400' }
  }
}

export function uid(prefix = ''): string {
  return `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

export function parsePriceNumber(p: number | string | undefined | null): number {
  if (p == null) return 0
  if (typeof p === 'number') return p
  const nums = p.replace(/,/g, '').split('-').map((x) => parseFloat(x)).filter((x) => !isNaN(x))
  return nums.length ? Math.min(...nums) : 0
}
