import { requiredValue } from '../required-value';
import { ringBounds, ringCentroid, type SectionRenderSegment } from './mass-geometry';

/* eslint-disable @typescript-eslint/no-explicit-any */

type RenderSectionProfileOverlayOptions = {
  viewer: any;
  Cesium: any;
  entityPrefix: string;
  designId: number;
  groundH: number;
  profile: any;
  segments: SectionRenderSegment[];
  isSelected: boolean;
};

export function renderSectionProfileOverlay(options: RenderSectionProfileOverlayOptions) {
  const { viewer, Cesium, entityPrefix, designId, groundH, profile, segments, isSelected } = options;
  if (!profile || !Array.isArray(segments) || segments.length === 0) return;
  const kind = String(profile.kind || '');
  const allPoints = segments.flatMap(segment => segment.ring);
  if (allPoints.length < 3) return;
  const bounds = ringBounds(allPoints);
  const minTop = Math.min(...segments.map(segment => Number(segment.top) || 0));
  const maxTop = Math.max(...segments.map(segment => Number(segment.top) || 0));
  const accent = isSelected ? '#ff2f92' : '#ec4899';
  const accentColor = Cesium.Color.fromCssColorString(accent);
  const zOffset = 1.2;

  if (kind === 'sloped_roof' || kind === 'sloped_roof_mass') {
    const high = groundH + maxTop + zOffset;
    const low = groundH + Math.max(minTop, maxTop * 0.56) + zOffset;
    const roofPositions = Cesium.Cartesian3.fromDegreesArrayHeights([
      bounds.minLng, bounds.minLat, high,
      bounds.maxLng, bounds.minLat, high,
      bounds.maxLng, bounds.maxLat, low,
      bounds.minLng, bounds.maxLat, low,
    ]);
    viewer.entities.add({
      id: `${entityPrefix}section-profile-sloped-${designId}`,
      properties: {
        interactionKind: 'section_profile',
        designId,
        target: { kind: 'section_profile', profile_kind: kind },
      },
      polygon: {
        hierarchy: new Cesium.PolygonHierarchy(roofPositions),
        perPositionHeight: true,
        material: Cesium.Color.fromCssColorString('#fed7aa').withAlpha(isSelected ? 0.46 : 0.34),
        outline: true,
        outlineColor: accentColor.withAlpha(0.95),
      },
    });
    for (const ratio of [0, 0.33, 0.66, 1]) {
      const lng = bounds.minLng + (bounds.maxLng - bounds.minLng) * ratio;
      viewer.entities.add({
        id: `${entityPrefix}section-profile-sloped-rib-${designId}-${ratio}`,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArrayHeights([
            lng, bounds.minLat, high + 0.15,
            lng, bounds.maxLat, low + 0.15,
          ]),
          width: ratio === 0 || ratio === 1 ? 4 : 2,
          material: accentColor.withAlpha(ratio === 0 || ratio === 1 ? 0.95 : 0.72),
          clampToGround: false,
        },
      });
    }
    return;
  }

  if (kind === 'diagonal_connector' || kind === 'diagonal_connect') {
    const lower = requiredValue(segments[0]);
    const upper = requiredValue(segments[segments.length - 1]);
    const lowerCenter = ringCentroid(lower.ring);
    const upperCenter = ringCentroid(upper.ring);
    if (!lowerCenter || !upperCenter) return;
    viewer.entities.add({
      id: `${entityPrefix}section-profile-diagonal-${designId}`,
      properties: {
        interactionKind: 'section_profile',
        designId,
        target: { kind: 'section_profile', profile_kind: kind },
      },
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArrayHeights([
          lowerCenter.lng, lowerCenter.lat, groundH + lower.top + zOffset,
          upperCenter.lng, upperCenter.lat, groundH + upper.top + zOffset,
        ]),
        width: isSelected ? 9 : 7,
        material: accentColor.withAlpha(isSelected ? 0.98 : 0.78),
        clampToGround: false,
      },
    });
    return;
  }

  if (kind === 'terrace_ribbon') {
    const side = String(profile.side || 'north');
    const terraceCount = 4;
    for (let i = 0; i < terraceCount; i++) {
      const t = (i + 1) / (terraceCount + 1);
      const lat = side === 'south'
        ? bounds.minLat + (bounds.maxLat - bounds.minLat) * t * 0.56
        : bounds.maxLat - (bounds.maxLat - bounds.minLat) * t * 0.56;
      const top = groundH + maxTop * (0.40 + i * 0.13) + zOffset;
      viewer.entities.add({
        id: `${entityPrefix}section-profile-terrace-${designId}-${i}`,
        properties: {
          interactionKind: 'section_profile',
          designId,
          target: { kind: 'section_profile', profile_kind: kind, band_index: i },
        },
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArrayHeights([
            bounds.minLng, lat, top,
            bounds.maxLng, lat, top,
          ]),
          width: isSelected ? 6 : 4,
          material: accentColor.withAlpha(isSelected ? 0.95 : 0.72),
          clampToGround: false,
        },
      });
    }
  }
}
