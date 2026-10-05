import { create } from 'zustand'
import type { ScheduledJob, ScheduleConfig, JobStatus } from './schedule.types'
import { nextRunTime, formatSchedule } from './schedule.utils'

interface ScheduleState {
  jobs: ScheduledJob[]
  panelOpen: boolean

  addJob: (teamId: number, teamName: string, task: string, config: ScheduleConfig) => void
  removeJob: (id: string) => void
  toggleJob: (id: string) => void
  updateJobStatus: (id: string, status: JobStatus, lastRunStatus?: 'success' | 'error') => void
  refreshNextRun: (id: string) => void
  setPanelOpen: (open: boolean) => void
  togglePanel: () => void
}

export const SCHEDULE_STORAGE_KEY = 'editor:schedule-jobs:v1'

function saveJobs(jobs: ScheduledJob[]) {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(SCHEDULE_STORAGE_KEY, JSON.stringify(jobs))
    }
  } catch { /* ignore */ }
}

let _counter = 0

export const useScheduleStore = create<ScheduleState>((set) => ({
  jobs: [],
  panelOpen: false,

  addJob: (teamId, teamName, task, config) =>
    set((state) => {
      const now = new Date()
      const job: ScheduledJob = {
        id: `sched-${Date.now()}-${++_counter}`,
        teamId,
        teamName,
        task,
        schedule: config,
        description: formatSchedule(config),
        enabled: true,
        status: 'active',
        lastRunAt: null,
        lastRunStatus: null,
        nextRunAt: nextRunTime(config, now).toISOString(),
        createdAt: now.toISOString(),
      }
      const jobs = [...state.jobs, job]
      saveJobs(jobs)
      return { jobs }
    }),

  removeJob: (id) =>
    set((state) => {
      const jobs = state.jobs.filter((j) => j.id !== id)
      saveJobs(jobs)
      return { jobs }
    }),

  toggleJob: (id) =>
    set((state) => {
      const jobs = state.jobs.map((j) => {
        if (j.id !== id) return j
        const enabled = !j.enabled
        return {
          ...j,
          enabled,
          status: (enabled ? 'active' : 'paused') as JobStatus,
          nextRunAt: enabled ? nextRunTime(j.schedule).toISOString() : null,
        }
      })
      saveJobs(jobs)
      return { jobs }
    }),

  updateJobStatus: (id, status, lastRunStatus) =>
    set((state) => {
      const jobs = state.jobs.map((j) => {
        if (j.id !== id) return j
        return {
          ...j,
          status,
          lastRunAt: new Date().toISOString(),
          lastRunStatus: lastRunStatus ?? j.lastRunStatus,
          nextRunAt: j.enabled ? nextRunTime(j.schedule).toISOString() : null,
        }
      })
      saveJobs(jobs)
      return { jobs }
    }),

  refreshNextRun: (id) =>
    set((state) => {
      const jobs = state.jobs.map((j) => {
        if (j.id !== id || !j.enabled) return j
        return { ...j, nextRunAt: nextRunTime(j.schedule).toISOString() }
      })
      saveJobs(jobs)
      return { jobs }
    }),

  setPanelOpen: (open) => set({ panelOpen: open }),
  togglePanel: () => set((state) => ({ panelOpen: !state.panelOpen })),
}))
