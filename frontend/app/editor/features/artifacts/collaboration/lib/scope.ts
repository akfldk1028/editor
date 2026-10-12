import { ORCHESTRATOR, USER } from '@/lib/agents'

import type { CollaborationMessage, Transcript } from './transcript'

/** A live line and a ledger row are the same call when they match this closely in time. */
const SAME_CALL_MS = 120_000

/**
 * True when the 협업 장부 already holds this live line: the person's words recorded verbatim, or the same call
 * (direction, caller, callee) recorded within two minutes. The ledger is the record; the panel's own feed only fills
 * what no one has written there yet (the Orchestrator's reply to the person, a run's progress before its hops arrive).
 */
export function coveredByLedger(live: CollaborationMessage, ledger: readonly CollaborationMessage[]): boolean {
  return ledger.some((row) => row.direction === live.direction && row.from === live.from && row.to === live.to
    && (live.from === USER ? row.text === live.text : Math.abs((row.at ?? 0) - (live.at ?? 0)) <= SAME_CALL_MS))
}

/** The ledger's messages with the live lines it does not hold yet, in time order and numbered. */
export function composeConversation(ledger: readonly CollaborationMessage[], live: readonly CollaborationMessage[]): CollaborationMessage[] {
  const kept = live.filter((message) => !coveredByLedger(message, ledger))
  return [...ledger, ...kept].sort((a, b) => (a.at ?? 0) - (b.at ?? 0)).map((message, index) => ({ ...message, step: index + 1 }))
}

/** A transcript over messages from any source: the Orchestrator first whenever anything was said, then each party as it appears. */
export function transcriptOf(messages: readonly CollaborationMessage[]): Transcript {
  const participants: string[] = []
  const seen = (id: string) => { if (id !== USER && !participants.includes(id)) participants.push(id) }
  if (messages.length) seen(ORCHESTRATOR)
  for (const message of messages) { seen(message.from); seen(message.to) }
  return { participants, messages: [...messages], available: true, truncated: messages.some((message) => message.truncated) }
}
