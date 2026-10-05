import type React from 'react';
import { requiredValue } from '../required-value';
import { polygonRing } from '../site-map-geometry';

export const getCesium = (): any => (window as any).Cesium;
export const MASS_PREFIX = 'design-mass-';
export const SETBACK_PREFIX = 'design-setback-';
export const CONSTRAINTS_PREFIX = 'design-constraints-';

export const hiddenBuildingTiles = new WeakMap<object, Map<any, boolean>>();

export function hideVworldBuildingTiles(viewer: any, Cesium: any) {
  const primitives = viewer?.scene?.primitives;
  if (!primitives) return;
  for (let i = 0; i < primitives.length; i++) {
    const p = primitives.get(i);
    const isTileset = (Cesium?.Cesium3DTileset && p instanceof Cesium.Cesium3DTileset)
      || (p && typeof p === 'object' && '_url' in p && '_root' in p);
    if (isTileset) {
      let previous = hiddenBuildingTiles.get(viewer);
      if (!previous) { previous = new Map(); hiddenBuildingTiles.set(viewer, previous); }
      if (!previous.has(p)) previous.set(p, p.show);
      p.show = false;
    }
  }
}

/** Fly camera to fit a GeoJSON geometry bounding box */
export function flyToGeometryBbox(viewerRef: React.RefObject<any>, geometry: any) {
  const Cesium = getCesium();
  const viewer = viewerRef.current;
  if (!Cesium || !viewer) return;

  const ring = geometry.type === 'Feature'
    ? polygonRing(geometry.geometry)
    : polygonRing(geometry);
  if (!ring || ring.length < 3) return;

  // Calculate bounding box
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
  for (const [lng, lat] of ring) {
    if (requiredValue(lng) < west) west = requiredValue(lng);
    if (requiredValue(lng) > east) east = requiredValue(lng);
    if (requiredValue(lat) < south) south = requiredValue(lat);
    if (requiredValue(lat) > north) north = requiredValue(lat);
  }

  // 2026-05-11 v4 — Cesium 공식 권장: flyToBoundingSphere + HeadingPitchRange.
  // BoundingSphere가 parcel bbox 자동 fit + range는 sphere.radius 비율로 결정.
  // 우주/검정 방지 — Cesium이 자동으로 적절한 거리 계산.
  // https://cesium.com/learn/cesiumjs/ref-doc/Camera.html#flyToBoundingSphere
  const rect = Cesium.Rectangle.fromDegrees(west, south, east, north);
  const sphere = Cesium.BoundingSphere.fromRectangle3D(rect, Cesium.Ellipsoid.WGS84);

  viewer.camera.flyToBoundingSphere(sphere, {
    offset: new Cesium.HeadingPitchRange(
      Cesium.Math.toRadians(80),          // 정북 수직벽과 사선 리본이 겹치지 않는 검토용 기본 각도
      Cesium.Math.toRadians(-32),         // 사선 볼륨과 대지 평면이 함께 읽히는 기본 투시
      Math.max(125, sphere.radius * 6),   // 작은 필지도 읽히되 주변 도로/인접대지 맥락을 유지
    ),
    duration: 1.5,
  });
}

