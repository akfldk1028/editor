import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { workspaceRequest } from '@/lib/workspace-request'
import { Button, Input, Badge } from '@/elements/workspace'
import { useTeams, getTeamName } from '@/features/team-templates/hooks/useTeams'
import { useTeamStore } from '@/features/team-templates/model/team-store'
import { useExecutionStore } from './executionStore'
import { useSessions, useSessionMessages, filterSessionsByTeam } from './useExecution'
import { ExecutionClient } from '@/features/playground/api/execution-client'
import type { FileAttachment } from '@/features/playground/api/execution-client'
import { api } from '@/features/playground/api'
import {
  Send, Square, Bot, User, AlertCircle, MessageSquare, History,
  ExternalLink,
} from 'lucide-react'
import { FileUpload } from './FileUpload'
import { LiveAgentFlow } from './LiveAgentFlow'
import { broadcastFlowState, onFlowPresence, getFlowChannelId } from './flowChannel'
import { useToolApproval, ToolApprovalCard, parseToolApproval, useToolApprovalStore } from '@/features/tool-approval'
import { useAutoScroll, stripThinkTags, ThinkingIndicator } from '@/features/streaming'
import { ScheduleIndicator, SchedulePanel, useScheduleStore, useScheduleRunner } from '@/features/schedule'
import { useContextUsage, ContextUsageRing } from '@/features/context-usage'
import { ExportButton } from '@/features/export'
import { PresetPanel } from '@/features/assistants'

import { AgentTurnCard, RunSummaryCard } from './components/MessageCards'

