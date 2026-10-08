import type { ProjectBinding } from '../../../agent-dialogue/projects'
import { type RunRequest, RunRequestError } from '../../../agent-dialogue/runs'
import { lotLabel } from './layers/parcelOutline'
import type { SavedSite } from './picks'

/** Which project binding a site run is submitted under. */
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

/** The Orchestrator takes one PNU today (no `parcels` key), so a bundle sends its first parcel. */
export function siteRunRequest(site: SavedSite): RunRequest {
  return { goal: 'limits', pnu: site.parcels[0]!.pnu }
}

export function bundleNotice(site: SavedSite): string | null {
  if (site.parcels.length < 2) return null
  const first = site.parcels[0]!
  return `지금은 첫 필지(${lotLabel(first.address, first.pnu)})만 오케스트레이터에 보내요 — 여러 필지 지원은 준비 중`
}

/** One key per attempt (the header allows `[A-Za-z0-9_-]{1,128}`); the same key replays the same run. */
export function idempotencyKey(site: SavedSite, attempt: number): string {
  return `site-${site.selection_id.replace(/[^A-Za-z0-9_-]/g, '-').slice(0, 100)}-${attempt}`
}

/** The card shows the first 8 hex of the 32-hex W3C trace id; the copy button carries the whole id. */
export const traceLabel = (traceId: string) => traceId.slice(0, 8)

/** The run page's statuses; anything else is terminal (RunPage polls on these three too). */
const OPEN = new Set(['queued', 'running', 'queued_input'])
export const isTerminal = (status: string) => !OPEN.has(status)

export function statusLabel(status: string): string {
  switch (status) {
    case 'queued': return '대기'
    case 'running': return '진행 중'
    case 'queued_input': return '입력 대기'
    case 'completed': case 'succeeded': case 'done': return '완료'
    case 'failed': case 'error': case 'cancelled': case 'canceled': case 'rejected': return '실패'
    default: return status
  }
}

export type RunFailure = { kind: 'unavailable' } | { kind: 'rejected'; text: string }

/** 503 and a dropped connection are "the Orchestrator is off" (retry); 4xx carries the backend's reason. */
export function describeFailure(error: unknown): RunFailure {
  if (error instanceof RunRequestError) {
    if (error.status === 503 || error.status === 502) return { kind: 'unavailable' }
    const reason = error.detail ?? error.message
    return { kind: 'rejected', text: `${error.status === 409 ? '요청이 충돌했어요' : '요청이 거절됐어요'} (${error.status}) — ${rejectionText(reason)}` }
  }
  if (error instanceof TypeError) return { kind: 'unavailable' }
  return { kind: 'rejected', text: error instanceof Error ? error.message : '검토를 요청하지 못했어요.' }
}

const REASONS: Record<string, string> = {
  'Request identity or source version conflict': '같은 키로 다른 내용이 접수됐거나 장면·원본 버전이 바뀌었어요. 다시 시도하면 새 키로 보내요.',
  'Project or run not found': '프로젝트 연결을 찾지 못했어요. 프로젝트를 다시 연결해 주세요.',
  'Cross-origin execution is not allowed': '이 화면에서는 실행을 보낼 수 없어요 (출처 검사).',
  'Invalid owner run contract': '오케스트레이터 응답 형식이 맞지 않아요.',
}
const rejectionText = (reason: string) => REASONS[reason] ?? reason
