import { requiredValue } from '../lib/required-value';
import React from 'react';
import type { DesignData, GeoJSONFeature } from '../lib/types';

const ALGO_COLORS: Record<string, string> = {
  additive: '#60a5fa', subtractive: '#a78bfa', grid: '#34d399',
  lshape: '#f97316', ushape: '#06b6d4', cross: '#ef4444',
  courtyard: '#f472b6', tower_podium: '#eab308', hshape: '#8b5cf6',
  radial: '#14b8a6',
};

const ALGO_LABELS: Record<string, string> = {
  additive: '자유', subtractive: '감산', grid: '격자',
  lshape: 'ㄱ자', ushape: 'ㄷ자', cross: '십자',
  courtyard: '중정', tower_podium: '타워', hshape: 'H형',
  radial: '방사',
};

const MASS_CONCEPT_COLORS: Record<string, string> = {
  legal_layered: '#f59e0b',
  legal_buildable: '#fb923c',
  bcr_fill: '#f97316',
  void_notch: '#38bdf8',
  courtyard: '#22c55e',
  slender_bar: '#a78bfa',
  split: '#06b6d4',
  branch: '#84cc16',
  pinch: '#f472b6',
  interlock: '#ef4444',
  overlap: '#eab308',
  stepback_tower: '#60a5fa',
  taper: '#14b8a6',
  grade: '#10b981',
  inset: '#94a3b8',
};

function massConceptKey(feature?: GeoJSONFeature | null): string | null {
  const raw = feature?.properties?.mass_shape;
  if (!raw) return null;
  const shape = raw.endsWith('_layered') ? raw.slice(0, -8) : raw;
  if (shape === 'legal_layered_max') return 'legal_layered';
  if (shape.startsWith('legal_buildable')) return 'legal_buildable';
  if (shape.startsWith('bcr_fill')) return 'bcr_fill';
  if (shape.startsWith('notch') || shape.startsWith('court_open')) return 'void_notch';
  if (shape === 'courtyard_void') return 'courtyard';
  if (shape.startsWith('slender_bar')) return 'slender_bar';
  if (shape.startsWith('split_bridge')) return 'split';
  if (shape.startsWith('branch_y')) return 'branch';
  if (shape.startsWith('pinch_waist')) return 'pinch';
  if (shape.startsWith('interlock_cross')) return 'interlock';
  if (shape.startsWith('overlap_slabs')) return 'overlap';
  if (shape === 'terrace_stepback' || shape === 'shifted_tower' || shape === 'lift_overlap_slabs') return 'stepback_tower';
  if (shape.startsWith('tapered')) return 'taper';
  if (shape.startsWith('grade_terrace')) return 'grade';
  if (shape.startsWith('inset')) return 'inset';
  return shape;
}

function massConceptLabel(feature?: GeoJSONFeature | null, fallback = 'MAAS'): string {
  const explicit = feature?.properties?.maas_concept;
  if (explicit) return explicit;
  const key = massConceptKey(feature);
  const labels: Record<string, string> = {
    legal_layered: '엔벨로프',
    legal_buildable: '최대건폐',
    bcr_fill: '건폐확장',
    void_notch: '오픈코트',
    courtyard: '중정',
    slender_bar: '바형',
    split: '분절',
    branch: '브랜치',
    pinch: '핀치',
    interlock: '인터락',
    overlap: '오버랩',
    stepback_tower: '타워',
    taper: '테이퍼',
    grade: '테라스',
    inset: '인셋',
  };
  return key ? (labels[key] || key) : fallback;
}

function parkingStrategyLabel(feature?: GeoJSONFeature | null): string {
  const p = feature?.properties as any;
  const precheck = p?.parking_precheck;
  const strategy = precheck?.selected_strategy || precheck?.strategy || p?.parking_strategy;
  const labels: Record<string, string> = {
    none: '주차없음',
    ground_surface: '외부지상',
    piloti_ground: '필로티',
    basement: '지하',
    semi_basement: '반지하',
    mechanical: '기계식',
    mixed: '혼합',
  };
  return strategy ? (labels[strategy] || String(strategy)) : '주차검토';
}