// Format session name for dropdown display
function formatSessionLabel(session: { id?: number; name: string; created_at?: string }): string {
  const date = session.created_at ? new Date(session.created_at).toLocaleDateString() : ''
  const time = session.created_at ? new Date(session.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''
  const name = session.name || `Session ${session.id ?? '?'}`
  return date ? `${name} (${date} ${time})` : name
}

export function PlaygroundPage() {
  const { t } = useTranslation()
  const [task, setTask] = useState('')
  const [files, setFiles] = useState<FileAttachment[]>([])
  const [starting, setStarting] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const submission = useRef(false)
  const inputSending = useRef(false)
  const generation = useRef(0)
  const popupTimer = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null)
  const { data: teams } = useTeams()
  const { data: allSessions, isLoading: sessionsLoading } = useSessions()
  const { selectedTeamId, selectTeam } = useTeamStore()
  const queryClient = useQueryClient()
  const {
    turns,
    status,
    isRunning,
    error,
    streamingChunks,
    streamingSource,
    inputRequest,
    currentSessionId,
    runSummary,
    startExecution,
    addWSMessage,
    submitInput,
    setSession,
    setTurns,
    setRunSummary,
    clearSession,
  } = useExecutionStore()
  const wsRef = useRef<ExecutionClient | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const selectedTeam = teams?.find((t) => t.id === selectedTeamId)
  const { data: capabilities } = useQuery({ queryKey: ['execution-capabilities'],
    queryFn: () => workspaceRequest<{ supported_providers: string[] }>('runs/capabilities') })
  const unsupportedProviders = useMemo(() => {
    if (!capabilities || !selectedTeam) return []
    const found = new Set<string>()
    const visit = (value: unknown) => {
      if (!value || typeof value !== 'object') return
      if ('provider' in value && typeof value.provider === 'string' && !capabilities.supported_providers.includes(value.provider)) found.add(value.provider)
      for (const child of Object.values(value)) visit(child)
    }
    visit(selectedTeam.component)
    return [...found]
  }, [capabilities, selectedTeam])
  const [flowPoppedOut, setFlowPoppedOut] = useState(false)
  const thinkingStartRef = useRef<number | null>(null)
  const { percentage, level, displayTotal, displayLimit, total: totalTokens } = useContextUsage(turns)

  // Track thinking start time
  const isThinking = isRunning && !streamingSource && turns.length > 0
  if (isThinking && thinkingStartRef.current === null) {
    thinkingStartRef.current = Date.now()
  } else if (!isThinking) {
    thinkingStartRef.current = null
  }

  // Filter sessions by selected team
  const teamSessions = useMemo(
    () => filterSessionsByTeam(allSessions ?? [], selectedTeamId),
    [allSessions, selectedTeamId],
  )

  // Load messages for selected session (only when session is selected and not running)
  const { turns: sessionTurns, isLoading: messagesLoading, runSummary: sessionRunSummary } = useSessionMessages(
    !isRunning && currentSessionId && teamSessions.some(session => session.id === currentSessionId) ? currentSessionId : null,
  )

  // When session messages load, populate the turns and summary (only if idle/completed and no live turns)
  useEffect(() => {
    if (sessionTurns.length > 0 && !isRunning && turns.length === 0) {
      setTurns(sessionTurns)
      if (sessionRunSummary) setRunSummary(sessionRunSummary)
    }
  }, [sessionTurns, isRunning, turns.length, setTurns, sessionRunSummary, setRunSummary])

  useEffect(() => {
    const value = Number(new URL(window.location.href).searchParams.get('team_id'))
    if (Number.isInteger(value) && value > 0) selectTeam(value)
  }, [selectTeam])

  useEffect(() => {
    generation.current++
    wsRef.current?.disconnect()
    wsRef.current = null
    submission.current = false
    setStarting(false)
    setUncertain(false)
    clearSession()
    const query = new URL(window.location.href).searchParams
    const session = Number(query.get('session_id'))
    if (Number(query.get('team_id')) === selectedTeamId && session > 0) {
      setSession(session)
      const runId = query.get('run_id')
      if (runId && /^[a-zA-Z0-9_-]+$/.test(runId)) {
        const token = generation.current
        const client = new ExecutionClient({ runId, sessionId: session,
          onMessage: message => { if (generation.current === token) addWSMessage(message) },
          onClose: () => {
            if (generation.current !== token) return
            setUncertain(false)
            useExecutionStore.getState().completeExecution()
            const url = new URL(window.location.href)
            url.searchParams.delete('run_id')
            window.history.replaceState(null, '', url)
            void queryClient.invalidateQueries({ queryKey: ['sessions'] })
          },
          onError: reason => {
            if (generation.current === token) { setUncertain(true); useExecutionStore.getState().setError(reason) }
          },
        })
        wsRef.current = client
        startExecution(runId, session)
        void api.getSessions().then(sessions => {
          if (generation.current !== token) return
          if (!sessions.some(item => item.id === session && item.team_id === selectedTeamId)) throw new Error('Saved session does not belong to the selected team')
          return client.resume()
        }).catch(reason => {
          if (generation.current === token) useExecutionStore.getState().setError(String(reason))
        })
      }
    }
    return () => {
      generation.current++
      wsRef.current?.disconnect()
      wsRef.current = null
      clearInterval(popupTimer.current)
    }
  }, [selectedTeamId, clearSession, setSession, addWSMessage, startExecution, queryClient])

  const rememberSelection = useCallback((teamId: number | null, sessionId: number | null, runId?: string) => {
    const url = new URL(window.location.href)
    if (teamId) url.searchParams.set('team_id', String(teamId))
    else url.searchParams.delete('team_id')
    if (sessionId) url.searchParams.set('session_id', String(sessionId))
    else url.searchParams.delete('session_id')
    if (runId) url.searchParams.set('run_id', runId)
    else url.searchParams.delete('run_id')
    window.history.replaceState(null, '', url)
  }, [])

  useAutoScroll(scrollRef, [turns, streamingChunks])

  // Build flow payload (memoized to avoid rebuilding on every render)
  const flowPayload = useMemo(() => ({
    type: 'flow-sync' as const,
    teamId: selectedTeamId,
    teamComponent: selectedTeam?.component ?? null,
    teamProvider: selectedTeam?.component?.provider ?? '',
    turns,
    status,
    isRunning,
    streamingSource,
    streamingChunks,
    stopReason: runSummary?.stopReason ?? null,
  }), [selectedTeamId, selectedTeam, turns, status, isRunning, streamingSource, streamingChunks, runSummary])

  // Always broadcast state changes to Flow window
  useEffect(() => {
    broadcastFlowState(flowPayload)
  }, [flowPayload])

  // Detect Flow window presence via periodic alive pings
  const flowTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => {
    const unsub = onFlowPresence(() => {
      setFlowPoppedOut(true)
      broadcastFlowState(flowPayload)
      // Reset timeout - if no ping in 3s, flow window is gone
      clearTimeout(flowTimeoutRef.current)
      flowTimeoutRef.current = setTimeout(() => setFlowPoppedOut(false), 3000)
    })
    return () => {
      unsub()
      clearTimeout(flowTimeoutRef.current)
    }
  }, [flowPayload])

  const handlePopOutFlow = useCallback(() => {
    const channel = getFlowChannelId()
    const w = window.open(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/playground/flow?channel=${channel}`, `editor-team-flow-${channel}`, 'width=900,height=700')
    if (w) {
      setFlowPoppedOut(true)
      // Detect when the popup window is closed
      clearInterval(popupTimer.current)
      const check = setInterval(() => {
        if (w.closed) {
          setFlowPoppedOut(false)
          clearInterval(check)
        }
      }, 1000)
      popupTimer.current = check
    }
  }, [])

  const handleSessionChange = useCallback((value: string) => {
    if (submission.current || useExecutionStore.getState().isRunning) return
    generation.current++
    wsRef.current?.disconnect()
    setUncertain(false)
    setRunSummary(null)
    rememberSelection(selectedTeamId, value === 'new' ? null : Number(value))
    if (value === 'new') {
      clearSession()
      return
    }
    const sessionId = value ? Number(value) : null
    if (sessionId !== null) {
      setSession(sessionId)
      // Clear current turns so session history can load
      setTurns([])
    } else {
      clearSession()
    }
  }, [clearSession, setSession, setTurns, setRunSummary, rememberSelection, selectedTeamId])

  const handleRun = useCallback(async (scheduledTask?: string) => {
    const prompt = typeof scheduledTask === 'string' ? scheduledTask : task
    if (!prompt.trim() || !selectedTeamId || unsupportedProviders.length || submission.current || uncertain || useExecutionStore.getState().isRunning) return false
    if (currentSessionId !== null && !teamSessions.some(session => session.id === currentSessionId)) return false
    submission.current = true
    setStarting(true)
    const token = generation.current
    const current = () => generation.current === token && useTeamStore.getState().selectedTeamId === selectedTeamId

    try {
      let sessionId = scheduledTask ? null : currentSessionId

      // If no existing session, create a new one
      if (sessionId === null) {
        const session = await api.createSession(selectedTeamId)
        if (!current()) return false
        sessionId = session.id ?? 0
        if (!sessionId) throw new Error('Invalid session identity')
        setSession(sessionId)
        rememberSelection(selectedTeamId, sessionId)
        // Invalidate sessions list so the dropdown updates
        queryClient.invalidateQueries({ queryKey: ['sessions'] })
      }

      const run = await api.createRun(sessionId)
      if (!current()) {
        const abandoned = new ExecutionClient({ runId: run.run_id, onMessage: () => {} })
        await abandoned.stop()
        abandoned.disconnect()
        return false
      }
      rememberSelection(selectedTeamId, sessionId, String(run.run_id))

      startExecution(String(run.run_id), sessionId)

      const ws = new ExecutionClient({
        runId: run.run_id,
        sessionId,
        onMessage: (msg) => {
          if (!current()) return
          // Intercept input_request to check for tool approval patterns
          if (msg.type === 'input_request') {
            const data = msg.data as Record<string, unknown> | undefined
            const prompt = (data?.prompt as string) ?? ''
            const source = (data?.source as string) ?? (msg.source as string) ?? 'agent'
            const parsed = parseToolApproval(prompt, source)
            if (parsed) {
              const result = useToolApprovalStore.getState().enqueue(parsed)
              if (result === 'auto-approved') {
                // Tool in always-allow cache — auto-respond
                void ws.sendInput('APPROVE').catch(() => {})
              }
              // Don't pass to store — handled by tool-approval UI
              return
            }
          }
          addWSMessage(msg)
        },
        onClose: () => {
          if (!current()) return
          setUncertain(false)
          rememberSelection(selectedTeamId, sessionId)
          useExecutionStore.getState().completeExecution()
          // Invalidate session runs so history reloads
          queryClient.invalidateQueries({ queryKey: ['sessions', sessionId, 'runs'] })
          queryClient.invalidateQueries({ queryKey: ['sessions'] })
        },
        onError: (error) => {
          if (current()) { setUncertain(true); useExecutionStore.getState().setError(error + ' Check session history before starting another run.') }
        },
      })

      wsRef.current = ws
      await ws.connect()
      if (!current()) return false
      await ws.startExecution(prompt, selectedTeam?.component, !scheduledTask && files.length > 0 ? files : undefined)
      if (!current()) return false
      if (!scheduledTask) { setTask(''); setFiles([]) }
      return true
    } catch (err) {
      if (current()) {
        setUncertain(true)
        useExecutionStore.getState().setError(String(err) + ' Check session history before starting another run.')
        void queryClient.invalidateQueries({ queryKey: ['sessions'] })
      }
      return false
    } finally {
      if (current()) { submission.current = false; setStarting(false) }
    }
  }, [task, selectedTeamId, selectedTeam, currentSessionId, files, startExecution, addWSMessage, setSession, queryClient, uncertain, teamSessions, rememberSelection, unsupportedProviders])

  const handleStop = useCallback(() => {
    void wsRef.current?.stop()
  }, [])

  const handleSendInput = useCallback(async () => {
    if (!task.trim() || !wsRef.current || inputSending.current) return
    inputSending.current = true
    const token = generation.current
    try {
      await wsRef.current.sendInput(task)
      if (generation.current !== token) return
      submitInput()
      setTask('')
    } catch { /* Transport callback displays the error without retrying input. */ }
    finally { inputSending.current = false }
  }, [task, submitInput])

  useScheduleRunner(useCallback(async (_jobId: string, teamId: number, prompt: string) => {
    if (teamId !== useTeamStore.getState().selectedTeamId) return false
    return handleRun(prompt)
  }, [handleRun]))

  // Tool approval integration
  const sendToolResponse = useCallback((response: string) => {
    void wsRef.current?.sendInput(response).catch(() => {})
  }, [])
  const {
    pending: pendingApproval,
    queueLength: approvalQueueLength,
    handleApprove,
    handleApproveAlways,
    handleReject,
  } = useToolApproval(sendToolResponse)

  // Schedule panel
  const scheduleOpen = useScheduleStore((s) => s.panelOpen)
  const toggleSchedule = useScheduleStore((s) => s.togglePanel)
  const closeSchedule = useCallback(() => useScheduleStore.getState().setPanelOpen(false), [])

  const handlePromptClick = useCallback((prompt: string) => {
    setTask(prompt)
  }, [])

  const handleFilesChange = setFiles

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    // Handle image paste from clipboard
    const items = Array.from(e.clipboardData.items)
    const imageItems = items.filter((item) => item.type.startsWith('image/'))

    if (imageItems.length > 0) {
      e.preventDefault()
      const imageFiles: File[] = []
      for (const item of imageItems) {
        const file = item.getAsFile()
        if (file) imageFiles.push(file)
      }
      if (imageFiles.length > 0) {
        // Read images and add to files
        Promise.all(
          imageFiles.map(async (file) => {
            const reader = new FileReader()
            return new Promise<FileAttachment>((resolve, reject) => {
              reader.onload = () => {
                resolve({
                  name: file.name || `pasted-image-${Date.now()}.png`,
                  type: file.type,
                  content: (reader.result as string).split(',')[1] ?? '',
                })
              }
              reader.onerror = () => reject(reader.error)
              reader.readAsDataURL(file)
            })
          }),
        ).then((newAttachments) => {
          setFiles((prev) => [...prev, ...newAttachments])
        }).catch(() => { /* Silently ignore paste read failures */ })
      }
      return
    }

    // Handle large text paste -> auto-convert to file attachment
    const pastedText = e.clipboardData.getData('text/plain')
    if (pastedText.length > 1500) {
      e.preventDefault()
      const content = btoa(unescape(encodeURIComponent(pastedText)))
      setFiles((prev) => [
        ...prev,
        {
          name: `pasted-text-${Date.now()}.txt`,
          type: 'text/plain',
          content,
        },
      ])
    }
  }, [])

  const isInputMode = inputRequest !== null

  return (
    <div className="flex flex-col h-full -m-6">
      {unsupportedProviders.length > 0 && <p role="alert" className="p-3">This team contains components not enabled for execution: {unsupportedProviders.join(', ')}. Edit the team to use supported components.</p>}
      {/* Top bar: Team selector + Session selector + Status */}
      <div className="flex items-center gap-3 p-4 border-b border-(--color-border-default) bg-(--color-surface-card) flex-wrap">
        {/* Team selector */}
        <span className="text-label text-(--color-text-secondary)">{t('playground.team')}</span>
        <select
          aria-label="Select a team"
          className="h-9 px-3 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-sm text-(--color-text-primary)"
          value={selectedTeamId ?? ''}
          disabled={starting || isRunning}
          onChange={(e) => {
            const team = e.target.value ? Number(e.target.value) : null
            rememberSelection(team, null)
            selectTeam(team)
          }}
        >
          <option value="">{t('playground.selectTeam')}</option>
          {teams?.map((t) => (
            <option key={t.id} value={t.id}>
              {getTeamName(t)}
            </option>
          ))}
        </select>

        {/* Separator */}
        <div className="w-px h-6 bg-(--color-border-default)" aria-hidden="true" />

        {/* Session selector */}
        <span className="text-label text-(--color-text-secondary)">
          <History className="w-4 h-4 inline-block mr-1 align-text-bottom" aria-hidden="true" />
          {t('playground.session')}
        </span>
        <select
          aria-label="Select a session"
          className="h-9 px-3 rounded-md border border-(--color-border-default) bg-(--color-surface-card) text-sm text-(--color-text-primary) max-w-[280px]"
          value={currentSessionId ?? 'new'}
          onChange={(e) => handleSessionChange(e.target.value)}
          disabled={!selectedTeamId || isRunning || starting}
        >
          <option value="new">
            {t('playground.newSession')}
          </option>
          {teamSessions.map((s) => (
            <option key={s.id} value={s.id}>
              {formatSessionLabel(s)}
            </option>
          ))}
        </select>

        {/* Loading indicator for sessions */}
        {(sessionsLoading || messagesLoading) && (
          <div className="w-4 h-4 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" aria-label="Loading sessions" />
        )}

        {/* Status badge */}
        {status !== 'idle' && (
          <Badge variant={status === 'running' ? 'success' : status === 'error' ? 'error' : 'default'}>
            {status}
          </Badge>
        )}

        {/* Pop Out Flow button */}
        {selectedTeam && !flowPoppedOut && (
          <button
            type="button"
            onClick={handlePopOutFlow}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs border border-(--color-border-default) hover:bg-(--color-background-secondary) text-(--color-text-secondary) hover:text-(--color-text-primary) transition-colors"
            aria-label="Open flow in new window"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            {t('playground.popOutFlow')}
          </button>
        )}

        {/* Export button */}
        <ExportButton
          turns={turns}
          teamName={selectedTeam ? getTeamName(selectedTeam) : ''}
          disabled={isRunning}
        />

        {/* Schedule indicator */}
        <ScheduleIndicator onClick={toggleSchedule} />

        {/* Context usage ring */}
        {totalTokens > 0 && (
          <ContextUsageRing
            percentage={percentage}
            level={level}
            displayTotal={displayTotal}
            displayLimit={displayLimit}
          />
        )}

        {/* Session indicator */}
        {currentSessionId !== null && (
          <span className="text-body-small text-(--color-text-tertiary) ml-auto">
            Session #{currentSessionId}
          </span>
        )}
      </div>

      {/* Live Agent Flow visualization (hidden when popped out to separate window) */}
      {selectedTeam && !flowPoppedOut && (
        <LiveAgentFlow
          team={selectedTeam}
          turns={turns}
          streamingSource={streamingSource}
          isRunning={isRunning}
          status={status}
          stopReason={runSummary?.stopReason}
        />
      )}

      {/* Pop-out indicator bar (when flow is in separate window) */}
      {selectedTeam && flowPoppedOut && (
        <div className="flex items-center gap-2 px-4 py-2 border-b border-(--color-border-default) bg-(--color-accent-primary)/5 text-xs text-(--color-accent-primary)">
          <ExternalLink className="w-3.5 h-3.5" />
          <span>{t('playground.flowInWindow')}</span>
          <button
            type="button"
            onClick={() => setFlowPoppedOut(false)}
            className="ml-auto text-xs underline hover:no-underline"
          >
            {t('playground.showInline')}
          </button>
        </div>
      )}

      {/* Chat area */}
      <div ref={scrollRef} className="flex-1 overflow-auto p-6 space-y-4 bg-(--color-background-primary)">
        {turns.length === 0 && !isRunning && status !== 'error' && !messagesLoading && (
          <div className="flex flex-col h-full">
            <div className="flex items-center justify-center flex-1">
              <div className="text-center">
                <Bot className="w-16 h-16 mx-auto text-(--color-text-tertiary) mb-4" />
                <h2 className="text-heading-medium text-(--color-text-secondary)">
                  {currentSessionId ? t('playground.emptySession') : t('playground.readyTitle')}
                </h2>
                <p className="text-body-medium text-(--color-text-tertiary) mt-2">
                  {currentSessionId
                    ? t('playground.emptySessionDesc')
                    : t('playground.readyDesc')}
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
              <p className="text-body-medium text-(--color-text-tertiary)">{t('playground.loadingHistory')}</p>
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
              {t('playground.requestingInput', { source: inputRequest.source, prompt: inputRequest.prompt })}
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
        {runSummary && !isRunning && (
          <RunSummaryCard summary={runSummary} />
        )}
      </div>

      {/* Input bar */}
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
          {(isRunning || uncertain) && <Button variant="danger" onClick={handleStop} aria-label="Stop execution"><Square className="w-4 h-4" /></Button>}
          {isRunning && !isInputMode ? (
            null
          ) : isInputMode ? (
            <Button onClick={handleSendInput} disabled={!task.trim()} aria-label="Send input">
              <Send className="w-4 h-4" />
            </Button>
          ) : (
            <Button onClick={() => void handleRun()} disabled={!task.trim() || !selectedTeamId || unsupportedProviders.length > 0 || starting || uncertain || messagesLoading} aria-label="Send task">
              <Send className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Schedule Panel (drawer) */}
      {scheduleOpen && (
        <SchedulePanel
          teamId={selectedTeamId}
          teamName={selectedTeam ? getTeamName(selectedTeam) : ''}
          onClose={closeSchedule}
        />
      )}
    </div>
  )
}
