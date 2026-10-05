import React, { useEffect } from 'react';
import type { GeoJSONFeature } from '../lib/types';
import { requiredValue } from '../lib/required-value';
import { extractRing, featureRing } from '../lib/site-map-geometry';
import { SHAPE_COLORS } from '../lib/cesium/mass-styles';

function featureBounds(rings: Array<number[][] | null>): { west: number; south: number; east: number; north: number } | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const ring of rings) {
    if (!ring) continue;
    for (const [lng, lat] of ring) {
      west = Math.min(west, requiredValue(lng));
      south = Math.min(south, requiredValue(lat));
      east = Math.max(east, requiredValue(lng));
      north = Math.max(north, requiredValue(lat));
    }
  }
  if (![west, south, east, north].every(Number.isFinite)) return null;
  return { west, south, east, north };
}

function projectFallbackPoint(
  point: number[],
  bounds: { west: number; south: number; east: number; north: number },
  width: number,
  height: number,
): [number, number] {
  const pad = 44;
  const spanX = Math.max(bounds.east - bounds.west, 1e-12);
  const spanY = Math.max(bounds.north - bounds.south, 1e-12);
  const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY);
  const x = width / 2 + (requiredValue(point[0]) - (bounds.west + bounds.east) / 2) * scale;
  const y = height / 2 - (requiredValue(point[1]) - (bounds.south + bounds.north) / 2) * scale;
  return [x, y];
}

function pathFromRing(
  ring: number[][],
  bounds: { west: number; south: number; east: number; north: number },
  width: number,
  height: number,
): string {
  return ring
    .map((point, index) => {
      const [x, y] = projectFallbackPoint(point, bounds, width, height);
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ') + ' Z';
}

const MassFallback2D: React.FC<{
  sitePolygon: object | null;
  massFeatures?: GeoJSONFeature[];
  selectedDesignId?: number;
  reason?: string;
}> = ({ sitePolygon, massFeatures, selectedDesignId, reason }) => {
  const siteRing = sitePolygon ? extractRing(sitePolygon as { type: string; coordinates: any }) : null;
  const massRings = (massFeatures || []).map(featureRing);
  const bounds = featureBounds([siteRing, ...massRings]);
  const width = 760;
  const height = 760;
  const selectedFeature = (massFeatures || [])[0];
  const selectedProps: Partial<GeoJSONFeature['properties']> = selectedFeature?.properties || {};
  useEffect(() => {
    (window as any).__arrDesignLastMassFeatures = massFeatures || [];
    (window as any).__arrDesignActiveMassFeature = selectedFeature || null;
  }, [massFeatures, selectedFeature]);
  if (!bounds || !massFeatures?.length) {
    return (
      <div style={{ color: '#f87171', fontSize: 13 }}>
        {reason || '3D 지도를 사용할 수 없습니다.'}
      </div>
    );
  }

  return (
    <div style={{
      width: '100%', height: '100%',
      display: 'grid', gridTemplateRows: 'auto 1fr auto',
      background: 'linear-gradient(180deg, #101827 0%, #0b1220 100%)',
      color: '#e2e8f0',
      padding: 20,
      boxSizing: 'border-box',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
        <div>
          <div style={{ color: '#60a5fa', fontSize: 12, fontWeight: 700, letterSpacing: '0.08em' }}>
            2D MASS PREVIEW
          </div>
          <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 4 }}>
            WebGL fallback · legal MAAS geometry from mass_geojson
          </div>
        </div>
        <div style={{ color: '#f87171', fontSize: 12, textAlign: 'right', maxWidth: 360 }}>
          {reason || '3D 지도 비활성화'}
        </div>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: '100%', minHeight: 0 }}>
        <defs>
          <filter id="mass-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="12" stdDeviation="10" floodColor="#020617" floodOpacity="0.38" />
          </filter>
          <linearGradient id="mass-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.86" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0.68" />
          </linearGradient>
        </defs>
        <rect x="0" y="0" width={width} height={height} rx="18" fill="#0f172a" />
        <g opacity="0.18">
          {Array.from({ length: 13 }, (_, i) => (
            <line key={`v-${i}`} x1={44 + i * 56} y1="44" x2={44 + i * 56} y2={height - 44} stroke="#475569" strokeWidth="1" />
          ))}
          {Array.from({ length: 13 }, (_, i) => (
            <line key={`h-${i}`} x1="44" y1={44 + i * 56} x2={width - 44} y2={44 + i * 56} stroke="#475569" strokeWidth="1" />
          ))}
        </g>
        {siteRing && (
          <path
            d={pathFromRing(siteRing, bounds, width, height)}
            fill="#1e293b"
            stroke="#94a3b8"
            strokeWidth="2"
            strokeDasharray="8 7"
            opacity="0.78"
          />
        )}
        {(massFeatures || []).map((feature, index) => {
          const ring = featureRing(feature);
          if (!ring) return null;
          const props = feature.properties || {};
          const designId = props.design_id ?? props.variant_id ?? index;
          const selected = selectedDesignId ? designId === selectedDesignId : index === 0;
          const color = SHAPE_COLORS[props.mass_shape || props.algorithm || ''] || '#60a5fa';
          const dx = selected ? 0 : (index % 4) * 5 - 8;
          const dy = selected ? 0 : Math.floor(index / 4) * 5 - 8;
          return (
            <g key={`${designId}-${index}`} transform={`translate(${dx} ${dy})`} opacity={selected ? 1 : 0.42}>
              <path
                d={pathFromRing(ring, bounds, width, height)}
                fill={selected ? 'url(#mass-fill)' : color}
                fillOpacity={selected ? 0.78 : 0.22}
                stroke={selected ? '#fbbf24' : color}
                strokeWidth={selected ? 5 : 2}
                filter={selected ? 'url(#mass-shadow)' : undefined}
              />
            </g>
          );
        })}
      </svg>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
        gap: 8,
        fontSize: 12,
      }}>
        {[
          ['형태', selectedProps.mass_shape || selectedProps.algorithm || '-'],
          ['높이', selectedProps.height ? `${Number(selectedProps.height).toFixed(1)}m` : '-'],
          ['층수', selectedProps.num_floors ? `${selectedProps.num_floors}F` : '-'],
          ['건폐율', selectedProps.bcr ? `${Number(selectedProps.bcr).toFixed(1)}%` : '-'],
          ['용적률', selectedProps.far ? `${Number(selectedProps.far).toFixed(1)}%` : '-'],
        ].map(([label, value]) => (
          <div key={label} style={{ background: '#111827', border: '1px solid #1e293b', borderRadius: 8, padding: '8px 10px' }}>
            <div style={{ color: '#64748b', fontSize: 10, marginBottom: 3 }}>{label}</div>
            <div style={{ color: '#e2e8f0', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
};


export default MassFallback2D;
