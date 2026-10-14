'use client'

import { useSyncExternalStore } from 'react'
import { startConversation } from '@/lib/orchestrator-runs/api'
import { activateConversationContext } from './context'
import { addProject, currentProjects } from './projects'

interface Selection { projectId: string | null; conversationId: string }
const initial: Selection = { projectId: null, conversationId: 'main' }
let selection = initial
// "새 대화" pressed before the project is known (the page is still reading it) starts one as soon as it is.
let pendingNew = false
const listeners = new Set<() => void>()
const key = (project: string) => `design-conversation:${project}`
const read = (name: string) => { try { return localStorage.getItem(name) } catch { return null } }
const write = (name: string, value: string) => { try { localStorage.setItem(name, value) } catch { /* Session still works when storage is unavailable. */ } }
const emit = () => listeners.forEach((listener) => { listener() })
export const currentConversation = () => selection
/** Shows a project's conversation: the one named, else the last one kept for it, else its first ('main'). */
export function selectConversationProject(projectId: string | null, conversationId?: string) {
  const saved = currentProjects().items.find((item) => item.project_id === projectId)?.conversation_id
  const nextId = conversationId ?? saved ?? (projectId ? read(key(projectId)) || 'main' : 'main')
  if (projectId === selection.projectId && selection.conversationId === nextId) return
  selection = { projectId, conversationId: nextId }
  if (projectId) write(key(projectId), nextId)
  activateConversationContext(projectId)
  write('design-conversation-project', projectId ?? '')
  emit()
  if (projectId && pendingNew) {
    pendingNew = false
    void newConversation().catch(() => undefined)
  }
}
export function restoreConversationProject() {
  if (!selection.projectId) selectConversationProject(new URLSearchParams(window.location.search).get('project') || read('design-conversation-project'))
}
/**
 * A new conversation starts in a workspace of its own - the project's scene on a new branch - like a new chat thread:
 * what it records (its parcel, assessment date, brief) never binds another conversation.
 */
let starting = false
export async function newConversation(): Promise<boolean> {
  if (!selection.projectId) { pendingNew = true; return false }
  // A second press while the workspace is being made would make a second one.
  if (starting) return false
  starting = true
  const source = selection.projectId
  try {
    const workspace = await startConversation(source)
    // The workspace exists once the server answered: it joins the list even when its id is missing.
    addProject(workspace)
    const conversationId = workspace.conversation_id ?? 'main'
    write(key(workspace.project_id), conversationId)
    // Opened only when the person is still where they pressed; otherwise it waits in the list.
    if (selection.projectId !== source) return false
    selectConversationProject(workspace.project_id, conversationId)
    return true
  } finally {
    starting = false
  }
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
export const useConversationSelection = () => useSyncExternalStore(subscribe, currentConversation, () => initial)
