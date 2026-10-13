import type { AgentSpec } from '../../spec'

/** Law Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'law',
  name: 'Law Agent',
  tools: { law_parcel_limits: '법규 한계', law_land_analyze: '법규 분석', law_search: '법령 검색', law_ordinance: '조례 조문', law_article: '조문', law_review_district_plan: '지구단위계획 검토', law_review_program: '프로그램 법규 검토', law_review_design_state: '설계 법규 검토', law_parking_design_rules: '주차 설계 기준', law_ground_datum: '지반고 기준', law_basement_storey: '지하층 판정',
    law_facility_review: '시설 기준 검토', law_facility_criteria: '시설 면적 기준', law_fire_requirements: '소방 설비 기준',
    law_statutory_uses: '법정 용도 분류', law_use_research_routes: '용도별 법령 찾기', law_ordinance_candidates: '관할 조례 찾기',
    law_annex: '별표', law_search_worker: '법령 검색(의미)', law_search_domain: '분야별 법령 검색', law_domains: '법령 분야 목록' },
}
