/**
 * Our building on the site: the MasterPlan Agent's layout (the editor's `RunResults.masterplan`) drawn over the
 * parcel in the 3D view — the footprint extruded to the storeys the result names (an assumption the result states),
 * parking stalls and the aisle flat on the ground, the buildable boundary as a dashed line. The declared intent
 * colours the facade: words for glass (커튼월, 유리, curtain wall, glass) give a glazed tint, otherwise a warm wall.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import type { Ground } from './context-masses'

export interface LayoutFeature {
  type: 'Feature'
  geometry: { type: string; coordinates: any }
  properties: { layer: string; level: number; area_m2: number | null }
}

export interface LayoutView {
  features: LayoutFeature[]
  /** The Mass form chosen to stand on the zone (volumes from base to top); the footprint box is drawn without one. */
  mass?: { label: string | null; volumes: { ring: number[][]; base_m: number; top_m: number }[] } | null
  storeys: number | null
  storey_height_m: number
  height_m: number | null
  height_basis: string | null
  footprint_m2: number | null
  coverage_pct: number | null
}

export interface IntentView {
  parti?: string
  material_attitude?: string | unknown
  massing_strategy?: string | unknown
  exterior_relationship?: string | unknown
}

const PREFIX = 'layout-'
const GLAZED = /커튼월|유리|curtain\s*wall|glass|glazed/i
/** A footprint whose storeys are not known is shown one storey high and pale, never given a made-up height. */
const UNKNOWN_STOREY_M = 3.5

/** Does the intent read as a glazed facade? Any intent text (parti, material attitude, massing) is searched. */
export function glazedFacade(intent: IntentView | null | undefined): boolean {
  if (!intent) return false
  return Object.values(intent).some((value) => GLAZED.test(typeof value === 'string' ? value : JSON.stringify(value ?? '')))
}

function rings(geometry: any): number[][] {
  const polys = geometry?.type === 'Polygon' ? [geometry.coordinates] : geometry?.type === 'MultiPolygon' ? geometry.coordinates : []
  return polys
    .filter((p: any) => Array.isArray(p?.[0]) && p[0].length >= 4)
    .map((p: any) => p[0].flatMap((c: number[]) => [c[0], c[1]]))
}

function lines(geometry: any): number[][] {
  const parts = geometry?.type === 'LineString' ? [geometry.coordinates] : geometry?.type === 'MultiLineString' ? geometry.coordinates : []
  return parts.filter((l: any) => Array.isArray(l) && l.length >= 2).map((l: any) => l.flatMap((c: number[]) => [c[0], c[1]]))
}

export function clearLayout(entities: any): void {
  for (const e of [...entities.values]) if (String(e.id).startsWith(PREFIX)) entities.remove(e)
}

/** Draws the layout; returns how many entities were added. `base` is the ground the context masses stand on. */
export function drawLayout(entities: any, Cesium: any, layout: LayoutView, intent: IntentView | null | undefined, base: Ground = 0): number {
  clearLayout(entities)
  const glazed = glazedFacade(intent)
  const wall = Cesium.Color.fromCssColorString(glazed ? '#8fc3e8' : '#e8d9c2').withAlpha(glazed ? 0.75 : 0.96)
  const wallEdge = Cesium.Color.fromCssColorString(glazed ? '#2f6f9f' : '#8a6d4b')
  const unknown = Cesium.Color.fromCssColorString('#f1e7d8').withAlpha(0.6)
  const stall = Cesium.Color.fromCssColorString('#ffffff').withAlpha(0.5)
  const stallEdge = Cesium.Color.fromCssColorString('#6b7280')
  const aisle = Cesium.Color.fromCssColorString('#cfd4da').withAlpha(0.6)
  const access = Cesium.Color.fromCssColorString('#f59e0b').withAlpha(0.6)
  const buildable = Cesium.Color.fromCssColorString('#d14343')
  const onTerrain = base === 'terrain'
  const ground = onTerrain ? 0 : base
  const flat = (z: number) => onTerrain
    ? { height: z, heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND }
    : { height: ground + z }
  let n = 0
  entities.suspendEvents()
  layout.features.forEach((f, index) => {
    const layer = f.properties.layer
    if (layer === 'building_footprint' && layout.mass?.volumes.length) {
      if (index !== layout.features.findIndex((g) => g.properties.layer === 'building_footprint')) return
      layout.mass.volumes.forEach((v, i) => {
        const ring = v.ring.flatMap((c) => [c[0]!, c[1]!])
        entities.add({
          id: `${PREFIX}building-mass-${i}`,
          name: `계획 건물 · ${layout.mass!.label ?? 'Mass 안'}`,
          description: `${Math.round(v.base_m * 10) / 10}~${Math.round(v.top_m * 10) / 10} m`,
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(ring),
            ...(onTerrain
              ? { height: v.base_m, extrudedHeight: v.top_m, heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND, extrudedHeightReference: Cesium.HeightReference.RELATIVE_TO_GROUND }
              : { height: ground + v.base_m, extrudedHeight: ground + v.top_m }),
            material: wall,
            outline: true,
            outlineColor: wallEdge,
          },
        })
        n++
      })
      return
    }
    if (layer === 'building_footprint') {
      const height = layout.height_m ?? UNKNOWN_STOREY_M
      rings(f.geometry).forEach((ring, i) => {
        entities.add({
          id: `${PREFIX}building-${index}-${i}`,
          name: '계획 건물',
          description: layout.storeys ? `${layout.storeys}층 · ${layout.height_basis ?? ''}` : (layout.height_basis ?? '층수 미정'),
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(ring),
            ...(onTerrain
              ? { height: -2, extrudedHeight: height, heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND, extrudedHeightReference: Cesium.HeightReference.RELATIVE_TO_GROUND }
              : { height: ground, extrudedHeight: ground + height }),
            material: layout.storeys ? wall : unknown,
            outline: true,
            outlineColor: wallEdge,
          },
        })
        n++
      })
      return
    }
    if (layer === 'parking_stall' || layer === 'parking_aisle' || layer === 'vehicular_access') {
      const material = layer === 'parking_stall' ? stall : layer === 'parking_aisle' ? aisle : access
      rings(f.geometry).forEach((ring, i) => {
        entities.add({
          id: `${PREFIX}${layer}-${index}-${i}`,
          name: layer === 'parking_stall' ? '주차 구획' : layer === 'parking_aisle' ? '차로' : '차량 진입',
          polygon: { hierarchy: Cesium.Cartesian3.fromDegreesArray(ring), ...flat(0.25), material, outline: layer === 'parking_stall', outlineColor: stallEdge },
        })
        n++
      })
      return
    }
    if (layer === 'buildable_boundary') {
      const strokes = [...rings(f.geometry), ...lines(f.geometry)]
      strokes.forEach((line, i) => {
        entities.add({
          id: `${PREFIX}buildable-${index}-${i}`,
          name: '건축 가능 범위',
          polyline: {
            positions: onTerrain ? Cesium.Cartesian3.fromDegreesArray(line) : Cesium.Cartesian3.fromDegreesArrayHeights(line.flatMap((v, k) => (k % 2 ? [v, ground + 0.6] : [v]))),
            clampToGround: onTerrain,
            width: 2,
            material: new Cesium.PolylineDashMaterialProperty({ color: buildable, dashLength: 12 }),
          },
        })
        n++
      })
    }
  })
  entities.resumeEvents()
  return n
}
