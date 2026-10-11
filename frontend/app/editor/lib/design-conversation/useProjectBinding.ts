'use client'

import { useCallback, useEffect, useState } from 'react'
import { listProjects } from '@/lib/orchestrator-runs/api'
import { resolveProject, type ProjectChoice } from '@/lib/orchestrator-runs/submit'
import type { ProjectBinding } from '@/lib/orchestrator-runs/types'
import { currentConversation, selectConversationProject, useConversationSelection } from './session'

export type BindingProjects = { kind: 'loading' } | { kind: 'error'; text: string } | ProjectChoice

export function useProjectBinding(projectParam?: string) {
  const selection = useConversationSelection()
  const [projects, setProjects] = useState<BindingProjects>({ kind: 'loading' })
  const [bindings, setBindings] = useState<ProjectBinding[]>([])
  const setChosen = useCallback((binding: ProjectBinding | null) => selectConversationProject(binding?.project_id ?? null), [])
  useEffect(() => {
    const controller = new AbortController()
    listProjects(controller.signal).then((items) => {
      if (controller.signal.aborted) return
      setBindings(items)
      const requested = currentConversation().projectId ?? projectParam
      const choice = requested && !items.some((item) => item.project_id === requested) && items.length
        ? { kind: 'choose' as const, projects: items } : resolveProject(items, requested)
      setProjects(choice)
      if (choice.kind === 'resolved') setChosen(choice.project)
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setProjects({ kind: 'error', text: error instanceof Error ? error.message : 'Unable to load projects.' })
    })
    return () => controller.abort()
  }, [projectParam, setChosen])
  return { projects, chosen: bindings.find((item) => item.project_id === selection.projectId) ?? null, setChosen, conversationId: selection.conversationId }
}
