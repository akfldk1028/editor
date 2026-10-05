/**
 * useTeamEditor - Edit-mode state management hook
 * Manages draft component, dirty tracking, undo/redo history, and save/cancel operations
 */

import type { TeamResponse } from '@/features/team-templates/api'
import { useUpdateTeam } from '@/features/team-templates/hooks/useTeams'
import type {
  AgentConfig,
  Component,
  TeamConfig,
  TerminationConfig,
} from '@/lib/contracts/workspace'
import { useCallback, useRef, useState } from 'react'
import type { PatternType } from '../agentflow/types'
import { patternToProvider } from '../agentflow/types'

interface DraftState {
  version: number
  teamId: number
  component: Component<TeamConfig>
}

const MAX_HISTORY = 50

function getParticipants(comp: Component<TeamConfig>): Component<AgentConfig>[] {
  const config = comp.config as unknown as Record<string, unknown>
  return (config?.participants ?? []) as Component<AgentConfig>[]
}

function setParticipants(
  comp: Component<TeamConfig>,
  participants: Component<AgentConfig>[],
): Component<TeamConfig> {
  return {
    ...comp,
    config: { ...comp.config, participants } as TeamConfig,
  }
}

export function useTeamEditor() {
  const [draft, setDraft] = useState<DraftState | null>(null)
  const [isDirty, setIsDirty] = useState(false)
  const updateTeam = useUpdateTeam()

  // Undo/Redo history (refs to avoid re-render on push)
  const historyRef = useRef<Component<TeamConfig>[]>([])
  const futureRef = useRef<Component<TeamConfig>[]>([])

  const isEditing = draft !== null

  /**
   * Push component snapshot to history stack.
   * Called INSIDE setDraft updater to always capture the correct prev state.
   */
  function pushToHistory(component: Component<TeamConfig>) {
    historyRef.current = [
      ...historyRef.current.slice(-(MAX_HISTORY - 1)),
      structuredClone(component),
    ]
    futureRef.current = [] // clear redo on new edit
  }

  const canUndo = isEditing && historyRef.current.length > 0
  const canRedo = isEditing && futureRef.current.length > 0

  const undo = useCallback(() => {
    setDraft((prev) => {
      if (!prev || historyRef.current.length === 0) return prev
      const snapshot = historyRef.current.pop()!
      futureRef.current = [...futureRef.current, structuredClone(prev.component)]
      return { ...prev, component: snapshot }
    })
    setIsDirty(true)
  }, [])

  const redo = useCallback(() => {
    setDraft((prev) => {
      if (!prev || futureRef.current.length === 0) return prev
      const snapshot = futureRef.current.pop()!
      historyRef.current = [...historyRef.current, structuredClone(prev.component)]
      return { ...prev, component: snapshot }
    })
    setIsDirty(true)
  }, [])

  const startEditing = useCallback((team: TeamResponse) => {
    if (!team.component) return
    historyRef.current = []
    futureRef.current = []
    setDraft({
      teamId: team.id,
      version: team.version,
      component: structuredClone(team.component),
    })
    setIsDirty(false)
  }, [])

  const cancelEditing = useCallback(() => {
    historyRef.current = []
    futureRef.current = []
    setDraft(null)
    setIsDirty(false)
  }, [])

  const updateParticipant = useCallback((index: number, agent: Component<AgentConfig>) => {
    setDraft((prev) => {
      if (!prev) return prev
      pushToHistory(prev.component)
      const participants = getParticipants(prev.component)
      const updated = [...participants]
      updated[index] = agent
      return { ...prev, component: setParticipants(prev.component, updated) }
    })
    setIsDirty(true)
  }, [])

  const addParticipant = useCallback((agent: Component<AgentConfig>) => {
    setDraft((prev) => {
      if (!prev) return prev
      pushToHistory(prev.component)
      const participants = getParticipants(prev.component)
      return { ...prev, component: setParticipants(prev.component, [...participants, agent]) }
    })
    setIsDirty(true)
  }, [])

  const removeParticipant = useCallback((index: number) => {
    setDraft((prev) => {
      if (!prev) return prev
      pushToHistory(prev.component)
      const participants = getParticipants(prev.component)
      const updated = participants.filter((_, i) => i !== index)
      return { ...prev, component: setParticipants(prev.component, updated) }
    })
    setIsDirty(true)
  }, [])

  const reorderParticipants = useCallback((fromIndex: number, toIndex: number) => {
    setDraft((prev) => {
      if (!prev) return prev
      pushToHistory(prev.component)
      const participants = [...getParticipants(prev.component)]
      const [moved] = participants.splice(fromIndex, 1)
      if (!moved) return prev
      participants.splice(toIndex, 0, moved)
      return { ...prev, component: setParticipants(prev.component, participants) }
    })
    setIsDirty(true)
  }, [])

  const updatePattern = useCallback((pattern: PatternType) => {
    setDraft((prev) => {
      if (!prev) return prev
      pushToHistory(prev.component)
      return {
        ...prev,
        component: { ...prev.component, provider: patternToProvider(pattern) },
      }
    })
    setIsDirty(true)
  }, [])

  const updateTermination = useCallback((termination: Component<TerminationConfig> | undefined) => {
    setDraft((prev) => {
      if (!prev) return prev
      pushToHistory(prev.component)
      const config = { ...prev.component.config } as Record<string, unknown>
      if (termination) {
        config.termination_condition = termination
      } else {
        delete config.termination_condition
      }
      return { ...prev, component: { ...prev.component, config: config as unknown as TeamConfig } }
    })
    setIsDirty(true)
  }, [])

  const updateDraftComponent = useCallback((component: Component<TeamConfig>) => {
    setDraft((prev) => {
      if (!prev) return prev
      pushToHistory(prev.component)
      return { ...prev, component }
    })
    setIsDirty(true)
  }, [])

  const save = useCallback(async () => {
    if (!draft) return
    await updateTeam.mutateAsync({
      id: draft.teamId,
      component: draft.component,
      version: draft.version,
    })
    historyRef.current = []
    futureRef.current = []
    setDraft(null)
    setIsDirty(false)
  }, [draft, updateTeam])

  const participants = draft ? getParticipants(draft.component) : []

  return {
    isEditing,
    isDirty,
    draft,
    participants,
    isSaving: updateTeam.isPending,
    canUndo,
    canRedo,
    startEditing,
    cancelEditing,
    updateParticipant,
    addParticipant,
    removeParticipant,
    reorderParticipants,
    updatePattern,
    updateTermination,
    updateDraftComponent,
    undo,
    redo,
    save,
  }
}
