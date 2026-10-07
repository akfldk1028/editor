/**
 * Clean context: the buildings around a point as white masses.
 * SceneAgent answers (SiteContext footprints + its height rule); each building says whether its height is
 * measured, estimated from storeys, or unknown — unknown ones are drawn pale and low, never given a made-up height.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
export interface ContextReply {
  status: 'ok' | 'needs_evidence'
  features?: { type: 'FeatureCollection'; features: any[] }
  counts?: { measured: number; estimated: number; unknown: number }
  reason?: string
  record?: Record<string, unknown>
}

export const fetchContextBuildings = (lat: number, lon: number, radiusM: number, signal?: AbortSignal) =>
  fetchContext('/api/v1/land/context-buildings', lat, lon, radiusM, signal)
export const fetchContextGround = (lat: number, lon: number, radiusM: number, signal?: AbortSignal) =>
  fetchContext('/api/v1/land/context-ground', lat, lon, radiusM, signal)

async function fetchContext(path: string, lat: number, lon: number, radiusM: number, signal?: AbortSignal): Promise<ContextReply> {
  const query = new URLSearchParams({ lat: String(lat), lon: String(lon), radius_m: String(radiusM) })
  const res = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}${path}?${query}`, { signal })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `${path} failed (${res.status})`)
  return body as ContextReply
}

const PREFIX = 'context-mass-'

/** Outer rings of a Polygon / MultiPolygon as flat [lon, lat, lon, lat, …] arrays; rings with fewer than 3 distinct
 *  corners are dropped (Cesium cannot centre them and stops rendering). */
function rings(geometry: any): number[][] {
  const polys = geometry?.type === 'Polygon' ? [geometry.coordinates] : geometry?.type === 'MultiPolygon' ? geometry.coordinates : []
  return polys
    .filter((p: any) => new Set((p?.[0] ?? []).map((c: number[]) => `${c[0]},${c[1]}`)).size >= 3)
    .map((p: any) => p[0].flatMap((c: number[]) => [c[0], c[1]]))
}

export type HeightCounts = { measured: number; estimated: number; unknown: number }

/** Where things stand: on a flat ground at this many metres, or on the terrain (DEM). */
export type Ground = number | 'terrain'

/** Adds the reply's buildings; one already drawn (neighbouring cells overlap) is skipped. Returns what was added. */
export function drawContextMasses(entities: any, Cesium: any, reply: ContextReply, base: Ground = 0, fallback = 0): { added: number; counts: HeightCounts } {
  const white = Cesium.Color.fromCssColorString('#fbfbf9')
  const pale = Cesium.Color.fromCssColorString('#ffffff').withAlpha(0.55)
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
          // On terrain a mass stands on the DEM height under it (SceneAgent base_m), never on a height Cesium samples
          // while drawing; without base_m it stands at the fallback ground level.
          ...(() => { const z = base === 'terrain' ? (p.base_m ?? fallback) : base; return { height: z, extrudedHeight: z + p.height_m } })(),
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

/**
 * Ground in the diagram style site-analysis tools use: road parcels a flat grey channel, every other parcel a white
 * block raised a little with a dashed edge. Water and green parcels keep a faint tint. Carriageways are not drawn here
 * (the grey road parcel already reads as the street); land cover inside lots is a separate layer.
 */
// Everything floats a little above the globe so it never z-fights with it at a distance.
const ROAD_HEIGHT_M = 0.3
const BLOCK_HEIGHT_M = 0.8
const BLOCK_COLOURS: Record<string, string> = { water: '#e3edf3', green: '#f1f4ec', forest: '#eef2e8' }
const ROAD_GREY = '#b4b4b0'
const COVER_COLOURS: Record<string, string> = {
  paved: '#e2e1dc', green: '#dfe8d1', forest: '#cfdcc0', farm: '#ece9da', bare: '#efe9de', water: '#d3e2ec', rail: '#d0d0cc',
}

export interface GroundTargets { blocks: any; cover: any }

/** Adds the reply's parcels (blocks + roads) and land cover; pieces already drawn are skipped. Returns how many were added. */
export function drawContextGround(targets: GroundTargets, Cesium: any, reply: ContextReply, base: Ground = 0): number {
  // On terrain everything is draped on the ground (ground primitives): blocks are not raised, the relief does that.
  const draped = base === 'terrain'
  const z = draped ? 0 : base
  let n = 0
  const edge = new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString('#b8b8b4'), dashLength: 8 })
  for (const t of [targets.blocks, targets.cover]) t.entities.suspendEvents()
  for (const f of reply.features?.features ?? []) {
    const p = f.properties ?? {}
    if (p.layer === 'carriageway') continue
    const cover = p.layer === 'cover'
    rings(f.geometry).forEach((ring, i) => {
      const id = `${cover ? 'cover' : 'parcel'}-${p.id ?? ''}${cover ? `${ring[0]!.toFixed(6)},${ring[1]!.toFixed(6)}` : ''}-${i}`
      const into = (cover ? targets.cover : targets.blocks).entities
      if (into.getById(id)) return
      const positions = Cesium.Cartesian3.fromDegreesArray(ring)
      if (cover) {
        const colour = COVER_COLOURS[p.cover]
        if (!colour) return
        into.add({ id, name: `토지피복 ${p.l3_name ?? p.cover}`, polygon: { hierarchy: positions,
          ...(draped ? { zIndex: 1 } : { height: z + BLOCK_HEIGHT_M + 0.03 }), material: Cesium.Color.fromCssColorString(colour) } })
      } else if (p.ground === 'road' || p.ground === 'rail') {
        into.add({ id, name: `도로 (지목 ${p.jimok})`, polygon: { hierarchy: positions,
          ...(draped ? { zIndex: 0 } : { height: z + ROAD_HEIGHT_M }), material: Cesium.Color.fromCssColorString(ROAD_GREY) } })
      } else {
        into.add({ id, name: `필지 (지목 ${p.jimok ?? '?'})`,
          polygon: { hierarchy: positions, ...(draped ? { zIndex: 0 } : { height: z + ROAD_HEIGHT_M, extrudedHeight: z + BLOCK_HEIGHT_M }),
            material: Cesium.Color.fromCssColorString(BLOCK_COLOURS[p.ground] ?? '#fbfbfa') },
          polyline: draped
            ? { positions, clampToGround: true, width: 1, material: edge }
            : { positions: Cesium.Cartesian3.fromDegreesArrayHeights(
              ring.flatMap((v, k) => (k % 2 ? [v, z + BLOCK_HEIGHT_M + 0.02] : [v]))), width: 1, material: edge } })
      }
      n++
    })
  }
  for (const t of [targets.blocks, targets.cover]) t.entities.resumeEvents()
  return n
}
