import { create } from 'zustand'
import { messageContent } from './message-content'
import type { WSMessage } from '@/features/playground/api/execution-client'
import type { BaseMessageConfig } from '@/lib/contracts/workspace'

export type MessageType = 'user' | 'agent' | 'llm_event'

export interface AgentTurn {
  source: string
  content: string
  images?: string[]
  timestamp: string
  messageType: MessageType
  tokensIn?: number
  tokensOut?: number
}

export interface RunSummary {
  stopReason: string | null
  duration: number | null
  totalTokensIn: number
  totalTokensOut: number
  turnCount: number
  agentTurnCount: number
  terminatedBy: string | null
}

interface ExecutionState {
  isRunning: boolean
  currentRunId: string | null
  currentSessionId: number | null
  turns: AgentTurn[]
  status: 'idle' | 'connecting' | 'running' | 'completed' | 'error'
  error: string | null
  streamingChunks: string
  streamingSource: string | null
  inputRequest: { prompt: string; source: string } | null
  runSummary: RunSummary | null

  startExecution: (runId: string, sessionId: number) => void
  addWSMessage: (msg: WSMessage) => void
  completeExecution: () => void
  setError: (error: string) => void
  submitInput: () => void
  clearStreaming: () => void
  setSession: (sessionId: number | null) => void
  setTurns: (turns: AgentTurn[]) => void
  setRunSummary: (summary: RunSummary | null) => void
  clearSession: () => void
  reset: () => void
}

export const useExecutionStore = create<ExecutionState>((set) => ({
  isRunning: false,
  currentRunId: null,
  currentSessionId: null,
  turns: [],
  status: 'idle',
  error: null,
  streamingChunks: '',
  streamingSource: null,
  inputRequest: null,
  runSummary: null,

  startExecution: (runId, sessionId) =>
    set({
      isRunning: true,
      currentRunId: runId,
      currentSessionId: sessionId,
      turns: [],
      status: 'connecting',
      error: null,
      streamingChunks: '',
      streamingSource: null,
      inputRequest: null,
      runSummary: null,
    }),

  addWSMessage: (msg) =>
    set((state) => {
      if (msg.type === 'message_chunk') {
        const data = msg.data as Record<string, unknown> | undefined
        const content = (data?.content as string) ?? (msg.content as string) ?? ''
        const source = (data?.source as string) ?? (msg.source as string) ?? state.streamingSource ?? 'agent'
        return {
          streamingChunks: state.streamingChunks + content,
          streamingSource: source,
          status: 'running' as const,
        }
      }

      if (msg.type === 'llm_call_event' && msg.data) {
        const raw = JSON.stringify(msg.data)
        const data = msg.data as unknown as Record<string, unknown>
        const response = data.response as Record<string, unknown> | undefined
        const usage = response?.usage as Record<string, unknown> | undefined
        return {
          turns: [...state.turns, {
            source: 'llm_call_event',
            content: raw,
            timestamp: msg.timestamp ?? new Date().toISOString(),
            messageType: 'llm_event' as const,
            tokensIn: usage?.prompt_tokens as number | undefined,
            tokensOut: usage?.completion_tokens as number | undefined,
          }],
          status: 'running' as const,
        }
      }

      if (msg.type === 'message' && msg.data) {
        const data = msg.data as BaseMessageConfig & { content?: string }
        if (data.source && data.content) {
          const usage = data.models_usage
          const messageType: MessageType = data.source === 'user'
            ? 'user'
            : data.source.includes('llm_call')
              ? 'llm_event'
              : 'agent'
          const turn: AgentTurn = {
            source: data.source,
            ...messageContent(data.content),
            timestamp: msg.timestamp ?? new Date().toISOString(),
            messageType,
            tokensIn: usage?.prompt_tokens,
            tokensOut: usage?.completion_tokens,
          }
          return {
            turns: [...state.turns, turn],
            status: 'running' as const,
            streamingChunks: '',
            streamingSource: null,
          }
        }
        return state
      }

      if (msg.type === 'input_request') {
        const data = msg.data as Record<string, unknown> | undefined
        const prompt = (data?.prompt as string) ?? 'Please provide input'
        const source = (data?.source as string) ?? (msg.source as string) ?? 'agent'
        return {
          inputRequest: { prompt, source },
          status: 'running' as const,
        }
      }

      if (msg.type === 'completion' || msg.type === 'result') {
        const data = msg.data as Record<string, unknown> | undefined
        const taskResult = data?.task_result as Record<string, unknown> | undefined
        const stopReason = (taskResult?.stop_reason as string) ?? null
        const duration = (data?.duration as number) ?? null

        const agentTurns = state.turns.filter(t => t.messageType === 'agent')
        const lastAgent = agentTurns.length > 0 ? agentTurns[agentTurns.length - 1]!.source : null

        let totalTokensIn = 0
        let totalTokensOut = 0
        for (const t of state.turns) {
          totalTokensIn += t.tokensIn ?? 0
          totalTokensOut += t.tokensOut ?? 0
        }

        return {
          status: 'completed' as const,
          isRunning: false,
          streamingChunks: '',
          streamingSource: null,
          inputRequest: null,
          runSummary: {
            stopReason,
            duration,
            totalTokensIn,
            totalTokensOut,
            turnCount: state.turns.length,
            agentTurnCount: agentTurns.length,
            terminatedBy: lastAgent,
          },
        }
      }

      if (msg.type === 'error') {
        return {
          status: 'error' as const,
          error: msg.error ?? 'Unknown error',
          isRunning: false,
          streamingChunks: '',
          streamingSource: null,
          inputRequest: null,
        }
      }

      return state
    }),

  completeExecution: () =>
    set((state) => ({ isRunning: false, status: state.status === 'error' ? 'error' : 'completed', streamingChunks: '', streamingSource: null, inputRequest: null })),

  setError: (error) =>
    set({ isRunning: false, status: 'error', error, streamingChunks: '', streamingSource: null, inputRequest: null }),

  submitInput: () =>
    set({ inputRequest: null }),

  clearStreaming: () =>
    set({ streamingChunks: '', streamingSource: null }),

  setSession: (sessionId) =>
    set({ currentSessionId: sessionId }),

  setTurns: (turns) =>
    set({ turns }),

  setRunSummary: (summary) =>
    set({ runSummary: summary }),

  clearSession: () =>
    set({ currentSessionId: null, currentRunId: null, turns: [], status: 'idle', error: null, isRunning: false, streamingChunks: '', streamingSource: null, inputRequest: null, runSummary: null }),

  // reset clears run state but preserves currentSessionId so user stays in the same session
  reset: () =>
    set((state) => ({
      isRunning: false,
      currentRunId: null,
      currentSessionId: state.currentSessionId,
      turns: state.turns,
      status: 'idle',
      error: null,
      streamingChunks: '',
      streamingSource: null,
      inputRequest: null,
      runSummary: state.runSummary,
    })),
}))
