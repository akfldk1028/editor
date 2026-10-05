import { requiredValue } from '../required-value';
import type { SetbackGeometry, SetbackGeometriesMap } from '../types';
import { extractRing, flattenRing } from '../site-map-geometry';
import { renderSunlightEnvelope } from '../envelopes/sunlight';
import { renderDaylightDiagonalEnvelope } from '../envelopes/daylight';
import { renderCleanLegalContext, renderRoadAndNeighborContext, renderFrontRoadDiagonalReference } from './legal-context';
import { SETBACK_PREFIX } from './site-scene';

export function clearSetbackEntities(viewer: any) {
  const toRemove: any[] = [];
  for (const e of viewer.entities.values) {
    if (typeof e.id === 'string' && e.id.startsWith(SETBACK_PREFIX)) toRemove.push(e);
  }
  for (const e of toRemove) viewer.entities.remove(e);
}

/** Clear and render setback geometry lines + 3D envelopes */
export function renderSetbackEntities(
  viewer: any,
  Cesium: any,
  setbacks: SetbackGeometriesMap,
  parcelRing: number[][] | null,
) {
  clearSetbackEntities(viewer);

  // 규제별 고유 색상 — 프런트/CLI 공통 레퍼런스.
  // 변경시 land/services/regulations/colors.py 와 동기화 필요.
  const colors: Record<string, string> = {
    buildable_area: '#ef4444',                 // 빨강 — 대지 안의 공지/건축가능 경계
    north_setback: '#22c55e',                  // 초록 — 정북 일조 기준선
    sunlight_envelope_wall: '#dc2626',         // 진홍 — 정북 수직 직각벽 (3D)
    sunlight_envelope_plateau: '#f472b6',      // 분홍 — 정북 평탄부 (3D)
    sunlight_envelope_slope: '#ec4899',        // 핑크 — 정북 경사 메쉬 (3D)
    adjacent_setback: '#111827',               // 검정 — 인접대지 이격
    road_setback: '#ef4444',                   // 빨강 — 도로/건축선 후퇴
    corner_cutoff: '#eab308',                  // 노랑 — 가각전제
    daylight_diagonal_envelope: '#a855f7',     // 보라 — 채광 검토 참고면 (정확 판정은 매스/채광창 벽면 필요)
    front_road_diagonal_reference: '#16a34a',  // 녹색 — 전면도로 사선/가로구역 높이 참고면
    building_designation_line: '#14b8a6',      // 청록 — 건축지정선 (지구단위)
    building_limit_line: '#06b6d4',            // 시안 — 건축한계선
    wall_designation_line: '#84cc16',          // 라임 — 벽면지정선
    wall_limit_line: '#f43f5e',                // 산호 — 벽면한계선
  };

  renderCleanLegalContext(viewer, Cesium, setbacks, parcelRing);

  for (const [key, sb] of Object.entries(setbacks)) {
    // sunlight_envelope has different structure — handled separately below
    if (key === 'sunlight_envelope' || !sb || !('geometry' in sb)) continue;
    const geom = (sb as SetbackGeometry).geometry;
    const color = colors[key] || '#f97316';

    if (geom.type === 'FeatureCollection') {
      const features = (geom as unknown as { features?: Array<{ geometry?: { type: string; coordinates: any } }> }).features ?? [];
      for (let i = 0; i < features.length; i++) {
        const featureGeom = features[i]?.geometry;
        if (!featureGeom) continue;
        if (featureGeom.type === 'LineString') {
          const coords = featureGeom.coordinates as number[][];
          if (!coords || coords.length < 2) continue;
          viewer.entities.add({
            id: `${SETBACK_PREFIX}${key}-feature-${i}`,
            polyline: {
              positions: Cesium.Cartesian3.fromDegreesArray(flattenRing(coords)),
              width: key === 'north_setback' ? 5 : 4,
              material: new Cesium.PolylineDashMaterialProperty({
                color: Cesium.Color.fromCssColorString(color),
                dashLength: key === 'north_setback' ? 10 : 16,
              }),
              clampToGround: true,
            },
          });
        } else if (featureGeom.type === 'Polygon' || featureGeom.type === 'MultiPolygon') {
          const ring = extractRing(featureGeom);
          if (!ring || ring.length < 3) continue;
          viewer.entities.add({
            id: `${SETBACK_PREFIX}${key}-feature-${i}-outline`,
            polyline: {
              positions: Cesium.Cartesian3.fromDegreesArray(flattenRing(ring)),
              width: 3,
              material: Cesium.Color.fromCssColorString(color),
              clampToGround: true,
            },
          });
        }
      }
    } else if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
      const ring = extractRing(geom);
      if (!ring || ring.length < 3) continue;
      const flat = flattenRing(ring);
      const params = new URLSearchParams(window.location.search);
      const showFill = key !== 'buildable_area' || params.get('fill') === '1' || params.get('layers') === 'all';
      if (showFill) {
        viewer.entities.add({
          id: `${SETBACK_PREFIX}${key}`,
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(flat),
            // height: 0.5 (sea level) → terrain 표면 따라가도록 클램프.
            // 강남 지표면 ~38m, sunlight envelope wall도 terrainH(~38m)에서 시작 → z축 일치.
            // (이전 height:0.5 시 envelope만 38m 위에 떠 보임 z축 불일치 발생)
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            material: Cesium.Color.fromCssColorString(color).withAlpha(key === 'buildable_area' ? 0.06 : 0.22),
            // outline은 CLAMP_TO_GROUND 모드에서 미지원 → outline 끄고 별도 polyline 추가
            outline: false,
          },
        });
      }
      // Polygon outline 별도 polyline (clampToGround로 terrain 따라감)
      viewer.entities.add({
        id: `${SETBACK_PREFIX}${key}-outline`,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(flat),
          width: key === 'buildable_area' ? 3 : 3,
            material: Cesium.Color.fromCssColorString(key === 'buildable_area' ? '#ef4444' : color),
          clampToGround: true,
        },
      });
    } else if (geom.type === 'LineString') {
      const coords = geom.coordinates as unknown as number[][];
      if (!coords || coords.length < 2) continue;
      const flat = flattenRing(coords);
      viewer.entities.add({
        id: `${SETBACK_PREFIX}${key}`,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(flat),
          width: 5,
          material: new Cesium.PolylineDashMaterialProperty({
            color: Cesium.Color.fromCssColorString(color),
            dashLength: 16,
          }),
          clampToGround: true,
        },
      });
    } else if (geom.type === 'MultiLineString') {
      const lines = geom.coordinates as number[][][];
      for (let i = 0; i < lines.length; i++) {
        const coords = lines[i];
        if (!coords || coords.length < 2) continue;
        const flat = flattenRing(coords);
        viewer.entities.add({
          id: `${SETBACK_PREFIX}${key}-${i}`,
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray(flat),
            width: 5,
            material: new Cesium.PolylineDashMaterialProperty({
              color: Cesium.Color.fromCssColorString(color),
              dashLength: 16,
            }),
            clampToGround: true,
          },
        });
      }
    }
  }

  renderRoadAndNeighborContext(viewer, Cesium, setbacks);

  // 정북일조 envelope — design/lib/envelopes/sunlight.ts 전담 모듈로 위임.
  // 북쪽 수직벽 + 경사 지붕만 렌더 (사용자 img_18 피드백 반영 LOCKED SPEC).
  renderSunlightEnvelope(viewer, Cesium, setbacks.sunlight_envelope, {
    wall: requiredValue(colors.sunlight_envelope_wall),
    slope: requiredValue(colors.sunlight_envelope_slope),
  });

  const params = new URLSearchParams(window.location.search);
  const showDaylight = params.get('daylight') === '1' || params.get('daylight') === 'detail' || params.get('layers') === 'all';
  if (showDaylight) {
    renderDaylightDiagonalEnvelope(viewer, Cesium, setbacks.daylight_diagonal_envelope, {
      wall: requiredValue(colors.daylight_diagonal_envelope),
    }, setbacks.datum_result?.parcel_datum_m ?? setbacks.datum_result?.elevation_m ?? 0);
  }

  renderFrontRoadDiagonalReference(viewer, Cesium, setbacks, parcelRing, {
    surface: requiredValue(colors.front_road_diagonal_reference),
    line: requiredValue(colors.front_road_diagonal_reference),
  });
}

