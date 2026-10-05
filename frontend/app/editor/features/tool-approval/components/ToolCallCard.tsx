import { memo, useState } from 'react'
import { ChevronRight, ChevronDown, Terminal, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ToolCallInfo } from '../tool-approval.types'

interface ToolCallCardProps {
  call: ToolCallInfo
}

const STATUS_ICON = {
  pending: Loader2,
  success: CheckCircle,
  error: XCircle,
} as const

const STATUS_COLOR = {
  pending: 'text-(--color-text-tertiary)',
  success: 'text-(--color-semantic-success)',
  error: 'text-(--color-semantic-error)',
} as const

export const ToolCallCard = memo(function ToolCallCard({ call }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const StatusIcon = STATUS_ICON[call.status]

  return (
    <div className="mx-10 my-1">
      <button
        type="button"
        onClick={() => setExpanded((p) => !p)}
        className="flex items-center gap-2 w-full px-3 py-1.5 rounded-md text-xs
          bg-(--color-background-secondary) hover:bg-(--color-background-primary)
          border border-(--color-border-default) transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-3 h-3 text-(--color-text-tertiary)" />
        ) : (
          <ChevronRight className="w-3 h-3 text-(--color-text-tertiary)" />
        )}
        <Terminal className="w-3 h-3 text-(--color-text-tertiary)" />
        <span className="font-mono text-(--color-accent-primary)">{call.name}</span>
        <StatusIcon className={cn('w-3 h-3 ml-auto', STATUS_COLOR[call.status], call.status === 'pending' && 'animate-spin')} />
        {call.duration != null && (
          <span className="text-(--color-text-tertiary)">{call.duration}ms</span>
        )}
      </button>
      {expanded && (
        <div className="mt-1 rounded-md border border-(--color-border-default) bg-(--color-background-primary) overflow-hidden">
          {call.args && (
            <div className="px-3 py-2 border-b border-(--color-border-default)">
              <p className="text-xs text-(--color-text-tertiary) mb-1">Arguments</p>
              <pre className="text-xs font-mono text-(--color-text-secondary) whitespace-pre-wrap break-all max-h-32 overflow-y-auto">
                {call.args}
              </pre>
            </div>
          )}
          {call.result && (
            <div className="px-3 py-2">
              <p className="text-xs text-(--color-text-tertiary) mb-1">Result</p>
              <pre className="text-xs font-mono text-(--color-text-secondary) whitespace-pre-wrap break-all max-h-48 overflow-y-auto">
                {call.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
})
