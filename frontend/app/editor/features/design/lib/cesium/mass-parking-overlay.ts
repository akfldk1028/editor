import { requiredValue } from '../required-value';
import { extractParkingEnvelopeRing, flattenRing, ringBounds, ringCentroid } from './mass-geometry';

/* eslint-disable @typescript-eslint/no-explicit-any */

export function renderParkingPrecheckOverlay({
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

export function renderPilotiSupports({
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
