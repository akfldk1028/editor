import { requiredValue } from '../required-value';
import type { GeoJSONFeature } from '../types';
import { renderFacadeWallEntities } from './facade-materials';
import {
  buildSectionRenderSegments,
  extractRing,
  extractSectionProfile,
  flattenRing,
  getGroundHeight,
  ringCentroid,
} from './mass-geometry';
import { renderParkingPrecheckOverlay } from './mass-parking-overlay';
import { attachTexturedGltfModel, clearMassEntities } from './mass-primitives';
import { renderSectionProfileOverlay } from './mass-section-profile';
import { SHAPE_COLORS } from './mass-styles';

export { clearMassEntities } from './mass-primitives';

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
