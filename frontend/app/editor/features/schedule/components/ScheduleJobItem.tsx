import { memo, useCallback } from 'react'
import { Trash2, Play, Pause } from 'lucide-react'
import { cn } from '@/lib/utils'
import { STATUS_DOT_COLORS } from '../schedule.constants'
import { formatTimeUntil } from '../schedule.utils'
import type { ScheduledJob } from '../schedule.types'

interface ScheduleJobItemProps {
  job: ScheduledJob
  onToggle: (id: string) => void
  onRemove: (id: string) => void
}

export const ScheduleJobItem = memo(function ScheduleJobItem({
  job,
  onToggle,
  onRemove,
}: ScheduleJobItemProps) {
  const handleToggle = useCallback(() => onToggle(job.id), [onToggle, job.id])
  const handleRemove = useCallback(() => onRemove(job.id), [onRemove, job.id])

  const nextRunStr = job.nextRunAt
    ? formatTimeUntil(new Date(job.nextRunAt))
    : '-'

  return (
    <div className="flex items-start gap-3 p-3 rounded-lg border border-(--color-border-default) bg-(--color-background-primary)">
      {/* Status dot */}
      <div className={cn('w-2 h-2 rounded-full mt-1.5 shrink-0', STATUS_DOT_COLORS[job.status] || 'bg-(--color-text-tertiary)')} />

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-(--color-text-primary) truncate">{job.teamName}</p>
        <p className="text-xs text-(--color-text-tertiary) truncate mt-0.5">{job.task}</p>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-xs text-(--color-text-tertiary)">{job.description}</span>
          {job.enabled && (
            <span className="text-xs text-(--color-accent-primary)">{nextRunStr}</span>
          )}
        </div>
        {job.lastRunAt && (
          <p className="text-xs text-(--color-text-tertiary) mt-0.5">
            Last: {new Date(job.lastRunAt).toLocaleTimeString()}
            {job.lastRunStatus === 'error' && (
              <span className="text-(--color-semantic-error) ml-1">(failed)</span>
            )}
          </p>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 shrink-0">
        <button
          type="button"
          onClick={handleToggle}
          className="p-1 rounded text-(--color-text-tertiary) hover:text-(--color-text-primary)"
          aria-label={job.enabled ? 'Pause job' : 'Resume job'}
        >
          {job.enabled ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
        </button>
        <button
          type="button"
          onClick={handleRemove}
          className="p-1 rounded text-(--color-text-tertiary) hover:text-(--color-semantic-error)"
          aria-label="Delete job"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
})
