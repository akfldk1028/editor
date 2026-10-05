/**
 * FlowPage - Standalone React Flow window that syncs with Playground via BroadcastChannel.
 * Opened via window.open('/flow') from the Playground "Pop Out" button.
 */

import { memo, useState, useEffect, useMemo, useCallback, lazy, Suspense } from 'react'
import { ChevronLeft, ChevronRight, X, Bot, User, Radio } from 'lucide-react'
import type { AgentTurn } from './executionStore'
import type { Participant } from '@/features/team-builder/agentflow'
import { onFlowState, requestFlowState, sendFlowAlive, type FlowSyncPayload } from './flowChannel'

const AgentFlow = lazy(() =>
  import('@/features/team-builder/agentflow').then(m => ({ default: m.AgentFlow }))
)

const MAX_MSG_LEN = 120

function truncateMsg(text: string): string {
  if (text.length <= MAX_MSG_LEN) return text
  return text.slice(0, MAX_MSG_LEN - 1) + '\u2026'
}

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

// Agent detail panel shown below the flow
const AgentDetailPanel = memo(function AgentDetailPanel({
  selectedAgent,
  msgs,
  msgIndex,
  onPrev,
  onNext,
  onClose,
}: {
  selectedAgent: string
  msgs: AgentTurn[]
  msgIndex: number
  onPrev: () => void
  onNext: () => void
  onClose: () => void
}) {
  const currentMsg = msgs[msgIndex]
  if (!currentMsg) return null
  const isUser = selectedAgent === 'user' || selectedAgent === 'User'

  return (
    <div className="border-t border-(--color-border-default) bg-(--color-background-primary) px-4 py-3 max-h-[40vh] overflow-y-auto">
      <div className="flex items-center gap-2 mb-2">
        <div className="w-7 h-7 rounded-full flex items-center justify-center bg-(--color-accent-primary)/10 text-(--color-accent-primary)">
          {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
        </div>
        <span className="text-sm font-semibold text-(--color-accent-primary)">{selectedAgent}</span>
        <span className="text-xs text-(--color-text-tertiary)">
          {currentMsg.timestamp ? new Date(currentMsg.timestamp).toLocaleTimeString() : ''}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={onPrev}
            disabled={msgIndex === 0}
            className="p-1 rounded hover:bg-(--color-background-secondary) disabled:opacity-30 transition-colors"
            aria-label="Previous message"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-xs text-(--color-text-tertiary) min-w-[40px] text-center">
            {msgIndex + 1} / {msgs.length}
          </span>
          <button
            type="button"
            onClick={onNext}
            disabled={msgIndex >= msgs.length - 1}
            className="p-1 rounded hover:bg-(--color-background-secondary) disabled:opacity-30 transition-colors"
            aria-label="Next message"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) hover:text-(--color-text-primary) ml-1 transition-colors"
            aria-label="Close agent detail"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
      <div className="text-sm text-(--color-text-primary) whitespace-pre-wrap leading-relaxed">
        {renderMessageContent(currentMsg.content)}
      </div>
    </div>
  )
})

