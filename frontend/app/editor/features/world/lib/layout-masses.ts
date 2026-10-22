/**
 * Our building on the site: the MasterPlan Agent's layout (the editor's `RunResults.masterplan`) drawn over the
 * parcel in the 3D view — the footprint extruded to the storeys the result names (an assumption the result states),
 * parking stalls and the aisle flat on the ground, the buildable boundary as a dashed line. The declared intent
 * colours the facade: words for glass (커튼월, 유리, curtain wall, glass) give a glazed tint, otherwise a warm wall.
 * A feature below the ground (level < 0) is drawn at its level's depth: the basement plate, its stalls and aisle, and
 * the ramp sloping down along its own height profile. The ground over the basement is made see-through
 * (`showUnderground`), otherwise the terrain hides all of it.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import type { Ground } from './context-masses'

export interface LayoutFeature {
  type: 'Feature'
  geometry: { type: string; coordinates: any }
  properties: { layer: string; level: number; area_m2: number | null; profile?: { distance_m: number; z_m: number }[] }
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
/** Depth of one basement level, as MasterPlan's ramps descend (their profile ends at -3.3 m per level). */
export const BASEMENT_STOREY_M = 3.3

/** The depth (m, negative) a feature of `level` is drawn at; 0 for the ground and above. */
export function levelDepth(level: number): number {
  return level < 0 ? level * BASEMENT_STOREY_M : 0
}

type Profile = { distance_m: number; z_m: number }[]

/** Height of each ramp vertex: its distance along the centreline (local metres) read on the ramp's profile. */
export function rampHeights(ring: number[], centreline: number[] | null, profile: Profile): number[] {
  const pts: [number, number][] = []
  for (let i = 0; i < ring.length; i += 2) pts.push([ring[i]!, ring[i + 1]!])
  const lowest = Math.min(0, ...profile.map((p) => p.z_m))
  if (!centreline || centreline.length < 4 || profile.length < 2) return pts.map(() => lowest / 2)
  const lat0 = (centreline[1]! * Math.PI) / 180
  const toM = (lon: number, lat: number): [number, number] => [lon * 111_320 * Math.cos(lat0), lat * 110_540]
  const line: [number, number][] = []
  for (let i = 0; i < centreline.length; i += 2) line.push(toM(centreline[i]!, centreline[i + 1]!))
  const along = (q: [number, number]): number => {
    let best = Infinity
    let at = 0
    let run = 0
    for (let i = 0; i + 1 < line.length; i++) {
      const a = line[i]!
      const b = line[i + 1]!
      const dx = b[0] - a[0]
      const dy = b[1] - a[1]
      const len = Math.hypot(dx, dy) || 1e-9
      const t = Math.max(0, Math.min(1, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / (len * len)))
      const d = Math.hypot(q[0] - a[0] - t * dx, q[1] - a[1] - t * dy)
      if (d < best) {
        best = d
        at = run + t * len
      }
      run += len
    }
    return at
  }
  const z = (d: number): number => {
    if (d <= profile[0]!.distance_m) return profile[0]!.z_m
    for (let i = 0; i + 1 < profile.length; i++) {
      const a = profile[i]!
      const b = profile[i + 1]!
      if (d <= b.distance_m) return a.z_m + (b.z_m - a.z_m) * ((d - a.distance_m) / Math.max(b.distance_m - a.distance_m, 1e-9))
    }
    return profile[profile.length - 1]!.z_m
  }
  return pts.map(([lon, lat]) => z(along(toM(lon, lat))))
}

/**
 * Lets the basement be seen: the globe turns see-through over the layout's below-ground features only (Cesium's
 * translucency rectangle), and back to opaque when the layout has none. `globe` is the viewer's scene.globe.
 */
