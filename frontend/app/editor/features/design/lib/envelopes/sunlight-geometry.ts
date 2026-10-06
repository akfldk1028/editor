import { requiredValue } from '../required-value';

/* eslint-disable @typescript-eslint/no-explicit-any */

export type ProfilePoint = [number, number, number];
export type WallSegment = {
  a: ProfilePoint;
  b: ProfilePoint;
  minA: number;
  minB: number;
};
export type WallLinePoint = [number, number, number, number];

export function simplifyClosedRing<T>(ring: T[], maxPoints: number): T[] {
  if (ring.length <= maxPoints) return ring;
  const step = Math.ceil(ring.length / maxPoints);
  const simplified: T[] = [];
  for (let i = 0; i < ring.length; i += step) simplified.push(requiredValue(ring[i]));
  return simplified.length >= 3 ? simplified : ring.slice(0, Math.min(ring.length, maxPoints));
}

export function layerRing(layer: unknown): number[][] | null {
  const ring = (layer as { footprint_wgs?: unknown })?.footprint_wgs;
  return Array.isArray(ring) && ring.length >= 4 ? ring as number[][] : null;
}

export function layerHeight(layer: unknown): number | null {
  const h = Number((layer as { h_top?: unknown })?.h_top);
  return Number.isFinite(h) ? h : null;
}

export function ringCenterWithHeight(corners: number[][], groundH: number): ProfilePoint {
  let lng = 0;
  let lat = 0;
  let h = 0;
  for (const c of corners) {
    lng += requiredValue(c[0]);
    lat += requiredValue(c[1]);
    h += requiredValue(c[2]);
  }
  const n = Math.max(1, corners.length);
  return [lng / n, lat / n, groundH + h / n];
}

export function buildPrimaryWallLine(
  segments: WallSegment[],
  profilePoints: number[][] | undefined,
): WallLinePoint[] {
  if (!segments.length) return [];
  const profile = profilePoints;
  if (!profile || profile.length < 3) return segmentsToWallLine(segments);

  const origin = profile[0] as ProfilePoint;
  const inwardTarget = profile[2] as ProfilePoint;
  const inwardDelta = toLocalMeters(origin, inwardTarget);
  const inwardLen = Math.hypot(inwardDelta.x, inwardDelta.y);
  if (!Number.isFinite(inwardLen) || inwardLen < 0.05) return segmentsToWallLine(segments);

  const ix = inwardDelta.x / inwardLen;
  const iy = inwardDelta.y / inwardLen;
  const ax = -iy;
  const ay = ix;

  const measured = segments.map((seg) => {
    const mid: ProfilePoint = [
      (seg.a[0] + seg.b[0]) / 2,
      (seg.a[1] + seg.b[1]) / 2,
      (seg.a[2] + seg.b[2]) / 2,
    ];
    const deltaMid = toLocalMeters(origin, mid);
    const deltaSeg = toLocalMeters(seg.a, seg.b);
    const len = Math.hypot(deltaSeg.x, deltaSeg.y);
    const alongInward = deltaMid.x * ix + deltaMid.y * iy;
    const dirInward = len > 0.05 ? Math.abs((deltaSeg.x / len) * ix + (deltaSeg.y / len) * iy) : 1;
    return { seg, alongInward, dirInward };
  });

  const parallel = measured.filter((item) => item.dirInward < 0.35);
  if (!parallel.length) return segmentsToWallLine(segments);

  const minInward = Math.min(...parallel.map((item) => item.alongInward));
  const selected = parallel
    .filter((item) => Math.abs(item.alongInward - minInward) <= 1.8)
    .map((item) => item.seg);
  return segmentsToWallLine(selected.length ? selected : parallel.map((item) => item.seg), origin, ax, ay);
}

function segmentsToWallLine(
  segments: WallSegment[],
  origin?: ProfilePoint,
  ax?: number,
  ay?: number,
): WallLinePoint[] {
  if (!segments.length) return [];
  if (origin && ax != null && ay != null) {
    const points = new Map<string, WallLinePoint>();
    for (const seg of segments) {
      points.set(`${seg.a[0].toFixed(12)},${seg.a[1].toFixed(12)}`, [seg.a[0], seg.a[1], seg.a[2], seg.minA]);
      points.set(`${seg.b[0].toFixed(12)},${seg.b[1].toFixed(12)}`, [seg.b[0], seg.b[1], seg.b[2], seg.minB]);
    }
    return [...points.values()].sort((a, b) => {
      const da = toLocalMeters(origin, [a[0], a[1], a[2]]);
      const db = toLocalMeters(origin, [b[0], b[1], b[2]]);
      return (da.x * ax + da.y * ay) - (db.x * ax + db.y * ay);
    });
  }

  const line: WallLinePoint[] = [[requiredValue(segments[0]).a[0], requiredValue(segments[0]).a[1], requiredValue(segments[0]).a[2], requiredValue(segments[0]).minA]];
  for (const seg of segments) line.push([seg.b[0], seg.b[1], seg.b[2], seg.minB]);
  return line;
}

