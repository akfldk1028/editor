import { requiredValue } from '../required-value';
/**
 * §119 datum 평면 시각화 (Cesium 3D).
 *
 * "지도에도 대지 레벨이 떠야 한다" 의도 반영. 사용자에게 §119 H=0 절대 표고를
 * 시각적으로 보여주는 보조 entity.
 *
 * **Phase 2D-3 LOCKED SPEC 보호**: envelope/setback 시각은 terrainH 통일 그대로.
 * 이 모듈은 추가 시각만 함. 기존 entity 변경 없음.
 *
 * Render:
 *   1. parcel ring 위 datum_m 높이의 반투명 노란 평면 (지면에서 떠 있음)
 *   2. parcel centroid에 텍스트 라벨 "H₀ = 38.42m"
 *
 * datum_m이 0/null/미계산이면 렌더 X (LOCKED SPEC fallback 동일).
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

export const DATUM_PLANE_PREFIX = 'design-datum-plane-';

export interface DatumPlaneColors {
  fill: string;     // 평면 채색 (반투명)
  outline: string;  // 외곽선
  label: string;    // 라벨 텍스트 색
}

export interface DatumPlaneOptions {
  colors?: DatumPlaneColors;
  idSuffix?: string;
  labelText?: string;
}

export interface DatumMarker {
  id: string;
  label: string;
  lng: number;
  lat: number;
  elevationM: number;
  color: string;
  labelOffset?: [number, number];
}

export const DEFAULT_DATUM_COLORS: DatumPlaneColors = {
  fill: '#facc15',     // 노랑 (datum 표고)
  outline: '#eab308',  // 진노랑
  label: '#fde047',    // 라벨 노랑
};

/**
 * Cesium viewer에 §119 datum 평면 + 라벨 렌더링.
 *
 * @param viewer Cesium viewer 인스턴스
 * @param Cesium global Cesium namespace
 * @param datum_m §119 H=0 절대 표고 (m, EGM2008). 0/null이면 렌더 X.
 * @param parcelRing parcel 외곽 polygon ring [[lng, lat], ...]
 * @param colors 색상 (선택)
 * @returns 추가된 entity id 배열 (정리용)
 */
export function renderDatumPlane(
  viewer: any,
  Cesium: any,
  datum_m: number | null | undefined,
  parcelRing: number[][] | null | undefined,
  options: DatumPlaneColors | DatumPlaneOptions = DEFAULT_DATUM_COLORS,
): string[] {
  if (!viewer || !Cesium) return [];
  if (datum_m == null || !isFinite(datum_m) || datum_m === 0) return [];
  if (!parcelRing || parcelRing.length < 3) return [];

  const opts: DatumPlaneOptions = 'fill' in options ? { colors: options } : options;
  const colors = opts.colors ?? DEFAULT_DATUM_COLORS;
  const suffix = opts.idSuffix ? `-${opts.idSuffix}` : '';
  const labelText = opts.labelText ?? `§119 H₀ = ${datum_m.toFixed(2)}m`;
  const fillC = Cesium.Color.fromCssColorString(colors.fill);
  const outlineC = Cesium.Color.fromCssColorString(colors.outline);
  const labelC = Cesium.Color.fromCssColorString(colors.label);
  const addedIds: string[] = [];

  // (1) datum 평면 — parcel ring을 terrain 표면에 클램프 (지형과 시각 일관성).
  // 정확한 §119 datum_m 값은 라벨에 표시. Cesium globe terrain DEM과 Open-Meteo 90m DEM이
  // 다른 출처라 두 값 수 m 차이 있음 (메모리 박제 known issue) — 평면은 시각용, 라벨이 정답.
  const flat: number[] = [];
  for (const [lng, lat] of parcelRing) flat.push(requiredValue(lng), requiredValue(lat));

  // Step 5 (2026-05-11) — datum 평면을 NGII §119 절대 z에 배치 (clamp 제거).
  // 매스/envelope과 동일 절대값 평면 → 시각 통일.
  const planeId = `${DATUM_PLANE_PREFIX}plane${suffix}`;
  viewer.entities.add({
    id: planeId,
    polygon: {
      hierarchy: Cesium.Cartesian3.fromDegreesArray(flat),
      height: datum_m,                 // §119 절대 z (envelope/매스와 동일)
      material: fillC.withAlpha(0.45),
      outline: true,
      outlineColor: outlineC,
    },
  });
  addedIds.push(planeId);

  // outline polyline (절대 z, datum_m)
  const flatWithH: number[] = [];
  for (const [lng, lat] of parcelRing) flatWithH.push(requiredValue(lng), requiredValue(lat), datum_m);
  const outlineId = `${DATUM_PLANE_PREFIX}outline${suffix}`;
  viewer.entities.add({
    id: outlineId,
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArrayHeights(flatWithH),
      width: 4,
      material: outlineC,
    },
  });
  addedIds.push(outlineId);

  // (2) parcel centroid 위 라벨 "H₀ = 38.42m" — datum_m + 약간 위 띄움
  let cx = 0;
  let cy = 0;
  for (const [lng, lat] of parcelRing) {
    cx += requiredValue(lng);
    cy += requiredValue(lat);
  }
  cx /= parcelRing.length;
  cy /= parcelRing.length;

  const labelId = `${DATUM_PLANE_PREFIX}label${suffix}`;
  viewer.entities.add({
    id: labelId,
    // 라벨은 terrain 표면 위로 클램프 (parcel 평면 위에 떠 있음)
    position: Cesium.Cartesian3.fromDegrees(cx, cy),
    label: {
      text: labelText,
      heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      font: '700 18px ui-monospace, SFMono-Regular, Menlo, monospace',
      fillColor: labelC,
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 4,
      style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
      pixelOffset: new Cesium.Cartesian2(0, -12),
      backgroundColor: Cesium.Color.BLACK.withAlpha(0.6),
      backgroundPadding: new Cesium.Cartesian2(8, 4),
      showBackground: true,
      // 멀리서도 보이게 거리 기반 스케일
      scaleByDistance: new Cesium.NearFarScalar(50, 1.2, 5000, 0.7),
      // disableDepthTestDistance — 평면 뒤에 가려지지 않도록
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });
  addedIds.push(labelId);

  return addedIds;
}

