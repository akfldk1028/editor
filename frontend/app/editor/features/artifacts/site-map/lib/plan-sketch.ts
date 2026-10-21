import type { RunLayout } from '@/lib/orchestrator-runs/types'

/** The colours of a small plan sketch: the footprint dark, the parking lighter, the parcel as an outline. */
const FILL: Record<string, string> = {
  building_footprint: '#4a4a46',
  building_ground_footprint: '#6b6b66',
  parking_stall: '#b9c7d6',
  parking_aisle: '#dfe6ee',
  vehicular_access: '#e8d9b5',
}
const STROKE: Record<string, string> = { site_boundary: '#8a8a85', buildable_boundary: '#c9a227', road_frontage: '#d14343' }

type Ring = number[][]

function rings(geometry: { type: string; coordinates: unknown }): Ring[] {
  if (geometry.type === 'Polygon') return (geometry.coordinates as Ring[]).slice(0, 1)
  if (geometry.type === 'MultiPolygon') return (geometry.coordinates as Ring[][]).map((polygon) => polygon[0]!)
  if (geometry.type === 'LineString') return [geometry.coordinates as Ring]
  if (geometry.type === 'MultiLineString') return geometry.coordinates as Ring[]
  return []
}

/**
 * A plan sketch of a layout as SVG (120×100), drawn from its WGS84 rings: when MasterPlan sends no drawing of a
 * candidate, the portfolio still shows what it is. Pure; null when there is nothing to draw.
 */
export function planSketch(layout: RunLayout | null | undefined, width = 120, height = 100): string | null {
  if (!layout?.features.length) return null
  const shapes = layout.features.map((f) => ({ layer: f.properties.layer, rings: rings(f.geometry) })).filter((s) => s.rings.length)
  const points = shapes.flatMap((s) => s.rings.flat())
  if (!points.length) return null
  const lons = points.map((p) => p[0]!)
  const lats = points.map((p) => p[1]!)
  const minLon = Math.min(...lons)
  const maxLon = Math.max(...lons)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  // metres per degree: longitude shrinks with latitude, so the sketch keeps the parcel's true proportions
  const kx = Math.cos(((minLat + maxLat) / 2) * (Math.PI / 180))
  const spanX = Math.max((maxLon - minLon) * kx, 1e-9)
  const spanY = Math.max(maxLat - minLat, 1e-9)
  const pad = 6
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY)
  const x = (lon: number) => pad + (lon - minLon) * kx * scale + ((width - 2 * pad) - spanX * scale) / 2
  const y = (lat: number) => height - pad - (lat - minLat) * scale - ((height - 2 * pad) - spanY * scale) / 2
  const path = (ring: Ring) => ring.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]!).toFixed(1)} ${y(p[1]!).toFixed(1)}`).join('')
  const order = ['site_boundary', 'buildable_boundary', 'parking_aisle', 'parking_stall', 'vehicular_access', 'road_frontage', 'building_ground_footprint', 'building_footprint']
  const body = shapes
    .sort((a, b) => order.indexOf(a.layer) - order.indexOf(b.layer))
    .flatMap((s) => s.rings.map((ring) => {
      const d = path(ring)
      if (s.layer in FILL) return `<path d="${d}Z" fill="${FILL[s.layer]}" stroke="#fff" stroke-width="0.5"/>`
      return `<path d="${d}" fill="none" stroke="${STROKE[s.layer] ?? '#999'}" stroke-width="${s.layer === 'road_frontage' ? 2 : 1}" stroke-dasharray="${s.layer === 'buildable_boundary' ? '3 2' : ''}"/>`
    }))
    .join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}"><rect width="${width}" height="${height}" fill="#fff"/>${body}</svg>`
}