export function capProfilePoints(points: number[][] | undefined, maxHeightM: number): number[][] | undefined {
  if (!points || points.length < 2) return points;
  const capped: number[][] = [];
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    const h = Number(p?.[2]);
    if (!p || !Number.isFinite(h)) continue;
    if (h <= maxHeightM) {
      capped.push(p);
      continue;
    }
    const prev = points[i - 1];
    const prevH = Number(prev?.[2]);
    if (prev && Number.isFinite(prevH) && prevH < maxHeightM && h > prevH) {
      const t = (maxHeightM - prevH) / (h - prevH);
      capped.push([
        requiredValue(prev[0]) + (requiredValue(p[0]) - requiredValue(prev[0])) * t,
        requiredValue(prev[1]) + (requiredValue(p[1]) - requiredValue(prev[1])) * t,
        maxHeightM,
      ]);
    }
    break;
  }
  return capped.length >= 2 ? capped : points;
}

function offsetLngLatMeters(point: number[], dxM: number, dyM: number, h: number): ProfilePoint {
  const latRad = requiredValue(point[1]) * Math.PI / 180;
  return [
    requiredValue(point[0]) + dxM / (111_320 * Math.cos(latRad)),
    requiredValue(point[1]) + dyM / 110_540,
    h,
  ];
}

export function buildConnectedProfileSurface(
  profilePoints: number[][] | undefined,
  wallTopLine: number[][],
  groundH: number,
  maxHeightM: number,
): { wallTopLine: ProfilePoint[]; plateauEndLine: ProfilePoint[]; slopeTopLine: ProfilePoint[] } | null {
  const capped = capProfilePoints(profilePoints, maxHeightM);
  if (!capped || capped.length < 4 || wallTopLine.length < 2) return null;
  const wallTop = capped[1] as ProfilePoint;
  const slopeStart = capped[2] as ProfilePoint;
  const end = capped[capped.length - 1] as ProfilePoint;
  const plateauDelta = toLocalMeters(wallTop, slopeStart);
  const topDelta = toLocalMeters(wallTop, end);
  if (!Number.isFinite(plateauDelta.x) || !Number.isFinite(plateauDelta.y)) return null;
  if (!Number.isFinite(topDelta.x) || !Number.isFinite(topDelta.y)) return null;

  const wallTopLineAbs = wallTopLine.map((p) => [p[0], p[1], groundH + 10] as ProfilePoint);
  const plateauEndLine = wallTopLine.map((p) =>
    offsetLngLatMeters(p, plateauDelta.x, plateauDelta.y, groundH + (slopeStart[2] ?? 10)),
  );
  const slopeTopLine = wallTopLine.map((p) =>
    offsetLngLatMeters(p, topDelta.x, topDelta.y, groundH + (end[2] ?? maxHeightM)),
  );
  return { wallTopLine: wallTopLineAbs, plateauEndLine, slopeTopLine };
}

function toLocalMeters(origin: ProfilePoint, point: ProfilePoint) {
  const latRad = origin[1] * Math.PI / 180;
  return {
    x: (point[0] - origin[0]) * 111_320 * Math.cos(latRad),
    y: (point[1] - origin[1]) * 110_540,
  };
}

function offsetLngLat(point: ProfilePoint, nx: number, ny: number, offsetM: number): ProfilePoint {
  const latRad = point[1] * Math.PI / 180;
  return [
    point[0] + (nx * offsetM) / (111_320 * Math.cos(latRad)),
    point[1] + (ny * offsetM) / 110_540,
    point[2],
  ];
}

function profileDirectionNormal(points: number[][]) {
  if (points.length < 2) return null;
  const start = points[0] as ProfilePoint;
  const end = points[points.length - 1] as ProfilePoint;
  const normal = profileNormal(start, end);
  if (normal) return normal;
  for (let i = 1; i < points.length; i++) {
    const candidate = profileNormal(points[i - 1] as ProfilePoint, points[i] as ProfilePoint);
    if (candidate) return candidate;
  }
  return null;
}

