import { memo, useMemo } from 'react'
import { RING_SIZE, RING_STROKE_WIDTH } from '../context-usage.constants'
import type { UsageLevel } from '../context-usage.types'

interface ContextUsageRingProps {
  percentage: number
  level: UsageLevel
  displayTotal: string
  displayLimit: string
  size?: number
}

const LEVEL_COLORS: Record<UsageLevel, string> = {
  normal: 'var(--color-accent-primary)',
  warning: 'var(--color-semantic-warning)',
  danger: 'var(--color-semantic-error)',
}

export const ContextUsageRing = memo(function ContextUsageRing({
  percentage,
  level,
  displayTotal,
  displayLimit,
  size = RING_SIZE,
}: ContextUsageRingProps) {
  const radius = (size - RING_STROKE_WIDTH) / 2
  const circumference = 2 * Math.PI * radius

  const strokeDashoffset = useMemo(
    () => circumference - (Math.min(percentage, 100) / 100) * circumference,
    [circumference, percentage],
  )

  const strokeColor = LEVEL_COLORS[level]
  const title = `${percentage.toFixed(1)}% context used (${displayTotal} / ${displayLimit})`

  return (
    <div
      className="inline-flex items-center justify-center cursor-default"
      style={{ width: size, height: size }}
      title={title}
      aria-label={title}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ transform: 'rotate(-90deg)' }}
      >
        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-border-default)"
          strokeWidth={RING_STROKE_WIDTH}
        />
        {/* Progress */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={strokeColor}
          strokeWidth={RING_STROKE_WIDTH}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          style={{ transition: 'stroke-dashoffset 0.3s ease, stroke 0.3s ease' }}
        />
      </svg>
    </div>
  )
})
