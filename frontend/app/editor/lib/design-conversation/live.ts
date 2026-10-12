'use client'

import { useSyncExternalStore } from 'react'

import type { ConversationSnapshot } from './types'

/**
 * The latest snapshot of each conversation, published by its controller as it polls, for views that watch the
 * conversation without running a second poller (the 협업 flow): one store, keyed by project and conversation.
 */
const latest = new Map<string, ConversationSnapshot | null>()
const listeners = new Set<() => void>()
const key = (projectId: string, conversationId: string) => JSON.stringify([projectId, conversationId])

export function publishConversation(projectId: string, conversationId: string, snapshot: ConversationSnapshot | null): void {
  latest.set(key(projectId, conversationId), snapshot)
  listeners.forEach((listener) => { listener() })
}

export const latestConversation = (projectId: string | null, conversationId: string): ConversationSnapshot | null =>
  (projectId ? latest.get(key(projectId, conversationId)) : null) ?? null

const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }

export function useLiveConversation(projectId: string | null, conversationId: string): ConversationSnapshot | null {
  return useSyncExternalStore(subscribe, () => latestConversation(projectId, conversationId), () => null)
}

/** Test seam. */
export function resetLiveConversations(): void {
  latest.clear()
}
