import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ExternalLink,
  User,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useContextUsage } from '@/features/context-usage'
import { api } from '@/features/playground/api'
import type { FileAttachment } from '@/features/playground/api/execution-client'
import { ExecutionClient } from '@/features/playground/api/execution-client'
import { SchedulePanel, useScheduleRunner, useScheduleStore } from '@/features/schedule'
import { useAutoScroll } from '@/features/streaming'
import { getTeamName, useTeams } from '@/features/team-templates/hooks/useTeams'
import { useTeamStore } from '@/features/team-templates/model/team-store'
import { parseToolApproval, useToolApproval, useToolApprovalStore } from '@/features/tool-approval'
import { workspaceRequest } from '@/lib/workspace-request'
import { PlaygroundChatArea } from './components/PlaygroundChatArea'
import { PlaygroundInputBar } from './components/PlaygroundInputBar'
import { PlaygroundTopBar } from './components/PlaygroundTopBar'
import { useExecutionStore } from './executionStore'
import { broadcastFlowState, getFlowChannelId, onFlowPresence } from './flowChannel'
import { LiveAgentFlow } from './LiveAgentFlow'
import { handleClipboardPaste } from './paste-attachments'
import { filterSessionsByTeam, useSessionMessages, useSessions } from './useExecution'

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
    queryFn: () => workspaceRequest<{ supported_providers: string[]; template_tools?: string[];
      template_workbenches?: string[]; template_mcp_providers?: string[] }>('runs/capabilities') })
  const unsupportedProviders = useMemo(() => {
    if (!capabilities || !selectedTeam) return []
    // Tools and workbenches the backend policy loads count as supported too.
    const known = new Set([...capabilities.supported_providers, ...(capabilities.template_tools ?? []),
      ...(capabilities.template_workbenches ?? []), ...(capabilities.template_mcp_providers ?? [])])
    const found = new Set<string>()
    const visit = (value: unknown) => {
      if (!value || typeof value !== 'object') return
      if ('provider' in value && typeof value.provider === 'string' && !known.has(value.provider)) found.add(value.provider)
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
    handleClipboardPaste(e, setFiles)
  }, [])


  return (
    <div className="flex flex-col h-full -m-6">
      {unsupportedProviders.length > 0 && <p role="alert" className="p-3">This team contains components not enabled for execution: {unsupportedProviders.join(', ')}. Edit the team to use supported components.</p>}
      {/* Top bar: Team selector + Session selector + Status */}
      <PlaygroundTopBar
        teams={teams}
        selectedTeamId={selectedTeamId}
        selectedTeam={selectedTeam}
        starting={starting}
        isRunning={isRunning}
        status={status}
        turns={turns}
        currentSessionId={currentSessionId}
        teamSessions={teamSessions}
        sessionsLoading={sessionsLoading}
        messagesLoading={messagesLoading}
        flowPoppedOut={flowPoppedOut}
        rememberSelection={rememberSelection}
        selectTeam={selectTeam}
        handleSessionChange={handleSessionChange}
        handlePopOutFlow={handlePopOutFlow}
        toggleSchedule={toggleSchedule}
        totalTokens={totalTokens}
        percentage={percentage}
        level={level}
        displayTotal={displayTotal}
        displayLimit={displayLimit}
      />

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
      <PlaygroundChatArea
        scrollRef={scrollRef}
        turns={turns}
        isRunning={isRunning}
        status={status}
        error={error}
        streamingChunks={streamingChunks}
        streamingSource={streamingSource}
        inputRequest={inputRequest}
        currentSessionId={currentSessionId}
        runSummary={runSummary}
        messagesLoading={messagesLoading}
        selectedPresetId={selectedPresetId}
        setSelectedPresetId={setSelectedPresetId}
        handlePromptClick={handlePromptClick}
        isThinking={isThinking}
        thinkingStartRef={thinkingStartRef}
        pendingApproval={pendingApproval}
        approvalQueueLength={approvalQueueLength}
        handleApprove={handleApprove}
        handleApproveAlways={handleApproveAlways}
        handleReject={handleReject}
      />

      {/* Input bar */}
      <PlaygroundInputBar
        files={files}
        handleFilesChange={handleFilesChange}
        task={task}
        setTask={setTask}
        handlePaste={handlePaste}
        isRunning={isRunning}
        inputRequest={inputRequest}
        currentSessionId={currentSessionId}
        selectedTeamId={selectedTeamId}
        unsupportedProviders={unsupportedProviders}
        starting={starting}
        uncertain={uncertain}
        messagesLoading={messagesLoading}
        handleRun={handleRun}
        handleSendInput={handleSendInput}
        handleStop={handleStop}
      />

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
