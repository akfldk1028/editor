import type { UsageLevel } from './context-usage.types'
import { WARNING_THRESHOLD, DANGER_THRESHOLD } from './context-usage.constants'

/** Calculate usage percentage */
export function getUsagePercentage(totalTokens: number, limit: number): number {
  if (limit <= 0) return 0
  return Math.min((totalTokens / limit) * 100, 100)
}

/** Determine usage level from percentage */
export function getUsageLevel(percentage: number): UsageLevel {
  if (percentage > DANGER_THRESHOLD) return 'danger'
  if (percentage > WARNING_THRESHOLD) return 'warning'
  return 'normal'
}

/** Format token count for display (e.g. 37000 -> "37.0K") */
export function formatTokenCount(count: number): string {
  if (count >= 1_000_000) {
    const value = count / 1_000_000
    const formatted = value.toFixed(1)
    return formatted.endsWith('.0') ? `${Math.floor(value)}M` : `${formatted}M`
  }
  if (count >= 1_000) {
    const value = count / 1_000
    const formatted = value.toFixed(1)
    return formatted.endsWith('.0') ? `${Math.floor(value)}K` : `${formatted}K`
  }
  return count.toString()
}
