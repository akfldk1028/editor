import type { ProjectBinding } from './projects'
import type { RunSummary } from './runs'
import { object, parseSpecialistRequest, type SpecialistItem, type SpecialistRequest } from './specialist-review'

export interface OwnerReviewNeed {
  agent: string | null; tool: string; state: string; task_id: string; needs: string[]; needs_truncated: boolean
}
export interface FollowupMaterial {
  run_id: string; request_id: string; owner_project_id: string; branch_id: string
  request: SpecialistRequest; source_versions: Record<string, number>; reviews: OwnerReviewNeed[]
}
export interface FollowupAnswers {
  domain: string; proposal: string; sourceId: string; brief: string; operationalType: string; functionalType: string
}

export function parseFollowupMaterial(value: unknown, project: ProjectBinding, run: RunSummary): FollowupMaterial {
  if (!object(value) || value.run_id !== run.run_id || value.request_id !== run.request_id ||
      value.owner_project_id !== project.owner_project_id || value.branch_id !== project.branch_id ||
      !run.request_id.startsWith(`editor:${project.project_id}:`) || !object(value.source_versions) ||
      !Object.values(value.source_versions).every(n => Number.isSafeInteger(n) && Number(n) >= 0) ||
      !Array.isArray(value.reviews) || value.reviews.some(row => !object(row) ||
        !['tool', 'state', 'task_id'].every(key => typeof row[key] === 'string') ||
        !(row.agent === null || typeof row.agent === 'string') || typeof row.needs_truncated !== 'boolean' ||
        !Array.isArray(row.needs) || row.needs.length > 300 || row.needs.some(item => typeof item !== 'string' || item.length > 2000))) {
    throw new Error('후속 검토 원본이 현재 프로젝트·실행과 일치하지 않습니다.')
  }
  const request = parseSpecialistRequest(value.request, project)
  const versions = value.source_versions
  if (request.specialist_reviews.some(item => Object.entries(item.source_versions).some(([key, revision]) => versions[key] !== revision))) {
    throw new Error('원본 검토 요청의 자료 버전과 접수 기록이 다릅니다.')
  }
  return value as unknown as FollowupMaterial
}

export async function loadFollowupMaterial(project: ProjectBinding, run: RunSummary, signal: AbortSignal) {
  const response = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/platform/runs/${encodeURIComponent(run.run_id)}/request?project_id=${encodeURIComponent(project.project_id)}`, { signal, cache: 'no-store' })
  if (!response.ok) throw new Error(`후속 검토 원본을 가져오지 못했습니다 (${response.status}). 원본 접수 기록이 있는 전문 검토 실행을 선택해 주세요.`)
  return parseFollowupMaterial(await response.json(), project, run)
}

export function prepareFollowup(item: SpecialistItem, answers: FollowupAnswers, runId: string): SpecialistRequest {
  const next = structuredClone(item)
  if (!object(next.args.request)) throw new Error('이 도구의 대화 입력 양식은 아직 연결되지 않았습니다.')
  const request = next.args.request
  if (next.agent === 'domain_expert' && next.tool === 'domain_review') {
    if (answers.domain.trim()) request.declared_domain = answers.domain.trim()
    const proposals = answers.proposal.split('\n').map(line => line.trim()).filter(Boolean)
    const sources = Array.isArray(request.sources) ? request.sources : []
    if (answers.sourceId && !sources.some(source => object(source) && source.id === answers.sourceId)) throw new Error('선택한 자료가 원본 요청에 없습니다.')
    const requirements = Array.isArray(request.requirements) ? request.requirements : []
    request.requirements = [...requirements, ...proposals.map((statement, index) => ({
      id: `dialogue-${runId}-${crypto.randomUUID()}-${index}`, statement,
      ...(answers.sourceId ? { source_id: answers.sourceId } : {}),
      provenance: { kind: 'user_proposal', previous_run_id: runId, professionally_verified: false },
    }))]
  } else if (next.agent === 'interior' && next.tool === 'interior_review') {
    if (!answers.brief.trim()) throw new Error('인테리어 방향 또는 질문을 입력해 주세요.')
    request.intent = { ...(object(request.intent) ? request.intent : {}), brief: answers.brief.trim() }
  } else if (next.agent === 'systems' && next.tool === 'systems_requirements') {
    if (answers.functionalType.trim() && !answers.operationalType.trim()) throw new Error('공간 기능을 지정하려면 운영 용도를 함께 선택해 주세요.')
    next.args.request = { schema_version: 'systems.use.catalog.request.v1',
      ...(answers.operationalType.trim() ? { operational_type: answers.operationalType.trim() } : {}),
      ...(answers.functionalType.trim() ? { functional_type: answers.functionalType.trim() } : {}),
    }
  } else {
    throw new Error('이 도구는 소유자가 작성한 수치·형상 요청이 필요합니다. 대화에서 임의로 수치 모델을 만들지 않습니다.')
  }
  return { goal: 'specialist_review', specialist_reviews: [next] }
}
