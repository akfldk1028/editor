import { agentLabel, askedFieldsLabel, isTerminal, statusLabel, toolLabel } from '@/lib/orchestrator-runs/labels'
import type { RunSummary } from '@/lib/orchestrator-runs/types'
import { ORCHESTRATOR, USER } from '@/lib/agents'

import { codeNote } from './describe'
import type { CollaborationMessage } from './transcript'

/** A goal in the user's words: the catalog's label (`/platform/capabilities`), else the id as words. */
export const goalLabel = (goal: string, labels: Readonly<Record<string, string>> = {}): string => labels[goal] ?? goal.replace(/_/g, ' ')

const codeOf = (message: CollaborationMessage): string | null => {
  try {
    const body = JSON.parse(message.text) as { code?: unknown }
    return typeof body.code === 'string' && body.code ? body.code : null
  } catch { return /"code"\s*:\s*"([^"]+)"/.exec(message.text)?.[1] ?? null /* a cut record may still name its code */ }
}

/** Why a run failed or stalled: the failing step's own code, else that step by name, else the last answer's code. */
function reasonFor(messages: readonly CollaborationMessage[], names: Readonly<Record<string, string>>): string | null {
  const responses = [...messages].reverse().filter((message) => message.direction === 'response')
  // The first step that failed is the cause; later steps fail because of it.
  const failed = [...responses].reverse().find((message) => /failed|error/.test(message.state))
  if (failed) {
    const code = codeOf(failed)
    return code ? codeNote(code) : `${names[failed.from] ?? agentLabel(failed.from)}의 ${toolLabel(failed.tool)} 단계에서 멈춤 (이유는 기록에 없음)`
  }
  const code = responses.map(codeOf).find(Boolean)
  return code ? codeNote(code) : null
}

/**
 * Who the conversation is waiting on, from the ledger: the newest call still running past the person's own turn —
 * "Law Agent에게 묻는 중 · 대지 법규 분석" — else the Orchestrator putting the answer together. A tool the agents' folders
 * do not name in words is left out rather than shown as an id.
 */
export function waitingLine(messages: readonly CollaborationMessage[], names: Readonly<Record<string, string>> = {}): string {
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
export function turnSteps(messages: readonly CollaborationMessage[], names: Readonly<Record<string, string>> = {},
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

/** One line on where the run stands: "실패 — Site의 답에 … 받지 않음", "용도를 묻는 중", "진행 중", "완료". */
export function runStatusLine(run: Pick<RunSummary, 'status' | 'pending_fields'>, messages: readonly CollaborationMessage[], names: Readonly<Record<string, string>> = {}): string {
  if (run.status === 'waiting_input') {
    const asked = askedFieldsLabel(run.pending_fields)
    return asked ? `${asked}를 묻는 중 — 아직 에이전트를 부르지 않았어요` : '조건을 묻는 중'
  }
  const label = statusLabel(run.status)
  if (!isTerminal(run.status)) return label
  const reason = run.status === 'failed' || run.status === 'blocked' ? reasonFor(messages, names) : null
  return reason ? `${label} — ${reason}` : label
}

export const runTone = (status: string): 'ok' | 'warn' | 'busy' =>
  !isTerminal(status) ? 'busy' : ['completed', 'succeeded', 'done'].includes(status) ? 'ok' : 'warn'
