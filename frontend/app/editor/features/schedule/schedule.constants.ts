import type { ScheduleConfig, ScheduleFrequency } from './schedule.types'

export const SCHEDULE_PRESETS: { label: string; frequency: ScheduleFrequency; config: ScheduleConfig }[] = [
  { label: 'Every hour', frequency: 'hourly', config: { frequency: 'hourly', minute: 0 } },
  { label: 'Daily at 9 AM', frequency: 'daily', config: { frequency: 'daily', hour: 9, minute: 0 } },
  { label: 'Daily at 6 PM', frequency: 'daily', config: { frequency: 'daily', hour: 18, minute: 0 } },
  { label: 'Weekly Monday 9 AM', frequency: 'weekly', config: { frequency: 'weekly', hour: 9, minute: 0, dayOfWeek: 1 } },
]

export const FREQUENCY_OPTIONS: { value: ScheduleFrequency; label: string }[] = [
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'custom', label: 'Custom interval' },
]

export const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export const STATUS_DOT_COLORS: Record<string, string> = {
  active: 'bg-(--color-semantic-success)',
  paused: 'bg-(--color-semantic-warning)',
  error: 'bg-(--color-semantic-error)',
}
