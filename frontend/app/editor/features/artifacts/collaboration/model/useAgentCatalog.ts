'use client'

import { useEffect, useMemo, useState } from 'react'

import { canonicalAgent } from '@/lib/agents'
import { listAgents } from '@/lib/orchestrator-runs/api'
import type { AgentSummary } from '@/lib/orchestrator-runs/types'

import { fetchSystemStatus } from '../../system/api/status'
import { type CatalogEntry, type LiveState, mergeCatalog, namesOf } from '../lib/catalog'

const POLL_MS = 15_000

/** What the canvas reads from a catalog row; `checked_at`/`evidence_ref` change every probe and are not drawn. */
const drawn = (rows: readonly AgentSummary[]) => JSON.stringify(rows.map(({ agent_id, label, capabilities, connection_status, description, skills }) => [agent_id, label, capabilities, connection_status, description ?? null, skills ?? null]))

/**
 * The network as it is right now: the Orchestrator's agent catalog (so an agent registered tomorrow is drawn
 * tomorrow) merged with the conversation's folders, plus the host's service states for the dot on each card.
 */
export function useAgentCatalog(): { entries: CatalogEntry[]; live: Readonly<Record<string, LiveState>>; names: Readonly<Record<string, string>> } {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [live, setLive] = useState<Record<string, LiveState>>({})
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      const [catalog, status] = await Promise.allSettled([listAgents(controller.signal), fetchSystemStatus(controller.signal, false)])
      if (controller.signal.aborted) return
      // Same answer, same identity: a poll that changes nothing the canvas shows (probe timestamps aside) must not re-lay it out.
      if (catalog.status === 'fulfilled') setAgents((current) => (drawn(current) === drawn(catalog.value) ? current : catalog.value))
      if (status.status === 'fulfilled') {
        const next: Record<string, LiveState> = { orchestrator: status.value.orchestrator.state === 'up' ? 'up' : status.value.orchestrator.state === 'down' ? 'down' : 'unknown' }
        for (const row of status.value.services) if (row.kind === 'agent') next[canonicalAgent(row.id)] = row.state
        setLive((current) => (JSON.stringify(current) === JSON.stringify(next) ? current : next))
      }
      timer = setTimeout(load, POLL_MS)
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [])
  const entries = useMemo(() => mergeCatalog(agents), [agents])
  const names = useMemo(() => namesOf(entries), [entries])
  return { entries, live, names }
}
