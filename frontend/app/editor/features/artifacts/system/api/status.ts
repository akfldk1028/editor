/** `GET /api/v1/platform/status`: every registered service's state (backend/app/modules/platform/status). */

export type ServiceKind = 'editor' | 'orchestrator' | 'agent' | 'infra'
export type ServiceState = 'up' | 'down' | 'unknown'

export interface OrchestratorView {
  connection_status: string
  checked_at: string | null
  evidence_ref: string | null
}

export interface ServiceStatus {
  id: string
  kind: ServiceKind
  label: string
  port: number | null
  lifecycle: string | null
  management: string | null
  notes: string | null
  state: ServiceState
  http_status: number | null
  version: string | null
  started_at: string | null
  latency_ms: number | null
  checked_at: string
  error: string | null
  managed_by: { host: string; pid: number; started_at: string | null; adopted: boolean } | null
  /** The Orchestrator's own record of this agent, when the Orchestrator answered. */
  orchestrator: OrchestratorView | null
}

export interface SystemStatus {
  checked_at: string
  orchestrator: { state: 'up' | 'down' | 'invalid'; error: string | null; agents?: number }
  services: ServiceStatus[]
}

const PATH = '/api/v1/platform/status'
const STATES: readonly string[] = ['up', 'down', 'unknown']

/** `refresh` asks the backend to probe again instead of answering from its 20 s cache. */
export async function fetchSystemStatus(signal?: AbortSignal, refresh = false): Promise<SystemStatus> {
  const base = process.env.NEXT_PUBLIC_BASE_PATH || ''
  const response = await fetch(base + PATH + (refresh ? '?refresh=1' : ''), { signal, cache: 'no-store' })
  if (!response.ok) throw new Error(`상태를 불러오지 못했어요 (${response.status})`)
  const data: unknown = await response.json()
  if (!isSystemStatus(data)) throw new Error('상태 응답 형식이 올바르지 않아요.')
  return data
}

function isSystemStatus(value: unknown): value is SystemStatus {
  if (!value || typeof value !== 'object') return false
  const { checked_at, orchestrator, services } = value as Record<string, unknown>
  if (typeof checked_at !== 'string' || !orchestrator || typeof orchestrator !== 'object' || !Array.isArray(services)) return false
  return services.every((row) => row && typeof row === 'object'
    && typeof (row as ServiceStatus).id === 'string' && typeof (row as ServiceStatus).kind === 'string'
    && STATES.includes((row as ServiceStatus).state))
}
