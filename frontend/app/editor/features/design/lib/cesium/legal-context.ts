import { requiredValue } from '../required-value';
import type { SetbackGeometriesMap } from '../types';
import { flattenRing, numberOrNull, ringCentroid, midpoint, lineCoords, lineMidpoint, lineKey, polygonRing, lngLatToLocalMeters, offsetPointMeters, clippedLineSegment } from '../site-map-geometry';
import { SETBACK_PREFIX } from './site-scene';

const CLEAN_CONTEXT_PREFIX = `${SETBACK_PREFIX}clean-context-`;

export function renderRoadAndNeighborContext(viewer: any, Cesium: any, setbacks: SetbackGeometriesMap): string[] {
  const addedIds: string[] = [];
  const datum = setbacks.datum_result;
  const roadFrontages = (setbacks as Record<string, unknown>).road_frontages as Array<Record<string, unknown>> | undefined;
  const neighborParcels = (setbacks as Record<string, unknown>).neighbor_parcels as Array<Record<string, unknown>> | undefined;
  const params = new URLSearchParams(window.location.search);
  const showAllLabels = params.get('roadLabels') === 'all' || params.get('layers') === 'all';
  const showRoadLabels = params.get('roadLabels') === '1' || showAllLabels;
  const roadC = Cesium.Color.fromCssColorString('#0ea5e9');
  const roadEdgeC = Cesium.Color.fromCssColorString('#f97316');
  const neighborC = Cesium.Color.fromCssColorString('#f472b6');

  const seenRoads = new Set<string>();
  const roads = (roadFrontages ?? [])
    .map((r, index) => {
      const shared = lineCoords(r.sharedEdge ?? r.shared_edge);
      const center = lineCoords(r.roadCenterline ?? r.road_centerline);
      const width = numberOrNull(r.roadWidthM ?? r.road_width_m) ?? 0;
      return { index, shared, center, width };
    })
    .filter((r) => r.shared && r.shared.length >= 2 && r.width > 0)
    .filter((r) => {
      const key = lineKey(r.shared!);
      if (seenRoads.has(key)) return false;
      seenRoads.add(key);
      return true;
    })
    .sort((a, b) => b.width - a.width);

  roads.forEach((road, order) => {
    const shared = road.shared!;
    const id = `${SETBACK_PREFIX}road-context-${road.index}`;
    viewer.entities.add({
      id: `${id}-edge`,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flattenRing(shared)),
        width: 4,
        material: roadEdgeC.withAlpha(0.92),
        clampToGround: true,
      },
    });
    addedIds.push(`${id}-edge`);

    if (road.center && road.center.length >= 2) {
      viewer.entities.add({
        id: `${id}-centerline`,
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(flattenRing(road.center)),
          width: 2,
          material: new Cesium.PolylineDashMaterialProperty({
            color: roadC.withAlpha(0.85),
            dashLength: 12,
          }),
          clampToGround: true,
        },
      });
      addedIds.push(`${id}-centerline`);
    }

    if (showRoadLabels && (showAllLabels || order < 2)) {
      const basis = lineMidpoint(road.center ?? shared);
      if (basis) {
        viewer.entities.add({
          id: `${id}-label`,
          position: Cesium.Cartesian3.fromDegrees(basis.lng, basis.lat, (datum?.road_datum_m ?? datum?.elevation_m ?? 0) + 6),
          label: {
            text: `도로 ${road.width.toFixed(1)}m\n레벨 ${(datum?.road_datum_m ?? datum?.elevation_m ?? 0).toFixed(2)}m`,
            font: '700 12px ui-monospace, SFMono-Regular, Menlo, monospace',
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            backgroundColor: Cesium.Color.BLACK.withAlpha(0.50),
            backgroundPadding: new Cesium.Cartesian2(7, 4),
            showBackground: true,
            pixelOffset: new Cesium.Cartesian2(-86, order === 0 ? 18 : -28),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
        addedIds.push(`${id}-label`);
      }
    }
  });

  const seenNeighbors = new Set<string>();
  (neighborParcels ?? []).forEach((neighbor, index) => {
    const shared = lineCoords(neighbor.sharedEdge ?? neighbor.shared_edge);
    if (!shared || shared.length < 2) return;
    const key = lineKey(shared);
    if (seenNeighbors.has(key)) return;
    seenNeighbors.add(key);
    const id = `${SETBACK_PREFIX}neighbor-context-${index}`;
    viewer.entities.add({
      id: `${id}-edge`,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flattenRing(shared)),
        width: 3,
        material: neighborC.withAlpha(0.82),
        clampToGround: true,
      },
    });
    addedIds.push(`${id}-edge`);
  });

  return addedIds;
}

