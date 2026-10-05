import { requiredValue } from '../required-value';
import type { GeoJSONFeature } from '../types';
import { renderFacadeWallEntities } from './facade-materials';
import { SHAPE_COLORS } from './mass-styles';

/* eslint-disable @typescript-eslint/no-explicit-any */

export type RenderMassEntitiesOptions = {
  viewer: any;
  Cesium: any;
  features: GeoJSONFeature[];
  entityPrefix: string;
  selectedId?: number;
  datumZ?: number;
  aestheticOverlayUrl?: string | null;
  aestheticOverlayStatus?: string | null;
  aestheticFacadeStyle?: string | null;
  aestheticFacadeTextureUrl?: string | null;
  aestheticFacadeTexturePanelUrls?: Record<string, string> | null;
  aestheticTexturedGltfUrl?: string | null;
};

type SectionRenderSegment = { ring: number[][]; bottom: number; top: number };

function extractRing(geometry: { type: string; coordinates: any }): number[][] | null {
  if (geometry.type === 'Polygon') return geometry.coordinates[0];
  if (geometry.type === 'MultiPolygon') return largestPolygonCoordinates(geometry.coordinates)?.[0] || null;
  return null;
}

function ringArea(ring: number[][] | null | undefined): number {
  if (!ring || ring.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = requiredValue(ring[i]);
    const b = requiredValue(ring[(i + 1) % ring.length]);
    sum += requiredValue(a[0]) * requiredValue(b[1]) - requiredValue(b[0]) * requiredValue(a[1]);
  }
  return Math.abs(sum) / 2;
}

function largestPolygonCoordinates(polygons: number[][][][] | null | undefined): number[][][] | null {
  if (!Array.isArray(polygons) || polygons.length === 0) return null;
  return polygons.reduce<number[][][] | null>((best, polygon) => {
    if (!Array.isArray(polygon) || !polygon[0]) return best;
    if (!best) return polygon;
    return ringArea(polygon[0]) > ringArea(best[0]) ? polygon : best;
  }, null);
}

function extractParkingEnvelopeRing(parkingPrecheck: any): number[][] | null {
  const geometry = parkingPrecheck?.parking_envelope_wgs84;
  if (!geometry || typeof geometry !== 'object') return null;
  return extractRing(geometry);
}

function flattenRing(ring: number[][]): number[] {
  const flat: number[] = [];
  for (const [lng, lat] of ring) flat.push(requiredValue(lng), requiredValue(lat));
  return flat;
}

function ringCentroid(ring: number[][] | null | undefined): { lng: number; lat: number } | null {
  if (!ring?.length) return null;
  let lng = 0;
  let lat = 0;
  for (const [x, y] of ring) {
    lng += requiredValue(x);
    lat += requiredValue(y);
  }
  return { lng: lng / ring.length, lat: lat / ring.length };
}

function ringBounds(ring: number[][]): { minLng: number; maxLng: number; minLat: number; maxLat: number } {
  let minLng = Number.POSITIVE_INFINITY;
  let maxLng = Number.NEGATIVE_INFINITY;
  let minLat = Number.POSITIVE_INFINITY;
  let maxLat = Number.NEGATIVE_INFINITY;
  for (const [lng, lat] of ring) {
    minLng = Math.min(minLng, requiredValue(lng));
    maxLng = Math.max(maxLng, requiredValue(lng));
    minLat = Math.min(minLat, requiredValue(lat));
    maxLat = Math.max(maxLat, requiredValue(lat));
  }
  return { minLng, maxLng, minLat, maxLat };
}

function getGroundHeight(Cesium: any, viewer: any, ring: number[][]): number {
  let cx = 0;
  let cy = 0;
  for (const [lng, lat] of ring) {
    cx += requiredValue(lng);
    cy += requiredValue(lat);
  }
  cx /= ring.length;
  cy /= ring.length;
  try {
    const carto = Cesium.Cartographic.fromDegrees(cx, cy);
    const h = viewer.scene?.globe?.getHeight?.(carto);
    if (typeof h === 'number' && isFinite(h)) return h;
  } catch { /* fallback */ }
  return 0;
}

function extractSectionProfile(props: any): any | null {
  const model = props?.maas_model;
  const profile = props?.section_profile || model?.section_profile;
  return profile && typeof profile === 'object' ? profile : null;
}

function ringFromRenderableGeometry(item: any): number[][] | null {
  const geometry = item?.geometry;
  if (!geometry || typeof geometry !== 'object') return null;
  return extractRing(geometry);
}

type BuildSectionRenderSegmentsOptions = {
  floorGroups: any[];
  massVolumes: any[];
  floorPlates: any[];
  fallbackRing: number[][];
  height: number;
  floorH: number;
};

function buildSectionRenderSegments(options: BuildSectionRenderSegmentsOptions): SectionRenderSegment[] {
  const { floorGroups, massVolumes, floorPlates, fallbackRing, height, floorH } = options;
  const source = floorGroups.length > 0
    ? floorGroups
    : massVolumes.length > 0
      ? massVolumes
      : floorPlates.length > 0
        ? floorPlates
        : [];
  const segments: SectionRenderSegment[] = [];
  if (source.length > 0) {
    for (let i = 0; i < source.length; i++) {
      const item = source[i];
      const itemRing = ringFromRenderableGeometry(item);
      if (!itemRing || itemRing.length < 3) continue;
      const prev = i > 0 ? source[i - 1] : null;
      const bottom = Number(item.bottom_height ?? prev?.top_height ?? 0) || 0;
      const top = Number(item.top_height ?? ((i + 1) * floorH)) || height;
      segments.push({ ring: itemRing, bottom, top });
    }
  }
  if (segments.length === 0) {
    segments.push({ ring: fallbackRing, bottom: 0, top: height });
  }
  return segments;
}

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

