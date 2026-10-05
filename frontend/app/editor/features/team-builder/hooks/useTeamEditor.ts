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
import { useCallback, useState } from 'react'
import type { PatternType } from '../agentflow/types'
import { patternToProvider } from '../agentflow/types'

interface DraftState {
  version: number
  teamId: number
  component: Component<TeamConfig>
  initial: Component<TeamConfig>
  history: Component<TeamConfig>[]
  future: Component<TeamConfig>[]
}

const MAX_HISTORY = 50

function checkpoint(draft: DraftState): DraftState {
  return {
    ...draft,
    history: [...draft.history.slice(-(MAX_HISTORY - 1)), draft.component],
    future: [],
  }
}

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
  const updateTeam = useUpdateTeam()
  const isEditing = draft !== null
  const isDirty =
    draft !== null && JSON.stringify(draft.component) !== JSON.stringify(draft.initial)
  const canUndo = !!draft?.history.length
  const canRedo = !!draft?.future.length

  const undo = useCallback(() => {
    setDraft((prev) => {
      if (!prev?.history.length) return prev
      return {
        ...prev,
        component: prev.history.at(-1)!,
        history: prev.history.slice(0, -1),
        future: [...prev.future, prev.component],
      }
    })
  }, [])

  const redo = useCallback(() => {
    setDraft((prev) => {
      if (!prev?.future.length) return prev
      return {
        ...prev,
        component: prev.future.at(-1)!,
        future: prev.future.slice(0, -1),
        history: [...prev.history, prev.component],
      }
    })
  }, [])

  const startEditing = useCallback((team: TeamResponse) => {
    if (!team.component) return
    setDraft({
      teamId: team.id,
      version: team.version,
      component: structuredClone(team.component),
      initial: structuredClone(team.component),
      history: [],
      future: [],
    })
  }, [])

  const cancelEditing = useCallback(() => {
    setDraft(null)
  }, [])

  const updateParticipant = useCallback((index: number, agent: Component<AgentConfig>) => {
    setDraft((prev) => {
      if (!prev) return prev
      const participants = getParticipants(prev.component)
      const updated = [...participants]
      updated[index] = agent
      return { ...checkpoint(prev), component: setParticipants(prev.component, updated) }
    })
  }, [])

  const addParticipant = useCallback((agent: Component<AgentConfig>) => {
    setDraft((prev) => {
      if (!prev) return prev
      const participants = getParticipants(prev.component)
      return {
        ...checkpoint(prev),
        component: setParticipants(prev.component, [...participants, agent]),
      }
    })
  }, [])

  const removeParticipant = useCallback((index: number) => {
    setDraft((prev) => {
      if (!prev) return prev
      const participants = getParticipants(prev.component)
      const updated = participants.filter((_, i) => i !== index)
      return { ...checkpoint(prev), component: setParticipants(prev.component, updated) }
    })
  }, [])

  const reorderParticipants = useCallback((fromIndex: number, toIndex: number) => {
    setDraft((prev) => {
      if (!prev) return prev
      const participants = [...getParticipants(prev.component)]
      const [moved] = participants.splice(fromIndex, 1)
      if (!moved) return prev
      participants.splice(toIndex, 0, moved)
      return { ...checkpoint(prev), component: setParticipants(prev.component, participants) }
    })
  }, [])

  const updatePattern = useCallback((pattern: PatternType) => {
    setDraft((prev) => {
      if (!prev) return prev
      return {
        ...checkpoint(prev),
        component: { ...prev.component, provider: patternToProvider(pattern) },
      }
    })
  }, [])

  const updateTermination = useCallback((termination: Component<TerminationConfig> | undefined) => {
    setDraft((prev) => {
      if (!prev) return prev
      const config = { ...prev.component.config } as Record<string, unknown>
      if (termination) {
        config.termination_condition = termination
      } else {
        delete config.termination_condition
      }
      return {
        ...checkpoint(prev),
        component: { ...prev.component, config: config as unknown as TeamConfig },
      }
    })
  }, [])

  const updateDraftComponent = useCallback((component: Component<TeamConfig>) => {
    setDraft((prev) => {
      if (!prev) return prev
      return { ...checkpoint(prev), component }
    })
  }, [])

  const save = useCallback(async () => {
    if (!draft) return
    const saved = await updateTeam.mutateAsync({
      id: draft.teamId,
      component: draft.component,
      version: draft.version,
    })
    setDraft((current) =>
      current === draft
        ? null
        : current?.teamId === draft.teamId
          ? { ...current, version: saved.version, initial: draft.component }
          : current,
    )
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