export function buildPolylineSegmentRibbons(Cesium: any, points: number[][], groundH: number, widthM: number) {
  if (points.length < 2) return [];
  const half = widthM / 2;
  const ribbons = [];
  for (let i = 0; i < points.length - 1; i++) {
    const start = points[i] as ProfilePoint;
    const end = points[i + 1] as ProfilePoint;
    const normal = profileNormal(start, end);
    if (!normal) continue;
    const a1 = offsetLngLat(start, normal.nx, normal.ny, half);
    const a2 = offsetLngLat(end, normal.nx, normal.ny, half);
    const b2 = offsetLngLat(end, normal.nx, normal.ny, -half);
    const b1 = offsetLngLat(start, normal.nx, normal.ny, -half);
    ribbons.push([a1, a2, b2, b1].map((p) => Cesium.Cartesian3.fromDegrees(p[0], p[1], groundH + p[2])));
  }
  return ribbons;
}

export function buildSectionVerticalRibbon(Cesium: any, points: number[][], groundH: number, widthM: number) {
  if (points.length < 3) return null;
  const normal = profileDirectionNormal(points.slice(1));
  if (!normal) return null;
  const p0 = points[0] as ProfilePoint;
  const p1 = points[1] as ProfilePoint;
  const half = widthM / 2;
  const a1 = offsetLngLat(p0, normal.nx, normal.ny, half);
  const a2 = offsetLngLat(p1, normal.nx, normal.ny, half);
  const b2 = offsetLngLat(p1, normal.nx, normal.ny, -half);
  const b1 = offsetLngLat(p0, normal.nx, normal.ny, -half);
  return [a1, a2, b2, b1].map((p) => Cesium.Cartesian3.fromDegrees(p[0], p[1], groundH + p[2]));
}

function profileNormal(start: ProfilePoint, end: ProfilePoint) {
  const delta = toLocalMeters(start, end);
  const len = Math.hypot(delta.x, delta.y);
  if (!isFinite(len) || len < 0.05) return null;
  return { nx: -delta.y / len, ny: delta.x / len };
}

export function buildProfileWallRibbon(Cesium: any, points: number[][], groundH: number, widthM: number) {
  const p0 = points[0] as ProfilePoint;
  const p2 = (points[2] ?? points[1]) as ProfilePoint;
  const normal = profileNormal(p0, p2);
  if (!normal) return null;

  const a = offsetLngLat(p0, normal.nx, normal.ny, widthM / 2);
  const b = offsetLngLat(p2, normal.nx, normal.ny, widthM / 2);
  return {
    positions: Cesium.Cartesian3.fromDegreesArray([a[0], a[1], b[0], b[1]]),
    minimumHeights: [groundH + (p0[2] ?? 0), groundH + (p2[2] ?? 10)],
    maximumHeights: [groundH + 10, groundH + (p2[2] ?? 10)],
  };
}

export function buildSlopedRibbon(Cesium: any, points: number[][], groundH: number, widthM: number) {
  const start = (points[2] ?? points[1]) as ProfilePoint;
  const end = points[points.length - 1] as ProfilePoint;
  const normal = profileNormal(start, end);
  if (!normal) return null;

  const half = widthM / 2;
  const a1 = offsetLngLat(start, normal.nx, normal.ny, half);
  const a2 = offsetLngLat(start, normal.nx, normal.ny, -half);
  const b2 = offsetLngLat(end, normal.nx, normal.ny, -half);
  const b1 = offsetLngLat(end, normal.nx, normal.ny, half);
  return [a1, b1, b2, a2].map((p) => Cesium.Cartesian3.fromDegrees(p[0], p[1], groundH + p[2]));
}

/**
 * Ring 모든 corner의 terrain 고도 평균 (Step 3 — datum 가중평균 시각).
 *
 * 모든 corner의 terrain.getHeight()를 sample해서 평균. parcel이 경사졌어도
 * envelope 베이스가 단일 평면 위에서 균일하게 솟도록 단일 z 값으로 통일.
 *
 * 실패한 sample은 평균에서 제외. 모두 실패면 0.
 */
export function ringTerrainMean(viewer: any, Cesium: any, corners: number[][]): number {
  if (!corners || corners.length === 0) return 0;
  let sum = 0;
  let n = 0;
  for (const c of corners) {
    if (!c || c.length < 2) continue;
    try {
      const carto = Cesium.Cartographic.fromDegrees(c[0], c[1]);
      const h = viewer.scene.globe.getHeight(carto);
      if (typeof h === 'number' && isFinite(h)) {
        sum += h;
        n += 1;
      }
    } catch {
      // sample 실패한 corner skip
    }
  }
  return n > 0 ? sum / n : 0;
}
