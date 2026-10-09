/**
 * The editor's platform door for Orchestrator runs (the platform proxy; every path is listed in
 * `lib/api-surface.test.ts`), one place for every slice. `features/agent-dialogue/{runs,projects,
 * communications}.ts` re-export from here for their older callers.
 */
import type { AskClause } from './commands'
import type {
  AskAnswer,
  Capabilities,
  Communications,
  Goal,
  OrchestratorConnection,
  ProjectBinding,
  RunContext,
  RunRequest,
  RunResults,
  RunSummary,
  RunWithResults, EnsureAnswer, HostStatus } from './types'

/** A refused platform call: `status` and the backend `detail` let a caller tell 503 (owner down) from 409/422. */
export class RunRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: string | null,
  ) {
    super(message)
  }
}

async function request(path: string, options?: RequestInit): Promise<unknown> {
  const response = await fetch((process.env.NEXT_PUBLIC_BASE_PATH || '') + '/api/v1/platform' + path, options)
  if (!response.ok) {
    const detail = await response
      .json()
      .then((v: unknown) => (typeof (v as { detail?: unknown })?.detail === 'string' ? (v as { detail: string }).detail : null))
      .catch(() => null)
    throw new RunRequestError(
      options?.method === 'POST' && response.status >= 500
        ? '실행 접수 여부를 확인하지 못했습니다. 같은 요청으로 다시 확인하거나 실행 목록을 조회하세요.'
        : `실행 연결 실패 (${response.status})`,
      response.status,
      detail,
    )
  }
  return response.json()
}

/** Longest request/response text a run row may carry (the backend's contract bound); longer is a contract error. */
const TEXT_CAP = 262_144

export function parseCommunications(value: Record<string, unknown>): Communications {
  const keys = ['communications', 'communications_available', 'communications_truncated']
  if (keys.every((key) => !(key in value))) return { communications: [], communications_available: false, communications_truncated: false }
  const rows = value.communications
  if (
    typeof value.communications_available !== 'boolean' ||
    typeof value.communications_truncated !== 'boolean' ||
    !Array.isArray(rows) ||
    rows.length > 100 ||
    rows.some(
      (row) =>
        !row ||
        typeof row !== 'object' ||
        !['id', 'task_id', 'tool', 'state'].every((key) => typeof row[key] === 'string') ||
        !(row.agent === null || typeof row.agent === 'string') ||
        // The door capped texts at 8,000 until 2026-10-09; it now sends whole answers (~30 KB). This bound only guards memory.
        !['request_text', 'response_text'].every((key) => row[key] === null || (typeof row[key] === 'string' && Array.from(row[key]).length <= TEXT_CAP)) ||
        !['a2a', 'unknown'].includes(row.transport) ||
        typeof row.truncated !== 'boolean',
    ) ||
    new Set(rows.map((row) => row.id)).size !== rows.length ||
    (!value.communications_available && (rows.length > 0 || value.communications_truncated))
  )
    throw new Error('대화 기록 응답 형식이 올바르지 않습니다.')
  return { communications: rows, communications_available: value.communications_available, communications_truncated: value.communications_truncated }
}

export function parseRun(value: unknown): RunSummary {
  const item = value as RunSummary | null
  if (
    !item ||
    !['run_id', 'request_id', 'owner_project_id', 'branch_id', 'goal', 'status'].every((key) => typeof item[key as keyof RunSummary] === 'string') ||
    !Array.isArray(item.receipt_task_ids) ||
    !item.receipt_task_ids.every((id) => typeof id === 'string') ||
    typeof item.pending_input !== 'boolean'
  ) {
    throw new Error('실행 응답 형식이 올바르지 않습니다.')
  }
  const { trace_id, ...rest } = item
  return {
    ...rest,
    ...(typeof trace_id === 'string' && /^[0-9a-f]{32}$/.test(trace_id) ? { trace_id } : {}),
    ...parseCommunications(value as Record<string, unknown>),
  }
}

export function parseBinding(value: unknown): ProjectBinding {
  const item = value as ProjectBinding | null
  if (
    !item ||
    !['project_id', 'owner_project_id', 'branch_id', 'scene_id'].every((key) => typeof item[key as keyof ProjectBinding] === 'string') ||
    !Number.isInteger(item.scene_revision) ||
    item.scene_revision < 0 ||
    (item.scene_project_id !== null && typeof item.scene_project_id !== 'string')
  ) {
    throw new Error('프로젝트 응답 형식이 올바르지 않습니다.')
  }
  return item
}

/** The parsed results contract is read loosely: the backend guarantees the keys, the UI tolerates nulls. */
export function parseResults(value: unknown): RunResults {
  const item = value as RunResults | null
  if (!item || typeof item !== 'object' || typeof item.status !== 'string' || !Array.isArray(item.steps) || !Array.isArray(item.missing_evidence_all)) {
    throw new Error('검토 결과 응답 형식이 올바르지 않습니다.')
  }
  return item
}

export async function listProjects(signal?: AbortSignal): Promise<ProjectBinding[]> {
  const data = await request('/projects', { signal })
  if (!Array.isArray(data)) throw new Error('프로젝트 목록 형식이 올바르지 않습니다.')
  return data.map(parseBinding)
}

