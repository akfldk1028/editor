export type ScheduleFrequency = 'hourly' | 'daily' | 'weekly' | 'custom'

export interface ScheduleConfig {
  frequency: ScheduleFrequency
  /** Hour of day (0-23) for daily/weekly */
  hour?: number
  /** Minute (0-59) */
  minute?: number
  /** Day of week (0=Sun..6=Sat) for weekly */
  dayOfWeek?: number
  /** Interval in minutes for custom */
  intervalMinutes?: number
}

export type JobStatus = 'active' | 'paused' | 'error'

export interface ScheduledJob {
  id: string
  teamId: number
  teamName: string
  task: string
  schedule: ScheduleConfig
  description: string
  enabled: boolean
  status: JobStatus
  lastRunAt: string | null
  lastRunStatus: 'success' | 'error' | null
  nextRunAt: string | null
  createdAt: string
}
