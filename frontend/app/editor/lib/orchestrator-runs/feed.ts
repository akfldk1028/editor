'use client'

import { useSyncExternalStore } from 'react'

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
  /** Opened through `shell.openArtifact(artifact, params)`; omitted: the button only dismisses the prompt. */
  artifact?: string
  params?: Record<string, string>
}

/** Structured content under a line: Law's numbers as stat tiles, or missing evidence as chips. */
export type FeedCard =
  | { type: 'stats'; items: { label: string; value: string }[] }
  | { type: 'chips'; items: string[] }

export interface FeedEntry {
  id: number
  kind: FeedKind
  text: string
  /** Epoch ms. */
  at: number
  run_id?: string
  /** The speaker; absent on a `user` line. */
  agent?: FeedAgent
  tone?: FeedTone
  card?: FeedCard
  actions?: FeedAction[]
}

export interface FeedInput {
  kind: FeedKind
  text: string
  at?: number
  run_id?: string
  agent?: FeedAgent
  tone?: FeedTone
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
        kind: input.kind,
        text: input.text,
        at: input.at ?? Date.now(),
        ...(input.run_id ? { run_id: input.run_id } : {}),
        ...(input.agent ? { agent: input.agent } : {}),
        ...(input.tone ? { tone: input.tone } : {}),
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

export const postFeed = (input: FeedInput) => feed.post(input)
export const dismissFeed = (id: number) => feed.dismiss(id)
export const clearFeed = () => feed.clear()

export function useFeed(): readonly FeedEntry[] {
  return useSyncExternalStore(feed.subscribe, feed.get, () => EMPTY)
}
