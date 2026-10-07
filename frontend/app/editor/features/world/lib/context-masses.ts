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

export async function fetchContextBuildings(lat: number, lon: number, radiusM: number, signal?: AbortSignal): Promise<ContextReply> {
  const query = new URLSearchParams({ lat: String(lat), lon: String(lon), radius_m: String(radiusM) })
  const res = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/context-buildings?${query}`, { signal })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `context buildings failed (${res.status})`)
  return body as ContextReply
}

const PREFIX = 'context-mass-'

/** Outer rings of a Polygon / MultiPolygon as flat [lon, lat, lon, lat, …] arrays. */
function rings(geometry: any): number[][] {
  const polys = geometry?.type === 'Polygon' ? [geometry.coordinates] : geometry?.type === 'MultiPolygon' ? geometry.coordinates : []
  return polys.filter((p: any) => p?.[0]?.length >= 3).map((p: any) => p[0].flatMap((c: number[]) => [c[0], c[1]]))
}

export function clearContextMasses(viewer: any) {
  const entities = viewer.entities.values.slice()
  for (const e of entities) if (String(e.id).startsWith(PREFIX)) viewer.entities.remove(e)
}

export type HeightCounts = { measured: number; estimated: number; unknown: number }

/** Adds the reply's buildings; one already drawn (neighbouring cells overlap) is skipped. Returns what was added. */
export function drawContextMasses(viewer: any, Cesium: any, reply: ContextReply): { added: number; counts: HeightCounts } {
  const white = Cesium.Color.fromCssColorString('#fbfbf9')
  const pale = Cesium.Color.fromCssColorString('#ffffff').withAlpha(0.55)
  const edge = Cesium.Color.fromCssColorString('#9a9a96')
  let n = 0
  const counts: HeightCounts = { measured: 0, estimated: 0, unknown: 0 }
  viewer.entities.suspendEvents()
  for (const f of reply.features?.features ?? []) {
    const p = f.properties ?? {}
    let drew = false
    rings(f.geometry).forEach((ring, i) => {
      // A building without a source id is named by its outline, so the same one from two cells is drawn once.
      const key = /^site-\d+$/.test(String(p.id)) ? `xy${ring[0]!.toFixed(6)},${ring[1]!.toFixed(6)}` : p.id
      const id = `${PREFIX}${key}-${i}`
      if (viewer.entities.getById(id)) return
      viewer.entities.add({
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
  viewer.entities.resumeEvents()
  return { added: n, counts }
}