export function renderCleanLegalContext(
  viewer: any,
  Cesium: any,
  setbacks: SetbackGeometriesMap,
  parcelRing: number[][] | null,
): string[] {
  const params = new URLSearchParams(window.location.search);
  if (params.get('diagram') === '0' || params.get('layers') === 'all') return [];

  const addedIds: string[] = [];
  const roadFrontages = (setbacks as Record<string, unknown>).road_frontages as Array<Record<string, unknown>> | undefined;
  const neighborParcels = (setbacks as Record<string, unknown>).neighbor_parcels as Array<Record<string, unknown>> | undefined;
  const roadFill = Cesium.Color.fromCssColorString('#d8dadd');
  const parcelFill = Cesium.Color.fromCssColorString('#f8fafc');
  const parcelLine = Cesium.Color.fromCssColorString('#9ca3af');
  const siteFill = Cesium.Color.fromCssColorString('#fbfff8');
  const siteLine = Cesium.Color.fromCssColorString('#111827');

  const drawPolygon = (
    id: string,
    ring: number[][] | null,
    fill: any,
    alpha: number,
    outline: any,
    width: number,
    z = 0,
  ) => {
    if (!ring || ring.length < 3) return;
    const flat = flattenRing(ring);
    viewer.entities.add({
      id: `${CLEAN_CONTEXT_PREFIX}${id}-fill`,
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(flat),
        height: z,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        material: fill.withAlpha(alpha),
        outline: false,
      },
    });
    addedIds.push(`${CLEAN_CONTEXT_PREFIX}${id}-fill`);
    viewer.entities.add({
      id: `${CLEAN_CONTEXT_PREFIX}${id}-outline`,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flat),
        width,
        material: outline,
        clampToGround: true,
      },
    });
    addedIds.push(`${CLEAN_CONTEXT_PREFIX}${id}-outline`);
  };

  (neighborParcels ?? []).slice(0, 12).forEach((neighbor, i) => {
    drawPolygon(`neighbor-${i}`, polygonRing(neighbor.geometry), parcelFill, 0.62, parcelLine.withAlpha(0.34), 1);
  });

  (roadFrontages ?? []).slice(0, 8).forEach((road, i) => {
    drawPolygon(`road-${i}`, polygonRing(road.geometry), roadFill, 0.48, roadFill.withAlpha(0.72), 1);
  });

  drawPolygon('site', parcelRing, siteFill, 0.92, siteLine, 2.2);
  return addedIds;
}

