import { requiredValue } from '../required-value';
import { midpoint, clippedLineSegment, lngLatToLocalMeters, offsetPointMeters } from '../site-map-geometry';
import { SETBACK_PREFIX } from '../cesium/site-scene';

export function renderDaylightDiagonalEnvelope(
  viewer: any,
  Cesium: any,
  envelope: {
    walls?: Array<{ positions?: number[][]; min_heights?: number[]; max_heights?: number[] }>;
    surface_polygons?: Array<{ positions?: number[][]; max_heights?: number[] }>;
    reference_edges?: Array<{ positions?: number[][]; height_m?: number }>;
    multiplier?: number;
  } | null | undefined,
  colors: { wall: string },
  datumElevationM: number,
) {
  if (!envelope?.walls?.length && !envelope?.surface_polygons?.length) return;
  const color = Cesium.Color.fromCssColorString(colors.wall);
  const params = new URLSearchParams(window.location.search);
  const detailed = params.get('daylight') === 'detail' || params.get('layers') === 'all';
  if (!detailed && envelope.walls?.length) {
    const wall = requiredValue(envelope.walls[0]);
    if (wall.positions && wall.positions.length >= 2) {
      const edgeA = { lng: requiredValue(requiredValue(wall.positions[0])[0]), lat: requiredValue(requiredValue(wall.positions[0])[1]) };
      const edgeB = { lng: requiredValue(requiredValue(wall.positions[1])[0]), lat: requiredValue(requiredValue(wall.positions[1])[1]) };
      const edgeMid = midpoint(edgeA, edgeB);
      const origin = edgeMid;
      const [a, b] = clippedLineSegment(edgeA, edgeB, origin, 30);
      const centroidLng = wall.positions.reduce((sum, p) => sum + requiredValue(p[0]), 0) / wall.positions.length;
      const centroidLat = wall.positions.reduce((sum, p) => sum + requiredValue(p[1]), 0) / wall.positions.length;
      const midLocal = lngLatToLocalMeters(edgeMid, origin);
      const insideLocal = lngLatToLocalMeters({ lng: centroidLng, lat: centroidLat }, origin);
      const inwardRaw = { x: insideLocal.x - midLocal.x, y: insideLocal.y - midLocal.y };
      const inwardLen = Math.hypot(inwardRaw.x, inwardRaw.y);
      if (inwardLen > 0.01) {
        const inward = { x: inwardRaw.x / inwardLen, y: inwardRaw.y / inwardLen };
        const depth = Math.min(18, Math.max(10, ((envelope as { max_depth_m?: number }).max_depth_m ?? 12)));
        const slope = (envelope as { multiplier?: number }).multiplier ?? 2;
        const innerB = offsetPointMeters(b, origin, inward, depth);
        const innerA = offsetPointMeters(a, origin, inward, depth);
        const innerH = depth * slope;
        const positions = [
          [a.lng, a.lat, datumElevationM],
          [b.lng, b.lat, datumElevationM],
          [innerB.lng, innerB.lat, datumElevationM + innerH],
          [innerA.lng, innerA.lat, datumElevationM + innerH],
        ];
        const flatHeights: number[] = [];
        positions.forEach((p) => flatHeights.push(requiredValue(p[0]), requiredValue(p[1]), requiredValue(p[2])));
        viewer.entities.add({
          id: `${SETBACK_PREFIX}daylight_diagonal_reference-section-surface`,
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArrayHeights(flatHeights),
            perPositionHeight: true,
            material: color.withAlpha(0.22),
            outline: false,
          },
        });
        const outline = positions.map((p) => Cesium.Cartesian3.fromDegrees(p[0], p[1], p[2]));
        outline.push(outline[0]);
        viewer.entities.add({
          id: `${SETBACK_PREFIX}daylight_diagonal_reference-section-outline`,
          polyline: {
            positions: outline,
            width: 3,
            material: color.withAlpha(0.72),
          },
        });
      }
    }
    return;
  }
  const surfaces = envelope.surface_polygons ?? [];
  if (surfaces.length) {
    let labelPoint: number[] | null = null;
    let labelHeight = 0;
    for (let i = 0; i < surfaces.length; i++) {
      const surface = requiredValue(surfaces[i]);
      if (!surface.positions || surface.positions.length < 3) continue;
      const heights = surface.max_heights ?? surface.positions.map(() => 0);
      const flatHeights: number[] = [];
      for (let j = 0; j < surface.positions.length; j++) {
        const p = requiredValue(surface.positions[j]);
        const h = heights[j] ?? 0;
        flatHeights.push(requiredValue(p[0]), requiredValue(p[1]), datumElevationM + h);
        if (h > labelHeight) {
          labelHeight = h;
          labelPoint = p;
        }
      }
      viewer.entities.add({
        id: `${SETBACK_PREFIX}daylight_diagonal_envelope-surface-${i}`,
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArrayHeights(flatHeights),
          perPositionHeight: true,
          material: color.withAlpha(detailed ? 0.24 : 0.22),
          outline: false,
        },
      });
      const outlinePositions = surface.positions.map((p, j) =>
        Cesium.Cartesian3.fromDegrees(p[0], p[1], datumElevationM + (heights[j] ?? 0)),
      );
      outlinePositions.push(outlinePositions[0]);
      viewer.entities.add({
        id: `${SETBACK_PREFIX}daylight_diagonal_envelope-surface-outline-${i}`,
        polyline: {
          positions: outlinePositions,
          width: detailed ? 4 : 2,
          material: color.withAlpha(detailed ? 0.90 : 0.62),
        },
      });
    }

    if (detailed) {
      for (let i = 0; i < (envelope.reference_edges ?? []).length; i++) {
        const edge = envelope.reference_edges?.[i];
        if (!edge?.positions || edge.positions.length < 2) continue;
        viewer.entities.add({
          id: `${SETBACK_PREFIX}daylight_diagonal_envelope-reference-edge-${i}`,
          polyline: {
            positions: edge.positions.map(p => Cesium.Cartesian3.fromDegrees(p[0], p[1], datumElevationM + (edge.height_m ?? 0))),
            width: 4,
            material: color.withAlpha(0.95),
          },
        });
      }
    }

    if (detailed && labelPoint) {
      viewer.entities.add({
        id: `${SETBACK_PREFIX}daylight_diagonal_envelope-label`,
        position: Cesium.Cartesian3.fromDegrees(labelPoint[0], labelPoint[1], datumElevationM + Math.max(8, labelHeight * 0.45)),
        label: {
          text: `채광사선 참고\n공동주택 창면 × ${((envelope as { multiplier?: number }).multiplier ?? 2).toFixed(0)}`,
          font: '700 12px ui-monospace, SFMono-Regular, Menlo, monospace',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          backgroundColor: Cesium.Color.BLACK.withAlpha(0.44),
          backgroundPadding: new Cesium.Cartesian2(7, 4),
          showBackground: true,
          pixelOffset: new Cesium.Cartesian2(-36, -28),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }
    if (!detailed) return;
  }

  const walls = envelope.walls ?? [];
  for (let i = 0; i < walls.length; i++) {
    const wall = requiredValue(walls[i]);
    if (!wall.positions || wall.positions.length < 2) continue;
    const heights = wall.max_heights ?? wall.positions.map(() => 0);
    const flatHeights: number[] = [];
    for (let j = 0; j < wall.positions.length; j++) {
      const p = requiredValue(wall.positions[j]);
      flatHeights.push(requiredValue(p[0]), requiredValue(p[1]), datumElevationM + (heights[j] ?? 0));
    }

    // Backend gives this daylight envelope as a sloped quadrilateral:
    // boundary edge at H=0 and inward edge at H=d*multiplier.
    // Rendering it as Cesium `wall` folds the 4-point polygon into vertical
    // fence pieces, which is visually and legally misleading. Use an actual
    // per-vertex-height polygon instead.
    viewer.entities.add({
      id: `${SETBACK_PREFIX}daylight_diagonal_envelope-${i}`,
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArrayHeights(flatHeights),
        perPositionHeight: true,
        material: color.withAlpha(detailed ? 0.20 : 0.14),
        outline: false,
      },
    });
    const outlinePositions = wall.positions.map((p, j) =>
      Cesium.Cartesian3.fromDegrees(p[0], p[1], datumElevationM + (heights[j] ?? 0)),
    );
    outlinePositions.push(outlinePositions[0]);
    viewer.entities.add({
      id: `${SETBACK_PREFIX}daylight_diagonal_envelope-outline-${i}`,
      polyline: {
        positions: outlinePositions,
        width: detailed ? 4 : 2,
        material: color.withAlpha(detailed ? 0.90 : 0.58),
      },
    });

    if (detailed && wall.positions.length >= 4) {
      const edgeMid = midpoint(
        { lng: requiredValue(requiredValue(wall.positions[0])[0]), lat: requiredValue(requiredValue(wall.positions[0])[1]) },
        { lng: requiredValue(requiredValue(wall.positions[1])[0]), lat: requiredValue(requiredValue(wall.positions[1])[1]) },
      );
      const innerMid = midpoint(
        { lng: requiredValue(requiredValue(wall.positions[wall.positions.length - 1])[0]), lat: requiredValue(requiredValue(wall.positions[wall.positions.length - 1])[1]) },
        { lng: requiredValue(requiredValue(wall.positions[2])[0]), lat: requiredValue(requiredValue(wall.positions[2])[1]) },
      );
      const maxHeight = Math.max(...heights);
      viewer.entities.add({
        id: `${SETBACK_PREFIX}daylight_diagonal_profile-${i}`,
        polyline: {
          positions: [
            Cesium.Cartesian3.fromDegrees(edgeMid.lng, edgeMid.lat, datumElevationM),
            Cesium.Cartesian3.fromDegrees(innerMid.lng, innerMid.lat, datumElevationM + maxHeight),
          ],
          width: detailed ? 6 : 4,
          material: color.withAlpha(0.92),
        },
      });
    }

    const labelPoint = requiredValue(wall.positions[Math.floor(wall.positions.length / 2)]);
    const maxHeight = Math.max(...heights);
    if (i === 0 && labelPoint) {
      viewer.entities.add({
        id: `${SETBACK_PREFIX}daylight_diagonal_envelope-label`,
        position: Cesium.Cartesian3.fromDegrees(labelPoint[0], labelPoint[1], datumElevationM + Math.max(8, maxHeight * 0.45)),
        label: {
          text: `채광사선 참고\n공동주택 창면 × ${((envelope as { multiplier?: number }).multiplier ?? 2).toFixed(0)}`,
          font: '700 12px ui-monospace, SFMono-Regular, Menlo, monospace',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          backgroundColor: Cesium.Color.BLACK.withAlpha(0.44),
          backgroundPadding: new Cesium.Cartesian2(7, 4),
          showBackground: true,
          pixelOffset: new Cesium.Cartesian2(-36, -28),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
    }
  }
  try {
    viewer.scene?.requestRender?.();
  } catch { /* ignore */ }
}

