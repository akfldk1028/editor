import type { AgentSpec } from '../../spec'

/** Program Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'program',
  name: 'Program Agent',
  tools: {
    program_from_brief: '프로그램 번역', program_get: '프로그램 읽기', program_validate: '면적 검증', program_compare: '개정 비교',
    program_build: '프로그램 작성', program_assess: '운영 기준 점검', program_apply_review: '전문 검토 반영',
    program_review_read: '법규 검토 읽기', program_source_fetch: '근거 원문', program_law_source: '법령 원문',
    program_research_context: '운영 조사 맥락', program_research_source: '새 근거 읽기', program_research_search: '자료 검색',
    program_use_research_routes: '용도별 근거 찾기', program_statutory_uses: '법정 용도 분류', program_facility_criteria: '시설 면적 기준',
    program_legal_research: '법령 근거 조사', program_request_law_review: '법규 검토 요청', program_facility_review: '시설 검토 요청',
  },
}