function parkingBadgeColor(feature?: GeoJSONFeature | null): string {
  const p = feature?.properties as any;
  const precheck = p?.parking_precheck;
  const strategy = precheck?.selected_strategy || precheck?.strategy || p?.parking_strategy;
  if (strategy === 'piloti_ground') return '#facc15';
  if (strategy === 'ground_surface') return '#38bdf8';
  if (strategy === 'basement' || strategy === 'semi_basement') return '#a78bfa';
  if (strategy === 'mechanical') return '#fb7185';
  return '#94a3b8';
}

interface Props {
  designs: DesignData[];
  selectedId: number | null;
  selectedUid?: string | null;
  selectedAlgorithm?: string | null;
  onSelect: (design: DesignData) => void;
  objectiveNames: string[];
  featureForDesign?: (design: DesignData) => GeoJSONFeature | null;
}

const OBJ_LABELS: Record<string, string> = {
  floor_area: '연면적',
  daylight_score: '일조',
  landscaping_pct: '외부공간',
  setback: '이격',
};

function outerRing(feature: GeoJSONFeature | null | undefined): number[][] | null {
  const geom = feature?.geometry;
  if (!geom) return null;
  if (geom.type === 'Polygon') return geom.coordinates[0] || null;
  if (geom.type === 'MultiPolygon') return largestPolygonCoordinates(geom.coordinates as unknown as number[][][][])?.[0] || null;
  return null;
}

function ringArea(ring: number[][] | null | undefined): number {
  if (!ring || ring.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = requiredValue(ring[i]);
    const b = requiredValue(ring[(i + 1) % ring.length]);
    sum += requiredValue(a[0]) * requiredValue(b[1]) - requiredValue(b[0]) * requiredValue(a[1]);
  }
  return Math.abs(sum) / 2;
}

function largestPolygonCoordinates(polygons: number[][][][] | null | undefined): number[][][] | null {
  if (!Array.isArray(polygons) || polygons.length === 0) return null;
  return polygons.reduce<number[][][] | null>((best, polygon) => {
    if (!Array.isArray(polygon) || !polygon[0]) return best;
    if (!best) return polygon;
    return ringArea(polygon[0]) > ringArea(best[0]) ? polygon : best;
  }, null);
}

