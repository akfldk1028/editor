'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchSystemStatus, type SystemStatus } from '../api/status'

const POLL_MS = 10_000

export type SystemPhase =
  | { kind: 'loading' }
  | { kind: 'ready'; status: SystemStatus; stale: boolean }
  | { kind: 'error'; text: string }

/**
 * Polls `/api/v1/platform/status` every 10 s while the page is visible; a hidden tab skips its
 * ticks and asks again the moment it is shown. `refresh()` bypasses the backend's probe cache.
 */
export function useSystemStatus(intervalMs = POLL_MS) {
  const [phase, setPhase] = useState<SystemPhase>({ kind: 'loading' })
  const [fetching, setFetching] = useState(false)
  const active = useRef<AbortController | null>(null)

  const load = useCallback(async (refresh: boolean) => {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setFetching(true)
    try {
      const status = await fetchSystemStatus(controller.signal, refresh)
      if (!controller.signal.aborted) setPhase({ kind: 'ready', status, stale: false })
    } catch (error) {
      if (controller.signal.aborted) return
      // A missed poll keeps the last table and marks it stale; the first failure is the error.
      setPhase((current) => current.kind === 'ready'
        ? { ...current, stale: true }
        : { kind: 'error', text: error instanceof Error ? error.message : '상태를 불러오지 못했어요.' })
    } finally {
      if (!controller.signal.aborted) setFetching(false)
    }
  }, [])

  useEffect(() => {
    let timer: number | undefined
    const tick = () => {
      if (!document.hidden) void load(false)
      timer = window.setTimeout(tick, intervalMs)
    }
    const onVisibility = () => {
      if (!document.hidden) void load(false)
    }
    tick()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
      active.current?.abort()
    }
  }, [load, intervalMs])

  const refresh = useCallback(() => void load(true), [load])
  return { phase, fetching, refresh }
}
