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

/** Outer rings of a Polygon / MultiPolygon as flat [lon, lat, lon, lat, …] arrays. */
function rings(geometry: any): number[][] {
  const polys = geometry?.type === 'Polygon' ? [geometry.coordinates] : geometry?.type === 'MultiPolygon' ? geometry.coordinates : []
  return polys.filter((p: any) => p?.[0]?.length >= 3).map((p: any) => p[0].flatMap((c: number[]) => [c[0], c[1]]))
}

export type HeightCounts = { measured: number; estimated: number; unknown: number }

/** Adds the reply's buildings; one already drawn (neighbouring cells overlap) is skipped. Returns what was added. */
export function drawContextMasses(entities: any, Cesium: any, reply: ContextReply): { added: number; counts: HeightCounts } {
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
          height: 0,
          extrudedHeight: p.height_m,
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

/** Diagram colours for the ground: paving light grey, carriageway a step darker, green, water. Plain lots stay the base colour. */
const GROUND_COLOURS: Record<string, string> = {
  road: '#dcdbd6', paved: '#dcdbd6', rail: '#d0d0cc', carriageway: '#c4c3bd',
  green: '#dde7cf', forest: '#d2dfc3', farm: '#ebe8da', water: '#d3e2ec',
}

/** Adds the reply's ground (parcels by 지목 class, then carriageways on top); already drawn pieces are skipped. */
export function drawContextGround(entities: any, Cesium: any, reply: ContextReply): number {
  let n = 0
  entities.suspendEvents()
  for (const f of reply.features?.features ?? []) {
    const p = f.properties ?? {}
    const kind = p.layer === 'carriageway' ? 'carriageway' : p.ground
    const colour = GROUND_COLOURS[kind]
    if (!colour) continue
    rings(f.geometry).forEach((ring, i) => {
      const id = `ground-${kind}-${p.id ?? `${ring[0]!.toFixed(6)},${ring[1]!.toFixed(6)}`}-${i}`
      if (entities.getById(id)) return
      entities.add({ id, name: kind === 'carriageway' ? `차도 ${p.width_m} m` : `지목 ${p.jimok ?? '?'}`,
        polygon: { hierarchy: Cesium.Cartesian3.fromDegreesArray(ring), height: kind === 'carriageway' ? 0.2 : 0.1,
          material: Cesium.Color.fromCssColorString(colour) } })
      n++
    })
  }
  entities.resumeEvents()
  return n
}
