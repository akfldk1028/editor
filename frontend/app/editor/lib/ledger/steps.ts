import { ORCHESTRATOR, USER } from '@/lib/agents'
import { agentLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import type { LedgerMessage } from './types'

/**
 * Who the conversation is waiting on, from the ledger: the newest call still running past the person's own turn —
 * "Law Agent에게 묻는 중 · 대지 법규 분석" — else the Orchestrator putting the answer together. A tool the agents' folders
 * do not name in words is left out rather than shown as an id.
 */
export function waitingLine(messages: readonly LedgerMessage[], names: Readonly<Record<string, string>> = {}): string {
  const running = [...messages].reverse().find((message) => message.state === 'running' && message.direction === 'request' && message.from !== USER)
  if (!running) return `${names[ORCHESTRATOR] ?? agentLabel(ORCHESTRATOR)}가 답을 정리하는 중`
  const tool = running.tool ? toolLabel(running.tool) : null
  return `${names[running.to] ?? agentLabel(running.to)}에게 묻는 중${tool && tool !== running.tool ? ` · ${tool}` : ''}`
}

export interface TurnStep { agent: string; label: string; tools: string[]; calls: number; running: boolean; failed: boolean }

/**
 * What the agents were asked since the person's last message, one line per agent in the order first asked:
 * "Law Agent · 용도 분류, 별표 조회 … 7번". A tool no folder names in words is counted, never shown as its id.
 */
export function turnSteps(messages: readonly LedgerMessage[], names: Readonly<Record<string, string>> = {},
  window: { since?: number; until?: number } = {}): TurnStep[] {
  // Without a window: since the person's last message (the turn still running).
  const since = window.since ?? [...messages].reverse().find((message) => message.direction === 'request' && message.from === USER)?.at ?? 0
  const until = window.until ?? Number.POSITIVE_INFINITY
  const steps = new Map<string, TurnStep>()
  for (const message of messages) {
    const at = message.at ?? 0
    if (message.direction !== 'request' || message.from === USER || message.to === USER || at < since || at > until) continue
    const step = steps.get(message.to) ?? { agent: message.to, label: names[message.to] ?? agentLabel(message.to), tools: [], calls: 0, running: false, failed: false }
    const tool = message.tool ? toolLabel(message.tool) : ''
    if (tool && tool !== message.tool && !step.tools.includes(tool)) step.tools.push(tool)
    step.calls += 1
    step.running ||= message.state === 'running'
    step.failed ||= /failed|error/.test(message.state)
    steps.set(message.to, step)
  }
  return [...steps.values()]
}
