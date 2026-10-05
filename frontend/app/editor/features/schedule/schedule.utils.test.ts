import { describe, it, expect } from 'bun:test'
import { nextRunTime, formatSchedule, formatTimeUntil } from './schedule.utils'
import type { ScheduleConfig } from './schedule.types'

describe('nextRunTime', () => {
  it('hourly: next occurrence at minute mark', () => {
    const from = new Date(2026, 1, 18, 10, 15, 0)
    const config: ScheduleConfig = { frequency: 'hourly', minute: 30 }
    const result = nextRunTime(config, from)
    expect(result.getMinutes()).toBe(30)
    expect(result.getHours()).toBe(10)
  })

  it('hourly: wraps to next hour if past minute', () => {
    const from = new Date(2026, 1, 18, 10, 45, 0)
    const config: ScheduleConfig = { frequency: 'hourly', minute: 30 }
    const result = nextRunTime(config, from)
    expect(result.getMinutes()).toBe(30)
    expect(result.getHours()).toBe(11)
  })

  it('daily: next day if past time', () => {
    const from = new Date(2026, 1, 18, 15, 0, 0)
    const config: ScheduleConfig = { frequency: 'daily', hour: 9, minute: 0 }
    const result = nextRunTime(config, from)
    expect(result.getDate()).toBe(19)
    expect(result.getHours()).toBe(9)
  })

  it('weekly: finds next matching day', () => {
    // Feb 18, 2026 is Wednesday (day 3)
    const from = new Date(2026, 1, 18, 15, 0, 0)
    const config: ScheduleConfig = { frequency: 'weekly', dayOfWeek: 1, hour: 9, minute: 0 } // Monday
    const result = nextRunTime(config, from)
    expect(result.getDay()).toBe(1) // Monday
    expect(result.getDate()).toBe(23)
  })

  it('custom: adds interval minutes', () => {
    const from = new Date(2026, 1, 18, 10, 0, 0)
    const config: ScheduleConfig = { frequency: 'custom', intervalMinutes: 30 }
    const result = nextRunTime(config, from)
    expect(result.getMinutes()).toBe(30)
    expect(result.getHours()).toBe(10)
  })
})

describe('formatSchedule', () => {
  it('formats hourly', () => {
    expect(formatSchedule({ frequency: 'hourly', minute: 15 })).toBe('Every hour at :15')
  })

  it('formats daily', () => {
    expect(formatSchedule({ frequency: 'daily', hour: 9, minute: 0 })).toBe('Daily at 09:00')
  })

  it('formats weekly', () => {
    expect(formatSchedule({ frequency: 'weekly', dayOfWeek: 1, hour: 9, minute: 0 })).toBe('Mon at 09:00')
  })

  it('formats custom', () => {
    expect(formatSchedule({ frequency: 'custom', intervalMinutes: 45 })).toBe('Every 45 minutes')
  })
})

describe('formatTimeUntil', () => {
  it('shows minutes when under an hour', () => {
    const now = new Date('2026-02-18T10:00:00Z')
    const target = new Date('2026-02-18T10:30:00Z')
    expect(formatTimeUntil(target, now)).toBe('in 30m')
  })

  it('shows hours and minutes', () => {
    const now = new Date('2026-02-18T10:00:00Z')
    const target = new Date('2026-02-18T12:15:00Z')
    expect(formatTimeUntil(target, now)).toBe('in 2h 15m')
  })

  it('shows overdue for past targets', () => {
    const now = new Date('2026-02-18T10:00:00Z')
    const target = new Date('2026-02-18T09:00:00Z')
    expect(formatTimeUntil(target, now)).toBe('overdue')
  })
})