export function showUnderground(Cesium: any, globe: any, layout: LayoutView | null): boolean {
  if (!globe?.translucency) return false
  const below = (layout?.features ?? []).filter((f) => f.properties.level < 0)
  const coords = below.flatMap((f) => [...rings(f.geometry), ...lines(f.geometry)])
  if (!coords.length) {
    globe.translucency.enabled = false
    return false
  }
  const lons = coords.flatMap((r) => r.filter((_, k) => k % 2 === 0))
  const lats = coords.flatMap((r) => r.filter((_, k) => k % 2 === 1))
  const pad = 0.0002
  globe.translucency.enabled = true
  globe.translucency.frontFaceAlpha = 0.35
  globe.translucency.backFaceAlpha = 0.35
  globe.translucency.rectangle = Cesium.Rectangle.fromDegrees(
    Math.min(...lons) - pad, Math.min(...lats) - pad, Math.max(...lons) + pad, Math.max(...lats) + pad)
  globe.undergroundColor = Cesium.Color.fromCssColorString('#3b3f45').withAlpha(0.6)
  return true
}

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
  const plate = Cesium.Color.fromCssColorString('#64748b').withAlpha(0.35)
  const plateEdge = Cesium.Color.fromCssColorString('#334155')
  const lowStall = Cesium.Color.fromCssColorString('#93c5fd').withAlpha(0.7)
  const lowAisle = Cesium.Color.fromCssColorString('#fde68a').withAlpha(0.7)
  const rampColour = Cesium.Color.fromCssColorString('#ef4444').withAlpha(0.7)
  const centreline = layout.features.find((f) => f.properties.layer === 'ramp_centerline')
  const centrelineCoords = centreline ? (lines(centreline.geometry)[0] ?? null) : null
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
    const level = f.properties.level
    const depth = levelDepth(level)
    if (layer === 'parking_stall' || layer === 'parking_aisle' || layer === 'vehicular_access') {
      const below = level < 0
      const material = layer === 'parking_stall' ? (below ? lowStall : stall) : layer === 'parking_aisle' ? (below ? lowAisle : aisle) : access
      const where = below ? `지하 ${-level}층 ` : ''
      rings(f.geometry).forEach((ring, i) => {
        entities.add({
          id: `${PREFIX}${layer}-${index}-${i}`,
          name: where + (layer === 'parking_stall' ? '주차 구획' : layer === 'parking_aisle' ? '차로' : '차량 진입'),
          polygon: { hierarchy: Cesium.Cartesian3.fromDegreesArray(ring), ...flat(depth + 0.25), material, outline: layer === 'parking_stall', outlineColor: stallEdge },
        })
        n++
      })
      return
    }
    if (layer === 'basement_boundary') {
      rings(f.geometry).forEach((ring, i) => {
        entities.add({
          id: `${PREFIX}basement-${index}-${i}`,
          name: `지하 ${-level}층 바닥`,
          description: f.properties.area_m2 != null ? `${Math.round(f.properties.area_m2)}㎡` : undefined,
          polygon: { hierarchy: Cesium.Cartesian3.fromDegreesArray(ring), ...flat(depth), material: plate, outline: true, outlineColor: plateEdge },
        })
        n++
      })
      return
    }
    if (layer === 'ramp') {
      const profile: Profile = f.properties.profile && f.properties.profile.length >= 2
        ? f.properties.profile
        : [{ distance_m: 0, z_m: 0 }, { distance_m: 1, z_m: depth }]
      rings(f.geometry).forEach((ring, i) => {
        const heights = rampHeights(ring, centrelineCoords, profile)
        // Flat ground: each vertex at its own height (a sloped surface). On terrain a polygon cannot follow both the
        // terrain and its own slope, so the ramp is drawn level at its mean depth there.
        const mean = heights.reduce((a, b) => a + b, 0) / Math.max(heights.length, 1)
        entities.add({
          id: `${PREFIX}ramp-${index}-${i}`,
          name: '램프',
          polygon: onTerrain
            ? { hierarchy: Cesium.Cartesian3.fromDegreesArray(ring), ...flat(mean), material: rampColour }
            : {
                hierarchy: Cesium.Cartesian3.fromDegreesArrayHeights(ring.flatMap((v, k) => (k % 2 ? [v, ground + heights[(k - 1) / 2]!] : [v]))),
                perPositionHeight: true,
                material: rampColour,
              },
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
