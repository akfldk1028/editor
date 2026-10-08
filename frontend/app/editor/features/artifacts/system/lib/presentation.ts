import type { ServiceKind, ServiceState, ServiceStatus, SystemStatus } from '../api/status'

export interface ServiceGroup {
  kind: ServiceKind
  title: string
  rows: ServiceStatus[]
  up: number
}

/** Sidebar order of the groups; rows keep the registry's order inside each. */
export const GROUPS: readonly { kind: ServiceKind; title: string }[] = [
  { kind: 'editor', title: '에디터' },
  { kind: 'orchestrator', title: '오케스트레이터' },
  { kind: 'agent', title: '에이전트' },
  { kind: 'infra', title: '인프라' },
]

export function groupServices(services: readonly ServiceStatus[]): ServiceGroup[] {
  return GROUPS
    .map(({ kind, title }) => {
      const rows = services.filter((row) => row.kind === kind)
      return { kind, title, rows, up: rows.filter((row) => row.state === 'up').length }
    })
    .filter((group) => group.rows.length > 0)
}

export const stateLabel: Record<ServiceState, string> = { up: '가동', down: '꺼짐', unknown: '확인 불가' }

/** Header subtitle: "17/22 가동 · 14:03:05 확인". */
export function summarize(status: SystemStatus, now = Date.now()): string {
  const probed = status.services.filter((row) => row.state !== 'unknown')
  const up = probed.filter((row) => row.state === 'up').length
  return `${up}/${probed.length} 가동 · ${formatClock(status.checked_at, now)} 확인`
}

export function formatUptime(startedAt: string | null, now = Date.now()): string {
  if (!startedAt) return '—'
  const seconds = Math.floor((now - Date.parse(startedAt)) / 1000)
  if (Number.isNaN(seconds) || seconds < 0) return '—'
  const days = Math.floor(seconds / 86_400)
  const hours = Math.floor((seconds % 86_400) / 3_600)
  const minutes = Math.floor((seconds % 3_600) / 60)
  if (days) return `${days}일 ${hours}시간`
  if (hours) return `${hours}시간 ${minutes}분`
  if (minutes) return `${minutes}분 ${seconds % 60}초`
  return `${seconds}초`
}

/** Local wall-clock time of an ISO stamp; "n초 전" when it is within the last minute. */
export function formatClock(iso: string | null, now = Date.now()): string {
  if (!iso) return '—'
  const time = Date.parse(iso)
  if (Number.isNaN(time)) return '—'
  const ago = Math.floor((now - time) / 1000)
  if (ago >= 0 && ago < 60) return `${ago}초 전`
  return new Date(time).toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** What a viewer can do about a row that is not up; null for a row that is. */
export function downHint(row: Pick<ServiceStatus, 'id' | 'kind' | 'state' | 'management'>): string | null {
  if (row.state === 'up') return null
  if (row.state === 'unknown') return 'HTTP 상태 주소가 없어요 (Bolt 포트) — 연결은 사용하는 에이전트가 확인해요.'
  if (row.kind === 'orchestrator') return '꺼져 있어요 — 검토 실행에는 오케스트레이터가 필요해요. 에이전트 담당 세션에서 켜 주세요.'
  if (row.management === 'editor-session') return `꺼져 있어요 — editor에서 \`bun run host:start ${row.id}\``
  if (row.management === 'external') return '꺼져 있어요 — 외부 서비스예요 (ops/db compose).'
  return '꺼져 있어요 — 에이전트 담당 세션에서 켜 주세요.'
}
