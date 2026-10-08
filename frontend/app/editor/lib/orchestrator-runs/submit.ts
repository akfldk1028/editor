/** Submitting a run: which project binding, and what a refused submission means in Korean. Pure. */
import { RunRequestError } from './api'
import type { ProjectBinding } from './types'

/** Which project binding a run is submitted under. */
export type ProjectChoice =
  | { kind: 'resolved'; project: ProjectBinding }
  | { kind: 'choose'; projects: ProjectBinding[] }
  | { kind: 'none'; reason: string }

/**
 * The shell's `?project=` when it is a binding id; else the only binding; several → the user
 * picks; none → say so (a binding needs a scene, so it is never created here).
 */
export function resolveProject(bindings: readonly ProjectBinding[], param: string | undefined): ProjectChoice {
  const named = bindings.find((binding) => binding.project_id === param)
  if (named) return { kind: 'resolved', project: named }
  if (bindings.length === 1) return { kind: 'resolved', project: bindings[0]! }
  if (bindings.length > 1) return { kind: 'choose', projects: [...bindings] }
  return { kind: 'none', reason: '프로젝트가 없어요 — 연결된 프로젝트가 하나도 없어서 검토를 보낼 곳이 없어요. 대화 패널에서 프로젝트를 먼저 연결해 주세요.' }
}

/** One key per attempt (the header allows `[A-Za-z0-9_-]{1,128}`); the same key replays the same run. */
export function idempotencyKey(prefix: string, id: string, attempt: number): string {
  return `${prefix}-${id.replace(/[^A-Za-z0-9_-]/g, '-').slice(0, 100)}-${attempt}`
}

export type RunFailure = { kind: 'unavailable' } | { kind: 'rejected'; text: string }

/** Site's code for a bundle whose parcels do not touch: a 409 at the door, or a failed `site_resolve` inside the run. */
export const NOT_CONTIGUOUS = 'parcels_not_contiguous'
export const NOT_CONTIGUOUS_TEXT = '필지가 서로 붙어 있지 않아 합필 검토가 거절됐어요'

/** 503 and a dropped connection are "the Orchestrator is off" (retry); 4xx carries the backend's reason. */
export function describeFailure(error: unknown): RunFailure {
  if (error instanceof RunRequestError) {
    if (error.status === 503 || error.status === 502) return { kind: 'unavailable' }
    const reason = error.detail ?? error.message
    if (error.status === 409 && reason.includes(NOT_CONTIGUOUS)) return { kind: 'rejected', text: `${NOT_CONTIGUOUS_TEXT} (409)` }
    return { kind: 'rejected', text: `${error.status === 409 ? '요청이 충돌했어요' : '요청이 거절됐어요'} (${error.status}) — ${rejectionText(reason)}` }
  }
  if (error instanceof TypeError) return { kind: 'unavailable' }
  return { kind: 'rejected', text: error instanceof Error ? error.message : '검토를 요청하지 못했어요.' }
}

export const failureText = (failure: RunFailure) =>
  failure.kind === 'unavailable' ? '오케스트레이터에 연결할 수 없어요 — 켜진 뒤 다시 시도' : failure.text

const REASONS: Record<string, string> = {
  'Request identity or source version conflict': '같은 키로 다른 내용이 접수됐거나 장면·원본 버전이 바뀌었어요. 다시 시도하면 새 키로 보내요.',
  'Project or run not found': '프로젝트 연결을 찾지 못했어요. 프로젝트를 다시 연결해 주세요.',
  'Cross-origin execution is not allowed': '이 화면에서는 실행을 보낼 수 없어요 (출처 검사).',
  'Invalid owner run contract': '오케스트레이터 응답 형식이 맞지 않아요.',
}
const rejectionText = (reason: string) => REASONS[reason] ?? reason
