import type { FloorPlanRoom } from './types';

const ROOM_PRESETS: Record<string, FloorPlanRoom[]> = {
  '공동주택': [
    { name: '거실', area: 40, adjacency: ['현관', '주방'] },
    { name: '현관', area: 8, adjacency: ['거실'] },
    { name: '주방', area: 15, adjacency: ['거실', '식당'] },
    { name: '식당', area: 12, adjacency: ['주방'] },
    { name: '침실1', area: 18, adjacency: [] },
    { name: '침실2', area: 12, adjacency: [] },
    { name: '화장실', area: 6, adjacency: [] },
  ],
  '업무시설': [
    { name: '오픈오피스', area: 80, adjacency: ['로비'] },
    { name: '로비', area: 20, adjacency: ['오픈오피스', '회의실'] },
    { name: '회의실', area: 25, adjacency: ['로비'] },
    { name: '임원실', area: 20, adjacency: [] },
    { name: '탕비실', area: 10, adjacency: [] },
    { name: '화장실', area: 8, adjacency: [] },
  ],
  '근린생활시설': [
    { name: '매장', area: 60, adjacency: ['입구'] },
    { name: '입구', area: 10, adjacency: ['매장'] },
    { name: '창고', area: 15, adjacency: ['매장'] },
    { name: '사무실', area: 20, adjacency: [] },
    { name: '화장실', area: 6, adjacency: [] },
  ],
};

export function getRoomPreset(buildingType: string): FloorPlanRoom[] {
  return ROOM_PRESETS[buildingType] || ROOM_PRESETS['공동주택']!;
}

export default ROOM_PRESETS;
