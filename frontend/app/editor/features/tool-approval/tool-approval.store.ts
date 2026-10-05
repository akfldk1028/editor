import { create } from 'zustand'
import type { ToolApproval } from './tool-approval.types'

interface ToolApprovalState {
  queue: ToolApproval[]
  alwaysAllowCache: Set<string>

  enqueue: (approval: ToolApproval) => 'queued' | 'auto-approved'
  approve: (id: string) => ToolApproval | undefined
  approveAlways: (id: string) => ToolApproval | undefined
  reject: (id: string) => ToolApproval | undefined
  peek: () => ToolApproval | undefined
  clearQueue: () => void
  clearCache: () => void
}

// Persist always-allow cache in sessionStorage (guarded for SSR / test envs)
function loadCache(): Set<string> {
  try {
    const raw = typeof sessionStorage !== 'undefined'
      ? sessionStorage.getItem('tool-approval-cache')
      : null
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set()
  } catch {
    return new Set()
  }
}

function saveCache(cache: Set<string>) {
  try {
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem('tool-approval-cache', JSON.stringify([...cache]))
    }
  } catch { /* ignore */ }
}

export const useToolApprovalStore = create<ToolApprovalState>((set, get) => ({
  queue: [],
  alwaysAllowCache: loadCache(),

  enqueue: (approval) => {
    const { alwaysAllowCache } = get()
    if (alwaysAllowCache.has(approval.toolName)) {
      // Auto-approve — don't add to queue
      return 'auto-approved'
    }
    set((state) => ({
      queue: [...state.queue, approval],
    }))
    return 'queued'
  },

  approve: (id) => {
    let found: ToolApproval | undefined
    set((state) => {
      found = state.queue.find((a) => a.id === id)
      return {
        queue: state.queue.filter((a) => a.id !== id),
      }
    })
    return found ? { ...found, status: 'approved' as const } : undefined
  },

  approveAlways: (id) => {
    let found: ToolApproval | undefined
    set((state) => {
      found = state.queue.find((a) => a.id === id)
      if (!found) return state
      const newCache = new Set(state.alwaysAllowCache)
      newCache.add(found.toolName)
      saveCache(newCache)
      return {
        queue: state.queue.filter((a) => a.id !== id),
        alwaysAllowCache: newCache,
      }
    })
    return found ? { ...found, status: 'approved' as const } : undefined
  },

  reject: (id) => {
    let found: ToolApproval | undefined
    set((state) => {
      found = state.queue.find((a) => a.id === id)
      return {
        queue: state.queue.filter((a) => a.id !== id),
      }
    })
    return found ? { ...found, status: 'rejected' as const } : undefined
  },

  peek: () => {
    const { queue } = get()
    return queue.length > 0 ? queue[0] : undefined
  },

  clearQueue: () => set({ queue: [] }),

  clearCache: () => {
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.removeItem('tool-approval-cache')
    }
    set({ alwaysAllowCache: new Set() })
  },
}))
