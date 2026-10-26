/**
 * Clean context: the buildings around a point as white masses.
 * SceneAgent answers (SiteContext footprints + its height rule); each building says whether its height is
 * measured, estimated from storeys, or unknown — unknown ones are drawn pale and low, never given a made-up height.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import { GroundStages, roadKey } from './ground-stages'

export interface ContextReply {
  status: 'ok' | 'needs_evidence'
  features?: { type: 'FeatureCollection'; features: any[] }
  counts?: { measured: number; estimated: number; unknown: number }
  reason?: string
  record?: Record<string, unknown>
  gaps?: unknown[]
  /** Absolute freshness of a prepared display snapshot, retained across browser caches. */
  displaySnapshot?: { sampledAt: string; expiresAt: number }
}

export const fetchContextBuildings = (lat: number, lon: number, radiusM: number, signal?: AbortSignal) =>
  fetchContext('/api/v1/land/context-buildings', lat, lon, radiusM, signal)
export const fetchContextGround = (lat: number, lon: number, radiusM: number, signal?: AbortSignal, detail: 'roads' | 'full' = 'full') =>
  fetchContext('/api/v1/land/context-ground', lat, lon, radiusM, signal, detail)

async function fetchContext(path: string, lat: number, lon: number, radiusM: number, signal?: AbortSignal, detail?: string): Promise<ContextReply> {
  const query = new URLSearchParams({ lat: String(lat), lon: String(lon), radius_m: String(radiusM) })
  if (detail) query.set('detail', detail)
  const res = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}${path}?${query}`, { signal })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `${path} failed (${res.status})`)
  return body as ContextReply
}

const PREFIX = 'context-mass-'
// Below the DEM's own fall under a mass: the drawn terrain (33 x 33 samples a tile, ~18 m apart) smears a terrace
// edge under a building (고산: 93 m platform beside a 60 m street, 6-11.5 m gaps at 4 m). Buried parts never show.
const FOOTING_M = 12

/** Keep polygon holes; drop degenerate outer rings which Cesium cannot centre. */
function polygons(geometry: any): number[][][][] {
  const polys = geometry?.type === 'Polygon' ? [geometry.coordinates] : geometry?.type === 'MultiPolygon' ? geometry.coordinates : []
  return polys
    .filter((p: any) => new Set((p?.[0] ?? []).map((c: number[]) => `${c[0]},${c[1]}`)).size >= 3 && areaDeg2(p[0]) > 1e-12)
}

function rings(geometry: any): number[][] {
  return polygons(geometry).map(p => p[0]!.flatMap(c => [c[0]!, c[1]!]))
}

function boundaryLines(geometry: any): number[][][] {
  if (geometry?.type === 'LineString') return [geometry.coordinates]
  if (geometry?.type === 'MultiLineString') return geometry.coordinates
  if (geometry?.type === 'GeometryCollection') return geometry.geometries.flatMap(boundaryLines)
  return []
}

/** Shoelace area in square degrees (1e-12 deg² ≈ 0.01 m²). */
function areaDeg2(ring: number[][]): number {
  const [x0, y0] = ring[0]!   // relative to the first corner: lon x lat products would eat the precision
  let a = 0
  for (let i = 0; i < ring.length - 1; i++) {
    a += (ring[i]![0]! - x0!) * (ring[i + 1]![1]! - y0!) - (ring[i + 1]![0]! - x0!) * (ring[i]![1]! - y0!)
  }
  return Math.abs(a) / 2
}

export type HeightCounts = { measured: number; estimated: number; unknown: number }

/** Where things stand: on a flat ground at this many metres, or on the terrain (DEM). */
export type Ground = number | 'terrain'

/** Adds the reply's buildings; one already drawn (neighbouring cells overlap) is skipped. Returns what was added. */
export function drawContextMasses(entities: any, Cesium: any, reply: ContextReply, base: Ground = 0): { added: number; counts: HeightCounts } {
  const white = Cesium.Color.fromCssColorString('#fbfbf9')
  const pale = Cesium.Color.fromCssColorString('#c7c7c2')
  const edge = Cesium.Color.fromCssColorString('#9a9a96')
  let n = 0
  const counts: HeightCounts = { measured: 0, estimated: 0, unknown: 0 }
  entities.suspendEvents()
  for (const f of reply.features?.features ?? []) {
    const p = f.properties ?? {}
    let drew = false
    rings(f.geometry).forEach((ring, i) => {
      // A building without a source id is named by its outline, so the same one from two cells is drawn once.
      const key = /^site-\d+$/.test(String(p.id)) ? `xy${ring[0]!.toFixed(6)},${ring[1]!.toFixed(6)}` : p.id
      const id = `${PREFIX}${key}-${i}`
      if (entities.getById(id)) return
      entities.add({
        id,
        name: p.use || '건물',
        description: `높이 ${p.height_m} m (${p.height_status}) — ${p.method}`,
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray(ring),
          // On terrain a mass stands on the ground as drawn (relative to ground): DEM tiles arrive late (5-12 s each)
          // and far ones are flat, so an absolute DEM height (SceneAgent base_m) hung masses in the air until then.
          // Its foot goes into the ground as far as the DEM falls from its centre to its lowest corner (SceneAgent:
          // centre = top_m - height_m, lowest = base_m) plus FOOTING_M, so a slope under it never shows a gap; the
          // terrain depth test hides the buried part.
          ...(base === 'terrain'
            ? { height: -(FOOTING_M + Math.max(0, p.top_m != null && p.base_m != null ? p.top_m - p.height_m - p.base_m : 0)),
                extrudedHeight: p.height_m, heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
                extrudedHeightReference: Cesium.HeightReference.RELATIVE_TO_GROUND }
            : { height: base, extrudedHeight: base + p.height_m }),
          material: p.height_status === 'unknown' ? pale : white,
          outline: true,
          outlineColor: edge,
        },
      })
      n++
      drew = true
    })
    if (drew && p.height_status in counts) counts[p.height_status as keyof HeightCounts]++
  }
  entities.resumeEvents()
  return { added: n, counts }
}

const ROAD_HEIGHT_M = 0.3
const BLOCK_HEIGHT_M = 0.8
const BLOCK_COLOURS: Record<string, string> = { paved: '#e2e1dc', water: '#e3edf3', green: '#f1f4ec', forest: '#eef2e8' }
const ROAD_GREY = '#b4b4b0'
const COVER_COLOURS: Record<string, string> = {
  paved: '#e2e1dc', green: '#dfe8d1', forest: '#cfdcc0', farm: '#ece9da', bare: '#efe9de', water: '#d3e2ec', rail: '#d0d0cc',
}

export interface GroundTargets { blocks: any; cover: any }

export function createGroundStages(targets: GroundTargets, Cesium: any, base: () => Ground): GroundStages {
  return new GroundStages((previous, next) => {
    if (previous) polygons(previous.geometry).forEach((_poly, i) => targets.blocks.entities.removeById(`${roadKey(previous)}-${i}`))
    if (next) drawContextGround(targets, Cesium, { status: 'ok', features: { type: 'FeatureCollection', features: [next] } }, base())
  })
}

export async function drawGroundIncrementally(targets: GroundTargets, Cesium: any, reply: ContextReply, base: Ground,
  live: () => boolean, render: () => void,
  stage?: { state: GroundStages; cellKey: string; detail: 'roads' | 'full' }, boundariesOnly = false): Promise<void> {
  if (boundariesOnly) stage = undefined
  // Full ground can succeed while Site reports its road source unavailable.
  // That is not evidence for removing the installed-road preview.
  const roadEvidence = reply.record?.roads as { source?: string; revision?: string } | undefined
  const roadGap = reply.gaps?.some(gap => typeof gap === 'string' && /^(roads|carriageways):/.test(gap))
  const canReplaceRoads = stage?.detail !== 'full' || !roadGap && (!roadEvidence || Boolean(roadEvidence.source || roadEvidence.revision))
  const batch = canReplaceRoads ? stage?.state.begin(stage.cellKey, stage.detail) : undefined
  if (stage && canReplaceRoads && !batch) return
  const current = () => live() && (!batch || batch.current())
  const features = reply.features?.features ?? []
  let deadline = performance.now() + 4
  const yieldWork = async () => {
    render()
    await new Promise(resolve => setTimeout(resolve, 0))
    deadline = performance.now() + 4
  }
  for (let i = 0; i < features.length && current(); i += 32) {
    const chunk = features.slice(i, i + 32)
    const ordinary = stage ? chunk.filter(f => {
      if (f.properties?.layer !== 'carriageway') return true
      // Roads have one owner system. Incomplete road evidence must neither
      // replace the installed preview nor claim it as ordinary cell geometry.
      batch?.apply(f)
      return false
    }) : chunk
    drawContextGround(targets, Cesium, { ...reply, features: { type: 'FeatureCollection', features: ordinary } }, base, boundariesOnly)
    // Budget actual work: a fixed frame delay per 32 features made cached scenes
    // take seconds even when each chunk needed only a fraction of a millisecond.
    if (performance.now() >= deadline) await yieldWork()
  }
  while (current() && batch && !batch.finish(32)) {
    if (performance.now() >= deadline) await yieldWork()
  }
  if (current()) render()
}

/** Adds the reply's parcels (blocks + roads) and land cover; pieces already drawn are skipped. Returns how many were added. */
export function drawContextGround(targets: GroundTargets, Cesium: any, reply: ContextReply, base: Ground = 0, boundariesOnly = false): number {
  // On terrain everything is draped on the ground (ground primitives): blocks are not raised, the relief does that.
  const draped = base === 'terrain'
  // Ground markings must not classify every 3D building as well as terrain.
  const classification = draped ? { classificationType: Cesium.ClassificationType.TERRAIN } : {}
  const z = draped ? 0 : base
  let n = 0
  const edge = new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString('#b8b8b4'), dashLength: 8 })
  for (const t of [targets.blocks, targets.cover]) t.entities.suspendEvents()
  try {
    for (const f of reply.features?.features ?? []) {
      const p = f.properties ?? {}
      const carriageway = p.layer === 'carriageway'
      const cover = p.layer === 'cover'
      if (!boundariesOnly) polygons(f.geometry).forEach((poly, i) => {
        const ring = poly[0]!.flatMap(c => [c[0]!, c[1]!])
        // The backend clips each response to its requested bounds. A shared
        // PNU (or first vertex) does not identify the same clipped geometry.
        // Keep distinct pieces; exact repeats still share GroundLayer owners.
        const id = carriageway ? `${roadKey(f)}-${i}`
          : `${cover ? 'cover' : 'parcel'}-${p.id ?? ''}-${cover ? p.cover : p.ground}-${JSON.stringify(poly)}`
        const into = (cover ? targets.cover : targets.blocks).entities
        if (into.getById(id)) return
        const addRoad = (entity: any) => into.addRoad ? into.addRoad(entity) : into.add(entity)
        const addSurface = (entity: any) => into.addSurface ? into.addSurface(entity) : into.add(entity)
        const positions = Cesium.Cartesian3.fromDegreesArray(ring)
        const hierarchy = new Cesium.PolygonHierarchy(positions, poly.slice(1)
          .filter(hole => hole.length >= 4 && areaDeg2(hole) > 1e-12)
          .map(hole => new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(hole.flatMap(c => [c[0]!, c[1]!])))))
        if (carriageway) {
          addRoad({ id, name: `차도 (${p.width_m ?? '?'} m)`, description: `${p.width_status ?? ''} · ${p.source ?? ''}`,
            polygon: { hierarchy, ...classification, ...(draped ? { zIndex: 2 } : { height: z + BLOCK_HEIGHT_M + 0.06 }),
              material: Cesium.Color.fromCssColorString('#999995') } })
        } else if (cover) {
          const colour = COVER_COLOURS[p.cover]
          if (!colour) return
          addSurface({ id, name: `토지피복 ${p.l3_name ?? p.cover}`, polygon: { hierarchy, ...classification,
            ...(draped ? { zIndex: 1 } : { height: z + BLOCK_HEIGHT_M + 0.03 }), material: Cesium.Color.fromCssColorString(colour) } })
        } else if (p.ground === 'road' || p.ground === 'rail') {
          const add = p.ground === 'road' ? addRoad : (entity: any) => into.add(entity)
          add({ id, name: `도로 (지목 ${p.jimok})`, polygon: { hierarchy, ...classification,
            ...(draped ? { zIndex: 0 } : { height: z + ROAD_HEIGHT_M }), material: Cesium.Color.fromCssColorString(ROAD_GREY) } })
        } else {
          addSurface({ id, name: `필지 (지목 ${p.jimok ?? '?'})`,
            polygon: { hierarchy, ...classification, ...(draped ? { zIndex: 0 } : { height: z + ROAD_HEIGHT_M, extrudedHeight: z + BLOCK_HEIGHT_M }),
              material: Cesium.Color.fromCssColorString(BLOCK_COLOURS[p.ground] ?? '#fbfbfa') } })
        }
        n++
      })
      if (!cover && !carriageway && p.ground !== 'road' && p.ground !== 'rail') {
        // Old cached polygons have no original-edge evidence. Preserve their
        // fill, but never turn request-clipping edges into parcel boundaries.
        for (const line of boundaryLines(p.parcel_boundary)) {
          if (line.length < 2) continue
          const id = `parcel-edge-${p.parcel_boundary_id ?? p.id ?? ''}-${JSON.stringify(line)}`
          const into = targets.blocks.entities
          if (into.getById(id)) continue
          const coordinates = line.flatMap(c => [c[0]!, c[1]!])
          into.add({ id, polyline: draped
            ? { positions: Cesium.Cartesian3.fromDegreesArray(coordinates), ...classification,
                clampToGround: true, width: 1, material: edge }
            : { positions: Cesium.Cartesian3.fromDegreesArrayHeights(line.flatMap(c => [c[0]!, c[1]!, z + BLOCK_HEIGHT_M + 0.02])),
                width: 1, material: edge } })
        }
      }
    }
  } finally {
    for (const t of [targets.blocks, targets.cover]) t.entities.resumeEvents()
  }
  return n
}
