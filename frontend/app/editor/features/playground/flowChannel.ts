/**
 * BroadcastChannel bridge between Playground (sender) and Flow window (receiver).
 * Enables real-time synchronization of execution state across browser windows.
 */

import type { AgentTurn } from './executionStore'

export interface FlowSyncPayload {
  type: 'flow-sync'
  teamId: number | null
  teamComponent: unknown | null
  teamProvider: string
  turns: AgentTurn[]
  status: string
  isRunning: boolean
  streamingSource: string | null
  streamingChunks: string
  stopReason?: string | null
}

interface FlowAlive {
  type: 'flow-alive'
}

interface FlowRequest {
  type: 'flow-request'
}

type FlowMessage = FlowSyncPayload | FlowAlive | FlowRequest

const CHANNEL_NAME = `editor-team-flow:${process.env.NEXT_PUBLIC_BASE_PATH || ''}`

let channel: BroadcastChannel | null = null
let channelId: string | null = null

export function getFlowChannelId(): string {
  if (!channelId) {
    const supplied = window.location.pathname.endsWith('/playground/flow')
      ? new URL(window.location.href).searchParams.get('channel') : null
    channelId = supplied && /^[a-zA-Z0-9_-]{1,80}$/.test(supplied) ? supplied : crypto.randomUUID()
  }
  return channelId
}

function getChannel(): BroadcastChannel {
  if (!channel) {
    channel = new BroadcastChannel(`${CHANNEL_NAME}:${getFlowChannelId()}`)
  }
  return channel
}

/** Send execution state from Playground to Flow window */
export function broadcastFlowState(payload: FlowSyncPayload): void {
  try {
    getChannel().postMessage(payload)
  } catch {
    // Channel may be closed
  }
}

/** Flow window requests current state from Playground */
export function requestFlowState(): void {
  try {
    getChannel().postMessage({ type: 'flow-request' } satisfies FlowRequest)
  } catch {
    // Channel may be closed
  }
}

/** Flow window sends periodic alive ping */
export function sendFlowAlive(): void {
  try {
    getChannel().postMessage({ type: 'flow-alive' } satisfies FlowAlive)
  } catch {
    // Channel may be closed
  }
}

/** Listen for execution state updates (used by Flow window) */
export function onFlowState(callback: (payload: FlowSyncPayload) => void): () => void {
  const ch = getChannel()
  const handler = (e: MessageEvent) => {
    if (e.data?.type === 'flow-sync') {
      callback(e.data as FlowSyncPayload)
    }
  }
  ch.addEventListener('message', handler)
  return () => {
    ch.removeEventListener('message', handler)
  }
}

/** Listen for flow window presence (request or alive ping) */
export function onFlowPresence(callback: () => void): () => void {
  const ch = getChannel()
  const handler = (e: MessageEvent) => {
    const t = (e.data as FlowMessage)?.type
    if (t === 'flow-request' || t === 'flow-alive') {
      callback()
    }
  }
  ch.addEventListener('message', handler)
  return () => {
    ch.removeEventListener('message', handler)
  }
}
