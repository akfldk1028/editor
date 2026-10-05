import { memo, useState } from 'react'
import { ChevronDown, ChevronRight, Cpu, Zap, User, Bot, StopCircle, BarChart3, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { MessageType, RunSummary } from '../executionStore'

// ---------- Markdown-lite renderer ----------
// Splits content by ``` code fences and renders code blocks with styling

function renderContent(text: string) {
  const parts = text.split(/(```[\s\S]*?```)/g)
  return parts.map((part, i) => {
    if (part.startsWith('```') && part.endsWith('```')) {
      const inner = part.slice(3, -3)
      const newlineIdx = inner.indexOf('\n')
      const lang = newlineIdx > 0 ? inner.slice(0, newlineIdx).trim() : ''
      const code = newlineIdx > 0 ? inner.slice(newlineIdx + 1) : inner
      return (
        <div key={i} className="my-2 rounded-lg overflow-hidden border border-(--color-border-default)">
          {lang && (
            <div className="px-3 py-1 text-xs font-mono bg-(--color-background-secondary) text-(--color-text-tertiary) border-b border-(--color-border-default)">
              {lang}
            </div>
          )}
          <pre className="px-4 py-3 text-sm font-mono bg-(--color-background-primary) text-(--color-text-primary) overflow-x-auto leading-relaxed">
            <code>{code}</code>
          </pre>
        </div>
      )
    }
    // Render inline code `...`
    const inlineParts = part.split(/(`[^`]+`)/g)
    return (
      <span key={i}>
        {inlineParts.map((ip, j) =>
          ip.startsWith('`') && ip.endsWith('`') ? (
            <code key={j} className="px-1.5 py-0.5 rounded bg-(--color-background-secondary) text-sm font-mono text-(--color-accent-primary)">
              {ip.slice(1, -1)}
            </code>
          ) : (
            <span key={j}>{ip}</span>
          ),
        )}
      </span>
    )
  })
}

// ---------- LLM Event Card (collapsible technical details) ----------

const LlmEventCard = memo(function LlmEventCard({
  content,
  timestamp,
  tokensIn,
  tokensOut,
}: {
  content: string
  timestamp: string
  tokensIn?: number
  tokensOut?: number
}) {
  const [expanded, setExpanded] = useState(false)

  // Parse model name from JSON content
  let model = ''
  try {
    const parsed = JSON.parse(content)
    model = parsed?.response?.model ?? ''
  } catch { /* ignore */ }

  const totalTokens = (tokensIn ?? 0) + (tokensOut ?? 0)

  return (
    <div className="mx-10 my-1">
      <button
        type="button"
        onClick={() => setExpanded((p) => !p)}
        className="flex items-center gap-2 w-full px-3 py-1.5 rounded-md text-xs
          bg-(--color-background-secondary) hover:bg-(--color-background-primary)
          border border-(--color-border-default) transition-colors group"
      >
        {expanded ? (
          <ChevronDown className="w-3 h-3 text-(--color-text-tertiary)" />
        ) : (
          <ChevronRight className="w-3 h-3 text-(--color-text-tertiary)" />
        )}
        <Cpu className="w-3 h-3 text-(--color-text-tertiary)" />
        <span className="text-(--color-text-tertiary)">LLM Call</span>
        {model && (
          <span className="font-mono text-(--color-accent-primary)">{model}</span>
        )}
        {totalTokens > 0 && (
          <span className="flex items-center gap-1 ml-auto text-(--color-text-tertiary)">
            <Zap className="w-3 h-3" />
            {tokensIn ?? 0}+{tokensOut ?? 0} tokens
          </span>
        )}
        <span className="text-(--color-text-tertiary) ml-2">
          {timestamp ? new Date(timestamp).toLocaleTimeString() : ''}
        </span>
      </button>
      {expanded && (
        <pre className="mt-1 px-4 py-3 rounded-md border border-(--color-border-default) bg-(--color-background-primary) text-xs font-mono text-(--color-text-secondary) overflow-x-auto max-h-64 overflow-y-auto leading-relaxed">
          {(() => {
            try { return JSON.stringify(JSON.parse(content), null, 2) }
            catch { return content }
          })()}
        </pre>
      )}
    </div>
  )
})

// ---------- Agent Message Card ----------

export const AgentTurnCard = memo(function AgentTurnCard({
  source,
  content,
  images,
  timestamp,
  messageType,
  tokensIn,
  tokensOut,
  isStreaming,
}: {
  source: string
  content: string
  images?: string[]
  timestamp: string
  messageType: MessageType
  tokensIn?: number
  tokensOut?: number
  isStreaming?: boolean
}) {
  // LLM events get their own compact card
  if (messageType === 'llm_event') {
    return <LlmEventCard content={content} timestamp={timestamp} tokensIn={tokensIn} tokensOut={tokensOut} />
  }

  const isUser = messageType === 'user'

  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      {/* Avatar */}
      <div className={cn(
        'w-9 h-9 rounded-full flex items-center justify-center shrink-0 shadow-sm',
        isUser
          ? 'bg-(--color-accent-primary) text-white'
          : 'bg-gradient-to-br from-(--color-accent-primary)/20 to-(--color-accent-primary)/5 text-(--color-accent-primary)'
      )}>
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-5 h-5" />}
      </div>

      {/* Message bubble */}
      <div className={cn(
        'max-w-[80%] rounded-2xl',
        isUser
          ? 'bg-(--color-accent-primary) text-white px-4 py-3'
          : 'bg-(--color-surface-card) shadow-sm border border-(--color-border-default) px-5 py-4',
      )}>
        {/* Header */}
        <div className={cn(
          'flex items-center gap-2 mb-2',
          isUser ? 'text-white/80' : '',
        )}>
          <span className={cn(
            'text-xs font-semibold',
            isUser ? 'text-white' : 'text-(--color-accent-primary)',
          )}>{source}</span>
          <span className={cn(
            'text-xs',
            isUser ? 'text-white/60' : 'text-(--color-text-tertiary)',
          )}>
            {timestamp ? new Date(timestamp).toLocaleTimeString() : 'now'}
          </span>
          {!isUser && tokensIn != null && tokensOut != null && (
            <span className="text-xs text-(--color-text-tertiary) flex items-center gap-1 ml-auto">
              <Zap className="w-3 h-3" />
              {tokensIn}+{tokensOut}
            </span>
          )}
        </div>

        {/* Content */}
        <div className={cn(
          'text-sm leading-relaxed whitespace-pre-wrap',
          isUser ? 'text-white' : 'text-(--color-text-primary)',
        )}>
          {isUser ? content : renderContent(content)}
          {images?.map((image, index) => <img key={index} src={image} alt={`Message attachment ${index + 1}`} className="max-w-full max-h-80 mt-2 rounded" />)}
          {isStreaming && <span className="animate-pulse text-(--color-accent-primary)">|</span>}
        </div>
      </div>
    </div>
  )
})

// ---------- Run Summary Card ----------

export const RunSummaryCard = memo(function RunSummaryCard({ summary }: { summary: RunSummary }) {
  const totalTokens = summary.totalTokensIn + summary.totalTokensOut
  const durationStr = summary.duration != null ? `${summary.duration.toFixed(1)}s` : '-'

  return (
    <div className="mx-4 my-3 rounded-lg border border-(--color-border-default) bg-(--color-surface-card) p-4">
      <div className="flex items-center gap-2 mb-3">
        <StopCircle className="w-4 h-4 text-(--color-semantic-success)" />
        <span className="text-sm font-semibold text-(--color-text-primary)">Execution Complete</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* Stop Reason */}
        <div className="space-y-1">
          <div className="flex items-center gap-1 text-xs text-(--color-text-tertiary)">
            <BarChart3 className="w-3 h-3" />
            Stop Reason
          </div>
          <p className="text-sm font-medium text-(--color-text-primary) truncate" title={summary.stopReason ?? 'Unknown'}>
            {summary.stopReason ?? 'Unknown'}
          </p>
        </div>
        {/* Duration */}
        <div className="space-y-1">
          <div className="flex items-center gap-1 text-xs text-(--color-text-tertiary)">
            <Clock className="w-3 h-3" />
            Duration
          </div>
          <p className="text-sm font-medium text-(--color-text-primary)">{durationStr}</p>
        </div>
        {/* Tokens */}
        <div className="space-y-1">
          <div className="flex items-center gap-1 text-xs text-(--color-text-tertiary)">
            <Zap className="w-3 h-3" />
            Tokens
          </div>
          <p className="text-sm font-medium text-(--color-text-primary)">
            {totalTokens > 0 ? `${summary.totalTokensIn}+${summary.totalTokensOut}` : '-'}
          </p>
        </div>
        {/* Terminated By */}
        <div className="space-y-1">
          <div className="flex items-center gap-1 text-xs text-(--color-text-tertiary)">
            <Bot className="w-3 h-3" />
            Last Agent
          </div>
          <p className="text-sm font-medium text-(--color-text-primary) truncate" title={summary.terminatedBy ?? '-'}>
            {summary.terminatedBy ?? '-'}
          </p>
        </div>
      </div>
      {/* Turn counts */}
      <div className="mt-2 text-xs text-(--color-text-tertiary)">
        {summary.agentTurnCount} agent turns / {summary.turnCount} total messages
      </div>
    </div>
  )
})
