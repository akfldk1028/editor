export const OBJECTIVE_LABELS: Record<string, string> = {
  floor_area: 'Floor Area (m\u00B2)',
  daylight_score: 'Daylight Score',
  landscaping_pct: 'Open Space (%)',
  setback: 'Setback (m)',
  bcr: 'BCR (%)',
  far: 'FAR (%)',
  height: 'Height (m)',
};

export const BUILDING_TYPES = [
  { key: '공동주택', label: '공동주택 (아파트)', floorHeight: 2.8 },
  { key: '근린생활시설', label: '근린생활시설', floorHeight: 3.5 },
  { key: '업무시설', label: '업무시설 (오피스)', floorHeight: 3.8 },
  { key: '판매시설', label: '판매시설 (상가)', floorHeight: 4.0 },
  { key: '숙박시설', label: '숙박시설 (호텔)', floorHeight: 3.0 },
  { key: '문화집회시설', label: '문화 및 집회시설', floorHeight: 4.5 },
  { key: '의료시설', label: '의료시설', floorHeight: 3.6 },
  { key: '교육연구시설', label: '교육연구시설', floorHeight: 3.5 },
  { key: '공장', label: '공장', floorHeight: 5.0 },
  { key: '창고시설', label: '창고시설', floorHeight: 6.0 },
];

export const ALGORITHMS = [
  { key: 'maas_legal_envelope', label: 'MAAS 법규 탐색' },
  { key: 'all', label: 'Legacy 10종 비교' },
];
