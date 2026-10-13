import type { AgentSpec } from '../../spec'

/** Site Agent as the conversation names it; tools it answers (`<id>_health` is implied). */
export const spec: AgentSpec = {
  id: 'site_context',
  name: 'Site Agent',
  aliases: ['site-context', 'site'],
  tools: {
    site_resolve: '대지 사실 확인', site_district_plan: '지구단위계획 자료', site_overlay_lookup: '중첩 규제 조회',
    site_road_sources: '도로 자료', site_street_height_sources: '가로구역 높이 자료', site_surroundings: '주변 현황',
    site_ground_heights: '지반 높이', site_buildings: '주변 건물', site_roads: '주변 도로', site_ground_cover: '주변 필지 지목',
    site_land_cover: '토지 피복', site_newer_notices: '최근 고시', site_land_use: '토지이용계획', site_layer_features: '지도 레이어',
    site_zoning: '용도지역', site_terrain_samples: '지형 표본',
  },
}
