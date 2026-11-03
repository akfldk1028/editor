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
  mass?: {
    label: string | null
    volumes: { ring: number[][]; holes?: number[][][]; base_m: number; top_m: number }[]
    /** The delivered glTF at its frame origin; drawn instead of the storey volumes when present. */
    model?: { href: string; origin: [number, number]; heading_deg: number } | null
  } | null
  storeys: number | null
  /** 'diagram': the OMA-style site diagram (accent mass, short labels); the map draws everything else plain. */
  style?: 'diagram' | null
  /** 지하 보기 (on by default): the ground is cut along the basement outline under a translucent ground-floor plate,
   *  so the ground floor reads on the plate and the car park shows through it. */
  cutaway?: boolean
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
const drawnLayouts = new WeakMap<object, { signature: string; count: number; entities: any[] }>()
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
 * Lets the basement be seen when `seeThrough` is asked: the globe turns see-through over the layout's below-ground
 * features (Cesium's translucency rectangle); otherwise, or when the layout has none, it stays opaque. `globe` is the
 * viewer's scene.globe.
 */
export function showUnderground(Cesium: any, globe: any, layout: LayoutView | null, seeThrough = false): boolean {
  if (!globe?.translucency) return false
  const below = (layout?.features ?? []).filter((f) => f.properties.level < 0)
  const coords = below.flatMap((f) => [...rings(f.geometry), ...lines(f.geometry)])
  // Off unless asked: Cesium's see-through globe is not local (the underground colour paints every back face in view,
  // its default black reads as a pit), so by default the basement stays drawn below an opaque ground.
  if (!seeThrough || !coords.length) {
    globe.translucency.enabled = false
    return false
  }
  const lons = coords.flatMap((r) => r.filter((_, k) => k % 2 === 0))
  const lats = coords.flatMap((r) => r.filter((_, k) => k % 2 === 1))
  const pad = 0.0002
  globe.translucency.enabled = true
  globe.translucency.frontFaceAlpha = 0.35
  // Translucent back faces (and an underground colour) switch every globe tile in view to the see-through path: the
  // rectangle only scales alpha, so buildings' buried parts and the globe's undersides showed everywhere as pillars and
  // dark slabs. Opaque back faces keep the see-through local to the rectangle.
  globe.translucency.backFaceAlpha = 1
  globe.translucency.rectangle = Cesium.Rectangle.fromDegrees(
    Math.min(...lons) - pad, Math.min(...lats) - pad, Math.max(...lons) + pad, Math.max(...lats) + pad)
  return true
}

/**
 * When 지하 보기 is on (`layout.cutaway`), cuts the ground open along the basement outline, so the car park below is
 * seen in its own excavation and nowhere else (CesiumJS 1.117+ `Globe.clippingPolygons`, concave outlines included). A see-through globe works only
 * on a rectangle and showed it as a square hole with a black underside (684-1, 2026-11-03). Clears the cut when the
 * layout has no basement. `globe` is the viewer's scene.globe.
 */
export function excavate(Cesium: any, globe: any, layout: LayoutView | null): boolean {
  if (!globe || !Cesium?.ClippingPolygonCollection) return false
  const outlines = (layout?.cutaway ? layout.features : [])
    .filter((f) => f.properties.layer === 'basement_boundary' && f.properties.level < 0)
    .flatMap((f) => rings(f.geometry))
    .filter((ring) => ring.length >= 6)
  if (!outlines.length) {
    globe.clippingPolygons = undefined
    return false
  }
  globe.clippingPolygons = new Cesium.ClippingPolygonCollection({
    polygons: outlines.map((ring) => new Cesium.ClippingPolygon({ positions: Cesium.Cartesian3.fromDegreesArray(ring) })),
  })
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
  drawnLayouts.delete(entities)
  for (const e of [...entities.values]) if (String(e.id).startsWith(PREFIX)) entities.remove(e)
}

/** Draws the layout; returns how many entities were added. `base` is the ground the context masses stand on. */
/** The diagram's one accent: the planned building against white context (OMA-style site diagrams). */
const DIAGRAM_ACCENT: [number, number, number] = [0.96, 0.36, 0.16]

/** Short diagram labels: the planned building (storeys) and the car park below (stall count), always on top. */
function drawDiagramLabels(entities: any, Cesium: any, layout: LayoutView, base: number): number {
  const label = (id: string, text: string, ring: number[] | undefined, height: number, colour: string) => {
    if (!ring || ring.length < 2) return 0
    const lons = ring.filter((_, k) => k % 2 === 0), lats = ring.filter((_, k) => k % 2 === 1)
    entities.add({
      id: `${PREFIX}label-${id}`,
      position: Cesium.Cartesian3.fromDegrees(lons.reduce((a, b) => a + b, 0) / lons.length,
        lats.reduce((a, b) => a + b, 0) / lats.length, base + height),
      label: {
        text, font: '600 13px Pretendard, "Noto Sans KR", sans-serif',
        fillColor: Cesium.Color.fromCssColorString(colour), showBackground: true,
        backgroundColor: Cesium.Color.WHITE.withAlpha(0.92),
        ...(base === 0 ? { heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND } : {}),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    })
    return 1
  }
  const footprint = layout.features.find((f) => f.properties.layer === 'building_footprint')
  const basement = layout.features.find((f) => f.properties.layer === 'basement_boundary' && f.properties.level < 0)
  const below = layout.features.filter((f) => f.properties.layer === 'parking_stall' && f.properties.level < 0).length
  const top = (layout.height_m ?? (layout.storeys ?? 1) * layout.storey_height_m) + 3
  return label('building', `계획 건물${layout.storeys ? ` · ${layout.storeys}F` : ''}`, footprint && rings(footprint.geometry)[0], top, '#111111')
    + (below ? label('parking', `B${-(basement?.properties.level ?? -1)} 주차 ${below}대`,
      basement && rings(basement.geometry)[0], 1, '#1d4ed8') : 0)
}

/** A fragment shader lighting each flat face by its screen-space normal (for glTF without normals). */
export function facetShader(rgb: [number, number, number]): string {
  const [r, g, b] = rgb.map((c) => c.toFixed(3))
  return `void fragmentMain(FragmentInput fsInput, inout czm_modelMaterial material) {
  vec3 p = fsInput.attributes.positionEC;
  vec3 n = normalize(cross(dFdx(p), dFdy(p)));
  float light = 0.45 + 0.55 * abs(dot(n, normalize(vec3(0.35, 0.6, 0.7))));
  material.diffuse = vec3(${r}, ${g}, ${b}) * light;
}`
}

/** Heading that turns Cesium's +X-forward glTF frame onto the site frame's east (see drawLayout). */
export const GLTF_FORWARD_DEG = 90

/** The editor's design proxy URL of a delivered artifact href (`design/maas/delivered-mass-export/...`). */
export function modelUrl(href: string): string {
  const base = (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_BASE_PATH) || ''
  return `${base}/api/v1/${href.replace(/^\/+/, '')}`
}

export function drawLayout(entities: any, Cesium: any, layout: LayoutView, intent: IntentView | null | undefined, base: Ground = 0): number {
  const signature = JSON.stringify([layout, intent ?? null, base])
  const previous = drawnLayouts.get(entities)
  const current = entities.values.filter((e: any) => String(e.id).startsWith(PREFIX))
  if (previous?.signature === signature && current.length === previous.entities.length
    && current.every((e: any, i: number) => e === previous.entities[i])) return previous.count
  clearLayout(entities)
  const glazed = glazedFacade(intent)
  const wall = Cesium.Color.fromCssColorString(glazed ? '#8fc3e8' : '#e8d9c2')
  const wallEdge = Cesium.Color.fromCssColorString(glazed ? '#2f6f9f' : '#8a6d4b')
  const unknown = Cesium.Color.fromCssColorString('#f1e7d8')
  const stall = Cesium.Color.fromCssColorString('#ffffff').withAlpha(0.5)
  const stallEdge = Cesium.Color.fromCssColorString('#6b7280')
  const aisle = Cesium.Color.fromCssColorString('#cfd4da').withAlpha(0.6)
  const access = Cesium.Color.fromCssColorString('#f59e0b').withAlpha(0.6)
  const buildable = Cesium.Color.fromCssColorString('#16a34a')
  const buildableArea = Cesium.Color.fromCssColorString('#22c55e').withAlpha(0.14)
  const plate = Cesium.Color.fromCssColorString('#64748b').withAlpha(0.35)
  const plateEdge = Cesium.Color.fromCssColorString('#334155')
  const pitWall = Cesium.Color.fromCssColorString('#a8a29e').withAlpha(0.95)
  const groundLid = Cesium.Color.fromCssColorString('#ece7dc').withAlpha(0.55)
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
    if (layer === 'building_footprint' && layout.mass?.model) {
      if (index !== layout.features.findIndex((g) => g.properties.layer === 'building_footprint')) return
      // The chosen form as Mass delivered it (sloped roofs, notches): storey volumes cut at mid-height lose them.
      // glTF is y-up in site-local metres from the frame origin; the heading turns grid north onto true north.
      // Cesium stands a glTF with its +X forward, so heading 0 lays the frame's east along north: measured on 684-1,
      // the model's centre landed 37 m west and 51 m north of where its +52 m east / +36 m north mesh belongs.
      // A further 90 degrees clockwise puts the frame's east on east.
      const model = layout.mass.model
      const position = Cesium.Cartesian3.fromDegrees(model.origin[0], model.origin[1], onTerrain ? 0 : ground)
      entities.add({
        id: `${PREFIX}building-mass-model`,
        name: `계획 건물 · ${layout.mass.label ?? 'Mass 안'}`,
        position,
        orientation: Cesium.Transforms.headingPitchRollQuaternion(
          position, new Cesium.HeadingPitchRoll(Cesium.Math.toRadians(model.heading_deg + GLTF_FORWARD_DEG), 0, 0)),
        model: {
          uri: modelUrl(model.href),
          // The delivered glTF carries positions only: unlit it is one flat colour, the same cream as the parcel
          // plate under it. Each face is shaded by its own normal, taken from the screen-space derivatives.
          customShader: new Cesium.CustomShader({
            lightingModel: Cesium.LightingModel.UNLIT,
            fragmentShaderText: facetShader(layout.style === 'diagram' ? DIAGRAM_ACCENT : glazed ? [0.56, 0.76, 0.91] : [0.93, 0.87, 0.78]),
          }),
          silhouetteColor: wallEdge,
          silhouetteSize: 1,
          ...(onTerrain ? { heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND } : {}),
        },
      })
      n++
      return
    }
    if (layer === 'building_footprint' && layout.mass?.volumes.length) {
      if (index !== layout.features.findIndex((g) => g.properties.layer === 'building_footprint')) return
      layout.mass.volumes.forEach((v, i) => {
        const degrees = (ring: number[][]) => Cesium.Cartesian3.fromDegreesArray(ring.flatMap((c) => [c[0]!, c[1]!]))
        // A courtyard form is one ring with the court as a hole, so the court stays open ground.
        const hierarchy = v.holes?.length
          ? new Cesium.PolygonHierarchy(degrees(v.ring), v.holes.map((hole) => new Cesium.PolygonHierarchy(degrees(hole))))
          : degrees(v.ring)
        entities.add({
          id: `${PREFIX}building-mass-${i}`,
          name: `계획 건물 · ${layout.mass!.label ?? 'Mass 안'}`,
          description: `${Math.round(v.base_m * 10) / 10}~${Math.round(v.top_m * 10) / 10} m`,
          polygon: {
            hierarchy,
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
        if (!layout.cutaway) return
        // The ground floor over the excavation: a translucent plate at grade, so the site's ground-level layout
        // (entrances, paths, landscape) still reads on it while the car park shows through below.
        entities.add({
          id: `${PREFIX}basement-lid-${index}-${i}`,
          name: '지상 1층 바닥 (지하 투시)',
          polygon: { hierarchy: Cesium.Cartesian3.fromDegreesArray(ring), ...flat(0.02), material: groundLid,
            outline: true, outlineColor: plateEdge },
        })
        n++
        // The excavation's sides (`excavate` cuts the ground to this outline): open top and bottom, ground to floor.
        entities.add({
          id: `${PREFIX}basement-wall-${index}-${i}`,
          name: `지하 ${-level}층 굴착 벽`,
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(ring),
            ...(onTerrain
              ? { height: depth, extrudedHeight: 0, heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND, extrudedHeightReference: Cesium.HeightReference.RELATIVE_TO_GROUND }
              : { height: ground + depth, extrudedHeight: ground }),
            closeTop: false,
            closeBottom: false,
            material: pitWall,
            outline: true,
            outlineColor: plateEdge,
          },
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
            ...(onTerrain ? { classificationType: Cesium.ClassificationType.TERRAIN } : {}),
            width: 2.5,
            // Solid green: the parcel's own outline is a red dashed line, and the two read as one where they meet.
            material: buildable,
          },
        })
        n++
      })
      rings(f.geometry).forEach((ring, i) => {
        entities.add({
          id: `${PREFIX}buildable-area-${index}-${i}`,
          name: '건축 가능 범위',
          polygon: { hierarchy: Cesium.Cartesian3.fromDegreesArray(ring), material: buildableArea,
            ...(onTerrain ? { classificationType: Cesium.ClassificationType.TERRAIN } : { height: ground + 0.05 }) },
        })
        n++
      })
    }
  })
  if (layout.style === 'diagram') n += drawDiagramLabels(entities, Cesium, layout, onTerrain ? 0 : ground)
  entities.resumeEvents()
  drawnLayouts.set(entities, { signature, count: n,
    entities: entities.values.filter((e: any) => String(e.id).startsWith(PREFIX)) })
  return n
}
