'use client'

import { useEffect, useSyncExternalStore } from 'react'
import { listProjects } from '@/lib/orchestrator-runs/api'
import type { ProjectBinding } from '@/lib/orchestrator-runs/types'

/**
 * The project bindings, held once for every panel: the conversation list, the map and the law panel read the same
 * list, so a conversation's new workspace is known to all of them the moment it is made (each used to read its own
 * copy once, and a run started from the map went to the project the page opened with).
 */
export interface ProjectsState {
  items: ProjectBinding[]
  loading: boolean
  error: string | null
}

const initial: ProjectsState = { items: [], loading: true, error: null }
let state = initial
let inflight: Promise<ProjectBinding[]> | null = null
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((listener) => { listener() })
const set = (next: Partial<ProjectsState>) => { state = { ...state, ...next }; emit() }

/** Reads the list again (one request at a time); the answer reaches every panel. */
export function refreshProjects(): Promise<ProjectBinding[]> {
  if (inflight) return inflight
  inflight = listProjects().then((items) => {
    set({ items, loading: false, error: null })
    return items
  }).catch((error: unknown) => {
    set({ loading: false, error: error instanceof Error ? error.message : '프로젝트 목록을 불러오지 못했어요.' })
    throw error
  }).finally(() => { inflight = null })
  return inflight
}

/** A binding the backend just made (a new conversation's workspace), known at once without reading the list again. */
export function addProject(binding: ProjectBinding) {
  if (state.items.some((item) => item.project_id === binding.project_id)) return
  set({ items: [...state.items, binding] })
}

export const currentProjects = () => state
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }

/** The shared list; the first panel to ask loads it. */
export function useProjects(): ProjectsState {
  const value = useSyncExternalStore(subscribe, currentProjects, () => initial)
  useEffect(() => {
    if (state.loading && !inflight) refreshProjects().catch(() => undefined)
  }, [])
  return value
}

/** Tests start from an empty list. */
export function resetProjects() {
  state = initial
  inflight = null
  emit()
}
