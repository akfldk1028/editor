'use client'

import { useEffect } from 'react'
import { currentConversation, restoreConversationProject, selectConversationProject, useConversationSelection } from '@/lib/design-conversation/session'
import { useProjects } from '@/lib/design-conversation/projects'

export function useConversationProject() {
  const selection = useConversationSelection()
  const { items: projects, loading, error } = useProjects()
  useEffect(() => {
    if (loading) return
    restoreConversationProject()
    const selected = currentConversation().projectId
    const known = !!selected && projects.some((item) => item.project_id === selected)
    // A remembered workspace that no longer exists (deleted, another actor) falls back like none was remembered.
    if (!known && projects.length) selectConversationProject((projects.find((item) => !item.conversation) ?? projects[0]!).project_id)
    else if (known) selectConversationProject(selected)
  }, [loading, projects, selection.projectId])
  const chosen = projects.find((project) => project.project_id === selection.projectId)
  return { ...selection, projectId: chosen?.project_id ?? null, projects, loading, error }
}
