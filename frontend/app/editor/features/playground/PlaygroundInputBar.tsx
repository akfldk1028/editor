import { Send, Square } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button, Input } from '@/elements/workspace'
import type { FileAttachment } from '@/features/playground/api/execution-client'
import type { useExecutionStore } from './executionStore'
import { FileUpload } from './FileUpload'

type ExecutionState = ReturnType<typeof useExecutionStore.getState>

interface PlaygroundInputBarProps {
  files: FileAttachment[]
  handleFilesChange: React.ComponentProps<typeof FileUpload>['onFilesChange']
  task: string
  setTask: (value: string) => void
  handlePaste: (e: React.ClipboardEvent) => void
  isRunning: ExecutionState['isRunning']
  inputRequest: ExecutionState['inputRequest']
  currentSessionId: ExecutionState['currentSessionId']
  selectedTeamId: number | null
  unsupportedProviders: string[]
  starting: boolean
  uncertain: boolean
  messagesLoading: boolean
  handleRun: (scheduledTask?: string) => Promise<boolean>
  handleSendInput: () => Promise<void>
  handleStop: () => void
}

export function PlaygroundInputBar({
  files,
  handleFilesChange,
  task,
  setTask,
  handlePaste,
  isRunning,
  inputRequest,
  currentSessionId,
  selectedTeamId,
  unsupportedProviders,
  starting,
  uncertain,
  messagesLoading,
  handleRun,
  handleSendInput,
  handleStop,
}: PlaygroundInputBarProps) {
  const { t } = useTranslation()
  const isInputMode = inputRequest !== null
  return (
    <div className="p-4 border-t border-(--color-border-default) bg-(--color-surface-card)">
      {/* File attachments list */}
      {files.length > 0 && (
        <div className="mb-2">
          <FileUpload
            files={files}
            onFilesChange={handleFilesChange}
            disabled={isRunning && !isInputMode}
          />
        </div>
      )}
      <div className="flex items-center gap-2">
        {/* Attach button (only show when no files displayed above) */}
        {files.length === 0 && (
          <FileUpload
            files={files}
            onFilesChange={handleFilesChange}
            disabled={isRunning && !isInputMode}
          />
        )}
        <Input
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onPaste={handlePaste}
          placeholder={
            isInputMode
              ? t('playground.inputPlaceholder', { source: inputRequest.source })
              : currentSessionId
                ? t('playground.continueSession')
                : t('playground.enterTask')
          }
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              if (isInputMode) handleSendInput()
              else handleRun()
            }
          }}
          disabled={starting || (isRunning && !isInputMode)}
          aria-label="Task or input"
        />
        {(isRunning || uncertain) && (
          <Button variant="danger" onClick={handleStop} aria-label="Stop execution">
            <Square className="w-4 h-4" />
          </Button>
        )}
        {isRunning && !isInputMode ? null : isInputMode ? (
          <Button onClick={handleSendInput} disabled={!task.trim()} aria-label="Send input">
            <Send className="w-4 h-4" />
          </Button>
        ) : (
          <Button
            onClick={() => void handleRun()}
            disabled={
              !task.trim() ||
              !selectedTeamId ||
              unsupportedProviders.length > 0 ||
              starting ||
              uncertain ||
              messagesLoading
            }
            aria-label="Send task"
          >
            <Send className="w-4 h-4" />
          </Button>
        )}
      </div>
    </div>
  )
}
