import { requiredValue } from '../required-value';

/* eslint-disable @typescript-eslint/no-explicit-any */

export type SectionRenderSegment = { ring: number[][]; bottom: number; top: number };

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

export function extractParkingEnvelopeRing(parkingPrecheck: any): number[][] | null {
  const geometry = parkingPrecheck?.parking_envelope_wgs84;
  if (!geometry || typeof geometry !== 'object') return null;
  return extractRing(geometry);
}

export function flattenRing(ring: number[][]): number[] {
  const flat: number[] = [];
  for (const [lng, lat] of ring) flat.push(requiredValue(lng), requiredValue(lat));
  return flat;
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

export function ringBounds(ring: number[][]): { minLng: number; maxLng: number; minLat: number; maxLat: number } {
  let minLng = Number.POSITIVE_INFINITY;
  let maxLng = Number.NEGATIVE_INFINITY;
  let minLat = Number.POSITIVE_INFINITY;
  let maxLat = Number.NEGATIVE_INFINITY;
  for (const [lng, lat] of ring) {
    minLng = Math.min(minLng, requiredValue(lng));
    maxLng = Math.max(maxLng, requiredValue(lng));
    minLat = Math.min(minLat, requiredValue(lat));
    maxLat = Math.max(maxLat, requiredValue(lat));
  }
  return { minLng, maxLng, minLat, maxLat };
}

export function getGroundHeight(Cesium: any, viewer: any, ring: number[][]): number {
  let cx = 0;
  let cy = 0;
  for (const [lng, lat] of ring) {
    cx += requiredValue(lng);
    cy += requiredValue(lat);
  }
  cx /= ring.length;
  cy /= ring.length;
  try {
    const carto = Cesium.Cartographic.fromDegrees(cx, cy);
    const h = viewer.scene?.globe?.getHeight?.(carto);
    if (typeof h === 'number' && isFinite(h)) return h;
  } catch { /* fallback */ }
  return 0;
}

export function extractSectionProfile(props: any): any | null {
  const model = props?.maas_model;
  const profile = props?.section_profile || model?.section_profile;
  return profile && typeof profile === 'object' ? profile : null;
}

function ringFromRenderableGeometry(item: any): number[][] | null {
  const geometry = item?.geometry;
  if (!geometry || typeof geometry !== 'object') return null;
  return extractRing(geometry);
}

type BuildSectionRenderSegmentsOptions = {
  floorGroups: any[];
  massVolumes: any[];
  floorPlates: any[];
  fallbackRing: number[][];
  height: number;
  floorH: number;
};

export function buildSectionRenderSegments(options: BuildSectionRenderSegmentsOptions): SectionRenderSegment[] {
  const { floorGroups, massVolumes, floorPlates, fallbackRing, height, floorH } = options;
  const source = floorGroups.length > 0
    ? floorGroups
    : massVolumes.length > 0
      ? massVolumes
      : floorPlates.length > 0
        ? floorPlates
        : [];
  const segments: SectionRenderSegment[] = [];
  if (source.length > 0) {
    for (let i = 0; i < source.length; i++) {
      const item = source[i];
      const itemRing = ringFromRenderableGeometry(item);
      if (!itemRing || itemRing.length < 3) continue;
      const prev = i > 0 ? source[i - 1] : null;
      const bottom = Number(item.bottom_height ?? prev?.top_height ?? 0) || 0;
      const top = Number(item.top_height ?? ((i + 1) * floorH)) || height;
      segments.push({ ring: itemRing, bottom, top });
    }
  }
  if (segments.length === 0) {
    segments.push({ ring: fallbackRing, bottom: 0, top: height });
  }
  return segments;
}
