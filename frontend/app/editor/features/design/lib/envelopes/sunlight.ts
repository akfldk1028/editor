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

export const SUNLIGHT_ENVELOPE_PREFIX = 'design-setback-sunlight-';

export interface SunlightColors {
  wall: string;  // 북쪽 수직벽 (진홍 권장)
  slope: string; // 경사 지붕 (핑크 권장)
}

export const DEFAULT_SUNLIGHT_COLORS: SunlightColors = {
  wall: '#dc2626',
  slope: '#ec4899',
};

function simplifyClosedRing<T>(ring: T[], maxPoints: number): T[] {
  if (ring.length <= maxPoints) return ring;
  const step = Math.ceil(ring.length / maxPoints);
  const simplified: T[] = [];
  for (let i = 0; i < ring.length; i += step) simplified.push(requiredValue(ring[i]));
  return simplified.length >= 3 ? simplified : ring.slice(0, Math.min(ring.length, maxPoints));
}

function layerRing(layer: unknown): number[][] | null {
  const ring = (layer as { footprint_wgs?: unknown })?.footprint_wgs;
  return Array.isArray(ring) && ring.length >= 4 ? ring as number[][] : null;
}

function layerHeight(layer: unknown): number | null {
  const h = Number((layer as { h_top?: unknown })?.h_top);
  return Number.isFinite(h) ? h : null;
}

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

  const showMesh = params.get('mesh') === '1' || params.get('layers') === 'all';
  if (showMesh && Array.isArray(envelope.envelope_layers)) {
    for (let i = 0; i < envelope.envelope_layers.length; i++) {
      const layer = envelope.envelope_layers[i];
      const ring = layer?.footprint_wgs;
      if (!ring || ring.length < 3) continue;
      const positions = ring.map((p) =>
        Cesium.Cartesian3.fromDegrees(p[0], p[1], groundH + layer.h_top),
      );
      positions.push(positions[0]);
      viewer.entities.add({
        id: `${SUNLIGHT_ENVELOPE_PREFIX}mesh-layer-${i}`,
        polyline: {
          positions,
          width: 3,
          material: slopeC.withAlpha(0.78),
        },
      });
      addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}mesh-layer-${i}`);
    }
  }

  const cleanMaxHeightM = cleanLayers.length ? requiredValue(cleanLayers[cleanLayers.length - 1]).h : null;
  const showProfileFill = params.get('profileFill') === '1' || params.get('layers') === 'all';
  // 기본 VWorld 법규 검토 화면에서는 50m까지 뻗는 원본 단면 대신
  // 현재 대지 envelope 높이까지만 잘라 정북일조 형태를 보여준다.
  const showProfileLine = params.get('profile') === '1' || params.get('profile') === 'detail' || params.get('layers') === 'all';
  const detailedProfile = params.get('profile') === 'detail' || params.get('layers') === 'all';
  const showLabels = params.get('labels') !== '0';
  if ((showProfileFill || showProfileLine) && Array.isArray(envelope.profile_polylines)) {
    for (let i = 0; i < envelope.profile_polylines.length; i++) {
      const profile = envelope.profile_polylines[i];
      const points = cleanMaxHeightM != null
        ? capProfilePoints(profile?.points, cleanMaxHeightM)
        : profile?.points;
      if (!points || points.length < 2) continue;
      if (showProfileFill && points.length >= 3) {
        const ribbonWidthM = Math.max(4, Math.min(22, Number(params.get('profileWidth') ?? 16) || 16));
        const wallRibbon = buildProfileWallRibbon(Cesium, points, groundH, ribbonWidthM);
        if (wallRibbon) {
          viewer.entities.add({
            id: `${SUNLIGHT_ENVELOPE_PREFIX}profile-fill-wall-${i}`,
            wall: {
              positions: wallRibbon.positions,
              minimumHeights: wallRibbon.minimumHeights,
              maximumHeights: wallRibbon.maximumHeights,
              material: wallC.withAlpha(0.16),
              outline: true,
              outlineColor: wallC.withAlpha(0.72),
            },
          });
          addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}profile-fill-wall-${i}`);
        }

        const slopeRibbon = buildSlopedRibbon(Cesium, points, groundH, ribbonWidthM);
        if (slopeRibbon) {
          viewer.entities.add({
            id: `${SUNLIGHT_ENVELOPE_PREFIX}profile-fill-slope-${i}`,
            polygon: {
              hierarchy: new Cesium.PolygonHierarchy(slopeRibbon),
              perPositionHeight: true,
              material: slopeC.withAlpha(0.28),
              outline: false,
            },
          });
          addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}profile-fill-slope-${i}`);
        }
      }
      if (showProfileLine) {
        const linePoints = detailedProfile || points.length < 4
          ? points
          : [points[0], points[1], points[points.length - 1]];
        viewer.entities.add({
          id: `${SUNLIGHT_ENVELOPE_PREFIX}profile-${i}`,
          polyline: {
            positions: linePoints.map((p) => Cesium.Cartesian3.fromDegrees(requiredValue(requiredValue(p)[0]), requiredValue(requiredValue(p)[1]), groundH + requiredValue(requiredValue(p)[2]))),
            width: detailedProfile ? 7 : 6,
            material: new Cesium.PolylineGlowMaterialProperty({
              color: slopeC,
              glowPower: 0.16,
              taperPower: 0.9,
            }),
          },
        });
        addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}profile-${i}`);
        const labelPoint = linePoints[Math.max(1, Math.floor(linePoints.length / 2))];
        if (showLabels && i === 0 && labelPoint) {
          viewer.entities.add({
            id: `${SUNLIGHT_ENVELOPE_PREFIX}profile-label`,
            position: Cesium.Cartesian3.fromDegrees(labelPoint[0], labelPoint[1], groundH + Math.max(12, requiredValue(labelPoint[2]) + 2)),
            label: {
              text: `정북일조\n수직 10m + ${envelope.slope ?? 2}:1`,
              font: '700 13px Pretendard, system-ui, sans-serif',
              fillColor: Cesium.Color.fromCssColorString('#111827'),
              outlineColor: Cesium.Color.WHITE,
              outlineWidth: 4,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              backgroundColor: Cesium.Color.WHITE.withAlpha(0.72),
              backgroundPadding: new Cesium.Cartesian2(8, 5),
              showBackground: true,
              pixelOffset: new Cesium.Cartesian2(44, -30),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          });
          addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}profile-label`);
        }
      }
    }
  }

  return addedIds;
}

type ProfilePoint = [number, number, number];
type WallSegment = {
  a: ProfilePoint;
  b: ProfilePoint;
  minA: number;
  minB: number;
};
type WallLinePoint = [number, number, number, number];

function renderParcelShapedSunlightSurface(
  viewer: any,
  Cesium: any,
  envelope: SunlightEnvelope,
  groundH: number,
  slopeC: any,
): string[] {
  const addedIds: string[] = [];
  const polygons = envelope.slanted_polygons ?? [];
  for (let i = 0; i < polygons.length; i++) {
    const sourceCorners = polygons[i]?.corners as number[][] | undefined;
    const corners = sourceCorners ? simplifyClosedRing(sourceCorners, 96) : null;
    if (!corners || corners.length < 3) continue;

    const center = ringCenterWithHeight(corners, groundH);
    for (let j = 0; j < corners.length; j++) {
      const a = requiredValue(corners[j]);
      const b = requiredValue(corners[(j + 1) % corners.length]);
      const tri = [
        center[0], center[1], center[2],
        requiredValue(a[0]), requiredValue(a[1]), groundH + requiredValue(a[2]),
        requiredValue(b[0]), requiredValue(b[1]), groundH + requiredValue(b[2]),
      ];
      viewer.entities.add({
        id: `${SUNLIGHT_ENVELOPE_PREFIX}parcel-shaped-surface-${i}-${j}`,
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArrayHeights(tri),
          perPositionHeight: true,
          material: slopeC.withAlpha(0.07),
          outline: false,
        },
      });
      addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}parcel-shaped-surface-${i}-${j}`);
    }

    const outline = corners.map((c) => Cesium.Cartesian3.fromDegrees(c[0], c[1], groundH + requiredValue(c[2])));
    outline.push(outline[0]);
    viewer.entities.add({
      id: `${SUNLIGHT_ENVELOPE_PREFIX}parcel-shaped-outline-${i}`,
      polyline: {
        positions: outline,
        width: 2,
        material: slopeC.withAlpha(0.58),
      },
    });
    addedIds.push(`${SUNLIGHT_ENVELOPE_PREFIX}parcel-shaped-outline-${i}`);
  }
  return addedIds;
}

function ringCenterWithHeight(corners: number[][], groundH: number): ProfilePoint {
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

function buildPrimaryWallLine(
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

function capProfilePoints(points: number[][] | undefined, maxHeightM: number): number[][] | undefined {
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

function buildConnectedProfileSurface(
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

function buildPolylineSegmentRibbons(Cesium: any, points: number[][], groundH: number, widthM: number) {
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

function buildSectionVerticalRibbon(Cesium: any, points: number[][], groundH: number, widthM: number) {
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

function buildProfileWallRibbon(Cesium: any, points: number[][], groundH: number, widthM: number) {
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

function buildSlopedRibbon(Cesium: any, points: number[][], groundH: number, widthM: number) {
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
function ringTerrainMean(viewer: any, Cesium: any, corners: number[][]): number {
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
