'use client'

import { useEffect, useState } from 'react'

import { canonicalAgent } from '@/lib/agents'

import { fetchSystemStatus } from '../../system/api/status'
import type { LiveState } from '../lib/graph'

const POLL_MS = 15_000

/** Which agents answer right now, by canonical id, from `GET /platform/status` (agents and the Orchestrator); empty until known. */
export function useAgentStates(): Readonly<Record<string, LiveState>> {
  const [states, setStates] = useState<Record<string, LiveState>>({})
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      try {
        const status = await fetchSystemStatus(controller.signal, false)
        if (controller.signal.aborted) return
        const next: Record<string, LiveState> = { orchestrator: status.orchestrator.state === 'up' ? 'up' : status.orchestrator.state === 'down' ? 'down' : 'unknown' }
        for (const row of status.services) if (row.kind === 'agent') next[canonicalAgent(row.id)] = row.state
        setStates(next)
      } catch { /* the graph is drawn without live dots */ }
      if (!controller.signal.aborted) timer = setTimeout(load, POLL_MS)
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [])
  return states
}
