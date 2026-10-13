'use client'

import { useCallback, useEffect, useState } from 'react'
import { resolveProject, type ProjectChoice } from '@/lib/orchestrator-runs/submit'
import type { ProjectBinding } from '@/lib/orchestrator-runs/types'
import { useProjects } from './projects'
import { currentConversation, selectConversationProject, useConversationSelection } from './session'

export type BindingProjects = { kind: 'loading' } | { kind: 'error'; text: string } | ProjectChoice

/**
 * The binding a panel works in: the conversation's (the shared project list knows a conversation's new workspace
 * at once), else the one the page was opened with, else the only one; several and none chosen → the user picks.
 */
export function useProjectBinding(projectParam?: string) {
  const selection = useConversationSelection()
  const list = useProjects()
  const [projects, setProjects] = useState<BindingProjects>({ kind: 'loading' })
  const setChosen = useCallback((binding: ProjectBinding | null) => selectConversationProject(binding?.project_id ?? null), [])
  useEffect(() => {
    if (list.loading) return
    if (list.error && !list.items.length) { setProjects({ kind: 'error', text: list.error }); return }
    const requested = currentConversation().projectId ?? projectParam
    const choice = requested && !list.items.some((item) => item.project_id === requested) && list.items.length
      ? { kind: 'choose' as const, projects: list.items } : resolveProject(list.items, requested)
    setProjects(choice)
    if (choice.kind === 'resolved') setChosen(choice.project)
  }, [projectParam, setChosen, list.loading, list.error, list.items])
  return { projects, chosen: list.items.find((item) => item.project_id === selection.projectId) ?? null, setChosen, conversationId: selection.conversationId }
}