/**
 * Plan PNG와 같은 법규 기준점 표시.
 *
 * 전체 표고 격자나 넓은 평면 대신, 산정 근거의 대표 위치에만 점/라벨을 찍는다.
 * - 대지 §119: parcel boundary weighted samples
 * - 도로레벨: road centerline/samples
 * - 인접대지레벨: north-side neighbor samples
 * - §86 평균: 대지 기준점과 인접대지 기준점 사이
 */
export function renderDatumMarkers(
  viewer: any,
  Cesium: any,
  markers: DatumMarker[],
): string[] {
  if (!viewer || !Cesium || !markers.length) return [];
  const addedIds: string[] = [];

  for (const marker of markers) {
    if (
      !isFinite(marker.lng)
      || !isFinite(marker.lat)
      || !isFinite(marker.elevationM)
      || marker.elevationM === 0
    ) {
      continue;
    }

    const baseId = `${DATUM_PLANE_PREFIX}marker-${marker.id}`;
    const color = Cesium.Color.fromCssColorString(marker.color);
    const params = new URLSearchParams(window.location.search);
    const showStems = params.get('datumStems') === '1' || params.get('layers') === 'all';
    const showLabels = params.get('datumLabels') !== '0' && params.get('labels') !== '0';
    const labelLiftM = 4;
    const pointHeightM = marker.elevationM + 0.8;
    const labelHeightM = marker.elevationM + labelLiftM;

    viewer.entities.add({
      id: `${baseId}-point`,
      position: Cesium.Cartesian3.fromDegrees(marker.lng, marker.lat, pointHeightM),
      point: {
        pixelSize: 11,
        color,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    addedIds.push(`${baseId}-point`);

    if (showStems) {
      viewer.entities.add({
        id: `${baseId}-stem`,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArrayHeights([
            marker.lng, marker.lat, marker.elevationM,
            marker.lng, marker.lat, labelHeightM,
          ]),
          width: 2,
          material: color.withAlpha(0.65),
        },
      });
      addedIds.push(`${baseId}-stem`);
    }

    if (showLabels) {
      viewer.entities.add({
        id: `${baseId}-label`,
        position: Cesium.Cartesian3.fromDegrees(marker.lng, marker.lat, labelHeightM),
        label: {
          text: `${marker.label}\n${marker.elevationM.toFixed(2)}m`,
          font: '700 12px Pretendard, system-ui, sans-serif',
          fillColor: Cesium.Color.fromCssColorString('#111827'),
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 4,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
          pixelOffset: new Cesium.Cartesian2(marker.labelOffset?.[0] ?? 0, marker.labelOffset?.[1] ?? -14),
          backgroundColor: Cesium.Color.WHITE.withAlpha(0.74),
          backgroundPadding: new Cesium.Cartesian2(8, 5),
          showBackground: true,
          scaleByDistance: new Cesium.NearFarScalar(50, 1.0, 5000, 0.72),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
      addedIds.push(`${baseId}-label`);
    }
  }

  return addedIds;
}

/** Viewer에서 기존 datum entity 제거 (re-render 전 정리용). */
export function clearDatumPlane(viewer: any): void {
  if (!viewer) return;
  const toRemove: any[] = [];
  for (const e of viewer.entities.values) {
    if (typeof e.id === 'string' && e.id.startsWith(DATUM_PLANE_PREFIX)) {
      toRemove.push(e);
    }
  }
  for (const e of toRemove) viewer.entities.remove(e);
}