export function renderFrontRoadDiagonalReference(
  viewer: any,
  Cesium: any,
  setbacks: SetbackGeometriesMap,
  parcelRing: number[][] | null,
  colors: { surface: string; line: string },
): string[] {
  const params = new URLSearchParams(window.location.search);
  const showReference = params.get('roadDiag') === '1' || params.get('layers') === 'all';
  if (!showReference) return [];

  const profile = (setbacks as Record<string, unknown>).front_road_diagonal_profile as Record<string, unknown> | undefined;
  const datum = setbacks.datum_result;
  const roadFrontages = (setbacks as Record<string, unknown>).road_frontages as Array<Record<string, unknown>> | undefined;
  const parcelBasis = parcelRing ? ringCentroid(parcelRing) : null;
  if (!profile || !datum || !roadFrontages?.length || !parcelBasis) return [];

  const slope = numberOrNull(profile.slope) ?? 1.5;
  const profileWidth = numberOrNull(profile.road_width_m) ?? 0;
  const roadDatum = numberOrNull(profile.road_datum_m) ?? datum.road_datum_m ?? datum.elevation_m ?? 0;
  const applies = Boolean(profile.applies);
  const alpha = applies ? 0.14 : 0.09;

  const roads = roadFrontages
    .map((r, index) => {
      const shared = lineCoords(r.sharedEdge ?? r.shared_edge);
      const width = numberOrNull(r.roadWidthM ?? r.road_width_m) ?? profileWidth;
      return { index, shared, width };
    })
    .filter((r) => r.shared && r.shared.length >= 2 && r.width > 0)
    .sort((a, b) => b.width - a.width);
  const road = roads[0];
  if (!road?.shared) return [];

  const shared = road.shared;
  const rawA = { lng: requiredValue(requiredValue(shared[0])[0]), lat: requiredValue(requiredValue(shared[0])[1]) };
  const rawB = { lng: requiredValue(requiredValue(shared[shared.length - 1])[0]), lat: requiredValue(requiredValue(shared[shared.length - 1])[1]) };
  const edgeMid = midpoint(rawA, rawB);
  const origin = edgeMid;
  const [a, b] = clippedLineSegment(rawA, rawB, origin, 32);
  const midLocal = lngLatToLocalMeters(edgeMid, origin);
  const parcelLocal = lngLatToLocalMeters(parcelBasis, origin);
  const inwardRaw = { x: parcelLocal.x - midLocal.x, y: parcelLocal.y - midLocal.y };
  const inwardLen = Math.hypot(inwardRaw.x, inwardRaw.y);
  if (inwardLen < 0.01) return [];
  const inward = { x: inwardRaw.x / inwardLen, y: inwardRaw.y / inwardLen };
  const roadWidth = road.width || profileWidth;
  const displayDepth = Math.min(18, Math.max(10, roadWidth * 1.2));

  // Clean reference ribbon: show the section plane only near the selected road
  // frontage. The legal section starts at the opposite road boundary, so the
  // shared-edge height includes roadWidth * slope; the ribbon then rises inward.
  const edgeH = slope * roadWidth;
  const innerB = offsetPointMeters(b, origin, inward, displayDepth);
  const innerA = offsetPointMeters(a, origin, inward, displayDepth);
  const innerH = edgeH + slope * displayDepth;
  const positions = [
    [a.lng, a.lat, roadDatum + edgeH],
    [b.lng, b.lat, roadDatum + edgeH],
    [innerB.lng, innerB.lat, roadDatum + innerH],
    [innerA.lng, innerA.lat, roadDatum + innerH],
  ];

  const surfaceC = Cesium.Color.fromCssColorString(colors.surface);
  const lineC = Cesium.Color.fromCssColorString(colors.line);
  const addedIds: string[] = [];
  const flatHeights: number[] = [];
  positions.forEach((p) => flatHeights.push(requiredValue(p[0]), requiredValue(p[1]), requiredValue(p[2])));
  viewer.entities.add({
    id: `${SETBACK_PREFIX}front-road-diagonal-reference-surface`,
    polygon: {
      hierarchy: Cesium.Cartesian3.fromDegreesArrayHeights(flatHeights),
      perPositionHeight: true,
      material: surfaceC.withAlpha(alpha),
      outline: false,
    },
  });
  addedIds.push(`${SETBACK_PREFIX}front-road-diagonal-reference-surface`);

  const outline = positions.map((p) => Cesium.Cartesian3.fromDegrees(p[0], p[1], p[2]));
  outline.push(outline[0]);
  viewer.entities.add({
    id: `${SETBACK_PREFIX}front-road-diagonal-reference-outline`,
    polyline: {
      positions: outline,
      width: applies ? 4 : 3,
      material: applies
        ? lineC.withAlpha(0.86)
        : new Cesium.PolylineDashMaterialProperty({
            color: lineC.withAlpha(0.72),
            dashLength: 14,
          }),
    },
  });
  addedIds.push(`${SETBACK_PREFIX}front-road-diagonal-reference-outline`);

  viewer.entities.add({
    id: `${SETBACK_PREFIX}front-road-diagonal-reference-label`,
    position: Cesium.Cartesian3.fromDegrees(edgeMid.lng, edgeMid.lat, roadDatum + Math.max(8, innerH * 0.35)),
    label: {
      text: applies
        ? `전면도로 사선\n도로 ${roadWidth.toFixed(1)}m / ${slope}:1`
        : `전면도로 참고\n${slope}:1`,
      font: '700 12px ui-monospace, SFMono-Regular, Menlo, monospace',
      fillColor: Cesium.Color.WHITE,
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 3,
      style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      backgroundColor: Cesium.Color.BLACK.withAlpha(0.46),
      backgroundPadding: new Cesium.Cartesian2(7, 4),
      showBackground: true,
      pixelOffset: new Cesium.Cartesian2(46, -34),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });
  addedIds.push(`${SETBACK_PREFIX}front-road-diagonal-reference-label`);

  return addedIds;
}

