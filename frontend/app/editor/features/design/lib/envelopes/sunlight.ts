import { requiredValue } from '../required-value';
/**
 * 정북 일조사선 envelope Cesium renderer (건축법 §61①, 시행령 §86①).
 *
 * ⚠️ LOCKED SPEC — DO NOT MODIFY without reading
 *     memory/arr/session14/envelope-locked-spec.md
 * session 14 (2026-04-21) 사용자 검증 결과. 과거 12회+ 반복 실패 후 확정.
 *
 * Contract (backend `land/services/envelopes/sunlight.py` 와 1:1):
 *   envelope = {
 *     walls:            [{positions, min_heights, max_heights, kind="north_vertical"}]
 *     slanted_polygons: [{corners: [[lng, lat, h]...], kind="slope"}]
 *     ...
 *   }
 *
 * 렌더 요소 (img_5 프로필과 일치):
 *   (1) 북쪽 수직벽 : 바닥 → H=10m (직선→사선 올라가는 면)
 *   (2) 경사 지붕   : H=10m → 50m (법규 사선)
 *
 * 렌더 안 하는 것 (사용자 img_18 피드백):
 *   - 사선에서 바닥으로 떨어지는 측면 벽
 *   - plateau 별도 polygon (경사 지붕이 H=10m에서 시작하므로 불필요)
 *   - daylight_diagonal_envelope (보라 채광사선, 정북일조와 시각 충돌)
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

import type { SunlightEnvelope } from '../../../land-map/lib/types';
import {
  buildConnectedProfileSurface,
  buildPolylineSegmentRibbons,
  buildPrimaryWallLine,
  buildSectionVerticalRibbon,
  capProfilePoints,
  layerHeight,
  layerRing,
  ringTerrainMean,
  simplifyClosedRing,
  type WallSegment,
} from './sunlight-geometry';
import {
  renderParcelShapedSunlightSurface,
  renderSunlightProfileOverlays,
  SUNLIGHT_ENVELOPE_PREFIX,
} from './sunlight-overlays';

export { SUNLIGHT_ENVELOPE_PREFIX } from './sunlight-overlays';

export interface SunlightColors {
  wall: string;  // 북쪽 수직벽 (진홍 권장)
  slope: string; // 경사 지붕 (핑크 권장)
}

export const DEFAULT_SUNLIGHT_COLORS: SunlightColors = {
  wall: '#dc2626',
  slope: '#ec4899',
};

/**
 * Cesium viewer에 sunlight envelope 렌더링.
 *
 * @param viewer  Cesium viewer 인스턴스
 * @param Cesium  global Cesium namespace
 * @param envelope  backend response의 sunlight_envelope 객체
 * @param colors  렌더 색상 (선택)
 *
 * @returns 추가된 entity id 배열 (정리용)
 */
