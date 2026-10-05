import { useState, useCallback } from 'react'
import { X, Plus, AlarmClock, AlertTriangle } from 'lucide-react'
import { Button, Input } from '@/elements/workspace'
import { useScheduleStore } from '../schedule.store'
import { SCHEDULE_PRESETS } from '../schedule.constants'
import type { ScheduleConfig } from '../schedule.types'
import { CronInput } from './CronInput'
import { ScheduleJobItem } from './ScheduleJobItem'

interface SchedulePanelProps {
  teamId: number | null
  teamName: string
  onClose: () => void
}

export function SchedulePanel({ teamId, teamName, onClose }: SchedulePanelProps) {
  const jobs = useScheduleStore((s) => s.jobs)
  const addJob = useScheduleStore((s) => s.addJob)
  const removeJob = useScheduleStore((s) => s.removeJob)
  const toggleJob = useScheduleStore((s) => s.toggleJob)

  const [showForm, setShowForm] = useState(false)
  const [task, setTask] = useState('')
  const [config, setConfig] = useState<ScheduleConfig>({ frequency: 'daily', hour: 9, minute: 0 })

  const handleAdd = useCallback(() => {
    if (!task.trim() || !teamId) return
    addJob(teamId, teamName, task.trim(), config)
    setTask('')
    setShowForm(false)
  }, [teamId, teamName, task, config, addJob])

  const handlePreset = useCallback(
    (preset: (typeof SCHEDULE_PRESETS)[0]) => {
      setConfig(preset.config)
    },
    [],
  )

  return (
    <div className="fixed right-0 top-0 h-full w-[400px] bg-(--color-surface-card) border-l border-(--color-border-default) shadow-xl z-50 flex flex-col"
      role="dialog"
      aria-modal="true"
      aria-label="Schedule Panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-(--color-border-default)">
        <div className="flex items-center gap-2">
          <AlarmClock className="w-5 h-5 text-(--color-accent-primary)" />
          <h2 className="text-heading-small">Scheduled Jobs</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary)"
          aria-label="Close schedule panel"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Warning */}
      <div className="px-4 py-2 text-xs text-(--color-semantic-warning) bg-(--color-semantic-warning)/5 border-b border-(--color-border-default) flex items-center gap-1.5">
        <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
        Browser-only: runs for the selected team while Playground is open and idle. Other teams wait. Requires browser Web Locks; this is not a background server scheduler.
      </div>

      {/* Job list */}
      <div className="flex-1 overflow-auto p-4 space-y-2">
        {jobs.length === 0 && !showForm && (
          <div className="text-center py-8">
            <AlarmClock className="w-10 h-10 mx-auto text-(--color-text-tertiary) mb-2" />
            <p className="text-body-small text-(--color-text-tertiary)">No scheduled jobs</p>
            <p className="text-xs text-(--color-text-tertiary) mt-1">Schedule recurring team executions</p>
          </div>
        )}

        {jobs.map((job) => (
          <ScheduleJobItem
            key={job.id}
            job={job}
            onToggle={toggleJob}
            onRemove={removeJob}
          />
        ))}
      </div>

      {/* Add form */}
      {showForm && (
        <div className="p-4 border-t border-(--color-border-default) space-y-3">
          <div>
            <label className="text-label-small block mb-1">Task</label>
            <Input
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Enter task to schedule..."
              aria-label="Scheduled task"
            />
          </div>

          {/* Presets */}
          <div className="flex flex-wrap gap-1">
            {SCHEDULE_PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => handlePreset(p)}
                className="px-2 py-1 rounded text-xs border border-(--color-border-default) hover:bg-(--color-background-secondary) text-(--color-text-secondary)"
              >
                {p.label}
              </button>
            ))}
          </div>

          <CronInput config={config} onChange={setConfig} />

          <div className="flex gap-2">
            <Button size="sm" onClick={handleAdd} disabled={!task.trim() || !teamId}>
              <Plus className="w-3.5 h-3.5 mr-1" />
              Add Job
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setShowForm(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* Add button (when form hidden) */}
      {!showForm && (
        <div className="p-4 border-t border-(--color-border-default)">
          <Button onClick={() => setShowForm(true)} disabled={!teamId} className="w-full">
            <Plus className="w-4 h-4 mr-1" />
            Add Scheduled Job
          </Button>
        </div>
      )}
    </div>
  )
}
