'use client'

import { useSyncExternalStore } from 'react'

/**
 * The agent feed: short lines about what the Orchestrator network did for the selected site, shown
 * in the conversation column by the shell. Slices only `post`; the shell renders. Kept in memory for
 * the session (a reload starts empty). A `key` makes a line post once — one line per step change.
 */
export type FeedKind = 'system' | 'progress' | 'result' | 'error'

export interface FeedAction {
  label: string
  /** Opened through `shell.openArtifact(artifact, params)`. */
  artifact: string
  params?: Record<string, string>
}

export interface FeedEntry {
  id: number
  kind: FeedKind
  text: string
  /** Epoch ms. */
  at: number
  run_id?: string
  actions?: FeedAction[]
}

export interface FeedInput {
  kind: FeedKind
  text: string
  at?: number
  run_id?: string
  actions?: FeedAction[]
  /** Posting the same key again is a no-op. */
  key?: string
}

export interface FeedStore {
  post(input: FeedInput): FeedEntry | null
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
        ...(input.actions?.length ? { actions: input.actions } : {}),
      }
      entries = [...entries, entry].slice(-limit)
      emit()
      return entry
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
export const clearFeed = () => feed.clear()

export function useFeed(): readonly FeedEntry[] {
  return useSyncExternalStore(feed.subscribe, feed.get, () => EMPTY)
}
