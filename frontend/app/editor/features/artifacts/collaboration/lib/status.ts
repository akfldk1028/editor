import { agentLabel, askedFieldsLabel, isTerminal, statusLabel, toolLabel } from '@/lib/orchestrator-runs/labels'
import type { RunSummary } from '@/lib/orchestrator-runs/types'

import { codeNote } from './describe'
import type { CollaborationMessage } from './transcript'

const GOALS: Record<string, string> = { limits: '법규 한계', health: '연결 점검', specialist_review: '전문가 검토', masterplan: '배치', interior_concept: '실내 콘셉트' }
export const goalLabel = (goal: string): string => GOALS[goal] ?? goal

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
