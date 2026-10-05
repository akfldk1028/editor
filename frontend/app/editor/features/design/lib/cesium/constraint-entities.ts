import { requiredValue } from '../required-value';
import type { ConstraintsResult } from '../api-client';
import { extractRing, flattenRing } from '../site-map-geometry';
import { CONSTRAINTS_PREFIX } from './site-scene';

/** Clear all constraint visualization entities */
export function clearConstraintEntities(viewer: any) {
  const toRemove: any[] = [];
  for (const e of viewer.entities.values) {
    if (typeof e.id === 'string' && e.id.startsWith(CONSTRAINTS_PREFIX)) toRemove.push(e);
  }
  for (const e of toRemove) viewer.entities.remove(e);
}

/**
 * Render constraint envelope features from /design/constraints/visualize/.
 * setbackGeometries fallback path — PNU 검색 없이 임의 polygon에 envelope 시각.
 *
 * features per kind:
 *   - site: 검정 outline (대지경계선)
 *   - adjacent_setback: 빨간 점선 (대지 안의 공지) — Flexity 광고 매칭
 *   - north_sunlight_base: 녹색 점선 + 반투명 fill (정북 일조 base 1.5m)
 *   - sunlight_slope_info: 라벨용 (3D는 sunlight 모듈 별도)
 *   - regulation_summary: metadata only (시각 X)
 */
export function renderConstraintEntities(viewer: any, Cesium: any, result: ConstraintsResult) {
  clearConstraintEntities(viewer);

  for (const feature of result.features) {
    const kind = feature.properties.kind;
    const color = feature.properties.color || '#888888';
    const dashArray = feature.properties.stroke_dasharray;
    const fillOpacity = feature.properties.fill_opacity ?? 0.0;
    const strokeWidth = feature.properties.stroke_width ?? 2;

    // Skip metadata-only features
    if (kind === 'regulation_summary' || kind === 'sunlight_slope_info') {
      continue;
    }

    const geom = feature.geometry as { type: string; coordinates: any };
    const ring = extractRing(geom);
    if (!ring || ring.length < 3) {
      continue;
    }
    const flat = flattenRing(ring);

    // Polygon fill (when fill_opacity > 0)
    if (fillOpacity > 0) {
      viewer.entities.add({
        id: `${CONSTRAINTS_PREFIX}${kind}-fill`,
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray(flat),
          // Cesium: heightReference + CLAMP_TO_GROUND 사용 시 height 명시 필요.
          // 0 = sea level, terrain 기반 자동 클램프 (renderSetbackEntities와 동일 패턴).
          height: 0,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          material: Cesium.Color.fromCssColorString(color).withAlpha(fillOpacity),
          outline: false,
        },
      });
    }

    // Outline polyline (dashed if stroke_dasharray present)
    const cesiumColor = Cesium.Color.fromCssColorString(color);
    const material = dashArray
      ? new Cesium.PolylineDashMaterialProperty({
          color: cesiumColor,
          dashLength: (requiredValue(dashArray[0]) + (dashArray[1] || 0)) * 4,
        })
      : cesiumColor;

    viewer.entities.add({
      id: `${CONSTRAINTS_PREFIX}${kind}-outline`,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flat),
        width: strokeWidth * 2,
        material,
        clampToGround: true,
      },
    });
  }
}

