import { requiredValue } from '../required-value';
import { type FacadePalette, facadePaletteFromStyle } from './facade-palette';
import {
  type AtlasView,
  createAtlasPanelCanvas,
  createDesignedFacadeCanvas,
} from './facade-panel-canvas';
import { createPatternCanvas } from './facade-pattern-canvas';

/* eslint-disable @typescript-eslint/no-explicit-any */

export { type FacadePalette, facadePaletteFromStyle } from './facade-palette';

export type RenderFacadeWallParams = {
  viewer: any;
  Cesium: any;
  entityPrefix: string;
  ring: number[][];
  groundH: number;
  bottom: number;
  top: number;
  designId: number;
  segmentKey: string;
  style?: string | null;
  textureUrl?: string | null;
  texturePanelUrls?: Record<string, string> | null;
  floorH: number;
  textureTotalHeight?: number;
};

function normalizedOpenRing(ring: number[][]): number[][] {
  if (ring.length < 2) return ring;
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first && last && Math.abs(requiredValue(first[0]) - requiredValue(last[0])) < 1e-10 && Math.abs(requiredValue(first[1]) - requiredValue(last[1])) < 1e-10) {
    return ring.slice(0, -1);
  }
  return ring;
}

function facadeViewForEdge(a: number[], b: number[], ring: number[][]): AtlasView {
  const xs = ring.map(p => requiredValue(p[0]));
  const ys = ring.map(p => requiredValue(p[1]));
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const mx = (requiredValue(a[0]) + requiredValue(b[0])) / 2;
  const my = (requiredValue(a[1]) + requiredValue(b[1])) / 2;
  const dx = mx - cx;
  const dy = my - cy;
  if (Math.abs(dx) > Math.abs(dy)) return dx >= 0 ? 'right' : 'left';
  return dy >= 0 ? 'back' : 'front';
}

function createFacadeMaterial(
  Cesium: any,
  palette: FacadePalette,
  floorCount: number,
  textureUrl: string | null | undefined,
  texturePanelUrl: string | null | undefined,
  atlasView: AtlasView,
  viewer: any,
  verticalRange?: { bottom: number; top: number; total: number },
): any {
  if ((textureUrl || texturePanelUrl) && Cesium.ImageMaterialProperty) {
    const panelCanvas = createDesignedFacadeCanvas(palette, floorCount, atlasView, texturePanelUrl || textureUrl, viewer)
      || (textureUrl ? createAtlasPanelCanvas(textureUrl, atlasView, viewer, verticalRange) : null);
    return new Cesium.ImageMaterialProperty({
      image: panelCanvas || texturePanelUrl || textureUrl,
      repeat: new Cesium.Cartesian2(1, 1),
      color: Cesium.Color.WHITE.withAlpha(1),
      transparent: false,
    });
  }
  const pattern = createPatternCanvas(palette);
  if (!pattern || !Cesium.ImageMaterialProperty) {
    return Cesium.Color.fromCssColorString(palette.base).withAlpha(palette.alpha);
  }
  return new Cesium.ImageMaterialProperty({
    image: pattern,
    repeat: new Cesium.Cartesian2(1.4, Math.max(1, floorCount * 0.5)),
    color: Cesium.Color.WHITE.withAlpha(0.98),
    transparent: true,
  });
}

export function renderFacadeWallEntities({
  viewer,
  Cesium,
  entityPrefix,
  ring,
  groundH,
  bottom,
  top,
  designId,
  segmentKey,
  style,
  textureUrl,
  texturePanelUrls,
  floorH,
  textureTotalHeight,
}: RenderFacadeWallParams) {
  const palette = facadePaletteFromStyle(style);
  if (!palette || top <= bottom) return;
  const open = normalizedOpenRing(ring);
  if (open.length < 3) return;

  const edgeColor = Cesium.Color.fromCssColorString(palette.edge).withAlpha(0.92);
  const floorColor = Cesium.Color.fromCssColorString(palette.floor).withAlpha(textureUrl ? 0.10 : 0.22);
  const minH = groundH + bottom + 0.04;
  const maxH = groundH + top + 0.04;
  const floorCount = Math.max(1, Math.round((top - bottom) / Math.max(1, floorH)));
  const verticalRange = textureUrl && textureTotalHeight
    ? { bottom, top, total: textureTotalHeight }
    : undefined;
  const baseMaterial = createFacadeMaterial(Cesium, palette, floorCount, textureUrl, texturePanelUrls?.front, 'front', viewer, verticalRange);

  for (let edgeIndex = 0; edgeIndex < open.length; edgeIndex++) {
    const a = requiredValue(open[edgeIndex]);
    const b = requiredValue(open[(edgeIndex + 1) % open.length]);
    const atlasView = textureUrl ? facadeViewForEdge(a, b, open) : 'front';
    const texturePanelUrl = texturePanelUrls?.[atlasView] || null;
    const facadeMaterial = textureUrl
      ? createFacadeMaterial(Cesium, palette, floorCount, textureUrl, texturePanelUrl, atlasView, viewer, verticalRange)
      : baseMaterial;
    viewer.entities.add({
      id: `${entityPrefix}facade-${designId}-${segmentKey}-${edgeIndex}`,
      properties: {
        interactionKind: 'facade_material',
        designId,
        facadeMaterial: palette.label,
        facadeAtlasView: atlasView,
        facadePanelUrl: texturePanelUrl,
        target: { kind: 'facade', segment: segmentKey, edge_index: edgeIndex },
      },
      wall: {
        positions: Cesium.Cartesian3.fromDegreesArray([requiredValue(a[0]), requiredValue(a[1]), requiredValue(b[0]), requiredValue(b[1])]),
        minimumHeights: [minH, minH],
        maximumHeights: [maxH, maxH],
        material: facadeMaterial,
        outline: !textureUrl,
        outlineColor: textureUrl ? edgeColor.withAlpha(0.32) : edgeColor.withAlpha(0.54),
      },
    });

    if (textureUrl) continue;
    for (let floor = 1; floor < floorCount; floor++) {
      const h = groundH + bottom + floor * ((top - bottom) / floorCount) + 0.07;
      viewer.entities.add({
        id: `${entityPrefix}facade-floor-${designId}-${segmentKey}-${edgeIndex}-${floor}`,
        polyline: {
          positions: [
            Cesium.Cartesian3.fromDegrees(requiredValue(a[0]), requiredValue(a[1]), h),
            Cesium.Cartesian3.fromDegrees(requiredValue(b[0]), requiredValue(b[1]), h),
          ],
          width: 1.4,
          material: floorColor,
          clampToGround: false,
        },
      });
    }
  }
}
