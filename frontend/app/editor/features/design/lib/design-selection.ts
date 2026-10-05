import { requiredValue } from './required-value';
import type { DesignData, GeoJSONFeature } from './types';

export type SiteGeometry = { type: string; coordinates: unknown };

function outerRing(geometry: SiteGeometry | GeoJSONFeature['geometry'] | null | undefined): number[][] | null {
  if (!geometry) return null;
  if (geometry.type === 'Polygon') return (geometry.coordinates as number[][][])[0] || null;
  if (geometry.type === 'MultiPolygon') return largestPolygonCoordinates(geometry.coordinates as unknown as number[][][][])?.[0] || null;
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

function pointInRing(point: [number, number], ring: number[][]): boolean {
  const [x, y] = point;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = requiredValue(requiredValue(ring[i])[0]), yi = requiredValue(requiredValue(ring[i])[1]);
    const xj = requiredValue(requiredValue(ring[j])[0]), yj = requiredValue(requiredValue(ring[j])[1]);
    const intersect = ((yi > y) !== (yj > y))
      && (x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-12) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function orientation(a: number[], b: number[], c: number[]): number {
  const value = (requiredValue(b[1]) - requiredValue(a[1])) * (requiredValue(c[0]) - requiredValue(b[0])) - (requiredValue(b[0]) - requiredValue(a[0])) * (requiredValue(c[1]) - requiredValue(b[1]));
  if (Math.abs(value) < 1e-12) return 0;
  return value > 0 ? 1 : 2;
}

function onSegment(a: number[], b: number[], c: number[]): boolean {
  return requiredValue(b[0]) <= Math.max(requiredValue(a[0]), requiredValue(c[0])) + 1e-12
    && requiredValue(b[0]) + 1e-12 >= Math.min(requiredValue(a[0]), requiredValue(c[0]))
    && requiredValue(b[1]) <= Math.max(requiredValue(a[1]), requiredValue(c[1])) + 1e-12
    && requiredValue(b[1]) + 1e-12 >= Math.min(requiredValue(a[1]), requiredValue(c[1]));
}

function segmentsIntersect(a1: number[], a2: number[], b1: number[], b2: number[]): boolean {
  const o1 = orientation(a1, a2, b1);
  const o2 = orientation(a1, a2, b2);
  const o3 = orientation(b1, b2, a1);
  const o4 = orientation(b1, b2, a2);
  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSegment(a1, b1, a2)) return true;
  if (o2 === 0 && onSegment(a1, b2, a2)) return true;
  if (o3 === 0 && onSegment(b1, a1, b2)) return true;
  if (o4 === 0 && onSegment(b1, a2, b2)) return true;
  return false;
}

function closeRing(ring: number[][]): number[][] {
  if (ring.length < 2) return ring;
  const first = requiredValue(ring[0]);
  const last = requiredValue(ring[ring.length - 1]);
  return requiredValue(first[0]) === requiredValue(last[0]) && requiredValue(first[1]) === requiredValue(last[1]) ? ring : [...ring, first];
}

function ringsOverlap(siteRing: number[][], featureRing: number[][]): boolean {
  if (siteRing.length < 3 || featureRing.length < 3) return true;
  if (featureRing.some(p => pointInRing([requiredValue(p[0]), requiredValue(p[1])], siteRing))) return true;
  if (siteRing.some(p => pointInRing([requiredValue(p[0]), requiredValue(p[1])], featureRing))) return true;
  const site = closeRing(siteRing);
  const feature = closeRing(featureRing);
  for (let i = 0; i < site.length - 1; i++) {
    for (let j = 0; j < feature.length - 1; j++) {
      if (segmentsIntersect(requiredValue(site[i]), requiredValue(site[i + 1]), requiredValue(feature[j]), requiredValue(feature[j + 1]))) return true;
    }
  }
  return false;
}

function pointOnRing(point: number[], ring: number[][]): boolean {
  const closed = closeRing(ring);
  for (let i = 0; i < closed.length - 1; i++) {
    if (orientation(requiredValue(closed[i]), point, requiredValue(closed[i + 1])) === 0 && onSegment(requiredValue(closed[i]), point, requiredValue(closed[i + 1]))) {
      return true;
    }
  }
  return false;
}

function pointInsideOrOnRing(point: number[], ring: number[][]): boolean {
  return pointInRing([requiredValue(point[0]), requiredValue(point[1])], ring) || pointOnRing(point, ring);
}

function ringContainedInSite(siteRing: number[][], featureRing: number[][]): boolean {
  if (siteRing.length < 3 || featureRing.length < 3) return true;
  const feature = closeRing(featureRing);
  for (let i = 0; i < feature.length - 1; i++) {
    const a = requiredValue(feature[i]);
    const b = requiredValue(feature[i + 1]);
    const mid = [(requiredValue(a[0]) + requiredValue(b[0])) / 2, (requiredValue(a[1]) + requiredValue(b[1])) / 2];
    const thirdA = [requiredValue(a[0]) + (requiredValue(b[0]) - requiredValue(a[0])) / 3, requiredValue(a[1]) + (requiredValue(b[1]) - requiredValue(a[1])) / 3];
    const thirdB = [requiredValue(a[0]) + (requiredValue(b[0]) - requiredValue(a[0])) * 2 / 3, requiredValue(a[1]) + (requiredValue(b[1]) - requiredValue(a[1])) * 2 / 3];
    if (![a, mid, thirdA, thirdB].every(p => pointInsideOrOnRing(requiredValue(p), siteRing))) {
      return false;
    }
  }
  return true;
}

export function featureFitsSite(feature: GeoJSONFeature | null | undefined, sitePolygon: object | null): boolean {
  if (!feature || !sitePolygon) return Boolean(feature);
  const siteRing = outerRing(sitePolygon as SiteGeometry);
  const featureRing = outerRing(feature.geometry);
  if (!siteRing || !featureRing) return true;
  return ringsOverlap(siteRing, featureRing) && ringContainedInSite(siteRing, featureRing);
}

function scoreParetoCandidate(design: DesignData, designs: DesignData[]): number {
  const xs = designs.map(d => d.objectives[0] || 0);
  const ys = designs.map(d => d.objectives[1] || 0);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const x = ((design.objectives[0] || 0) - xMin) / ((xMax - xMin) || 1);
  const y = ((design.objectives[1] || 0) - yMin) / ((yMax - yMin) || 1);
  return x * 0.72 + y * 0.28 - Math.max(0, design.penalty || 0) * 0.05;
}

function designShapeKey(design: DesignData, feature: GeoJSONFeature | null): string {
  const props = feature?.properties;
  return props?.mass_shape || props?.algorithm || design.algorithm || 'unknown';
}

export function designIdentityKey(design: DesignData): string {
  return design.uid || `${design.algorithm || 'unknown'}:${design.id}`;
}

export function pickDiverseParetoDesigns(
  designs: DesignData[],
  features: GeoJSONFeature[],
  sitePolygon: object | null,
  limit: number,
): DesignData[] {
  const locationChecked = features.length > 0
    ? designs.filter(d => {
      const feat = features.find(f => matchesDesignFeature(f, d));
      return !feat || featureFitsSite(feat, sitePolygon);
    })
    : designs;
  const candidates = locationChecked.length > 0 ? locationChecked : designs;
  if (candidates.length <= limit) return candidates;

  const ranked = [...candidates]
    .sort((a, b) => scoreParetoCandidate(b, candidates) - scoreParetoCandidate(a, candidates));
  const selected: DesignData[] = [];
  const usedShapes = new Set<string>();

  for (const design of ranked) {
    if (selected.length >= limit) break;
    const feature = features.find(f => matchesDesignFeature(f, design)) || null;
    const key = designShapeKey(design, feature);
    if (usedShapes.has(key)) continue;
    selected.push(design);
    usedShapes.add(key);
  }

  for (const design of ranked) {
    if (selected.length >= limit) break;
    if (!selected.some(d => designIdentityKey(d) === designIdentityKey(design))) {
      selected.push(design);
    }
  }
  return selected;
}

export const matchesDesignFeature = (feature: any, design: DesignData) => {
  const props = feature.properties || {};
  if (design.uid && props.design_uid) {
    return props.design_uid === design.uid;
  }
  return props.design_id === design.id
    && (!design.algorithm || props.algorithm === design.algorithm);
};

export function normalizeSitePolygon(geometry: SiteGeometry | null | undefined): SiteGeometry | undefined {
  if (!geometry) return undefined;
  if (geometry.type !== 'MultiPolygon') return geometry;
  const coords = geometry.coordinates as number[][][][];
  const largest = largestPolygonCoordinates(coords);
  return largest ? { type: 'Polygon', coordinates: largest as unknown as number[][][] } : undefined;
}

