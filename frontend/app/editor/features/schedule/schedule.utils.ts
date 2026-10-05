import type { ScheduleConfig } from './schedule.types'
import { DAY_LABELS } from './schedule.constants'

/** Calculate next run time from now based on schedule config */
export function nextRunTime(config: ScheduleConfig, from: Date = new Date()): Date {
  const next = new Date(from)

  switch (config.frequency) {
    case 'hourly': {
      const minute = config.minute ?? 0
      next.setMinutes(minute, 0, 0)
      if (next <= from) next.setHours(next.getHours() + 1)
      break
    }
    case 'daily': {
      const hour = config.hour ?? 9
      const minute = config.minute ?? 0
      next.setHours(hour, minute, 0, 0)
      if (next <= from) next.setDate(next.getDate() + 1)
      break
    }
    case 'weekly': {
      const dayOfWeek = config.dayOfWeek ?? 1
      const hour = config.hour ?? 9
      const minute = config.minute ?? 0
      next.setHours(hour, minute, 0, 0)
      const currentDay = next.getDay()
      let daysUntil = dayOfWeek - currentDay
      if (daysUntil < 0 || (daysUntil === 0 && next <= from)) {
        daysUntil += 7
      }
      next.setDate(next.getDate() + daysUntil)
      break
    }
    case 'custom': {
      const interval = config.intervalMinutes ?? 60
      next.setTime(from.getTime() + interval * 60_000)
      break
    }
  }

  return next
}

/** Format schedule config into human-readable description */
export function formatSchedule(config: ScheduleConfig): string {
  const pad = (n: number) => String(n).padStart(2, '0')

  switch (config.frequency) {
    case 'hourly':
      return `Every hour at :${pad(config.minute ?? 0)}`
    case 'daily':
      return `Daily at ${pad(config.hour ?? 9)}:${pad(config.minute ?? 0)}`
    case 'weekly':
      return `${DAY_LABELS[config.dayOfWeek ?? 1]} at ${pad(config.hour ?? 9)}:${pad(config.minute ?? 0)}`
    case 'custom':
      return `Every ${config.intervalMinutes ?? 60} minutes`
  }
}

/** Format relative time until next run */
export function formatTimeUntil(target: Date, now: Date = new Date()): string {
  const diff = target.getTime() - now.getTime()
  if (diff < 0) return 'overdue'

  const minutes = Math.floor(diff / 60_000)
  const hours = Math.floor(minutes / 60)

  if (hours > 24) {
    const days = Math.floor(hours / 24)
    return `in ${days}d ${hours % 24}h`
  }
  if (hours > 0) return `in ${hours}h ${minutes % 60}m`
  return `in ${minutes}m`
}
