'use client'

import { useCallback, useSyncExternalStore } from 'react'

import type { Hop } from '@/lib/orchestrator-runs/types'

import { listHops, openHopStream } from '../api/ledger'
import { fromHops, type LedgerScope } from '../lib/hops'
import type { CollaborationMessage } from '../lib/transcript'

export type LedgerLoad = { kind: 'loading' } | { kind: 'ready' } | { kind: 'error'; text: string }
interface LedgerView { hops: Hop[]; messages: CollaborationMessage[]; load: LedgerLoad }

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

const LOADING: LedgerView = { hops: [], messages: [], load: { kind: 'loading' } }
const IDLE: LedgerView = { hops: [], messages: [], load: { kind: 'ready' } }

/**
 * One tail per scope for the whole page: the chat's waiting line and the flow read the same conversation, and a
 * browser holds only six connections to the editor — a stream each per panel per tab used them all up and new
 * pages never finished loading.
 */
interface Tail { view: LedgerView; users: number; listeners: Set<() => void>; stop: () => void }
const tails = new Map<string, Tail>()

function show(tail: Tail, hops: Hop[], load: LedgerLoad) {
  if (hops === tail.view.hops && load === tail.view.load) return
  tail.view = { hops, messages: hops === tail.view.hops ? tail.view.messages : fromHops(hops), load }
  for (const listener of tail.listeners) listener()
}

function start(key: string, tail: Tail) {
  const scope = JSON.parse(key) as LedgerScope
  const controller = new AbortController()
  let close: (() => void) | null = null
  show(tail, [], { kind: 'loading' })
  listHops(scope, 0, controller.signal)
    .then((first) => {
      if (controller.signal.aborted) return
      show(tail, merge(tail.view.hops, first.hops), { kind: 'ready' })
      close = openHopStream(scope, first.latest_id, (hop) => show(tail, merge(tail.view.hops, [hop]), tail.view.load))
    })
    .catch((error: unknown) => {
      if (!controller.signal.aborted) show(tail, tail.view.hops, { kind: 'error', text: error instanceof Error ? error.message : '장부를 읽지 못했어요.' })
    })
  tail.stop = () => { controller.abort(); close?.() }
}

function join(key: string, listener: () => void): () => void {
  let tail = tails.get(key)
  if (!tail) {
    tail = { view: LOADING, users: 0, listeners: new Set(), stop: () => undefined }
    tails.set(key, tail)
    start(key, tail)
  }
  const joined = tail
  joined.users += 1
  joined.listeners.add(listener)
  return () => {
    joined.listeners.delete(listener)
    joined.users -= 1
    if (joined.users === 0) { joined.stop(); tails.delete(key) }
  }
}

/**
 * The ledger for one scope — this conversation (and the runs it started) or one run — read once, then tailed
 * live over SSE, shared by every reader of that scope on the page. The messages are derived once per change, so
 * the canvas keeps its layout while nothing happens.
 */
export function useLedger(scope: LedgerScope | null): LedgerView & { reload: () => void } {
  const key = scope ? JSON.stringify(scope) : null
  const subscribe = useCallback((listener: () => void) => (key ? join(key, listener) : () => undefined), [key])
  const view = useSyncExternalStore(subscribe, () => (key ? tails.get(key)?.view ?? LOADING : IDLE), () => (key ? LOADING : IDLE))
  const reload = useCallback(() => {
    const tail = key ? tails.get(key) : undefined
    if (tail) { tail.stop(); start(key!, tail) }
  }, [key])
  return { ...view, reload }
}
