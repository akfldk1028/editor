import { Badge } from '@/elements/workspace'
import { ChevronDown, ChevronUp, Clock } from 'lucide-react'
import type { Run, AgentMessageConfig, Message } from '@/lib/contracts/workspace'
import { MessageBubble } from './MessageBubble'

const STATUS_COLORS: Record<string, 'primary' | 'success' | 'error' | 'warning' | 'default'> = {
  created: 'default',
  active: 'primary',
  awaiting_input: 'warning',
  complete: 'success',
  error: 'error',
  timeout: 'warning',
  stopped: 'default',
}

export function RunCard({
  run,
  isExpanded,
  onToggle,
}: {
  run: Run
  isExpanded: boolean
  onToggle: () => void
}) {
  const messages = run.team_result?.task_result?.messages ?? []
  const runMessages = (run.messages ?? []) as Message[]
  const allMessages = messages.length > 0 ? messages : runMessages.map((m) => m.config)

  return (
    <div key={run.id} className="border border-(--color-border-default) rounded-lg">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-3 hover:bg-(--color-background-secondary) transition-colors rounded-lg"
        aria-expanded={isExpanded}
      >
        <div className="flex items-center gap-2">
          <Badge variant={STATUS_COLORS[run.status] ?? 'default'}>{run.status}</Badge>
          <span className="text-sm text-(--color-text-secondary)">Run #{run.id}</span>
          {allMessages.length > 0 && (
            <span className="text-xs text-(--color-text-tertiary)">
              ({allMessages.length} messages)
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {run.team_result?.duration != null && (
            <span className="text-xs text-(--color-text-tertiary) flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {run.team_result.duration.toFixed(1)}s
            </span>
          )}
          {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </div>
      </button>

      {isExpanded && (
        <div className="px-3 pb-3 border-t border-(--color-border-default)">
          {run.error_message && (
            <p className="text-sm text-(--color-semantic-error) mt-2 p-2 rounded bg-(--color-semantic-error)/10">
              {run.error_message}
            </p>
          )}
          {allMessages.length === 0 ? (
            <p className="text-sm text-(--color-text-tertiary) py-2 text-center">
              No messages recorded.
            </p>
          ) : (
            <div className="divide-y divide-(--color-border-default) mt-2">
              {allMessages.map((msg: AgentMessageConfig, i: number) => (
                <MessageBubble key={i} message={msg} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
