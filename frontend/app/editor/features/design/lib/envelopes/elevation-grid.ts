/**
 * 주변 표고 격자 시각화 (Cesium 3D).
 *
 * "주변 몇m 표고는 다 나오게 해야지" 사용자 의도 반영.
 * backend `/land/elevation-grid/` 응답을 점 + 라벨로 표시.
 *
 * - 각 격자 점에 작은 노란 점 (point) + 높이 라벨 ("38.5m")
 * - 평면 위에 떠있도록 disableDepthTestDistance=infinity (다른 entity 가려도 보임)
 * - 모든 entity는 ELEVATION_GRID_PREFIX로 mark → 정리 단순
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

export interface ElevationGridPoint { lng: number; lat: number; elev_m: number }

export const ELEVATION_GRID_PREFIX = 'design-elev-grid-';

export function renderElevationGrid(
  viewer: any,
  Cesium: any,
  points: ElevationGridPoint[] | null | undefined,
  centerColor = '#facc15',
  pointColor = '#94a3b8',
): string[] {
  if (!viewer || !Cesium || !points || points.length === 0) return [];

  const ptColor = Cesium.Color.fromCssColorString(pointColor);
  const ctrColor = Cesium.Color.fromCssColorString(centerColor);
  const addedIds: string[] = [];

  // 격자 정중앙 idx 추출 (n×n에서 (n²-1)/2)
  const centerIdx = Math.floor((points.length - 1) / 2);

  for (let i = 0; i < points.length; i++) {
    const p = points[i]!;
    const isCenter = i === centerIdx;

    // 점
    const pointId = `${ELEVATION_GRID_PREFIX}p-${i}`;
    viewer.entities.add({
      id: pointId,
      position: Cesium.Cartesian3.fromDegrees(p.lng, p.lat, p.elev_m),
      point: {
        pixelSize: isCenter ? 7 : 4,
        color: isCenter ? ctrColor : ptColor,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 1,
        heightReference: Cesium.HeightReference.NONE,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    addedIds.push(pointId);

    // 라벨 — 모든 점에 표고 표시 (사용자 "주변 몇m 표고 다 나오게" 요청)
    const labelId = `${ELEVATION_GRID_PREFIX}l-${i}`;
    viewer.entities.add({
      id: labelId,
      position: Cesium.Cartesian3.fromDegrees(p.lng, p.lat, p.elev_m),
      label: {
        text: `${p.elev_m.toFixed(1)}m`,
        font: isCenter
          ? '700 13px ui-monospace, SFMono-Regular, Menlo, monospace'
          : '500 11px ui-monospace, SFMono-Regular, Menlo, monospace',
        fillColor: isCenter ? ctrColor : Cesium.Color.fromCssColorString('#e2e8f0'),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
        pixelOffset: new Cesium.Cartesian2(0, -6),
        scaleByDistance: new Cesium.NearFarScalar(50, 1.0, 5000, 0.5),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        // 카메라가 멀어지면 라벨 숨김 (격자 25개라 줌아웃 시 혼잡)
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 2000),
      },
    });
    addedIds.push(labelId);
  }

  return addedIds;
}

/** Viewer에서 격자 entity 제거 (re-render 전 정리). */
export function clearElevationGrid(viewer: any): void {
  if (!viewer) return;
  const toRemove: any[] = [];
  for (const e of viewer.entities.values) {
    if (typeof e.id === 'string' && e.id.startsWith(ELEVATION_GRID_PREFIX)) {
      toRemove.push(e);
    }
  }
  for (const e of toRemove) viewer.entities.remove(e);
}