export function renderSunlightEnvelope(
  viewer: any,
  Cesium: any,
  envelope: SunlightEnvelope | null | undefined,
  colors: SunlightColors = DEFAULT_SUNLIGHT_COLORS,
): string[] {
  if (!envelope) return [];

  const wallC = Cesium.Color.fromCssColorString(colors.wall);
  const slopeC = Cesium.Color.fromCssColorString(colors.slope);
  const addedIds: string[] = [];

  // Step 5 (2026-05-11) — envelope base z = NGII §119 datum 절대값 우선.
  // backend `envelope.datum_elevation_m` (NGII 5m EGM2008) 가 있으면 그걸 사용 →
  // 매스/envelope/datum 평면 모두 단일 절대 평면 위에서 솟음 (시각 통일).
  // fallback: ring corner terrain 평균 (Step 3, NGII datum 없을 때).
  const corners = envelope.slanted_polygons?.[0]?.corners ?? [];
  const datumZ = envelope.datum_elevation_m;
  const groundH = (datumZ != null && isFinite(datumZ) && datumZ !== 0)
    ? datumZ
    : ringTerrainMean(viewer, Cesium, corners);

  // (1) 북쪽 수직벽 (H=0→10m).
  // 기본 clean view에서도 북측 수직 시작면은 보여준다. 숨김은 `?walls=0`.
  const params = new URLSearchParams(window.location.search);
  const showWalls = params.get('walls') !== '0';
  let wallTopLine: number[][] = [];
  if (showWalls && Array.isArray(envelope.walls)) {
    const wallSegments: WallSegment[] = [];
    const wallStep = Math.max(1, Math.ceil(envelope.walls.length / 120));
    for (let i = 0; i < envelope.walls.length; i += wallStep) {
      const wall = envelope.walls[i];
      if (!wall?.positions || wall.positions.length < 2) continue;
      const c1 = requiredValue(wall.positions[0]);
      const c2 = requiredValue(wall.positions[1]);
      const min1 = wall.min_heights?.[0] ?? 0;
      const min2 = wall.min_heights?.[1] ?? min1;
      const max1 = wall.max_heights?.[0] ?? 10;
      const max2 = wall.max_heights?.[1] ?? max1;
      wallSegments.push({
        a: [c1[0], c1[1], groundH + max1],
        b: [c2[0], c2[1], groundH + max2],
        minA: groundH + min1,
        minB: groundH + min2,
      });
    }
    const primaryWall = buildPrimaryWallLine(wallSegments, envelope.profile_polylines?.[0]?.points);
    const wallPositions = primaryWall.map((p) => [p[0], p[1]]);
    const minHeights = primaryWall.map((p) => p[3]);
    const maxHeights = primaryWall.map((p) => p[2]);
    const topLine = primaryWall.map((p) => [p[0], p[1], p[2]]);
    const baseLine = primaryWall.map((p) => [p[0], p[1], p[3]]);
    const showWallFill = params.get('wallFill') !== '0' || params.get('layers') === 'all';
    if (showWallFill && wallPositions.length >= 2) {
      viewer.entities.add({
        id: `${SUNLIGHT_ENVELOPE_PREFIX}wall-continuous`,
        wall: {
          positions: Cesium.Cartesian3.fromDegreesArray(wallPositions.flat()),
          minimumHeights: minHeights,
          maximumHeights: maxHeights,
          material: wallC.withAlpha(0.13),
          outline: false,
        },
      });
      addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}wall-continuous`);
    }
    if (topLine.length >= 2) {
      viewer.entities.add({
        id: `${SUNLIGHT_ENVELOPE_PREFIX}wall-top-line`,
        polyline: {
          positions: topLine.map((p) => Cesium.Cartesian3.fromDegrees(p[0], p[1], p[2])),
          width: 2,
          material: wallC.withAlpha(0.72),
        },
      });
      addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}wall-top-line`);
      wallTopLine = topLine;
    }
    if (baseLine.length >= 2) {
      viewer.entities.add({
        id: `${SUNLIGHT_ENVELOPE_PREFIX}wall-base-line`,
        polyline: {
          positions: baseLine.map((p) => Cesium.Cartesian3.fromDegrees(p[0], p[1], p[2])),
          width: 1,
          material: wallC.withAlpha(0.28),
        },
      });
      addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}wall-base-line`);
    }
    const showWallEndEdges = params.get('wallEdges') === '1' || params.get('layers') === 'all';
    if (showWallEndEdges && topLine.length >= 2 && baseLine.length >= 2) {
      for (const idx of [0, topLine.length - 1]) {
        const base = baseLine[idx];
        const top = topLine[idx];
        if (!base || !top) continue;
        viewer.entities.add({
          id: `${SUNLIGHT_ENVELOPE_PREFIX}wall-vertical-edge-${idx}`,
          polyline: {
            positions: [
              Cesium.Cartesian3.fromDegrees(base[0], base[1], base[2]),
              Cesium.Cartesian3.fromDegrees(top[0], top[1], top[2]),
            ],
            width: 2,
            material: wallC.withAlpha(0.74),
          },
        });
        addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}wall-vertical-edge-${idx}`);
      }
    }
  }

  // Step 13 (2026-05-11) — plateau footprint 분리. 사용자 docs/img_44 요구:
  // plateau는 박스 윗면 전체가 아니라 정북 boundary ~ PLATEAU_END_M(5m) 띠만.
  // backend가 envelope.plateau_polygon으로 정확한 footprint 제공 → 그걸 사용.
  // backend가 못 제공하면 (정북 edge 없음 등) plateau 생략.
  // plateau polygon은 단면 프로파일에 포함해서 표현한다. 별도 채움면은
  // VWorld 지적/도로/레벨 마커를 가려 검토성이 떨어진다.

  // (2) 사선면은 기본 clean view에서 끈다.
  // 허용 볼륨 계산상 H<=10m 구간은 수평 plateau가 생길 수 있지만, VWorld에서
  // 넓은 면으로 보이면 사용자가 "정북일조는 수직벽→사선"이라는 단면 규칙을
  // 읽기 어렵다. 법규 debug가 필요할 때만 `?surface=1/detail`로 켠다.
  // backend 원본은 계산용 상세 geometry라 500+ corner가 될 수 있고,
  // 그대로 그리면 VWorld 위에서 contour/fence처럼 보여 사용자가 법규면을 읽기 어렵다.
  // 정밀 geometry 확인은 `?surface=detail` 또는 `?layers=all`로 켠다.
  const surfaceMode = params.get('surface');
  const showDetailedSurface = surfaceMode === 'detail' || params.get('layers') === 'all';
  const showSurface = surfaceMode !== '0';
  const showFootprintSurface = surfaceMode === 'footprint' || params.get('layers') === 'all';
  const cleanLayers = Array.isArray(envelope.envelope_layers)
    ? envelope.envelope_layers
      .map((layer) => ({ ring: layerRing(layer), h: layerHeight(layer) }))
      .filter((layer): layer is { ring: number[][]; h: number } => Boolean(layer.ring) && layer.h != null)
      .sort((a, b) => a.h - b.h)
    : [];
  if (showSurface && !showDetailedSurface && cleanLayers.length >= 2) {
    const base = requiredValue(cleanLayers[0]);
    const top = requiredValue(cleanLayers[cleanLayers.length - 1]);
    if (surfaceMode === 'footprint') {
      const fullSurfaceIds = renderParcelShapedSunlightSurface(viewer, Cesium, envelope, groundH, slopeC);
      addedIds.push(...fullSurfaceIds);
    }

    const showConnectedParcelSurface = surfaceMode !== 'section' || params.get('layers') === 'all';
    const connectedProfile = showConnectedParcelSurface
      ? buildConnectedProfileSurface(envelope.profile_polylines?.[0]?.points, wallTopLine, groundH, top.h)
      : null;
    if (connectedProfile) {
      const bands = [
        { id: 'plateau', from: connectedProfile.wallTopLine, to: connectedProfile.plateauEndLine, alpha: 0.11 },
        { id: 'slope', from: connectedProfile.plateauEndLine, to: connectedProfile.slopeTopLine, alpha: 0.14 },
      ];
      for (const band of bands) {
        if (band.from.length < 2 || band.to.length < 2) continue;
        for (let i = 0; i < Math.min(band.from.length, band.to.length) - 1; i++) {
          const quad = [
            band.from[i],
            band.from[i + 1],
            band.to[i + 1],
            band.to[i],
          ];
          viewer.entities.add({
            id: `${SUNLIGHT_ENVELOPE_PREFIX}profile-connected-${band.id}-surface-${i}`,
            polygon: {
              hierarchy: Cesium.Cartesian3.fromDegreesArrayHeights(quad.flat()),
              perPositionHeight: true,
              material: slopeC.withAlpha(band.alpha),
              outline: false,
            },
          });
          addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}profile-connected-${band.id}-surface-${i}`);
        }
      }

      const connectedLines = [
        { id: 'wall-top-line', line: connectedProfile.wallTopLine, width: 2.2, alpha: 0.82 },
        { id: 'plateau-kink-line', line: connectedProfile.plateauEndLine, width: 2.8, alpha: 0.86 },
        { id: 'slope-top-line', line: connectedProfile.slopeTopLine, width: 1.6, alpha: 0.64 },
      ];
      for (const item of connectedLines) {
        if (item.line.length < 2) continue;
        viewer.entities.add({
          id: `${SUNLIGHT_ENVELOPE_PREFIX}profile-connected-${item.id}`,
          polyline: {
            positions: item.line.map((p) => Cesium.Cartesian3.fromDegrees(p[0], p[1], p[2])),
            width: item.width,
            material: slopeC.withAlpha(item.alpha),
          },
        });
        addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}profile-connected-${item.id}`);
      }
    }

    const showSectionProfile = params.get('profile') === 'section'
      || params.get('profile') === '1'
      || params.get('profile') === 'detail'
      || params.get('layers') === 'all';
    if (showSectionProfile && Array.isArray(envelope.profile_polylines)) {
      const profile = envelope.profile_polylines[0];
      const points = capProfilePoints(profile?.points, top.h);
      if (points && points.length >= 3) {
        const ribbonWidthM = Math.max(5, Math.min(14, Number(params.get('profileWidth') ?? 8) || 8));
        const verticalRibbon = buildSectionVerticalRibbon(Cesium, points, groundH, ribbonWidthM);
        if (verticalRibbon) {
          viewer.entities.add({
            id: `${SUNLIGHT_ENVELOPE_PREFIX}section-vertical-10m-surface`,
            polygon: {
              hierarchy: new Cesium.PolygonHierarchy(verticalRibbon),
              perPositionHeight: true,
              material: wallC.withAlpha(0.20),
              outline: false,
            },
          });
          addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}section-vertical-10m-surface`);
        }

        const upperRibbon = buildPolylineSegmentRibbons(Cesium, points.slice(1), groundH, ribbonWidthM);
        upperRibbon.forEach((segmentRibbon, segmentIndex) => {
          viewer.entities.add({
            id: `${SUNLIGHT_ENVELOPE_PREFIX}section-slope-from-10m-surface-${segmentIndex}`,
            polygon: {
              hierarchy: new Cesium.PolygonHierarchy(segmentRibbon),
              perPositionHeight: true,
              material: slopeC.withAlpha(0.16),
              outline: false,
            },
          });
          addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}section-slope-from-10m-surface-${segmentIndex}`);
        });

        const vertical = [points[0], points[1]].map((p) =>
          Cesium.Cartesian3.fromDegrees(requiredValue(requiredValue(p)[0]), requiredValue(requiredValue(p)[1]), groundH + requiredValue(requiredValue(p)[2])),
        );
        viewer.entities.add({
          id: `${SUNLIGHT_ENVELOPE_PREFIX}section-vertical-10m-line`,
          polyline: {
            positions: vertical,
            width: 3,
            material: wallC.withAlpha(0.9),
          },
        });
        addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}section-vertical-10m-line`);

        const slopeStartIdx = Math.min(2, points.length - 1);
        const upper = points.slice(1).map((p) =>
          Cesium.Cartesian3.fromDegrees(p[0], p[1], groundH + requiredValue(p[2])),
        );
        viewer.entities.add({
          id: `${SUNLIGHT_ENVELOPE_PREFIX}section-slope-from-10m-line`,
          polyline: {
            positions: upper,
            width: 3,
            material: slopeC.withAlpha(0.86),
          },
        });
        addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}section-slope-from-10m-line`);

        const tenM = requiredValue(points[slopeStartIdx]);
        viewer.entities.add({
          id: `${SUNLIGHT_ENVELOPE_PREFIX}section-10m-label`,
          position: Cesium.Cartesian3.fromDegrees(requiredValue(tenM[0]), requiredValue(tenM[1]), groundH + requiredValue(tenM[2]) + 1.2),
          label: {
            text: '10m',
            font: '700 12px ui-monospace, SFMono-Regular, Menlo, monospace',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            backgroundColor: Cesium.Color.BLACK.withAlpha(0.38),
            backgroundPadding: new Cesium.Cartesian2(6, 3),
            showBackground: true,
            pixelOffset: new Cesium.Cartesian2(18, -14),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
        addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}section-10m-label`);
      }
    }

    if (showFootprintSurface) {
      const mainPlane = [
        [requiredValue(requiredValue(top.ring[3])[0]), requiredValue(requiredValue(top.ring[3])[1]), groundH + top.h],
        [requiredValue(requiredValue(top.ring[2])[0]), requiredValue(requiredValue(top.ring[2])[1]), groundH + top.h],
        [requiredValue(requiredValue(base.ring[2])[0]), requiredValue(requiredValue(base.ring[2])[1]), groundH + base.h],
        [requiredValue(requiredValue(base.ring[3])[0]), requiredValue(requiredValue(base.ring[3])[1]), groundH + base.h],
      ];
      viewer.entities.add({
        id: `${SUNLIGHT_ENVELOPE_PREFIX}roof-main-surface`,
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArrayHeights(mainPlane.flat()),
          perPositionHeight: true,
          material: slopeC.withAlpha(0.18),
          outline: false,
        },
      });
      addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}roof-main-surface`);

      const mainOutline = [...mainPlane, mainPlane[0]];
      viewer.entities.add({
        id: `${SUNLIGHT_ENVELOPE_PREFIX}roof-main-outline`,
        polyline: {
          positions: mainOutline.map((p) => Cesium.Cartesian3.fromDegrees(requiredValue(requiredValue(p)[0]), requiredValue(requiredValue(p)[1]), requiredValue(requiredValue(p)[2]))),
          width: 4,
          material: slopeC.withAlpha(0.78),
        },
      });
      addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}roof-main-outline`);
    }

    const showLayerOutlines = params.get('mesh') === '1' || params.get('layers') === 'all';
    if (showLayerOutlines) for (let i = 1; i < cleanLayers.length; i++) {
      const curr = requiredValue(cleanLayers[i]);
      const layerOutline = [...curr.ring, requiredValue(curr.ring[0])].map((p) =>
        Cesium.Cartesian3.fromDegrees(requiredValue(p[0]), requiredValue(p[1]), groundH + curr.h),
      );
      viewer.entities.add({
        id: `${SUNLIGHT_ENVELOPE_PREFIX}roof-layer-outline-${i}`,
        polyline: {
          positions: layerOutline,
          width: 3,
          material: slopeC.withAlpha(0.72),
        },
      });
      addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}roof-layer-outline-${i}`);
    }

    if (params.get('slopeLabel') === '1' || params.get('labels') === 'all') {
      const labelPoint = requiredValue(top.ring[3]) ?? requiredValue(top.ring[0]);
      viewer.entities.add({
        id: `${SUNLIGHT_ENVELOPE_PREFIX}surface-label`,
        position: Cesium.Cartesian3.fromDegrees(requiredValue(labelPoint[0]), requiredValue(labelPoint[1]), groundH + top.h + 3),
        label: {
          text: `정북일조 사선\n§86 / ${envelope.slope ?? 2}:1`,
          font: '700 13px Pretendard, system-ui, sans-serif',
          fillColor: Cesium.Color.fromCssColorString('#111827'),
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 4,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          backgroundColor: Cesium.Color.WHITE.withAlpha(0.72),
          backgroundPadding: new Cesium.Cartesian2(8, 5),
          showBackground: true,
          pixelOffset: new Cesium.Cartesian2(38, -24),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
      addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}surface-label`);
    }
  } else
  if (showSurface && Array.isArray(envelope.slanted_polygons)) {
    for (let pi = 0; pi < envelope.slanted_polygons.length; pi++) {
      const poly = requiredValue(envelope.slanted_polygons[pi]);
      const sourceCorners = poly.corners as number[][];
      const corners = showDetailedSurface ? sourceCorners : simplifyClosedRing(sourceCorners, 48);
      if (!corners || corners.length < 3) continue;

      const id = `${SUNLIGHT_ENVELOPE_PREFIX}roof-${pi}`;
      const roofFlat: number[] = [];
      for (const c of corners) roofFlat.push(requiredValue(c[0]), requiredValue(c[1]), requiredValue(c[2]) + groundH);
      viewer.entities.add({
        id: `${id}-surface`,
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArrayHeights(roofFlat),
          perPositionHeight: true,
          material: slopeC.withAlpha(showDetailedSurface ? 0.30 : 0.24),
          outline: false,
        },
      });
      addedIds.push(`${id}-surface`);

      const outlinePositions = corners.map((c) =>
        Cesium.Cartesian3.fromDegrees(c[0], c[1], groundH + requiredValue(c[2])),
      );
      outlinePositions.push(outlinePositions[0]);
      viewer.entities.add({
        id,
        polyline: {
          positions: outlinePositions,
          width: showDetailedSurface ? 5 : 4,
          material: slopeC.withAlpha(showDetailedSurface ? 0.9 : 0.72),
        },
      });
      addedIds.push(id);

      const showLabels = params.get('labels') !== '0';
      if (showLabels && pi === 0) {
        const labelCorner = corners[Math.floor(corners.length * 0.55)];
        if (labelCorner) {
          viewer.entities.add({
            id: `${SUNLIGHT_ENVELOPE_PREFIX}surface-label`,
            position: Cesium.Cartesian3.fromDegrees(labelCorner[0], labelCorner[1], groundH + Math.max(14, requiredValue(labelCorner[2]) + 3)),
            label: {
              text: `정북일조 사선\n§86 / ${envelope.slope ?? 2}:1`,
              font: '700 13px Pretendard, system-ui, sans-serif',
              fillColor: Cesium.Color.fromCssColorString('#111827'),
              outlineColor: Cesium.Color.WHITE,
              outlineWidth: 4,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              backgroundColor: Cesium.Color.WHITE.withAlpha(0.72),
              backgroundPadding: new Cesium.Cartesian2(8, 5),
              showBackground: true,
              pixelOffset: new Cesium.Cartesian2(38, -24),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          });
          addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}surface-label`);
        }
      }
    }
  }

  renderSunlightProfileOverlays({
    viewer,
    Cesium,
    envelope,
    params,
    groundH,
    wallC,
    slopeC,
    cleanLayers,
    addedIds,
  });

  return addedIds;
}
