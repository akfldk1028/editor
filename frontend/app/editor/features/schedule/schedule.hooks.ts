import { useEffect, useRef } from 'react'
import { useScheduleStore, SCHEDULE_STORAGE_KEY } from './schedule.store'
import type { ScheduledJob } from './schedule.types'

export function useScheduleRunner(onExecute: (jobId: string, teamId: number, task: string) => Promise<boolean>) {
  const callback = useRef(onExecute)
  callback.current = onExecute
  useEffect(() => {
    if (!navigator.locks) return
    let disposed = false
    const pending = new Set<string>()
    const check = () => {
      try {
        const saved = JSON.parse(localStorage.getItem(SCHEDULE_STORAGE_KEY) || '[]')
        if (!Array.isArray(saved)) return
        useScheduleStore.setState({ jobs: saved as ScheduledJob[] })
      } catch { return }
      for (const job of useScheduleStore.getState().jobs) {
        if (!job.enabled || !job.nextRunAt || Date.parse(job.nextRunAt) > Date.now() || pending.has(job.id)) continue
        pending.add(job.id)
        void navigator.locks.request(`editor:schedule:${job.id}`, { ifAvailable: true }, async lock => {
          if (!lock || disposed) return
          // Another tab may have already advanced this occurrence while this store was stale.
          const saved = JSON.parse(localStorage.getItem(SCHEDULE_STORAGE_KEY) || '[]') as Array<{id: string; nextRunAt: string | null; enabled: boolean}>
          const current = saved.find(item => item.id === job.id)
          if (!current?.enabled || current.nextRunAt !== job.nextRunAt) return
          if (await callback.current(job.id, job.teamId, job.task)) useScheduleStore.getState().refreshNextRun(job.id)
        }).catch(() => {}).finally(() => pending.delete(job.id))
      }
    }
    check()
    const interval = setInterval(check, 30_000)
    return () => { disposed = true; clearInterval(interval) }
  }, [])
}
