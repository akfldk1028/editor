import { describe, it, expect, beforeEach } from 'bun:test'
import { useScheduleStore } from './schedule.store'

describe('useScheduleStore', () => {
  beforeEach(() => {
    useScheduleStore.setState({ jobs: [], panelOpen: false })
  })

  it('adds a job', () => {
    useScheduleStore.getState().addJob(1, 'Test Team', 'Run test', { frequency: 'hourly', minute: 0 })
    const jobs = useScheduleStore.getState().jobs
    expect(jobs).toHaveLength(1)
    expect(jobs[0].teamName).toBe('Test Team')
    expect(jobs[0].enabled).toBe(true)
    expect(jobs[0].status).toBe('active')
    expect(jobs[0].nextRunAt).not.toBeNull()
  })

  it('removes a job', () => {
    useScheduleStore.getState().addJob(1, 'Team', 'task', { frequency: 'daily', hour: 9, minute: 0 })
    const id = useScheduleStore.getState().jobs[0].id
    useScheduleStore.getState().removeJob(id)
    expect(useScheduleStore.getState().jobs).toHaveLength(0)
  })

  it('toggles a job on/off', () => {
    useScheduleStore.getState().addJob(1, 'Team', 'task', { frequency: 'daily', hour: 9, minute: 0 })
    const id = useScheduleStore.getState().jobs[0].id

    useScheduleStore.getState().toggleJob(id)
    expect(useScheduleStore.getState().jobs[0].enabled).toBe(false)
    expect(useScheduleStore.getState().jobs[0].status).toBe('paused')

    useScheduleStore.getState().toggleJob(id)
    expect(useScheduleStore.getState().jobs[0].enabled).toBe(true)
    expect(useScheduleStore.getState().jobs[0].status).toBe('active')
  })

  it('updates job status', () => {
    useScheduleStore.getState().addJob(1, 'Team', 'task', { frequency: 'hourly', minute: 0 })
    const id = useScheduleStore.getState().jobs[0].id
    useScheduleStore.getState().updateJobStatus(id, 'error', 'error')
    const job = useScheduleStore.getState().jobs[0]
    expect(job.status).toBe('error')
    expect(job.lastRunStatus).toBe('error')
    expect(job.lastRunAt).not.toBeNull()
  })

  it('toggles panel open/close', () => {
    useScheduleStore.getState().togglePanel()
    expect(useScheduleStore.getState().panelOpen).toBe(true)
    useScheduleStore.getState().togglePanel()
    expect(useScheduleStore.getState().panelOpen).toBe(false)
  })
})