function footprintPath(ring: number[][] | null, size = 34, pad = 4): string {
  if (!ring || ring.length < 3) return '';
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of ring) {
    if (requiredValue(x) < minX) minX = requiredValue(x);
    if (requiredValue(x) > maxX) maxX = requiredValue(x);
    if (requiredValue(y) < minY) minY = requiredValue(y);
    if (requiredValue(y) > maxY) maxY = requiredValue(y);
  }
  const w = maxX - minX || 1;
  const h = maxY - minY || 1;
  const scale = Math.min((size - pad * 2) / w, (size - pad * 2) / h);
  const offsetX = (size - w * scale) / 2;
  const offsetY = (size - h * scale) / 2;
  return ring.map(([x, y], i) => {
    const px = offsetX + (requiredValue(x) - minX) * scale;
    const py = size - (offsetY + (requiredValue(y) - minY) * scale);
    return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)} ${py.toFixed(1)}`;
  }).join(' ') + ' Z';
}

const MassThumbnail: React.FC<{ feature?: GeoJSONFeature | null; color: string; index: number }> = ({ feature, color, index }) => {
  const path = footprintPath(outerRing(feature));
  const height = feature?.properties?.height ?? 0;
  const floorCount = feature?.properties?.num_floors ?? 0;
  const heightRatio = Math.max(0.18, Math.min(1, height / 80));
  return (
    <div style={{
      width: 34,
      height: 34,
      borderRadius: 6,
      background: 'rgba(15,23,42,0.9)',
      border: '1px solid rgba(148,163,184,0.16)',
      position: 'relative',
      overflow: 'hidden',
      flexShrink: 0,
    }} data-testid={`mass-thumbnail-${index}`}>
      <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
        {path ? (
          <path d={path} fill={`${color}55`} stroke={color} strokeWidth="1.3" />
        ) : (
          <rect x="9" y="9" width="16" height="16" fill="rgba(100,116,139,0.25)" stroke="rgba(148,163,184,0.4)" />
        )}
      </svg>
      {floorCount > 0 && (
        <span style={{
          position: 'absolute',
          right: 2,
          bottom: 2,
          width: 4,
          height: Math.round(23 * heightRatio),
          background: color,
          borderRadius: 2,
          opacity: 0.85,
        }} />
      )}
    </div>
  );
};

const DesignList: React.FC<Props> = React.memo(({ designs, selectedId, selectedUid, selectedAlgorithm, onSelect, objectiveNames, featureForDesign }) => {
  if (designs.length === 0) return null;

  const obj0 = objectiveNames[0] || 'floor_area';
  const obj1 = objectiveNames[1] || 'daylight_score';

  return (
    <div style={{
      background: 'linear-gradient(180deg, #0c1120 0%, #0e1525 100%)',
      borderRadius: 12,
      border: '1px solid rgba(255,255,255,0.06)',
      boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 14px',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
      }}>
        <span style={{ color: '#8b95a8', fontSize: 11, fontWeight: 700, letterSpacing: '0.1em' }}>
          DESIGN LIST
        </span>
        <span style={{
          padding: '2px 8px', borderRadius: 10,
          background: 'rgba(96,200,255,0.08)', color: '#60c8ff',
          fontSize: 10, fontFamily: 'ui-monospace, monospace', fontWeight: 600,
        }}>
          {designs.length}
        </span>
      </div>

      {/* Column headers */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '28px 40px 46px 1fr 1fr 52px',
        gap: 0,
        padding: '6px 10px',
        fontSize: 9, color: '#475569', fontWeight: 600, letterSpacing: '0.05em',
        borderBottom: '1px solid rgba(255,255,255,0.03)',
      }}>
        <span>#</span>
        <span>매스</span>
        <span>형태</span>
        <span>{OBJ_LABELS[obj0] || obj0}</span>
        <span>{OBJ_LABELS[obj1] || obj1}</span>
        <span>주차</span>
      </div>

      {/* Scrollable list */}
      <div style={{ maxHeight: 240, overflowY: 'auto' }}>
        {designs.map((d, i) => {
          const algo = (d as any).algorithm || 'additive';
          const rowUid = d.uid || `${algo}:${d.id}`;
          const feature = featureForDesign?.(d);
          const conceptKey = massConceptKey(feature);
          const isSelected = selectedUid
            ? rowUid === selectedUid
            : d.id === selectedId && (!selectedAlgorithm || selectedAlgorithm === algo);
          const algoColor = (conceptKey && MASS_CONCEPT_COLORS[conceptKey]) || ALGO_COLORS[algo] || '#60a5fa';
          const algoLabel = massConceptLabel(feature, ALGO_LABELS[algo] || algo);

          return (
	            <div
	              key={`${rowUid}-${i}`}
	              data-testid={`design-row-${i}`}
	              onClick={() => onSelect(d)}
              style={{
                display: 'grid',
                gridTemplateColumns: '28px 40px 46px 1fr 1fr 52px',
                gap: 0,
                padding: '7px 10px',
                cursor: 'pointer',
                fontSize: 11,
                fontFamily: 'ui-monospace, monospace',
                background: isSelected
                  ? 'rgba(96,200,255,0.08)'
                  : i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
                borderLeft: isSelected ? '2px solid #60c8ff' : '2px solid transparent',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => {
                if (!isSelected) (e.currentTarget.style.background = 'rgba(255,255,255,0.03)');
              }}
              onMouseLeave={e => {
                if (!isSelected) (e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)');
              }}
            >
              <span style={{ color: isSelected ? '#60c8ff' : '#5a6577' }}>
                {i + 1}
              </span>
              <MassThumbnail feature={feature} color={algoColor} index={i} />
              <span style={{
                display: 'flex', alignItems: 'center', gap: 4,
              }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: algoColor, display: 'inline-block',
                  flexShrink: 0,
                }} />
                <span style={{ color: algoColor, fontSize: 9 }}>
                  {algoLabel}
                </span>
              </span>
              <span style={{ color: '#e2e8f0' }}>
                {requiredValue(d.objectives[0]) >= 1000
                  ? (requiredValue(d.objectives[0]) / 1000).toFixed(1) + 'k'
                  : d.objectives[0]?.toFixed(0)}
              </span>
              <span style={{ color: '#e2e8f0' }}>
                {d.objectives[1]?.toFixed(1)}
              </span>
              <span style={{
                fontSize: 9,
                color: parkingBadgeColor(feature),
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }} title={`${parkingStrategyLabel(feature)} / ${d.feasible ? 'OK' : 'X'}`}>
                {parkingStrategyLabel(feature)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
});

DesignList.displayName = 'DesignList';
export default DesignList;
