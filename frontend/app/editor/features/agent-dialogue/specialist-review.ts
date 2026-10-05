import type { ProjectBinding } from './projects'
import type { RunContext } from './runs'

const tools: Record<string, readonly string[]> = {
  systems: ['systems_review', 'systems_ifc_review', 'systems_clearance', 'systems_requirements'],
  domain_expert: ['domain_review'],
  interior: ['interior_review'],
}
export interface SpecialistItem {
  agent: string
  tool: string
  args: Record<string, unknown>
  source_versions: Record<string, number>
}
export interface SpecialistRequest {
  goal: 'specialist_review'
  specialist_reviews: SpecialistItem[]
}
export interface ReviewAttempt {
  key: string
  owner_project_id: string
  branch_id: string
  scene_id: string
  body: string
}
export const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value)
const exact = (value: Record<string, unknown>, keys: string[]) =>
  Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key))
const versions = (value: unknown, minimum: number): value is Record<string, number> =>
  object(value) &&
  Object.values(value).every((n) => Number.isSafeInteger(n) && Number(n) >= minimum)
const storageKey = (project: string) =>
  `editor:pending-specialist:v1:${process.env.NEXT_PUBLIC_BASE_PATH || ''}:${project}`

export function parseSpecialistRequest(value: unknown, project: ProjectBinding): SpecialistRequest {
  const invalid = () => new Error('읽기 전용 전문 검토 요청 파일 형식이 올바르지 않습니다.')
  if (
    !object(value) ||
    !exact(value, ['goal', 'specialist_reviews']) ||
    value.goal !== 'specialist_review' ||
    !Array.isArray(value.specialist_reviews) ||
    !value.specialist_reviews.length ||
    value.specialist_reviews.length > 6
  )
    throw invalid()
  const seen = new Set<string>()
  for (const item of value.specialist_reviews) {
    if (
      !object(item) ||
      !exact(item, ['agent', 'tool', 'args', 'source_versions']) ||
      typeof item.agent !== 'string' ||
      typeof item.tool !== 'string' ||
      !Object.hasOwn(tools, item.agent) ||
      !tools[item.agent]?.includes(item.tool) ||
      seen.has(item.tool) ||
      !object(item.args) ||
      !versions(item.source_versions, 1) ||
      !Object.keys(item.source_versions).length
    )
      throw invalid()
    seen.add(item.tool)
    for (const supplied of [item.args, item.args.request]) {
      if (
        object(supplied) &&
        (('project_id' in supplied && supplied.project_id !== project.owner_project_id) ||
          ('branch_id' in supplied && supplied.branch_id !== project.branch_id))
      )
        throw new Error('요청의 담당 프로젝트·브랜치가 선택한 프로젝트와 일치하지 않습니다.')
    }
  }
  return value as unknown as SpecialistRequest
}

export function prepareReview(
  request: SpecialistRequest,
  context: RunContext,
  project: ProjectBinding,
): ReviewAttempt {
  parseSpecialistRequest(request, project)
  if (
    context.scene_revision !== project.scene_revision ||
    request.specialist_reviews.some((item) =>
      Object.entries(item.source_versions).some(
        ([key, revision]) => context.source_versions[key] !== revision,
      ),
    )
  )
    throw new Error(
      '현재 원본 버전이 달라 검토를 접수하지 않았습니다. 담당 에이전트에서 요청을 갱신하세요.',
    )
  return {
    key: crypto.randomUUID(),
    owner_project_id: project.owner_project_id,
    branch_id: project.branch_id,
    scene_id: project.scene_id,
    body: JSON.stringify({ ...context, request }),
  }
}

export function readReview(storage: Storage, project: ProjectBinding): ReviewAttempt | null {
  try {
    const raw = storage.getItem(storageKey(project.project_id))
    if (raw === null) return null
    const value = JSON.parse(raw)
    if (
      !object(value) ||
      !exact(value, ['key', 'owner_project_id', 'branch_id', 'scene_id', 'body']) ||
      typeof value.key !== 'string' ||
      !/^[A-Za-z0-9_-]{1,128}$/.test(value.key) ||
      typeof value.body !== 'string' ||
      value.owner_project_id !== project.owner_project_id ||
      value.branch_id !== project.branch_id ||
      value.scene_id !== project.scene_id
    )
      throw new Error()
    const body = JSON.parse(value.body)
    if (
      !object(body) ||
      !exact(body, ['scene_revision', 'source_versions', 'request']) ||
      !Number.isSafeInteger(body.scene_revision) ||
      Number(body.scene_revision) < 0 ||
      !versions(body.source_versions, 0)
    )
      throw new Error()
    const request = parseSpecialistRequest(body.request, project)
    if (
      request.specialist_reviews.some((item) =>
        Object.entries(item.source_versions).some(
          ([key, revision]) => (body.source_versions as Record<string, number>)[key] !== revision,
        ),
      )
    )
      throw new Error()
    return value as unknown as ReviewAttempt
  } catch {
    throw new Error(
      '저장된 검토 요청을 복원하지 못했습니다. 실행 목록에서 접수 여부를 먼저 확인하세요.',
    )
  }
}
export function saveReview(storage: Storage, projectId: string, attempt: ReviewAttempt) {
  try {
    storage.setItem(storageKey(projectId), JSON.stringify(attempt))
  } catch {
    throw new Error(
      '재확인 정보를 저장하지 못해 검토를 보내지 않았습니다. 브라우저 저장소를 확인하세요.',
    )
  }
}
export function clearReview(storage: Storage, projectId: string) {
  storage.removeItem(storageKey(projectId))
}

export class ReviewRejected extends Error {}
export async function submitReview(
  project: ProjectBinding,
  attempt: ReviewAttempt,
  signal: AbortSignal,
): Promise<string> {
  const response = await fetch(
    `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/platform/projects/${encodeURIComponent(project.project_id)}/runs`,
    {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': attempt.key },
      body: attempt.body,
    },
  )
  if (!response.ok) {
    if (response.status < 500)
      throw new ReviewRejected(
        `검토 요청이 거절되었습니다 (${response.status}). 프로젝트와 원본 버전을 확인하세요.`,
      )
    throw new Error(
      '검토 접수 여부를 확인하지 못했습니다. 같은 요청으로 재확인하거나 실행 목록을 확인하세요.',
    )
  }
  const run = await response.json()
  if (
    !object(run) ||
    typeof run.run_id !== 'string' ||
    !run.run_id ||
    run.goal !== 'specialist_review' ||
    run.owner_project_id !== project.owner_project_id ||
    run.branch_id !== project.branch_id ||
    run.request_id !== `editor:${project.project_id}:${attempt.key}`
  )
    throw new Error(
      '접수 응답의 프로젝트·요청 연결이 일치하지 않습니다. 같은 요청으로 재확인하세요.',
    )
  return run.run_id
}
