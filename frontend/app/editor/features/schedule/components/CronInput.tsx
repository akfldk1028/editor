import { memo, useCallback } from 'react'
import { FREQUENCY_OPTIONS, DAY_LABELS } from '../schedule.constants'
import type { ScheduleConfig, ScheduleFrequency } from '../schedule.types'

interface CronInputProps {
  config: ScheduleConfig
  onChange: (config: ScheduleConfig) => void
}

export const CronInput = memo(function CronInput({ config, onChange }: CronInputProps) {
  const handleFrequency = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const frequency = e.target.value as ScheduleFrequency
      onChange({ ...config, frequency })
    },
    [config, onChange],
  )

  const handleHour = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onChange({ ...config, hour: Number(e.target.value) })
    },
    [config, onChange],
  )

  const handleMinute = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onChange({ ...config, minute: Number(e.target.value) })
    },
    [config, onChange],
  )

  const handleDayOfWeek = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onChange({ ...config, dayOfWeek: Number(e.target.value) })
    },
    [config, onChange],
  )

  const handleInterval = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = parseInt(e.target.value, 10)
      if (!isNaN(val) && val > 0) onChange({ ...config, intervalMinutes: val })
    },
    [config, onChange],
  )

  const selectClass = 'h-8 px-2 rounded border border-(--color-border-default) bg-(--color-surface-card) text-xs text-(--color-text-primary)'

  return (
    <div className="space-y-2">
      {/* Frequency */}
      <select
        aria-label="Schedule frequency"
        className={`${selectClass} w-full`}
        value={config.frequency}
        onChange={handleFrequency}
      >
        {FREQUENCY_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      {/* Time pickers based on frequency */}
      <div className="flex items-center gap-2">
        {(config.frequency === 'daily' || config.frequency === 'weekly') && (
          <>
            <select aria-label="Hour" className={selectClass} value={config.hour ?? 9} onChange={handleHour}>
              {Array.from({ length: 24 }, (_, i) => (
                <option key={i} value={i}>{String(i).padStart(2, '0')}</option>
              ))}
            </select>
            <span className="text-xs text-(--color-text-tertiary)">:</span>
            <select aria-label="Minute" className={selectClass} value={config.minute ?? 0} onChange={handleMinute}>
              {[0, 15, 30, 45].map((m) => (
                <option key={m} value={m}>{String(m).padStart(2, '0')}</option>
              ))}
            </select>
          </>
        )}

        {config.frequency === 'hourly' && (
          <>
            <span className="text-xs text-(--color-text-tertiary)">at minute</span>
            <select aria-label="Minute" className={selectClass} value={config.minute ?? 0} onChange={handleMinute}>
              {[0, 15, 30, 45].map((m) => (
                <option key={m} value={m}>{String(m).padStart(2, '0')}</option>
              ))}
            </select>
          </>
        )}

        {config.frequency === 'weekly' && (
          <select aria-label="Day of week" className={selectClass} value={config.dayOfWeek ?? 1} onChange={handleDayOfWeek}>
            {DAY_LABELS.map((d, i) => (
              <option key={i} value={i}>{d}</option>
            ))}
          </select>
        )}

        {config.frequency === 'custom' && (
          <>
            <span className="text-xs text-(--color-text-tertiary)">every</span>
            <input
              type="number"
              min={1}
              max={1440}
              value={config.intervalMinutes ?? 60}
              onChange={handleInterval}
              className="h-8 w-16 px-2 rounded border border-(--color-border-default) bg-(--color-surface-card) text-xs text-(--color-text-primary) text-center"
              aria-label="Interval in minutes"
            />
            <span className="text-xs text-(--color-text-tertiary)">min</span>
          </>
        )}
      </div>
    </div>
  )
})
