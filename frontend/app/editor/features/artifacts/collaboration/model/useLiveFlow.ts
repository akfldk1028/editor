'use client'

import { useMemo } from 'react'

import { useLiveConversation } from '@/lib/design-conversation/live'
import { useConversationSelection } from '@/lib/design-conversation/session'
import { feedForProject, useFeed } from '@/lib/orchestrator-runs/feed'

import { liveMessages, waitingOn } from '../lib/live'
import type { CollaborationMessage } from '../lib/transcript'

/**
 * The conversation as it happens: the feed the panel posts while it asks and runs (relays, answers), and the saved
 * conversation the panel's controller polls (owners' replies) — both already in memory, no second poller.
 */
export function useLiveFlow(projectId: string | null): { messages: CollaborationMessage[]; waitingOn: string | null; conversationId: string } {
  const { conversationId } = useConversationSelection()
  const entries = useFeed()
  const snapshot = useLiveConversation(projectId, conversationId)
  const messages = useMemo(() => liveMessages(feedForProject(entries, projectId, conversationId), snapshot?.messages ?? []), [entries, snapshot, projectId, conversationId])
  return { messages, waitingOn: waitingOn(messages), conversationId }
}