export function FlowPage() {
  const [state, setState] = useState<FlowSyncPayload | null>(null)
  const [connected, setConnected] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null)
  const [msgIndex, setMsgIndex] = useState(0)

  // Listen for BroadcastChannel updates + send periodic alive pings
  useEffect(() => {
    const unsub = onFlowState((payload) => {
      setState(payload)
      setConnected(true)
    })
    // Request initial state + send alive pings every 2s
    requestFlowState()
    sendFlowAlive()
    const interval = setInterval(() => sendFlowAlive(), 2000)
    return () => {
      unsub()
      clearInterval(interval)
    }
  }, [])

  const turns = state?.turns ?? []
  const teamProvider = state?.teamProvider ?? ''
  const isRunning = state?.isRunning ?? false
  const status = state?.status ?? 'idle'
  const streamingSource = state?.streamingSource ?? null

  const participants = useMemo(() => {
    if (!state?.teamComponent) return []
    const config = (state.teamComponent as Record<string, unknown>)?.config as Record<string, unknown> | undefined
    return (config?.participants ?? []) as Participant[]
  }, [state?.teamComponent])

  const activeAgents = useMemo(() => {
    const set = new Set<string>()
    if (streamingSource) set.add(streamingSource)
    const agentTurns = turns.filter((t) => t.messageType === 'agent')
    const recent = agentTurns.slice(-2)
    for (const t of recent) set.add(t.source)
    return set
  }, [streamingSource, turns])

  const agentMessages = useMemo(() => {
    const map = new Map<string, string>()
    for (const t of turns) {
      if (t.source !== 'user' && t.messageType !== 'llm_event' && t.content) {
        map.set(t.source, truncateMsg(t.content))
      }
    }
    return map
  }, [turns])

  const selectedAgentMsgs = useMemo(() => {
    if (!selectedAgent) return []
    return turns.filter((t) => t.source === selectedAgent && t.messageType !== 'llm_event')
  }, [selectedAgent, turns])

  const handleNodeClick = useCallback((agentName: string) => {
    setSelectedAgent((prev) => prev === agentName ? null : agentName)
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

  const isComplete = status === 'completed'
  const runStatus = status === 'error' ? 'error' : status === 'completed' ? 'complete' : undefined

  const stopReason = state?.stopReason ?? null

  const runReason = useMemo(() => {
    if (!isComplete) return undefined
    if (stopReason) return stopReason
    const agentTurns = turns.filter(t => t.messageType === 'agent')
    const last = agentTurns[agentTurns.length - 1]
    return last ? `by ${last.source}` : undefined
  }, [isComplete, stopReason, turns])

  return (
    <div className="h-screen flex flex-col bg-(--color-background-secondary)">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-(--color-border-default) bg-(--color-surface-card)">
        <Bot className="w-5 h-5 text-(--color-accent-primary)" />
        <span className="text-sm font-semibold text-(--color-text-primary)">Agent Flow Monitor</span>
        <div className="flex items-center gap-1.5 ml-2">
          <Radio className={`w-3.5 h-3.5 ${connected ? 'text-(--color-semantic-success)' : 'text-(--color-text-tertiary)'}`} />
          <span className={`text-xs ${connected ? 'text-(--color-semantic-success)' : 'text-(--color-text-tertiary)'}`}>
            {connected ? 'Connected' : 'Waiting for Playground...'}
          </span>
        </div>
        {isRunning && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-(--color-semantic-success)/10 text-(--color-semantic-success) ml-auto">
            Running
          </span>
        )}
        {status === 'completed' && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-(--color-accent-primary)/10 text-(--color-accent-primary) ml-auto">
            Completed
          </span>
        )}
      </div>

      {/* Flow area - takes all available space */}
      <div className="flex-1 min-h-0">
        {!connected && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div className="w-10 h-10 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              <p className="text-sm text-(--color-text-secondary)">Waiting for Playground connection...</p>
              <p className="text-xs text-(--color-text-tertiary) mt-1">Open the Playground page in another window</p>
            </div>
          </div>
        )}

        {connected && participants.length > 0 && (
          <Suspense fallback={
            <div className="flex items-center justify-center h-full">
              <div className="w-6 h-6 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" />
            </div>
          }>
            <AgentFlow
              teamProvider={teamProvider}
              participants={participants}
              height="100%"
              activeAgents={activeAgents}
              isProcessing={isRunning}
              isComplete={isComplete}
              runStatus={runStatus}
              runReason={runReason}
              agentMessages={agentMessages}
              onNodeClick={handleNodeClick}
            />
          </Suspense>
        )}

        {connected && participants.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-(--color-text-tertiary)">Select a team in the Playground to see the flow</p>
          </div>
        )}
      </div>

      {/* Agent detail panel */}
      {selectedAgent && selectedAgentMsgs.length > 0 && (
        <AgentDetailPanel
          selectedAgent={selectedAgent}
          msgs={selectedAgentMsgs}
          msgIndex={msgIndex}
          onPrev={handlePrev}
          onNext={handleNext}
          onClose={handleClose}
        />
      )}
    </div>
  )
}
