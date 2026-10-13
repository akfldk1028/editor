'use client'

import { useSyncExternalStore } from 'react'
import { activateConversationContext } from './context'

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
export function selectConversationProject(projectId: string | null) {
  if (projectId === selection.projectId) return
  selection = { projectId, conversationId: projectId ? read(key(projectId)) || 'main' : 'main' }
  if (projectId && pendingNew) {
    pendingNew = false
    selection = { projectId, conversationId: crypto.randomUUID() }
    write(key(projectId), selection.conversationId)
  }
  activateConversationContext(projectId)
  write('design-conversation-project', projectId ?? '')
  emit()
}
export function restoreConversationProject() {
  if (!selection.projectId) selectConversationProject(new URLSearchParams(window.location.search).get('project') || read('design-conversation-project'))
}
export function newConversation() {
  if (!selection.projectId) { pendingNew = true; return }
  selection = { ...selection, conversationId: crypto.randomUUID() }
  write(key(selection.projectId!), selection.conversationId)
  emit()
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
export const useConversationSelection = () => useSyncExternalStore(subscribe, currentConversation, () => initial)
