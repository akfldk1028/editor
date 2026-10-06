import type { SunlightEnvelope } from '../../../land-map/lib/types';
import { requiredValue } from '../required-value';
import {
  buildProfileWallRibbon,
  buildSlopedRibbon,
  capProfilePoints,
  ringCenterWithHeight,
  simplifyClosedRing,
} from './sunlight-geometry';

/* eslint-disable @typescript-eslint/no-explicit-any */

export const SUNLIGHT_ENVELOPE_PREFIX = 'design-setback-sunlight-';

export function renderParcelShapedSunlightSurface(
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

type SunlightProfileOverlayOptions = {
  viewer: any;
  Cesium: any;
  envelope: SunlightEnvelope;
  params: URLSearchParams;
  groundH: number;
  wallC: any;
  slopeC: any;
  cleanLayers: { ring: number[][]; h: number }[];
  addedIds: string[];
};

/** Mesh layers + 정북일조 profile polylines/ribbons; appends entity ids to `addedIds`. */
export function renderSunlightProfileOverlays({
  viewer,
  Cesium,
  envelope,
  params,
  groundH,
  wallC,
  slopeC,
  cleanLayers,
  addedIds,
}: SunlightProfileOverlayOptions): void {
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
}
