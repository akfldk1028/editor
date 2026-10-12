import { listHops } from '@/lib/orchestrator-runs/api'
import type { Hop } from '@/lib/orchestrator-runs/types'

import { type LedgerScope, scopeQuery } from '../lib/hops'

export { listHops }

const base = () => process.env.NEXT_PUBLIC_BASE_PATH || ''

/**
 * Tails the ledger for a scope over SSE (`GET /platform/ledger/hops/stream`, through the Next proxy). Each event
 * is one row; the browser reconnects itself with `Last-Event-ID`. Returns the closer.
 */
export function openHopStream(scope: LedgerScope, sinceId: number, onHop: (hop: Hop) => void, onError?: () => void): () => void {
  if (typeof EventSource === 'undefined') return () => undefined
  const source = new EventSource(`${base()}/api/v1/platform/ledger/hops/stream?${scopeQuery(scope)}&since_id=${sinceId}`)
  source.onmessage = (event) => {
    try {
      const hop = JSON.parse(event.data) as Hop
      if (hop && typeof hop === 'object' && typeof hop.id === 'number') onHop(hop)
    } catch { /* a malformed event is skipped; the next one is whole */ }
  }
  source.onerror = () => { onError?.() }
  return () => source.close()
}