export async function listRuns(projectId: string, signal?: AbortSignal): Promise<RunSummary[]> {
  const values = await request(`/projects/${encodeURIComponent(projectId)}/runs`, { signal })
  if (!Array.isArray(values)) throw new Error('실행 목록 형식이 올바르지 않습니다.')
  return values.map(parseRun)
}

export async function getRun(projectId: string, runId: string, signal?: AbortSignal): Promise<RunSummary> {
  return parseRun(await request(`/runs/${encodeURIComponent(runId)}?project_id=${encodeURIComponent(projectId)}`, { signal }))
}

export async function getResults(projectId: string, runId: string, signal?: AbortSignal): Promise<RunResults> {
  return parseResults(await request(`/runs/${encodeURIComponent(runId)}/results?project_id=${encodeURIComponent(projectId)}`, { signal }))
}

/** The newest run of `goal` for `pnu` (or any parcel when omitted); null when the project has none. */
export async function latestRun(projectId: string, goal: string, pnu?: string, signal?: AbortSignal): Promise<RunWithResults | null> {
  const query = new URLSearchParams({ goal, ...(pnu ? { pnu } : {}) })
  try {
    const value = await request(`/projects/${encodeURIComponent(projectId)}/runs/latest?${query}`, { signal })
    const run = parseRun(value)
    return { ...run, results: parseResults((value as { results?: unknown }).results) }
  } catch (error) {
    if (error instanceof RunRequestError && error.status === 404) return null
    throw error
  }
}

export async function getRunContext(projectId: string, signal?: AbortSignal): Promise<RunContext> {
  const value = (await request(`/projects/${encodeURIComponent(projectId)}/context`, { signal })) as RunContext | null
  if (
    !value ||
    !Number.isInteger(value.scene_revision) ||
    value.scene_revision < 0 ||
    !value.source_versions ||
    typeof value.source_versions !== 'object' ||
    Array.isArray(value.source_versions) ||
    !Object.values(value.source_versions).every((v) => Number.isInteger(v) && Number(v) >= 0)
  ) {
    throw new Error('원본 버전 응답이 올바르지 않습니다.')
  }
  return value
}

export async function submitRun(projectId: string, context: RunContext, key: string, body: RunRequest, signal?: AbortSignal): Promise<RunSummary> {
  return parseRun(
    await request(`/projects/${encodeURIComponent(projectId)}/runs`, {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
      body: JSON.stringify({ ...context, request: body }),
    }),
  )
}

export function submitHealth(projectId: string, context: RunContext, key: string, signal?: AbortSignal): Promise<RunSummary> {
  return submitRun(projectId, context, key, { goal: 'health' }, signal)
}

/** Is the Orchestrator reachable, and how many of the registered agents are up (`GET /platform/status`). */
/** The goal catalog (`GET /platform/capabilities`): what the conversation may offer and what the door takes. */
export async function getCapabilities(signal?: AbortSignal): Promise<Capabilities> {
  const value = (await request('/capabilities', { signal })) as Partial<Capabilities>
  const goals = Array.isArray(value.goals) ? value.goals.filter((goal): goal is Goal => typeof goal?.id === 'string' && typeof goal?.label === 'string') : []
  return {
    goals: goals.map((goal) => ({ ...goal, owners: goal.owners ?? [], inputs: goal.inputs ?? [], optional: goal.optional ?? [], available: goal.available === true, offer: goal.offer === true })),
    conversation: { ask: value.conversation?.ask === true, law_analysis: value.conversation?.law_analysis === true },
    source: typeof value.source === 'string' ? value.source : '',
  }
}

/** A typed question for the Law Agent (`POST /platform/ask`); the backend picks the tool and shapes the answer. */
/** The host's last tick, cached 5 s server-side: the conversation reads it to know whom to wake. */
export async function getHostStatus(signal?: AbortSignal): Promise<HostStatus> {
  return (await request('/host/status', { signal })) as HostStatus
}

/** Brings agents up (parallel, dependency-ordered by the host) and waits for their health; `lease_s` = how long they stay "in use". */
export async function ensureAgents(agents: string[], lease_s: number, signal?: AbortSignal, timeout_s = 90): Promise<EnsureAnswer> {
  return (await request('/host/ensure', { method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agents, lease_s, timeout_s }) })) as EnsureAnswer
}

export async function askLaw(body: { text: string; pnu?: string; address?: string; assessment_date?: string; role?: string; clause?: AskClause }, signal?: AbortSignal): Promise<AskAnswer> {
  return (await request('/ask', { method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })) as AskAnswer
}

export async function getOrchestratorConnection(refresh = false, signal?: AbortSignal): Promise<OrchestratorConnection> {
  const value = (await request('/status' + (refresh ? '?refresh=1' : ''), { signal, cache: 'no-store' })) as {
    orchestrator?: { state?: unknown }
    services?: { kind?: unknown; state?: unknown }[]
  } | null
  const state = value?.orchestrator?.state
  const agents = Array.isArray(value?.services) ? value.services.filter((row) => row?.kind === 'agent') : []
  return {
    state: state === 'up' || state === 'invalid' ? state : 'down',
    agentsUp: agents.filter((row) => row.state === 'up').length,
    agentsTotal: agents.length,
  }
}
