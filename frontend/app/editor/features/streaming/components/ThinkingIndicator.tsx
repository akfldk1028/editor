import { memo, useState, useEffect, useRef } from 'react'
import { Loader2 } from 'lucide-react'

interface ThinkingIndicatorProps {
  /** When the thinking started (ms timestamp) */
  startedAt: number
}

export const ThinkingIndicator = memo(function ThinkingIndicator({ startedAt }: ThinkingIndicatorProps) {
  const [elapsed, setElapsed] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval>>(undefined)

  useEffect(() => {
    setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    intervalRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => clearInterval(intervalRef.current)
  }, [startedAt])

  const minutes = Math.floor(elapsed / 60)
  const seconds = elapsed % 60
  const timeStr = minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`

  return (
    <div className="flex items-center gap-2 text-(--color-text-tertiary) px-2">
      <Loader2 className="w-4 h-4 animate-spin text-(--color-accent-primary)" />
      <span className="text-body-small">Agent thinking...</span>
      <span className="text-body-small font-mono text-(--color-text-tertiary)">{timeStr}</span>
    </div>
  )
})
