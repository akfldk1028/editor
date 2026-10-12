'use client'

import { useEffect, useMemo, useState } from 'react'

import type { Hop } from '@/lib/orchestrator-runs/types'

import { listHops, openHopStream } from '../api/ledger'
import { fromHops, type LedgerScope } from '../lib/hops'
import type { CollaborationMessage } from '../lib/transcript'

export type LedgerLoad = { kind: 'loading' } | { kind: 'ready' } | { kind: 'error'; text: string }

/** Rows by id, so a row recorded twice (its start, then its end) is one row. */
function merge(current: readonly Hop[], incoming: readonly Hop[]): Hop[] {
  if (!incoming.length) return current as Hop[]
  const byId = new Map(current.map((hop) => [hop.id, hop]))
  let changed = false
  for (const hop of incoming) {
    const known = byId.get(hop.id)
    if (!known || JSON.stringify(known) !== JSON.stringify(hop)) { byId.set(hop.id, hop); changed = true }
  }
  return changed ? [...byId.values()].sort((a, b) => a.id - b.id) : (current as Hop[])
}

/**
 * The ledger for one scope — this conversation (and the runs it started) or one run — read once, then tailed
 * live over SSE. The messages are derived once per change, so the canvas keeps its layout while nothing happens.
 */
export function useLedger(scope: LedgerScope | null): { hops: Hop[]; messages: CollaborationMessage[]; load: LedgerLoad; reload: () => void } {
  const [hops, setHops] = useState<Hop[]>([])
  const [load, setLoad] = useState<LedgerLoad>({ kind: 'loading' })
  const [reloads, setReloads] = useState(0)
  const key = scope ? JSON.stringify(scope) : null

  useEffect(() => {
    setHops([])
    if (!key) { setLoad({ kind: 'ready' }); return }
    const parsed = JSON.parse(key) as LedgerScope
    const controller = new AbortController()
    let close: (() => void) | null = null
    setLoad({ kind: 'loading' })
    listHops(parsed, 0, controller.signal)
      .then((first) => {
        if (controller.signal.aborted) return
        setHops((current) => merge(current, first.hops))
        setLoad({ kind: 'ready' })
        close = openHopStream(parsed, first.latest_id, (hop) => setHops((current) => merge(current, [hop])))
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoad({ kind: 'error', text: error instanceof Error ? error.message : '장부를 읽지 못했어요.' })
      })
    return () => { controller.abort(); close?.() }
  }, [key, reloads])

  const messages = useMemo(() => fromHops(hops), [hops])
  return { hops, messages, load, reload: () => setReloads((count) => count + 1) }
}
