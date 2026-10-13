import { ORCHESTRATOR, USER } from '@/lib/agents'
import type { ConversationMessage } from '@/lib/design-conversation/types'
import type { FeedEntry } from '@/lib/orchestrator-runs/feed'

import type { CollaborationMessage } from './transcript'

/**
 * What the conversation is doing right now, as messages the flow can draw — before any run record exists:
 * the person's lines, the Orchestrator's relays ("Law Agent에게 묻는 중" → a request that is running until that
 * agent's line arrives), each agent's answers in the feed, and the owners' replies in the saved conversation.
 */
interface Timed { message: CollaborationMessage; at: number }

const party = (entry: FeedEntry): string => entry.agent ?? (entry.kind === 'user' ? USER : ORCHESTRATOR)

const cardText = (entry: FeedEntry): string => {
  const card = entry.card
  if (!card) return ''
  if (card.type === 'stats') return card.items.map((item) => `${item.label} ${item.value}`).join(' · ')
  if (card.type === 'chips') return card.items.join(' · ')
  if (card.type === 'checks') return card.items.map((item) => `${item.label}${item.note ? ` ${item.note}` : ''}`).join(' · ')
  if (card.type === 'findings') return card.items.map((item) => item.title).join(' · ')
  if (card.type === 'lots') return `획지 후보: ${(card.question.candidates?.lots ?? []).map((lot) => lot.lot).join(' · ')}`
  return card.items.map((item) => item.label).join(' · ')
}

/** The feed as messages: a relay is a request that runs until the party it went to has spoken after it. */
export function fromFeed(entries: readonly FeedEntry[]): Timed[] {
  const out: Timed[] = []
  const relays: { to: string; index: number }[] = []
  for (const entry of entries) {
    if (entry.kind === 'prompt' || entry.kind === 'system') continue
    if (entry.relay) {
      relays.push({ to: entry.relay.to, index: out.length })
      out.push({ at: entry.at, message: { id: `feed:${entry.id}`, step: 0, direction: 'request', from: entry.relay.from, to: entry.relay.to, tool: '', state: 'running', transport: 'a2a', truncated: false, text: entry.text } })
      continue
    }
    const from = party(entry)
    const text = [entry.text, cardText(entry)].filter(Boolean).join(' — ')
    if (from === USER) {
      out.push({ at: entry.at, message: { id: `feed:${entry.id}`, step: 0, direction: 'request', from: USER, to: ORCHESTRATOR, tool: '', state: 'succeeded', transport: 'a2a', truncated: false, text } })
      continue
    }
    // An agent's line answers the relay that went to it; the Orchestrator's own lines are its words to the person.
    const open = relays.findIndex((relay) => relay.to === from)
    if (open >= 0) { out[relays[open]!.index]!.message.state = entry.kind === 'error' ? 'failed' : 'succeeded'; relays.splice(open, 1) }
    const state = entry.kind === 'error' ? 'failed' : entry.tone === 'warn' ? 'needs_evidence' : entry.tone === 'busy' ? 'running' : 'succeeded'
    out.push({ at: entry.at, message: { id: `feed:${entry.id}`, step: 0, direction: 'response', from, to: from === ORCHESTRATOR ? USER : ORCHESTRATOR, tool: '', state, transport: 'a2a', truncated: false, text } })
  }
  return out
}

/** The saved conversation as messages: the person asks the Orchestrator; an owner (or the Orchestrator) answers the person. */
export function fromConversation(messages: readonly ConversationMessage[]): Timed[] {
  return messages.map((message) => {
    const at = Date.parse(message.at) || 0
    if (message.role === 'user') return { at, message: { id: `conv:${message.id}`, step: 0, direction: 'request' as const, from: USER, to: ORCHESTRATOR, tool: '', state: 'succeeded', transport: 'a2a' as const, truncated: false, text: message.text } }
    const from = message.agent ?? ORCHESTRATOR
    return { at, message: { id: `conv:${message.id}`, step: 0, direction: 'response' as const, from, to: USER, tool: '', state: 'succeeded', transport: 'a2a' as const, truncated: false, text: message.text } }
  })
}

/** Everything live, in time order and numbered; the feed's copy of a user line wins over the saved one when both exist. */
export function liveMessages(entries: readonly FeedEntry[], conversation: readonly ConversationMessage[]): CollaborationMessage[] {
  const feed = fromFeed(entries)
  const feedUserTexts = new Set(feed.filter((item) => item.message.from === USER).map((item) => item.message.text))
  const saved = fromConversation(conversation).filter((item) => !(item.message.from === USER && feedUserTexts.has(item.message.text)))
  return [...feed, ...saved].sort((a, b) => a.at - b.at).map((item, index) => ({ ...item.message, step: index + 1, at: item.at }))
}

/** Who the conversation is waiting on right now, if anyone. */
export const waitingOn = (messages: readonly CollaborationMessage[]): string | null =>
  [...messages].reverse().find((message) => message.state === 'running' && message.direction === 'request')?.to ?? null
