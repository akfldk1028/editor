import { memo, useMemo } from 'react'
import { AlarmClock } from 'lucide-react'
import { useScheduleStore } from '../schedule.store'

export const ScheduleIndicator = memo(function ScheduleIndicator({
  onClick,
}: {
  onClick: () => void
}) {
  const jobs = useScheduleStore((s) => s.jobs)

  const { activeCount, hasError } = useMemo(() => {
    let active = 0
    let error = false
    for (const j of jobs) {
      if (j.enabled) active++
      if (j.status === 'error') error = true
    }
    return { activeCount: active, hasError: error }
  }, [jobs])

  if (jobs.length === 0) return null

  const dotColor = hasError
    ? 'bg-(--color-semantic-error)'
    : activeCount > 0
      ? 'bg-(--color-semantic-success)'
      : 'bg-(--color-semantic-warning)'

  return (
    <button
      type="button"
      onClick={onClick}
      className="relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs border border-(--color-border-default) hover:bg-(--color-background-secondary) text-(--color-text-secondary) hover:text-(--color-text-primary) transition-colors"
      aria-label={`Schedule: ${activeCount} active jobs`}
    >
      <AlarmClock className="w-3.5 h-3.5" />
      <span>{activeCount}</span>
      <span className={`absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full ${dotColor}`} />
    </button>
  )
})
