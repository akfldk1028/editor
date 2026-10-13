'use client'

import { useSyncExternalStore } from 'react'
import { startConversation } from '@/lib/orchestrator-runs/api'
import { activateConversationContext } from './context'
import { addProject } from './projects'

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
  if (projectId === selection.projectId) return
  selection = { projectId, conversationId: conversationId ?? (projectId ? read(key(projectId)) || 'main' : 'main') }
  activateConversationContext(projectId)
  write('design-conversation-project', projectId ?? '')
  emit()
  if (projectId && pendingNew) {
    pendingNew = false
    void newConversation()
  }
}
export function restoreConversationProject() {
  if (!selection.projectId) selectConversationProject(new URLSearchParams(window.location.search).get('project') || read('design-conversation-project'))
}
/**
 * A new conversation starts in a workspace of its own - the project's scene on a new branch - like a new chat thread:
 * what it records (its parcel, assessment date, brief) never binds another conversation. If the workspace cannot be
 * made, the conversation still starts, in the current one.
 */
export async function newConversation() {
  if (!selection.projectId) { pendingNew = true; return }
  const conversationId = crypto.randomUUID()
  try {
    const workspace = await startConversation(selection.projectId)
    addProject(workspace)
    write(key(workspace.project_id), conversationId)
    selectConversationProject(workspace.project_id, conversationId)
    return
  } catch {
    selection = { ...selection, conversationId }
    write(key(selection.projectId!), conversationId)
    emit()
  }
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
export const useConversationSelection = () => useSyncExternalStore(subscribe, currentConversation, () => initial)
