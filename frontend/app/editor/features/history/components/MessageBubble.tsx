/**
 * MessageBubble - Renders a single agent message with type-specific styling
 * Handles Text, ToolCall, ToolCallResult, Stop, Handoff message types
 */

import { memo } from 'react'
import { Badge } from '@/elements/workspace'
import type {
  AgentMessageConfig,
  FunctionCall,
  FunctionExecutionResult,
} from '@/lib/contracts/workspace'

interface MessageBubbleProps {
  message: AgentMessageConfig
}

function getMessageType(msg: AgentMessageConfig): string {
  if ('target' in msg) return 'handoff'
  if ('content' in msg && Array.isArray(msg.content)) {
    const first = msg.content[0]
    if (first && typeof first === 'object' && 'id' in first) return 'tool_call'
    if (first && typeof first === 'object' && 'call_id' in first) return 'tool_result'
  }
  if ('type' in msg && msg.type === 'ModelClientStreamingChunkEvent') return 'chunk'
  return 'text'
}

export const MessageBubble = memo(function MessageBubble({ message }: MessageBubbleProps) {
  const type = getMessageType(message)
  const source = message.source ?? 'unknown'

  return (
    <div className="flex gap-3 py-2">
      <div className="w-8 h-8 rounded-full bg-(--color-background-secondary) flex items-center justify-center shrink-0 text-xs font-bold text-(--color-text-secondary)">
        {source.charAt(0).toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-medium text-(--color-text-primary)">{source}</span>
          <Badge
            variant={
              type === 'handoff'
                ? 'warning'
                : type === 'tool_call'
                  ? 'primary'
                  : type === 'tool_result'
                    ? 'success'
                    : 'default'
            }
          >
            {type}
          </Badge>
        </div>

        {type === 'text' && (
          <p className="text-sm text-(--color-text-secondary) whitespace-pre-wrap break-words">
            {String((message as { content: string }).content ?? '')}
          </p>
        )}

        {type === 'handoff' && (
          <p className="text-sm text-(--color-text-secondary)">
            Handing off to <strong>{(message as { target: string }).target}</strong>
            {': '}
            {String((message as { content: string }).content ?? '')}
          </p>
        )}

        {type === 'tool_call' && (
          <div className="space-y-1">
            {((message as { content: FunctionCall[] }).content ?? []).map((call: FunctionCall) => (
              <div
                key={call.id}
                className="p-2 rounded bg-(--color-background-secondary) text-xs font-mono"
              >
                <span className="text-(--color-accent-primary)">{call.name}</span>
                <span className="text-(--color-text-tertiary)">
                  (
                  {call.arguments.length > 100
                    ? call.arguments.slice(0, 100) + '...'
                    : call.arguments}
                  )
                </span>
              </div>
            ))}
          </div>
        )}

        {type === 'tool_result' && (
          <div className="space-y-1">
            {((message as { content: FunctionExecutionResult[] }).content ?? []).map(
              (result: FunctionExecutionResult) => (
                <pre
                  key={result.call_id}
                  className="p-2 rounded bg-(--color-background-secondary) text-xs font-mono whitespace-pre-wrap break-words max-h-40 overflow-y-auto"
                >
                  {result.content.length > 500
                    ? result.content.slice(0, 500) + '...'
                    : result.content}
                </pre>
              ),
            )}
          </div>
        )}

        {type === 'chunk' && (
          <span className="text-sm text-(--color-text-tertiary) italic">
            {String((message as { content: string }).content ?? '')}
          </span>
        )}
      </div>
    </div>
  )
})
