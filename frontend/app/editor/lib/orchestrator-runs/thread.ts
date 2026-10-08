/**
 * The feed as a multi-agent conversation: the user's lines are their bubbles, receipts stay small
 * system lines, and consecutive lines of one speaker (the same agent, the same run) fold into one
 * turn of that agent — 대지, 법규, 검토 조정 each speak for themselves, the Orchestrator moderates
 * (receipt, verdict, question). A prompt is a turn of its own so its answers sit under the question.
 * Pure; the shell renders.
 */
import type { FeedEntry } from './feed'

export type Turn =
  /** 대지 선택 · 검토 시작: the user's bubble. */
  | { kind: 'user'; entry: FeedEntry }
  /** 연결됨 · 접수: a small centred line. */
  | { kind: 'system'; entry: FeedEntry }
  /** One speaker's consecutive lines in one run. */
  | { kind: 'agent'; id: number; at: number; agent: string; run_id?: string; steps: FeedEntry[]; error: boolean }
  /** The network's question with its answers. */
  | { kind: 'prompt'; entry: FeedEntry }

const ORCHESTRATOR = 'orchestrator'

export function threadOf(entries: readonly FeedEntry[]): Turn[] {
  const turns: Turn[] = []
  for (const entry of entries) {
    if (entry.kind === 'user' || entry.kind === 'system' || entry.kind === 'prompt') {
      turns.push({ kind: entry.kind, entry })
      continue
    }
    const agent = entry.agent ?? ORCHESTRATOR
    const last = turns[turns.length - 1]
    if (last?.kind === 'agent' && last.agent === agent && last.run_id === entry.run_id) {
      last.steps.push(entry)
      last.error ||= entry.kind === 'error'
      continue
    }
    turns.push({ kind: 'agent', id: entry.id, at: entry.at, agent, ...(entry.run_id ? { run_id: entry.run_id } : {}), steps: [entry], error: entry.kind === 'error' })
  }
  return turns
}

/** The agent turn's lead line: its result line when it has one, else the latest step. */
export function leadOf(turn: Extract<Turn, { kind: 'agent' }>): FeedEntry {
  return turn.steps.find((step) => step.kind === 'result' || step.kind === 'error') ?? turn.steps[turn.steps.length - 1]!
}