function renderSectionProfileOverlay(options: RenderSectionProfileOverlayOptions) {
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

function renderParkingPrecheckOverlay({
  viewer,
  Cesium,
  entityPrefix,
  designId,
  ring,
  groundH,
  parkingPrecheck,
}: {
  viewer: any;
  Cesium: any;
  entityPrefix: string;
  designId: number;
  ring: number[][];
  groundH: number;
  parkingPrecheck: any;
}) {
  if (!parkingPrecheck || typeof parkingPrecheck !== 'object') return;
  const strategy = parkingPrecheck.selected_strategy || parkingPrecheck.strategy;
  if (!strategy || strategy === 'none') return;

  const required = parkingPrecheck.required_count?.required_spaces;
  const layout = parkingPrecheck.layout_candidate;
  const provided = layout?.provided_spaces;
  const unmet = layout?.unmet_spaces;
  const layoutStatus = layout?.status || parkingPrecheck.status || parkingPrecheck.required_count?.status;
  const isFail = layoutStatus === 'fail' || (typeof unmet === 'number' && unmet > 0);
  const isPass = layoutStatus === 'pass';
  const isReview = !isFail && !isPass;
  const mainColor = isFail ? '#ef4444' : isPass ? '#22c55e' : isReview ? '#f59e0b' : '#22c55e';
  const labelColor = isFail ? '#fecaca' : isPass ? '#bbf7d0' : '#fde68a';
  const groundOffset = 0.08;
  const envelopeRing = extractParkingEnvelopeRing(parkingPrecheck) || ring;
  const envelopeFlat = flattenRing(envelopeRing);
  const stalls = Array.isArray(layout?.stalls) ? layout.stalls : [];
  const hasExactStalls = stalls.some((stall: any) => Array.isArray(stall?.polygon_wgs84));
  const connectorRing = Array.isArray(layout?.grid_solver?.entrance_connector_polygon_wgs84)
    ? layout.grid_solver.entrance_connector_polygon_wgs84
    : null;
  const params = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null;
  const showConnectorDebug = params?.get('parkingDebug') === '1' || params?.get('layers') === 'all';
  if (!hasExactStalls && typeof required !== 'number') return;

  if (!hasExactStalls) {
    viewer.entities.add({
      id: `${entityPrefix}parking-envelope-${designId}`,
      properties: {
        interactionKind: 'parking_envelope',
        designId,
        target: { kind: 'parking', strategy },
      },
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(envelopeFlat),
        height: groundH + groundOffset,
        material: Cesium.Color.fromCssColorString(mainColor).withAlpha(isFail ? 0.14 : 0.08),
        outline: true,
        outlineColor: Cesium.Color.fromCssColorString(mainColor).withAlpha(0.78),
      },
    });
    viewer.entities.add({
      id: `${entityPrefix}parking-boundary-${designId}`,
      polyline: {
        positions: envelopeRing.map(([lng, lat]) => Cesium.Cartesian3.fromDegrees(lng, lat, groundH + groundOffset + 0.22)),
        width: 4,
        material: Cesium.Color.fromCssColorString(mainColor).withAlpha(0.78),
        clampToGround: false,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  for (let i = 0; i < stalls.length; i++) {
    const stall = stalls[i];
    const stallRing = Array.isArray(stall?.polygon_wgs84) ? stall.polygon_wgs84 : null;
    if (!stallRing || stallRing.length < 4) continue;
    const isAccessible = stall.type === 'accessible';
    const stallLine = '#ff2f92';
    const stallLinePositions = stallRing.map(([lng, lat]: number[]) => Cesium.Cartesian3.fromDegrees(lng, lat));
    viewer.entities.add({
      id: `${entityPrefix}parking-line-shadow-${designId}-${i}`,
      properties: {
        interactionKind: 'parking_stall_outline',
        designId,
        target: {
          kind: 'parking_stall',
          stall_id: stall.stall_id,
          stall_type: stall.type,
          strategy,
        },
      },
      polyline: {
        positions: stallLinePositions,
        width: isAccessible ? 10 : 9,
        material: Cesium.Color.fromCssColorString('#020617').withAlpha(0.82),
        clampToGround: true,
        zIndex: 10000 + i * 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    viewer.entities.add({
      id: `${entityPrefix}parking-space-outline-${designId}-${i}`,
      properties: {
        interactionKind: 'parking_stall_outline',
        designId,
        target: {
          kind: 'parking_stall',
          stall_id: stall.stall_id,
          stall_type: stall.type,
          strategy,
        },
      },
      polyline: {
        positions: stallLinePositions,
        width: isAccessible ? 7 : 6,
        material: Cesium.Color.fromCssColorString(stallLine).withAlpha(1),
        clampToGround: true,
        zIndex: 10001 + i * 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    const labelPoint = ringCentroid(stallRing);
    if (labelPoint) {
      viewer.entities.add({
        id: `${entityPrefix}parking-stall-label-${designId}-${i}`,
        position: Cesium.Cartesian3.fromDegrees(labelPoint.lng, labelPoint.lat, groundH + 0.35),
        label: {
          text: String(stall.stall_id || `P${i + 1}`),
          font: '800 11px ui-monospace, SFMono-Regular, Menlo, monospace',
          fillColor: Cesium.Color.fromCssColorString('#ffffff'),
          outlineColor: Cesium.Color.fromCssColorString('#be185d'),
          outlineWidth: 5,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          showBackground: true,
          backgroundColor: Cesium.Color.fromCssColorString('#be185d').withAlpha(0.82),
          backgroundPadding: new Cesium.Cartesian2(5, 3),
          pixelOffset: new Cesium.Cartesian2(0, -8),
          verticalOrigin: Cesium.VerticalOrigin.CENTER,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }
  }

  // The connector is a solver/debug helper for road access, not a parking stall.
  // Keep it out of the default review view so only the legal stall lines read as parking.
  if (showConnectorDebug && connectorRing && connectorRing.length >= 4) {
    const connectorColor = '#22d3ee';
    const connectorFlat = flattenRing(connectorRing);
    const connectorCenter =
      connectorRing.length >= 4
        ? [
          [
            (connectorRing[0][0] + connectorRing[1][0]) / 2,
            (connectorRing[0][1] + connectorRing[1][1]) / 2,
          ],
          [
            (connectorRing[2][0] + connectorRing[3][0]) / 2,
            (connectorRing[2][1] + connectorRing[3][1]) / 2,
          ],
        ]
        : null;
    viewer.entities.add({
      id: `${entityPrefix}parking-connector-corridor-${designId}`,
      properties: {
        interactionKind: 'parking_connector',
        designId,
        target: {
          kind: 'parking_connector',
          connection_type: layout?.grid_solver?.entrance_connection_type,
          width_m: layout?.grid_solver?.entrance_connector_width_m,
          length_m: layout?.grid_solver?.entrance_connector_length_m,
        },
      },
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(connectorFlat),
        height: groundH + 0.45,
        material: Cesium.Color.fromCssColorString(connectorColor).withAlpha(0.1),
        outline: true,
        outlineColor: Cesium.Color.fromCssColorString(connectorColor).withAlpha(0.32),
      },
    });
    viewer.entities.add({
      id: `${entityPrefix}parking-connector-outline-${designId}`,
      properties: {
        interactionKind: 'parking_connector',
        designId,
        target: { kind: 'parking_connector' },
      },
      polyline: {
        positions: connectorRing.map(([lng, lat]: number[]) => Cesium.Cartesian3.fromDegrees(lng, lat, groundH + 0.7)),
        width: 3,
        material: Cesium.Color.fromCssColorString(connectorColor).withAlpha(0.42),
        clampToGround: false,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    if (connectorCenter) {
      viewer.entities.add({
        id: `${entityPrefix}parking-connector-centerline-${designId}`,
        properties: {
          interactionKind: 'parking_connector',
          designId,
          target: { kind: 'parking_connector_centerline' },
        },
        polyline: {
          positions: connectorCenter.map(([lng, lat]: number[]) => Cesium.Cartesian3.fromDegrees(lng, lat, groundH + 0.82)),
          width: 3,
          material: Cesium.Color.fromCssColorString(connectorColor).withAlpha(0.38),
          clampToGround: false,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }
  }

  const bounds = ringBounds(envelopeRing);
  const lineCount = Math.max(
    3,
    Math.min(10, typeof provided === 'number' && provided > 0 ? Math.ceil(provided / 2) : 5),
  );
  const spanLat = bounds.maxLat - bounds.minLat;
  const spanLng = bounds.maxLng - bounds.minLng;
  const longHorizontal = spanLng >= spanLat;
  for (let i = 1; !hasExactStalls && i <= lineCount; i++) {
    const t = i / (lineCount + 1);
    const id = `${entityPrefix}parking-guide-${designId}-${i}`;
    if (longHorizontal) {
      const lat = bounds.minLat + spanLat * t;
      viewer.entities.add({
        id,
        polyline: {
          positions: [
            Cesium.Cartesian3.fromDegrees(bounds.minLng, lat),
            Cesium.Cartesian3.fromDegrees(bounds.maxLng, lat),
          ],
          width: 2,
          material: Cesium.Color.fromCssColorString(mainColor).withAlpha(0.42),
          clampToGround: true,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    } else {
      const lng = bounds.minLng + spanLng * t;
      viewer.entities.add({
        id,
        polyline: {
          positions: [
            Cesium.Cartesian3.fromDegrees(lng, bounds.minLat),
            Cesium.Cartesian3.fromDegrees(lng, bounds.maxLat),
          ],
          width: 2,
          material: Cesium.Color.fromCssColorString(mainColor).withAlpha(0.42),
          clampToGround: true,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }
  }

  if (hasExactStalls) return;

  const center = ringCentroid(ring);
  if (!center) return;
  const countText = typeof required === 'number'
    ? `REQ ${required} / PROV ${typeof provided === 'number' ? provided : '?'}`
    : String(parkingPrecheck.required_count?.status || 'needs requirement');
  viewer.entities.add({
    id: `${entityPrefix}parking-label-${designId}`,
    position: Cesium.Cartesian3.fromDegrees(center.lng, center.lat, groundH + 0.6),
    label: {
      text: `${String(strategy).toUpperCase()}\n${countText}`,
      font: '700 12px ui-monospace, SFMono-Regular, Menlo, monospace',
      fillColor: Cesium.Color.fromCssColorString(labelColor),
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 4,
      style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      showBackground: true,
      backgroundColor: Cesium.Color.BLACK.withAlpha(0.58),
      backgroundPadding: new Cesium.Cartesian2(8, 5),
      pixelOffset: new Cesium.Cartesian2(0, 20),
      verticalOrigin: Cesium.VerticalOrigin.TOP,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });
}

function renderPilotiSupports({
  viewer,
  Cesium,
  entityPrefix,
  designId,
  ring,
  groundH,
  pilotiHeight,
}: {
  viewer: any;
  Cesium: any;
  entityPrefix: string;
  designId: number;
  ring: number[][];
  groundH: number;
  pilotiHeight: number;
}) {
  if (pilotiHeight <= 0 || ring.length < 4) return;
  const openRing = ring.slice(0, -1);
  const center = ringCentroid(ring);
  const supportPoints = [
    ...openRing,
    ...(center ? [[center.lng, center.lat]] : []),
  ].slice(0, 9);
  for (let i = 0; i < supportPoints.length; i++) {
    const [lng, lat] = requiredValue(supportPoints[i]);
    viewer.entities.add({
      id: `${entityPrefix}piloti-column-${designId}-${i}`,
      properties: {
        interactionKind: 'piloti_column',
        designId,
        target: { kind: 'piloti_column', column_index: i },
      },
      polyline: {
        positions: [
          Cesium.Cartesian3.fromDegrees(lng, lat, groundH + 0.25),
          Cesium.Cartesian3.fromDegrees(lng, lat, groundH + pilotiHeight),
        ],
        width: 8,
        material: Cesium.Color.fromCssColorString('#e5e7eb').withAlpha(0.95),
        clampToGround: false,
      },
    });
  }
  if (!center) return;
  viewer.entities.add({
    id: `${entityPrefix}piloti-label-${designId}`,
    position: Cesium.Cartesian3.fromDegrees(center.lng, center.lat, groundH + pilotiHeight + 0.3),
    label: {
      text: `PILOTI VOID\n${pilotiHeight.toFixed(1)}m`,
      font: '700 11px ui-monospace, SFMono-Regular, Menlo, monospace',
      fillColor: Cesium.Color.fromCssColorString('#fef3c7'),
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 4,
      style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      showBackground: true,
      backgroundColor: Cesium.Color.BLACK.withAlpha(0.58),
      backgroundPadding: new Cesium.Cartesian2(7, 4),
      pixelOffset: new Cesium.Cartesian2(0, -10),
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });
}

function attachTexturedGltfModel({
  viewer,
  Cesium,
  entityPrefix,
  designId,
  ring,
  groundH,
  gltfUrl,
  debug,
}: {
  viewer: any;
  Cesium: any;
  entityPrefix: string;
  designId: number;
  ring: number[][];
  groundH: number;
  gltfUrl: string;
  debug: { gltfStatus: string };
}) {
  const origin = ring[0];
  if (!origin || origin.length < 2) {
    debug.gltfStatus = 'missing-origin';
    return;
  }
  const tokenKey = '__arrMassGltfToken';
  const token = ((viewer as any)[tokenKey] || 0) + 1;
  (viewer as any)[tokenKey] = token;

  const originCartesian = Cesium.Cartesian3.fromDegrees(origin[0], origin[1], groundH);
  const modelMatrix = Cesium.Transforms.eastNorthUpToFixedFrame(originCartesian);
  const primitives = viewer.scene?.primitives;
  if (!primitives) {
    debug.gltfStatus = 'missing-primitives';
    return;
  }

  const markAndAdd = (model: any) => {
    if ((viewer as any)[tokenKey] !== token) {
      model?.destroy?.();
      return;
    }
    model.__arrEntityPrefix = entityPrefix;
    model.__arrDesignId = designId;
    primitives.add(model);
    debug.gltfStatus = 'added';
    try {
      viewer.scene?.requestRender?.();
    } catch { /* ignore */ }
  };

  try {
    if (typeof Cesium.Model?.fromGltfAsync === 'function') {
      debug.gltfStatus = 'loading-async';
      Cesium.Model.fromGltfAsync({
        url: gltfUrl,
        modelMatrix,
        scale: 1.0,
      }).then(markAndAdd).catch((error: unknown) => {
        debug.gltfStatus = `error:${error instanceof Error ? error.message : 'load-failed'}`;
      });
    } else if (typeof Cesium.Model?.fromGltf === 'function') {
      debug.gltfStatus = 'loading-sync';
      markAndAdd(Cesium.Model.fromGltf({
        url: gltfUrl,
        modelMatrix,
        scale: 1.0,
      }));
    } else {
      debug.gltfStatus = 'missing-model-api';
    }
  } catch (error) {
    debug.gltfStatus = `error:${error instanceof Error ? error.message : 'load-failed'}`;
  }
}

export function clearMassEntities(viewer: any, entityPrefix: string) {
  const toRemove: any[] = [];
  for (const e of viewer.entities.values) {
    if (typeof e.id === 'string' && e.id.startsWith(entityPrefix)) {
      toRemove.push(e);
    }
  }
  for (const e of toRemove) viewer.entities.remove(e);
  clearMassPrimitives(viewer, entityPrefix);
  try {
    viewer.scene?.requestRender?.();
  } catch { /* ignore */ }
}

function clearMassPrimitives(viewer: any, entityPrefix: string) {
  const primitives = viewer.scene?.primitives;
  if (!primitives || typeof primitives.length !== 'number' || typeof primitives.get !== 'function') return;
  for (let i = primitives.length - 1; i >= 0; i--) {
    const primitive = primitives.get(i);
    if (primitive?.__arrEntityPrefix === entityPrefix) {
      primitives.remove(primitive);
    }
  }
}

export function renderMassEntities({
  viewer,
  Cesium,
  features,
  entityPrefix,
  selectedId,
  datumZ,
  aestheticOverlayUrl,
  aestheticOverlayStatus,
  aestheticFacadeStyle,
  aestheticFacadeTextureUrl,
  aestheticFacadeTexturePanelUrls,
  aestheticTexturedGltfUrl,
}: RenderMassEntitiesOptions) {
  clearMassEntities(viewer, entityPrefix);
  const hasValidatedFacadeTexture = Boolean(
    aestheticFacadeTextureUrl
    || aestheticTexturedGltfUrl
    || (aestheticFacadeTexturePanelUrls && Object.keys(aestheticFacadeTexturePanelUrls).length > 0),
  );
  const debug = {
    featureCount: features.length,
    selectedId,
    hasOverlayUrl: Boolean(aestheticOverlayUrl),
    hasFacadeTextureUrl: Boolean(aestheticFacadeTextureUrl),
    hasTexturedGltfUrl: Boolean(aestheticTexturedGltfUrl),
    facadeTexturePanelViews: Object.keys(aestheticFacadeTexturePanelUrls || {}),
    aestheticFacadeStyle: hasValidatedFacadeTexture ? (aestheticFacadeStyle || '') : '',
    facadeAttempts: 0,
    facadeEligibleFeatures: 0,
    overlayAttempts: 0,
    gltfAttempts: 0,
    gltfStatus: '',
    pilotiFeatures: [] as Array<{ designId: number; strategy: string; voidHeight: number }>,
    parkingLayouts: [] as Array<{
      designId: number;
      strategy: string;
      status: string;
      provided: number | null;
      stalls: number;
      stallsWithWgs84: number;
    }>,
  };

  for (let featureIndex = 0; featureIndex < features.length; featureIndex++) {
    const feature = requiredValue(features[featureIndex]);
    const ring = extractRing(feature.geometry);
    if (!ring || ring.length < 3) continue;

    const p = feature.properties;
    const height = p.height || 15;
    const numFloors = p.num_floors || 1;
    const floorH = p.floor_height || (height / numFloors);
    const parkingPrecheck = (p as any).parking_precheck;
    const parkingStrategy = parkingPrecheck?.selected_strategy || parkingPrecheck?.strategy || (p as any).parking_strategy;
    const isPilotiParking = parkingStrategy === 'piloti_ground';
    const designId = p.design_id ?? featureIndex;
    const isSelected = selectedId != null && designId === selectedId;
    const shapeColor = SHAPE_COLORS[p.mass_shape || 'rectangle'] || '#60a5fa';
    const groundH = (datumZ != null && isFinite(datumZ) && datumZ !== 0)
      ? datumZ
      : getGroundHeight(Cesium, viewer, ring);
    const flat = flattenRing(ring);
    const effectiveFacadeStyle = aestheticFacadeStyle?.trim() || '';
    const shouldAttachAestheticOverlay = Boolean(aestheticOverlayUrl)
      && !aestheticFacadeTextureUrl
      && (selectedId == null || isSelected || features.length === 1);
    const shouldAttachAestheticFacade = Boolean(effectiveFacadeStyle)
      && hasValidatedFacadeTexture
      && (selectedId == null || isSelected || features.length === 1);
    const textureFacadeMode = shouldAttachAestheticFacade && Boolean(aestheticFacadeTextureUrl);
    const gltfTextureMode = textureFacadeMode && Boolean(aestheticTexturedGltfUrl);
    const pilotiVoidHeight = isPilotiParking && !textureFacadeMode
      ? Math.max(3.0, Math.min(Number(floorH) || 3.0, 4.5))
      : 0;
    if (isPilotiParking) {
      debug.pilotiFeatures.push({ designId, strategy: String(parkingStrategy), voidHeight: pilotiVoidHeight });
    }
    if (parkingPrecheck && typeof parkingPrecheck === 'object') {
      const layout = parkingPrecheck.layout_candidate;
      const stalls = Array.isArray(layout?.stalls) ? layout.stalls : [];
      debug.parkingLayouts.push({
        designId,
        strategy: String(parkingStrategy || ''),
        status: String(layout?.status || parkingPrecheck.status || ''),
        provided: typeof layout?.provided_spaces === 'number' ? layout.provided_spaces : null,
        stalls: stalls.length,
        stallsWithWgs84: stalls.filter((stall: any) => Array.isArray(stall?.polygon_wgs84)).length,
      });
    }
    if (shouldAttachAestheticFacade) debug.facadeEligibleFeatures += 1;
    const selectedMassAlpha = gltfTextureMode ? 0.0 : shouldAttachAestheticFacade
      ? (aestheticFacadeTextureUrl ? 0.06 : 0.14)
      : 0.30;
    const unselectedMassAlpha = gltfTextureMode ? 0.0 : shouldAttachAestheticFacade
      ? (aestheticFacadeTextureUrl ? 0.035 : 0.08)
      : 0.20;

    const maasModel = p.maas_model;
    const floorPlates = Array.isArray(maasModel?.floor_plates)
      ? maasModel.floor_plates
      : Array.isArray(p.floor_plates) ? p.floor_plates : [];
    const floorGroups = Array.isArray(maasModel?.floor_groups)
      ? maasModel.floor_groups
      : Array.isArray(p.floor_groups) ? p.floor_groups : [];
    const massVolumes = Array.isArray(maasModel?.volumes)
      ? maasModel.volumes
      : Array.isArray(p.mass_volumes) ? p.mass_volumes : [];
    const sectionProfile = extractSectionProfile(p);
    const sectionSegments = buildSectionRenderSegments({
      floorGroups,
      massVolumes,
      floorPlates,
      fallbackRing: ring,
      height,
      floorH,
    });
    const hasStepback = p.step_floor && p.upper_geometry && p.lower_height;
    const visibleBottom = (relativeHeight: number) => Math.max(relativeHeight, pilotiVoidHeight);
    const shouldRenderBand = (top: number) => textureFacadeMode || top > pilotiVoidHeight + 0.05;

    const attachFacade = (
      facadeRing: number[][],
      bottom: number,
      top: number,
      segmentKey: string,
    ) => {
      if (!shouldAttachAestheticFacade) return;
      debug.facadeAttempts += 1;
      renderFacadeWallEntities({
        viewer,
        Cesium,
        entityPrefix,
        ring: facadeRing,
        groundH,
        bottom,
        top,
        designId,
        segmentKey,
        style: effectiveFacadeStyle,
        textureUrl: aestheticFacadeTextureUrl,
        texturePanelUrls: aestheticFacadeTexturePanelUrls,
        floorH,
        textureTotalHeight: height,
      });
    };

    if (gltfTextureMode && aestheticTexturedGltfUrl) {
      debug.gltfAttempts += 1;
      attachTexturedGltfModel({
        viewer,
        Cesium,
        entityPrefix,
        designId,
        ring,
        groundH,
        gltfUrl: aestheticTexturedGltfUrl,
        debug,
      });
    } else if (textureFacadeMode) {
      attachFacade(ring, 0, height, 'texture-shell');
    }

    if (floorGroups.length > 0) {
      for (let i = 0; i < floorGroups.length; i++) {
        const group = requiredValue(floorGroups[i]);
        const groupRing = extractRing(group.geometry);
        if (!groupRing || groupRing.length < 3) continue;
        const groupFlat = flattenRing(groupRing);
        const bottom = group.bottom_height || 0;
        const top = group.top_height || height;
        if (!shouldRenderBand(top)) continue;
        viewer.entities.add({
          id: `${entityPrefix}floor-group-${designId}-${i}`,
          properties: {
            interactionKind: 'floor_group',
            designId,
            floorIndex: i,
            target: {
              kind: 'floor_group',
              group_index: i,
              start_floor: group.start_floor,
              end_floor: group.end_floor,
            },
          },
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(groupFlat),
            height: textureFacadeMode ? groundH + top : groundH + visibleBottom(bottom),
            extrudedHeight: textureFacadeMode ? undefined : groundH + top,
            material: isSelected
              ? Cesium.Color.fromCssColorString('#f59e0b').withAlpha(selectedMassAlpha)
              : Cesium.Color.fromCssColorString(shapeColor).withAlpha(gltfTextureMode ? unselectedMassAlpha : Math.max(0.12, 0.25 - i * 0.026)),
            outline: !textureFacadeMode,
            outlineColor: isSelected
              ? Cesium.Color.fromCssColorString('#fbbf24')
              : Cesium.Color.fromCssColorString(shapeColor).withAlpha(0.84),
          },
        });
        if (!textureFacadeMode) attachFacade(groupRing, visibleBottom(bottom), top, `floor-group-${i}`);
      }
    } else if (massVolumes.length > 0) {
      for (let i = 0; i < massVolumes.length; i++) {
        const volume = requiredValue(massVolumes[i]);
        const volumeRing = extractRing(volume.geometry);
        if (!volumeRing || volumeRing.length < 3) continue;
        const volumeFlat = flattenRing(volumeRing);
        const bottom = volume.bottom_height || 0;
        const top = volume.top_height || height;
        if (!shouldRenderBand(top)) continue;
        viewer.entities.add({
          id: `${entityPrefix}volume-${designId}-${i}`,
          properties: {
            interactionKind: 'mass_volume',
            designId,
            floorIndex: i,
            target: { kind: 'volume', band_index: i },
          },
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(volumeFlat),
            height: textureFacadeMode ? groundH + top : groundH + visibleBottom(bottom),
            extrudedHeight: textureFacadeMode ? undefined : groundH + top,
            material: isSelected
              ? Cesium.Color.fromCssColorString('#f59e0b').withAlpha(selectedMassAlpha)
              : Cesium.Color.fromCssColorString(shapeColor).withAlpha(gltfTextureMode ? unselectedMassAlpha : Math.max(0.13, 0.24 - i * 0.025)),
            outline: !textureFacadeMode,
            outlineColor: isSelected
              ? Cesium.Color.fromCssColorString('#fbbf24')
              : Cesium.Color.fromCssColorString(shapeColor).withAlpha(0.82),
          },
        });
        if (!textureFacadeMode) attachFacade(volumeRing, visibleBottom(bottom), top, `volume-${i}`);
      }
    } else if (floorPlates.length > 0) {
      for (let i = 0; i < floorPlates.length; i++) {
        const plate = requiredValue(floorPlates[i]);
        const plateRing = extractRing(plate.geometry);
        if (!plateRing || plateRing.length < 3) continue;
        const plateFlat = flattenRing(plateRing);
        const bottom = i === 0 ? 0 : requiredValue(floorPlates[i - 1]).top_height;
        const top = plate.top_height || (i + 1) * floorH;
        if (!shouldRenderBand(top)) continue;
        viewer.entities.add({
          id: `${entityPrefix}layer-${designId}-${i}`,
          properties: {
            interactionKind: 'floor_plate',
            designId,
            floorIndex: i,
            target: { kind: 'top', floor_index: i },
          },
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(plateFlat),
            height: textureFacadeMode ? groundH + top : groundH + visibleBottom(bottom),
            extrudedHeight: textureFacadeMode ? undefined : groundH + top,
            material: isSelected
              ? Cesium.Color.fromCssColorString('#f59e0b').withAlpha(selectedMassAlpha)
              : Cesium.Color.fromCssColorString(shapeColor).withAlpha(gltfTextureMode ? unselectedMassAlpha : Math.max(0.10, 0.22 - i * 0.008)),
            outline: !textureFacadeMode,
            outlineColor: isSelected
              ? Cesium.Color.fromCssColorString('#fbbf24')
              : Cesium.Color.fromCssColorString(shapeColor).withAlpha(0.75),
          },
        });
        if (!textureFacadeMode) attachFacade(plateRing, visibleBottom(bottom), top, `layer-${i}`);
      }
    } else if (hasStepback) {
      const lowerRelativeTop = Number(p.lower_height) || 0;
      const lowerVisibleBottom = visibleBottom(0);
      const shouldRenderLower = textureFacadeMode || lowerRelativeTop > lowerVisibleBottom + 0.05;
      if (shouldRenderLower) {
        const lowerTop = groundH + lowerRelativeTop;
        viewer.entities.add({
          id: `${entityPrefix}lower-${designId}`,
            polygon: {
              hierarchy: Cesium.Cartesian3.fromDegreesArray(flat),
              height: textureFacadeMode ? lowerTop : groundH + lowerVisibleBottom,
              extrudedHeight: textureFacadeMode ? undefined : lowerTop,
            material: isSelected
              ? Cesium.Color.fromCssColorString('#f59e0b').withAlpha(selectedMassAlpha)
              : Cesium.Color.fromCssColorString(shapeColor).withAlpha(unselectedMassAlpha),
            outline: !textureFacadeMode,
            outlineColor: isSelected
              ? Cesium.Color.fromCssColorString('#fbbf24')
              : Cesium.Color.fromCssColorString(shapeColor),
          },
        });
      }
      if (!textureFacadeMode && lowerRelativeTop > lowerVisibleBottom + 0.05) {
        attachFacade(ring, lowerVisibleBottom, lowerRelativeTop, 'lower');
      }

      const upperRing = extractRing(p.upper_geometry!);
      if (upperRing && upperRing.length >= 3) {
        const upperFlat = flattenRing(upperRing);
        const upperRelativeBottom = Math.max(lowerRelativeTop, pilotiVoidHeight);
        const shouldRenderUpper = textureFacadeMode || height > upperRelativeBottom + 0.05;
        if (!shouldRenderUpper) continue;
        viewer.entities.add({
          id: `${entityPrefix}upper-${designId}`,
            polygon: {
              hierarchy: Cesium.Cartesian3.fromDegreesArray(upperFlat),
              height: textureFacadeMode ? groundH + height : groundH + upperRelativeBottom,
              extrudedHeight: textureFacadeMode ? undefined : groundH + height,
            material: isSelected
              ? Cesium.Color.fromCssColorString('#f59e0b').withAlpha(selectedMassAlpha)
              : Cesium.Color.fromCssColorString(shapeColor).withAlpha(unselectedMassAlpha),
            outline: !textureFacadeMode,
            outlineColor: isSelected
              ? Cesium.Color.fromCssColorString('#fbbf24')
              : Cesium.Color.fromCssColorString(shapeColor).withAlpha(0.8),
          },
        });
        if (!textureFacadeMode && height > upperRelativeBottom + 0.05) {
          attachFacade(upperRing, upperRelativeBottom, height, 'upper');
        }
      }
    } else {
      viewer.entities.add({
        id: `${entityPrefix}body-${designId}`,
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray(flat),
          height: textureFacadeMode ? groundH + height : groundH + visibleBottom(0),
          extrudedHeight: textureFacadeMode ? undefined : groundH + height,
          material: isSelected
            ? Cesium.Color.fromCssColorString('#f59e0b').withAlpha(selectedMassAlpha)
            : Cesium.Color.fromCssColorString(shapeColor).withAlpha(unselectedMassAlpha),
          outline: !textureFacadeMode,
          outlineColor: isSelected
            ? Cesium.Color.fromCssColorString('#fbbf24')
            : Cesium.Color.fromCssColorString(shapeColor),
        },
      });
      if (!textureFacadeMode) attachFacade(ring, visibleBottom(0), height, 'body');
    }

    if (!textureFacadeMode) for (let i = 1; i < numFloors; i++) {
      const relativePlateH = floorH * i;
      if (relativePlateH <= pilotiVoidHeight + 0.05) continue;
      const plateH = groundH + relativePlateH;
      const useUpper = hasStepback && p.step_floor && i >= p.step_floor;
      let plateFlat = flat;
      if (floorPlates.length > 0) {
        const plate = requiredValue(floorPlates[Math.min(i, floorPlates.length - 1)]);
        const plateRing = extractRing(plate.geometry);
        if (plateRing && plateRing.length >= 3) plateFlat = flattenRing(plateRing);
      }
      if (useUpper && p.upper_geometry) {
        const uRing = extractRing(p.upper_geometry);
        if (uRing && uRing.length >= 3) plateFlat = flattenRing(uRing);
      }
      viewer.entities.add({
        id: `${entityPrefix}floor-${designId}-${i}`,
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray(plateFlat),
          height: plateH,
          material: Cesium.Color.fromCssColorString('#93c5fd').withAlpha(0.06),
          outline: !textureFacadeMode,
          outlineColor: isSelected
            ? Cesium.Color.fromCssColorString('#fbbf24').withAlpha(0.3)
            : Cesium.Color.fromCssColorString(shapeColor).withAlpha(0.15),
        },
      });
    }

    if (!textureFacadeMode && sectionProfile) {
      renderSectionProfileOverlay({
        viewer,
        Cesium,
        entityPrefix,
        designId,
        groundH,
        profile: sectionProfile,
        segments: sectionSegments,
        isSelected,
      });
    }

    const handleRing = floorPlates.length > 0
      ? (extractRing(requiredValue(floorPlates[0]).geometry) || ring)
      : ring;
    const parkingStalls = parkingPrecheck?.layout_candidate?.stalls;
    const hasExactParkingStalls = Array.isArray(parkingStalls)
      && parkingStalls.some((stall: any) => Array.isArray(stall?.polygon_wgs84));

    if (!textureFacadeMode) {
      viewer.entities.add({
        id: `${entityPrefix}footprint-${designId}`,
        properties: {
          interactionKind: 'footprint',
          designId,
          target: { kind: 'footprint' },
        },
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray(flat),
          height: groundH + 0.3,
          material: Cesium.Color.fromCssColorString('#f97316').withAlpha(0.15),
          outline: true,
          outlineColor: Cesium.Color.fromCssColorString('#f97316'),
        },
      });
    }

    if (!textureFacadeMode) {
      renderParkingPrecheckOverlay({
        viewer,
        Cesium,
        entityPrefix,
        designId,
        ring: handleRing,
        groundH,
        parkingPrecheck,
      });
    }

    // Column/core geometry is intentionally hidden until structural input is explicit.
    void isPilotiParking;
    void pilotiVoidHeight;

    if (!textureFacadeMode && !hasExactParkingStalls) for (let edgeIndex = 0; edgeIndex < handleRing.length - 1; edgeIndex++) {
      const a = requiredValue(handleRing[edgeIndex]);
      const b = requiredValue(handleRing[edgeIndex + 1]);
      viewer.entities.add({
        id: `${entityPrefix}edge-${designId}-${edgeIndex}`,
        properties: {
          interactionKind: 'edge',
          designId,
          edgeIndex,
          target: { kind: 'side', edge_index: edgeIndex },
        },
        polyline: {
          positions: [
            Cesium.Cartesian3.fromDegrees(requiredValue(a[0]), requiredValue(a[1]), groundH + 0.8),
            Cesium.Cartesian3.fromDegrees(requiredValue(b[0]), requiredValue(b[1]), groundH + 0.8),
          ],
          width: 7,
          material: Cesium.Color.fromCssColorString('#14b8a6').withAlpha(isSelected ? 0.55 : 0.28),
          clampToGround: false,
        },
      });
    }

    if (shouldAttachAestheticOverlay && aestheticOverlayUrl) {
      debug.overlayAttempts += 1;
      const center = ringCentroid(ring);
      if (!center) continue;
      viewer.entities.add({
        id: `${entityPrefix}aesthetic-overlay-${designId}`,
        position: Cesium.Cartesian3.fromDegrees(center.lng, center.lat, groundH + height + 5),
        billboard: {
          image: aestheticOverlayUrl,
          width: 170,
          height: 170,
          scaleByDistance: new Cesium.NearFarScalar(80, 1.15, 900, 0.45),
          translucencyByDistance: new Cesium.NearFarScalar(80, 1.0, 1200, 0.58),
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          text: `AI facade${aestheticOverlayStatus ? `\n${aestheticOverlayStatus}` : ''}`,
          font: '700 11px ui-monospace, SFMono-Regular, Menlo, monospace',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          backgroundColor: Cesium.Color.BLACK.withAlpha(0.46),
          backgroundPadding: new Cesium.Cartesian2(7, 4),
          showBackground: true,
          pixelOffset: new Cesium.Cartesian2(0, -176),
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }
  }
  try {
    (window as any).__arrLastMassRender = debug;
    (window as any).__arrDesignLastMassFeatures = features;
  } catch { /* ignore */ }
}
