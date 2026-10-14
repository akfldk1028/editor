import { listHops } from '@/lib/orchestrator-runs/api'
import type { Hop } from '@/lib/orchestrator-runs/types'

import { hopText, type LedgerScope, scopeQuery } from './hops'

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

/** A ledger message id (`hop:7:request` / `hop:7:response`) as its call and side; null for any other message. */
export function hopOf(messageId: string): { id: number; side: 'request' | 'response' } | null {
  const match = /^hop:(\d+):(request|response)$/.exec(messageId)
  return match ? { id: Number(match[1]), side: match[2] as 'request' | 'response' } : null
}

/** The whole text of one side of a recorded call (a list and a stream cut long texts); null when it is not a ledger call. */
export async function fullHopText(messageId: string, signal?: AbortSignal): Promise<string | null> {
  const which = hopOf(messageId)
  if (!which) return null
  const response = await fetch(`${base()}/api/v1/platform/ledger/hops/${which.id}`, { signal })
  if (!response.ok) throw new Error(`기록을 읽지 못했어요 (${response.status})`)
  const hop = await response.json() as Hop
  return hopText(which.side === 'request' ? hop.input_messages : hop.output_messages)
}
