'use client'

import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react'
import { ConversationController, type ConversationState } from './controller'

const empty: ConversationState = { snapshot: null, loading: false, error: null, pending: [] }
const noop = () => () => {}
/** `onLocated`: a sent message that was one address came back located by the editor (not stored by the owner). */
export function useConversation(projectId: string | null, conversationId: string, onLocated?: ConversationController['onLocated']) {
  const sessions = useRef(new Map<string, ConversationController>())
  const controller = useMemo(() => {
    if (!projectId) return null
    const key = JSON.stringify([projectId, conversationId])
    const existing = sessions.current.get(key)
    if (existing) return existing
    const created = new ConversationController(projectId, conversationId)
    sessions.current.set(key, created)
    return created
  }, [projectId, conversationId])
  const state = useSyncExternalStore(controller?.subscribe ?? noop, controller?.getSnapshot ?? (() => empty), () => empty)
  useEffect(() => {
    if (controller) controller.onLocated = onLocated ?? null
  }, [controller, onLocated])
  useEffect(() => {
    if (!controller) return
    const refresh = () => { if (document.visibilityState === 'visible') void controller.refresh() }
    controller.start()
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      controller.stop()
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [controller])
  return { ...state, send: controller?.send, confirm: controller?.confirm, retry: controller?.retry, discard: controller?.discard, refresh: controller?.refresh }
}
