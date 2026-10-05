/**
 * LiveAgentFlow - Real-time agent flow visualization for Playground
 * Connects executionStore state to AgentFlow to show live agent activity.
 * Click an agent node to browse all its messages with < > navigation.
 */

import { memo, useState, useMemo, useCallback, lazy, Suspense } from 'react'
import { ChevronUp, ChevronDown, ChevronLeft, ChevronRight, X, Bot, User } from 'lucide-react'
import type { TeamResponse } from '@/features/team-templates/api'
import type { AgentTurn } from './executionStore'
import type { Participant } from '@/features/team-builder/agentflow'

const AgentFlow = lazy(() =>
  import('@/features/team-builder/agentflow').then(m => ({ default: m.AgentFlow }))
)

const MAX_MSG_LEN = 80

function truncateMsg(text: string): string {
  if (text.length <= MAX_MSG_LEN) return text
  return text.slice(0, MAX_MSG_LEN - 1) + '\u2026'
}

// Simple code block renderer (shared with PlaygroundPage)
function renderMessageContent(text: string) {
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
          <pre className="px-3 py-2 text-xs font-mono bg-(--color-background-primary) text-(--color-text-primary) overflow-x-auto">
            <code>{code}</code>
          </pre>
        </div>
      )
    }
    return <span key={i}>{part}</span>
  })
}

interface LiveAgentFlowProps {
  team: TeamResponse
  turns: AgentTurn[]
  streamingSource: string | null
  isRunning: boolean
  status: string
  stopReason?: string | null
}

export const LiveAgentFlow = memo(function LiveAgentFlow({
  team,
  turns,
  streamingSource,
  isRunning,
  status,
  stopReason,
}: LiveAgentFlowProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)
  const [msgIndex, setMsgIndex] = useState(0)

  const activeAgents = useMemo(() => {
    const set = new Set<string>()
    if (streamingSource) set.add(streamingSource)
    const agentTurns = turns.filter((t) => t.messageType === 'agent')
    const recent = agentTurns.slice(-2)
    for (const t of recent) {
      set.add(t.source)
    }
    return set
  }, [streamingSource, turns])

  const participants = useMemo(() => {
    const config = team.component?.config as Record<string, unknown> | undefined
    return (config?.participants ?? []) as Participant[]
  }, [team])

  const teamProvider = team.component?.provider ?? ''

  const agentMessages = useMemo(() => {
    const map = new Map<string, string>()
    for (const t of turns) {
      if (t.source !== 'user' && t.messageType !== 'llm_event' && t.content) {
        map.set(t.source, truncateMsg(t.content))
      }
    }
    return map
  }, [turns])

  // All messages from selected agent (including user)
  const selectedAgentMsgs = useMemo(() => {
    if (!selectedAgent) return []
    return turns.filter((t) => t.source === selectedAgent && t.messageType !== 'llm_event')
  }, [selectedAgent, turns])

  const handleNodeClick = useCallback((agentName: string) => {
    setSelectedAgent((prev) => {
      if (prev === agentName) return null // toggle off
      return agentName
    })
    setMsgIndex(0)
  }, [])

  const handlePrev = useCallback(() => {
    setMsgIndex((prev) => Math.max(0, prev - 1))
  }, [])

  const handleNext = useCallback(() => {
    setMsgIndex((prev) => Math.min(selectedAgentMsgs.length - 1, prev + 1))
  }, [selectedAgentMsgs.length])

  const handleClose = useCallback(() => {
    setSelectedAgent(null)
    setMsgIndex(0)
  }, [])

  const isProcessing = isRunning
  const isComplete = status === 'completed'
  const runStatus = status === 'error' ? 'error' : status === 'completed' ? 'complete' : undefined

  // Determine run reason: prefer actual stop_reason from backend, fall back to last agent
  const runReason = useMemo(() => {
    if (!isComplete) return undefined
    if (stopReason) return stopReason
    const agentTurns = turns.filter(t => t.messageType === 'agent')
    const last = agentTurns[agentTurns.length - 1]
    return last ? `by ${last.source}` : undefined
  }, [isComplete, stopReason, turns])

  const currentMsg = selectedAgentMsgs[msgIndex]
  const isUser = selectedAgent === 'user' || selectedAgent === 'User'

  return (
    <div className="relative border-b border-(--color-border-default) bg-(--color-background-secondary)">
      {/* Collapse toggle */}
      <button
        type="button"
        onClick={() => setCollapsed(prev => !prev)}
        className="absolute top-2 right-2 z-10 p-1 rounded-md hover:bg-(--color-background-primary) text-(--color-text-tertiary) hover:text-(--color-text-primary) transition-colors"
        aria-label={collapsed ? 'Expand agent flow' : 'Collapse agent flow'}
      >
        {collapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
      </button>

      {/* Flow container */}
      <div
        className="overflow-hidden transition-[height] duration-300 ease-in-out"
        style={{ height: collapsed ? 0 : 300 }}
      >
        {!collapsed && (
          <Suspense fallback={
            <div className="flex items-center justify-center h-full">
              <div className="w-6 h-6 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" />
            </div>
          }>
            <AgentFlow
              teamProvider={teamProvider}
              participants={participants}
              height={300}
              activeAgents={activeAgents}
              isProcessing={isProcessing}
              isComplete={isComplete}
              runStatus={runStatus}
              runReason={runReason}
              agentMessages={agentMessages}
              onNodeClick={handleNodeClick}
            />
          </Suspense>
        )}
      </div>

      {/* Agent message detail panel (appears below flow when agent is selected) */}
      {selectedAgent && selectedAgentMsgs.length > 0 && currentMsg && (
        <div className="border-t border-(--color-border-default) bg-(--color-background-primary) px-4 py-3 max-h-[200px] overflow-y-auto">
          {/* Header */}
          <div className="flex items-center gap-2 mb-2">
            <div className="w-6 h-6 rounded-full flex items-center justify-center bg-(--color-accent-primary)/10 text-(--color-accent-primary)">
              {isUser ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
            </div>
            <span className="text-sm font-semibold text-(--color-accent-primary)">{selectedAgent}</span>
            <span className="text-xs text-(--color-text-tertiary)">
              {currentMsg.timestamp ? new Date(currentMsg.timestamp).toLocaleTimeString() : ''}
            </span>

            {/* Navigation */}
            <div className="ml-auto flex items-center gap-1">
              <button
                type="button"
                onClick={handlePrev}
                disabled={msgIndex === 0}
                className="p-1 rounded hover:bg-(--color-background-secondary) disabled:opacity-30 transition-colors"
                aria-label="Previous message"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-xs text-(--color-text-tertiary) min-w-[40px] text-center">
                {msgIndex + 1} / {selectedAgentMsgs.length}
              </span>
              <button
                type="button"
                onClick={handleNext}
                disabled={msgIndex >= selectedAgentMsgs.length - 1}
                className="p-1 rounded hover:bg-(--color-background-secondary) disabled:opacity-30 transition-colors"
                aria-label="Next message"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={handleClose}
                className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) hover:text-(--color-text-primary) ml-1 transition-colors"
                aria-label="Close agent detail"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Message content */}
          <div className="text-sm text-(--color-text-primary) whitespace-pre-wrap leading-relaxed">
            {renderMessageContent(currentMsg.content)}
          </div>
        </div>
      )}
    </div>
  )
})
