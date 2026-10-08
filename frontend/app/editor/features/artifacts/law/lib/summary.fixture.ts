import type { LawAnalysis } from '../api/analyze'

/** Shaped after the live `POST /land/analyze` answer for 산곡동 684-1 (2026-10-08), trimmed. */
export const fixture: LawAnalysis = {
  pnu: { pnu: '4115011300106840001', sido: '41', sigungu: '150', eupmyeondong: '113', ri: '00', land_type: '1', main_number: '0684', sub_number: '0001', land_type_name: '대' },
  zone_info: {
    bcr_limit: null, far_limit: null,
    zones: ['제2종일반주거지역', '자연녹지지역'], matched: 2,
    unmatched: ['과밀억제권역', '공공청사', '공공주택지구', '지구단위계획구역', '가축사육제한구역'],
    zone_areas_m2: { 자연녹지지역: 4.85, 제2종일반주거지역: 2499.69 },
    overlap: { article: '국토의 계획 및 이용에 관한 법률 제84조', capacity_method: 'area_weighted_average' },
  },
  regulations: {
    bcr: { limit_pct: undefined, article: '의정부시 도시계획 조례 제42조; 국토의 계획 및 이용에 관한 법률 제84조', ...{ national_ceiling_pct: 59.9225, status: 'needs_evidence' } },
    far: { limit_pct: undefined, article: '의정부시 도시계획 조례 제46조', ...{ national_ceiling_pct: 249.7094, status: 'needs_evidence' } },
    height: { limit_m: undefined, rule: '가로구역별 높이제한 적용', article: '건축법 제60조' },
    sunlight_setback: { applies: true, direction: '정북방향', rules: [{ condition: 'H <= 10m', setback_m: 1.5 }, { condition: 'H > 10m', formula: 'H * 0.5' }] as unknown as string[], article: '건축법 제61조제1항' },
    corner_cutoff: { required: true, rule: '8m 미만 도로 모퉁이 (교차각별 2~4m 후퇴)', article: '건축법 제46조제1항, 시행령 제31조' },
    road_diagonal: { multiplier: undefined, rule: '삭제', article: '건축법 제60조' },
    building_line: { setback_m: undefined, rule: '도로경계선 후퇴 (조례에 따름)', article: '건축법 제46-47조' },
    adjacent_setback: { min_m: 0.5, article: '민법 제242조' },
    parking: { rule: '주차장법 시행령 별표 1', article: '주차장법 제19조' },
    landscaping: { threshold_m2: 200, article: '의정부시 건축 조례 제29조' },
    extended: { site_road_requirement: { name: '대지와 도로' }, cpted: { name: '범죄예방' } },
  },
  land_info: { success: true, land_area_m2: 2500, official_land_price: 1_660_000, land_use_situation: '대', zones: ['과밀억제권역', '제2종일반주거지역'] },
  law_articles: { articles: [], total_count: 0, errors: [] },
  restrictions: ['건폐율·용적률: 적용 조례·판본·용도지역 증거 부족 — 상한 미확정', '일조사선: 정북방향 H/2 이격', '인접대지 이격: 0.5m 이상'],
  overlay_regulations: [
    { name: '과밀억제권역', raw_zone: '과밀억제권역', category: 'capital_region', constraint: 'facility', article: '수도권정비계획법 §7, §8', description: '대규모 건축물 제한', values: {} },
    { name: '지구단위계획구역', raw_zone: '지구단위계획구역', category: 'planning', constraint: 'plan', article: '국토계획법 §49', description: '별도 계획 확인', values: {} },
    { name: '가축사육제한구역', raw_zone: '가축사육제한구역', category: 'livestock', constraint: 'use', article: '가축분뇨법 §8', description: '가축 사육 금지', values: {} },
  ],
  setback_lines: {
    buildable_area: { type: 'Polygon', coordinates: [[[127.108, 37.73], [127.109, 37.73], [127.109, 37.731], [127.108, 37.731], [127.108, 37.73]]] },
    north_setback: { type: 'FeatureCollection', coordinates: null },
    adjacent_setback: { type: 'MultiLineString', coordinates: [] },
    road_setback: null,
    corner_cutoff: null,
    sunlight_envelope: {
      walls: [], slope: 2, base_setback_m: 1.5, base_height_m: 10, max_depth_m: 25, plateau_end_m: 5,
      thresholds: [{ distance_m: 5, max_height_m: 10, kind: 'plateau' }, { distance_m: 25, max_height_m: 50, kind: 'cap' }],
      law_basis: '건축법 §61①, 시행령 §86①', datum_elevation_m: 0, datum_case: null, datum_basis: null, elevation_source: null,
    },
    datum_result: null,
  },
  program: { building_type: '', floor_area_m2: null, assessment_date: '2026-10-08' },
  assessment: {
    status: 'needs_evidence', permit_compliance_verified: false, scope: 'regulation_lookup_and_partial_calculation',
    missing_evidence: ['complete_design_applicability_and_permit_checks'],
    municipal_coverage: {
      status: 'needs_evidence', assessment_date: '2026-10-08',
      sources: [{ name: '의정부시 도시계획 조례', effective_date: '20250925' }],
      missing_evidence: ['unresolved_zoning:공공청사', 'unresolved_zoning:공공주택지구'],
    },
  },
  storage: { saved: true, analysis_id: '7cf0e223' },
}
