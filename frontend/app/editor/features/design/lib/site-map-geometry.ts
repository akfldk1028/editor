import { requiredValue } from './required-value';
import type { DatumBoundarySegment, DatumPointSample, GeoJSONFeature, SetbackGeometriesMap } from './types';
import type { DatumMarker } from './envelopes/datum-plane';

/** Extract outer ring from Polygon or MultiPolygon geometry */
export function extractRing(geometry: { type: string; coordinates: any }): number[][] | null {
  if (geometry.type === 'Polygon') return geometry.coordinates[0];
  if (geometry.type === 'MultiPolygon') return largestPolygonCoordinates(geometry.coordinates)?.[0] || null;
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

export function featureRing(feature: GeoJSONFeature | null | undefined): number[][] | null {
  const geometry = feature?.geometry as { type: string; coordinates: any } | undefined;
  if (!geometry) return null;
  return extractRing(geometry);
}

/** Flatten a coordinate ring to [lng, lat, lng, lat, ...] */
export function flattenRing(ring: number[][]): number[] {
  const flat: number[] = [];
  for (const [lng, lat] of ring) flat.push(requiredValue(lng), requiredValue(lat));
  return flat;
}

export function numberOrNull(value: unknown): number | null {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function weightedPoint<T>(
  items: T[] | null | undefined,
  lngKey: keyof T,
  latKey: keyof T,
  weightKey?: keyof T,
): { lng: number; lat: number } | null {
  if (!items?.length) return null;
  let sumLng = 0;
  let sumLat = 0;
  let sumWeight = 0;
  for (const item of items) {
    const lng = numberOrNull(item[lngKey]);
    const lat = numberOrNull(item[latKey]);
    if (lng == null || lat == null) continue;
    const weight = weightKey ? (numberOrNull(item[weightKey]) ?? 1) : 1;
    if (weight <= 0) continue;
    sumLng += lng * weight;
    sumLat += lat * weight;
    sumWeight += weight;
  }
  if (sumWeight <= 0) return null;
  return { lng: sumLng / sumWeight, lat: sumLat / sumWeight };
}

export function ringCentroid(ring: number[][] | null | undefined): { lng: number; lat: number } | null {
  if (!ring?.length) return null;
  let lng = 0;
  let lat = 0;
  for (const [x, y] of ring) {
    lng += requiredValue(x);
    lat += requiredValue(y);
  }
  return { lng: lng / ring.length, lat: lat / ring.length };
}

export function midpoint(a: { lng: number; lat: number }, b: { lng: number; lat: number }): { lng: number; lat: number } {
  return { lng: (a.lng + b.lng) / 2, lat: (a.lat + b.lat) / 2 };
}

export function lineCoords(geom: unknown): number[][] | null {
  const g = geom as { type?: string; coordinates?: unknown } | undefined;
  if (!g?.coordinates) return null;
  if (g.type === 'LineString' && Array.isArray(g.coordinates)) return g.coordinates as number[][];
  if (g.type === 'MultiLineString' && Array.isArray(g.coordinates)) return (g.coordinates as number[][][])[0] ?? null;
  return null;
}

export function lineMidpoint(coords: number[][]): { lng: number; lat: number } | null {
  if (!coords.length) return null;
  const mid = coords[Math.floor(coords.length / 2)];
  if (!mid || mid.length < 2) return null;
  return { lng: requiredValue(mid[0]), lat: requiredValue(mid[1]) };
}

export function lineKey(coords: number[][]): string {
  return coords.map((p) => `${p[0]?.toFixed(7)},${p[1]?.toFixed(7)}`).join('|');
}

export function polygonRing(geom: unknown): number[][] | null {
  const g = geom as { type?: string; coordinates?: unknown } | undefined;
  if (!g?.coordinates) return null;
  if (g.type === 'Polygon') return (g.coordinates as number[][][])[0] ?? null;
  if (g.type === 'MultiPolygon') return largestPolygonCoordinates(g.coordinates as number[][][][])?.[0] ?? null;
  if (g.type === 'Feature') {
    return polygonRing((g as { geometry?: unknown }).geometry);
  }
  return null;
}

function metersPerDegreeLng(lat: number): number {
  return Math.max(1, 111_320 * Math.cos((lat * Math.PI) / 180));
}

export function lngLatToLocalMeters(point: { lng: number; lat: number }, origin: { lng: number; lat: number }) {
  return {
    x: (point.lng - origin.lng) * metersPerDegreeLng(origin.lat),
    y: (point.lat - origin.lat) * 110_540,
  };
}

function localMetersToLngLat(point: { x: number; y: number }, origin: { lng: number; lat: number }) {
  return {
    lng: origin.lng + point.x / metersPerDegreeLng(origin.lat),
    lat: origin.lat + point.y / 110_540,
  };
}

export function offsetPointMeters(
  point: { lng: number; lat: number },
  origin: { lng: number; lat: number },
  unit: { x: number; y: number },
  meters: number,
): { lng: number; lat: number } {
  const local = lngLatToLocalMeters(point, origin);
  return localMetersToLngLat({ x: local.x + unit.x * meters, y: local.y + unit.y * meters }, origin);
}

export function clippedLineSegment(
  a: { lng: number; lat: number },
  b: { lng: number; lat: number },
  origin: { lng: number; lat: number },
  maxLengthM: number,
): [{ lng: number; lat: number }, { lng: number; lat: number }] {
  const al = lngLatToLocalMeters(a, origin);
  const bl = lngLatToLocalMeters(b, origin);
  const dx = bl.x - al.x;
  const dy = bl.y - al.y;
  const len = Math.hypot(dx, dy);
  if (len <= maxLengthM || len < 0.01) return [a, b];
  const ux = dx / len;
  const uy = dy / len;
  const half = maxLengthM / 2;
  return [
    localMetersToLngLat({ x: -ux * half, y: -uy * half }, origin),
    localMetersToLngLat({ x: ux * half, y: uy * half }, origin),
  ];
}

export function buildDatumMarkers(setbacks: SetbackGeometriesMap, parcelRing: number[][] | null): DatumMarker[] {
  const datum = setbacks.datum_result;
  if (!datum) return [];

  const parcelDatumM = datum.parcel_datum_m ?? datum.elevation_m ?? null;
  const roadDatumM = datum.road_datum_m ?? null;
  const neighborDatumM = datum.neighbor_datum_m ?? null;
  const neighborAvgM = datum.neighbor_avg_datum_m ?? null;
  const sunlightApplies = Boolean(setbacks.sunlight_envelope);

  const parcelBasis = weightedPoint<DatumBoundarySegment>(
    datum.parcel_segments,
    'midpoint_lng',
    'midpoint_lat',
    'length_m',
  ) ?? ringCentroid(parcelRing);
  const roadBasis = weightedPoint<DatumPointSample>(
    datum.road_samples,
    'lng',
    'lat',
    'weight',
  );
  const neighborBasis = weightedPoint<DatumBoundarySegment>(
    datum.neighbor_segments,
    'midpoint_lng',
    'midpoint_lat',
    'length_m',
  );

  const markers: DatumMarker[] = [];
  if (parcelBasis && parcelDatumM != null) {
    markers.push({
      id: 'parcel-119',
      label: '대지 §119',
      lng: parcelBasis.lng,
      lat: parcelBasis.lat,
      elevationM: parcelDatumM,
      color: '#facc15',
      labelOffset: [0, 28],
    });
  }
  if (roadBasis && roadDatumM != null) {
    markers.push({
      id: 'road',
      label: '도로레벨',
      lng: roadBasis.lng,
      lat: roadBasis.lat,
      elevationM: roadDatumM,
      color: '#38bdf8',
      labelOffset: [-78, 18],
    });
  }
  if (neighborBasis && neighborDatumM != null) {
    markers.push({
      id: 'neighbor',
      label: '인접대지',
      lng: neighborBasis.lng,
      lat: neighborBasis.lat,
      elevationM: neighborDatumM,
      color: '#f472b6',
      labelOffset: [-90, -28],
    });
  }
  if (sunlightApplies && parcelBasis && neighborBasis && neighborAvgM != null) {
    const basis = midpoint(parcelBasis, neighborBasis);
    markers.push({
      id: 'neighbor-avg-86',
      label: '§86 평균',
      lng: basis.lng,
      lat: basis.lat,
      elevationM: neighborAvgM,
      color: '#22c55e',
      labelOffset: [42, -70],
    });
  }
  return markers;
}

