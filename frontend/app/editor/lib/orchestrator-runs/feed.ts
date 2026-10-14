'use client'

import { useSyncExternalStore } from 'react'

import { currentConversation } from '@/lib/design-conversation/session'

import type { Command } from './commands'

/**
 * The agent feed: short lines about what the Orchestrator network did for the selected site, shown
 * in the conversation column by the shell. Slices only `post`; the shell renders. Kept in memory for
 * the session (a reload starts empty). A `key` makes a line post once — one line per step change.
 */
/**
 * `user`: what the user did (대지 선택, 검토 시작) — their bubble. `system`: a receipt or connection
 * note. `prompt`: the network asks the user something ("법규를 보시겠어요?") — its actions are the answers.
 */
export type FeedKind = 'user' | 'system' | 'progress' | 'result' | 'error' | 'prompt'

/** Who speaks a line: an agent id of `labels.agentLabel` (`site_context`, `law`, `revision`, …) or `orchestrator`. */
export type FeedAgent = string

/** How a progress line went: a dot before the text. */
export type FeedTone = 'ok' | 'warn' | 'busy'

export interface FeedAction {
  label: string
  /** Opened through `shell.openArtifact(artifact, params)`. */
  artifact?: string
  params?: Record<string, string>
  /** Sent through `commands.sendCommand`; the owning slice carries it out. */
  command?: Command
  /** Neither: the button only dismisses the prompt. */
}

/**
 * Structured content under a line, shaped after what each agent returns: Law's numbers as stat
 * tiles (with the article or ceiling as a hint), Site's eight facts as a checklist, Revision's
 * findings, the ordinance sources as links, codes as chips.
 */
export type FeedCard =
  | { type: 'stats'; items: { label: string; value: string; hint?: string }[] }
  | { type: 'chips'; items: string[] }
  | { type: 'checks'; items: { label: string; state: 'ok' | 'missing' | 'unread'; note?: string; critical?: boolean }[] }
  | { type: 'findings'; items: { title: string; by: string; category: string; action: string; owners: string }[] }
  | { type: 'links'; items: { label: string; href?: string; note?: string }[] }


/** A request in flight between two parties ("Orchestrator Agent ⟶ Law Agent"): drawn as a diagram while the line lives. */
export interface FeedRelay {
  from: FeedAgent
  to: FeedAgent
}

export interface FeedEntry {
  id: number
  kind: FeedKind
  text: string
  /** Epoch ms. */
  at: number
  project_id?: string | null
  conversation_id?: string
  run_id?: string
  /** The speaker; absent on a `user` line. */
  agent?: FeedAgent
  tone?: FeedTone
  relay?: FeedRelay
  card?: FeedCard
  actions?: FeedAction[]
}

export interface FeedInput {
  kind: FeedKind
  text: string
  at?: number
  project_id?: string | null
  conversation_id?: string
  run_id?: string
  agent?: FeedAgent
  tone?: FeedTone
  relay?: FeedRelay
  card?: FeedCard
  actions?: FeedAction[]
  /** Posting the same key again is a no-op. */
  key?: string
}

export interface FeedStore {
  post(input: FeedInput): FeedEntry | null
  /** Removes one line (a prompt the user answered); its key stays taken. */
  dismiss(id: number): void
  clear(): void
  subscribe(listener: () => void): () => void
  get(): readonly FeedEntry[]
}

const EMPTY: readonly FeedEntry[] = []

export function createFeedStore(limit = 200): FeedStore {
  let entries: readonly FeedEntry[] = EMPTY
  let nextId = 1
  const keys = new Set<string>()
  const listeners = new Set<() => void>()
  const emit = () => {
    for (const listener of listeners) listener()
  }
  return {
    post(input) {
      if (input.key) {
        if (keys.has(input.key)) return null
        keys.add(input.key)
      }
      const entry: FeedEntry = {
        id: nextId++,
        ...(input.project_id !== undefined ? { project_id: input.project_id } : {}),
        ...(input.conversation_id ? { conversation_id: input.conversation_id } : {}),
        kind: input.kind,
        text: input.text,
        at: input.at ?? Date.now(),
        ...(input.run_id ? { run_id: input.run_id } : {}),
        ...(input.agent ? { agent: input.agent } : {}),
        ...(input.tone ? { tone: input.tone } : {}),
        ...(input.relay ? { relay: input.relay } : {}),
        ...(input.card?.items.length ? { card: input.card } : {}),
        ...(input.actions?.length ? { actions: input.actions } : {}),
      }
      entries = [...entries, entry].slice(-limit)
      emit()
      return entry
    },
    dismiss(id) {
      if (!entries.some((entry) => entry.id === id)) return
      entries = entries.filter((entry) => entry.id !== id)
      emit()
    },
    clear() {
      entries = EMPTY
      keys.clear()
      emit()
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    get: () => entries,
  }
}

/** The one feed of this browser session. */
export const feed = createFeedStore()

export const postFeed = (input: FeedInput) => feed.post({ project_id: currentConversation().projectId, conversation_id: currentConversation().conversationId, ...input })
export const feedForProject = (entries: readonly FeedEntry[], projectId: string | null, conversationId?: string) => entries.filter((entry) => entry.project_id === projectId && (!conversationId || entry.conversation_id === conversationId))
export const projectFeed = (projectId: string | null, conversationId = currentConversation().conversationId) => (input: FeedInput) => postFeed({ ...input, project_id: projectId, conversation_id: conversationId })
export const dismissFeed = (id: number) => feed.dismiss(id)
export const clearFeed = () => feed.clear()

export function useFeed(): readonly FeedEntry[] {
  return useSyncExternalStore(feed.subscribe, feed.get, () => EMPTY)
}
