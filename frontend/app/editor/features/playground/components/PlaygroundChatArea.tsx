import { AlertCircle, Bot, MessageSquare } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { PresetPanel } from '@/features/assistants'
import { stripThinkTags, ThinkingIndicator } from '@/features/streaming'
import type { useToolApproval } from '@/features/tool-approval'
import { ToolApprovalCard } from '@/features/tool-approval'
import type { useExecutionStore } from '../executionStore'
import { AgentTurnCard, RunSummaryCard } from './MessageCards'

type ExecutionState = ReturnType<typeof useExecutionStore.getState>
type ToolApproval = ReturnType<typeof useToolApproval>

interface PlaygroundChatAreaProps {
  scrollRef: React.RefObject<HTMLDivElement | null>
  turns: ExecutionState['turns']
  isRunning: ExecutionState['isRunning']
  status: ExecutionState['status']
  error: ExecutionState['error']
  streamingChunks: ExecutionState['streamingChunks']
  streamingSource: ExecutionState['streamingSource']
  inputRequest: ExecutionState['inputRequest']
  currentSessionId: ExecutionState['currentSessionId']
  runSummary: ExecutionState['runSummary']
  messagesLoading: boolean
  selectedPresetId: string | null
  setSelectedPresetId: (id: string | null) => void
  handlePromptClick: (prompt: string) => void
  isThinking: boolean
  thinkingStartRef: React.RefObject<number | null>
  pendingApproval: ToolApproval['pending']
  approvalQueueLength: ToolApproval['queueLength']
  handleApprove: ToolApproval['handleApprove']
  handleApproveAlways: ToolApproval['handleApproveAlways']
  handleReject: ToolApproval['handleReject']
}

export function PlaygroundChatArea({
  scrollRef,
  turns,
  isRunning,
  status,
  error,
  streamingChunks,
  streamingSource,
  inputRequest,
  currentSessionId,
  runSummary,
  messagesLoading,
  selectedPresetId,
  setSelectedPresetId,
  handlePromptClick,
  isThinking,
  thinkingStartRef,
  pendingApproval,
  approvalQueueLength,
  handleApprove,
  handleApproveAlways,
  handleReject,
}: PlaygroundChatAreaProps) {
  const { t } = useTranslation()
  const isInputMode = inputRequest !== null
  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-auto p-6 space-y-4 bg-(--color-background-primary)"
    >
      {turns.length === 0 && !isRunning && status !== 'error' && !messagesLoading && (
        <div className="flex flex-col h-full">
          <div className="flex items-center justify-center flex-1">
            <div className="text-center">
              <Bot className="w-16 h-16 mx-auto text-(--color-text-tertiary) mb-4" />
              <h2 className="text-heading-medium text-(--color-text-secondary)">
                {currentSessionId ? t('playground.emptySession') : t('playground.readyTitle')}
              </h2>
              <p className="text-body-medium text-(--color-text-tertiary) mt-2">
                {currentSessionId ? t('playground.emptySessionDesc') : t('playground.readyDesc')}
              </p>
            </div>
          </div>
          {!currentSessionId && (
            <PresetPanel
              selectedPresetId={selectedPresetId}
              onSelectPreset={setSelectedPresetId}
              onPromptClick={handlePromptClick}
            />
          )}
        </div>
      )}

      {/* Loading state for session history */}
      {messagesLoading && turns.length === 0 && (
        <div className="flex items-center justify-center h-full">
          <div className="text-center">
            <div className="w-8 h-8 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-body-medium text-(--color-text-tertiary)">
              {t('playground.loadingHistory')}
            </p>
          </div>
        </div>
      )}

      {turns.map((turn, i) => (
        <AgentTurnCard
          key={`${turn.source}-${turn.timestamp}-${i}`}
          source={turn.source}
          content={turn.content}
          images={turn.images}
          timestamp={turn.timestamp}
          messageType={turn.messageType}
          tokensIn={turn.tokensIn}
          tokensOut={turn.tokensOut}
        />
      ))}

      {/* Streaming chunk display (think tags stripped) */}
      {streamingSource && streamingChunks && (
        <AgentTurnCard
          source={streamingSource}
          content={stripThinkTags(streamingChunks)}
          timestamp=""
          messageType="agent"
          isStreaming
        />
      )}

      {/* Thinking indicator with elapsed timer */}
      {isThinking && thinkingStartRef.current && (
        <ThinkingIndicator startedAt={thinkingStartRef.current} />
      )}

      {/* Tool approval card */}
      {pendingApproval && (
        <ToolApprovalCard
          approval={pendingApproval}
          queueLength={approvalQueueLength}
          onApprove={handleApprove}
          onApproveAlways={handleApproveAlways}
          onReject={handleReject}
        />
      )}

      {/* Input request indicator */}
      {isInputMode && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-(--color-accent-primary-light)">
          <MessageSquare className="w-4 h-4 text-(--color-accent-primary) shrink-0" />
          <span className="text-body-small text-(--color-text-secondary)">
            {t('playground.requestingInput', {
              source: inputRequest.source,
              prompt: inputRequest.prompt,
            })}
          </span>
        </div>
      )}

      {/* Error display */}
      {status === 'error' && error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-(--color-semantic-error)/10">
          <AlertCircle className="w-4 h-4 text-(--color-semantic-error) shrink-0 mt-0.5" />
          <span className="text-body-small text-(--color-semantic-error)">{error}</span>
        </div>
      )}

      {/* Run Summary (shown after completion) */}
      {runSummary && !isRunning && <RunSummaryCard summary={runSummary} />}
    </div>
  )
}
