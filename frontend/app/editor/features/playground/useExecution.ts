import { useQuery } from '@tanstack/react-query'
import { api } from '@/features/playground/api'
import { messageContent } from './message-content'
import type { AgentTurn, RunSummary } from './executionStore'
import type { Message, AgentMessageConfig, TextMessageConfig, Run } from '@/lib/contracts/workspace'

export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: api.getSessions,
  })
}

export function useSessionRuns(sessionId: number | null) {
  return useQuery({
    queryKey: ['sessions', sessionId, 'runs'],
    queryFn: () => api.getSessionRuns(sessionId!),
    enabled: sessionId !== null,
  })
}

// Convert session run messages into AgentTurn[] for display in the chat area
function messagesFromRuns(runs: { runs: Array<{ messages?: Message[]; created_at?: string }> }): AgentTurn[] {
  const turns: AgentTurn[] = []
  for (const run of runs.runs ?? []) {
    for (const msg of run.messages ?? []) {
      const config = msg.config as AgentMessageConfig
      // Only show text messages (skip tool calls, handoffs, etc.)
      if ('source' in config && 'content' in config) {
        const textConfig = config as TextMessageConfig
        const messageType = textConfig.source === 'user'
          ? 'user' as const
          : textConfig.source.includes('llm_call')
            ? 'llm_event' as const
            : 'agent' as const
        turns.push({
          source: textConfig.source,
          ...messageContent(textConfig.content),
          timestamp: msg.created_at ?? run.created_at ?? new Date().toISOString(),
          messageType,
          tokensIn: config.models_usage?.prompt_tokens,
          tokensOut: config.models_usage?.completion_tokens,
        })
      }
    }
  }
  return turns
}

// Extract RunSummary from the last completed run
function summaryFromLastRun(runs: Run[]): RunSummary | null {
  if (runs.length === 0) return null
  const lastRun = runs[runs.length - 1]
  if (!lastRun?.team_result?.task_result) return null

  const { task_result, duration } = lastRun.team_result
  const stopReason = task_result.stop_reason ?? null

  const turns = messagesFromRuns({ runs })
  const agentTurns = turns.filter(t => t.messageType === 'agent')
  const lastAgent = agentTurns.at(-1)?.source ?? null

  let totalTokensIn = 0
  let totalTokensOut = 0
  for (const t of turns) {
    totalTokensIn += t.tokensIn ?? 0
    totalTokensOut += t.tokensOut ?? 0
  }

  return {
    stopReason,
    duration,
    totalTokensIn,
    totalTokensOut,
    turnCount: turns.length,
    agentTurnCount: agentTurns.length,
    terminatedBy: lastAgent,
  }
}

// Load previous messages for a session by fetching all runs
export function useSessionMessages(sessionId: number | null) {
  const runsQuery = useSessionRuns(sessionId)

  return {
    ...runsQuery,
    turns: runsQuery.data ? messagesFromRuns(runsQuery.data) : [],
    runSummary: runsQuery.data ? summaryFromLastRun(runsQuery.data.runs) : null,
  }
}

// Check if a session belongs to a specific team
export function filterSessionsByTeam(
  sessions: Array<{ id?: number; team_id?: number; name: string; created_at?: string }>,
  teamId: number | null,
): Array<{ id?: number; team_id?: number; name: string; created_at?: string }> {
  if (teamId === null) return sessions
  return sessions.filter((s) => s.team_id === teamId)
}
