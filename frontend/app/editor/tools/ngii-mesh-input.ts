import type { Footprint } from '../features/world/lib/building-geometry'
import { TERRAIN_HEIGHT_CONTRACT } from '../features/world/lib/terrain-height-contract'

type Polygon = number[][][]
export type CanonicalBuilding = {
  canonicalBuildingId: string
  sourceUFID: string | null
  geomWGS84: { type: 'Polygon'; coordinates: Polygon } | { type: 'MultiPolygon'; coordinates: Polygon[] }
  anchorWGS84: number[]
  h: number
  heightSource: { kind: 'source-metric' | 'source-floors' | 'declared-default'; [key: string]: unknown }
  provenance: { family: string; productCode: string; productKind: string; layer: string; edition: string;
    sourceManifestSHA256: string; productReceiptSHA256: string; [key: string]: unknown }
}
export type TerrainSample = { height: number; sourceLevels: number[]; ellipsoidZero: boolean;
  archiveSha256: string; contract: typeof TERRAIN_HEIGHT_CONTRACT }

const sha = (value: string) => /^[a-f0-9]{64}$/.test(value)
const position = (p: number[]) => p.length === 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])
  && p[0]! >= -180 && p[0]! <= 180 && p[1]! >= -90 && p[1]! <= 90
const validRing = (ring: number[][]) => {
  if (ring.length < 4 || !ring.every(position) || ring[0]![0] !== ring.at(-1)![0] || ring[0]![1] !== ring.at(-1)![1]) return false
  const [ox, oy] = ring[0]!
  // Translate before computing area so small positive footprints survive floating-point cancellation.
  return ring.slice(0, -1).reduce((sum, p, i) => {
    const q = ring[i + 1]!
    return sum + (p[0]! - ox!) * (q[1]! - oy!) - (q[0]! - ox!) * (p[1]! - oy!)
  }, 0) !== 0
}

/** Lossless component bridge to the existing v3 mesh baker; it never reads runtime PMTiles. */
export async function ngiiMeshInput(row: CanonicalBuilding, archiveSha256: string,
  sample: (lon: number, lat: number) => Promise<TerrainSample>) {
  const p = row.provenance
  if (!['B020', 'B021'].includes(p.productCode) || p.family !== `NGII-${p.productCode}`
    || p.productKind !== 'continuous-topographic' || p.layer !== 'N3A_B0010000' || p.crs !== 'EPSG:5179'
    || !p.edition || !sha(p.sourceManifestSHA256) || !sha(p.productReceiptSHA256)
    || !/^ngii:[a-f0-9]{64}$/.test(row.canonicalBuildingId)) throw Error('Invalid NGII continuous source identity')
  if (!sha(archiveSha256)) throw Error('Invalid terrain archive SHA256')
  if (!Number.isFinite(row.h) || row.h <= 0) throw Error('Invalid canonical building height')
  const status = { 'source-metric': 'm', 'source-floors': 'e', 'declared-default': 'u' } as const
  const s = status[row.heightSource.kind]
  if (!s) throw Error('Invalid canonical building height source')
  const polygons = row.geomWGS84.type === 'Polygon' ? [row.geomWGS84.coordinates]
    : row.geomWGS84.type === 'MultiPolygon' ? row.geomWGS84.coordinates : []
  if (!position(row.anchorWGS84) || !polygons.length || polygons.some(rings => !rings.length || !rings.every(validRing))) {
    throw Error('Invalid canonical building geometry')
  }
  const ground = await sample(row.anchorWGS84[0]!, row.anchorWGS84[1]!)
  if (ground.archiveSha256 !== archiveSha256 || ground.contract !== TERRAIN_HEIGHT_CONTRACT) throw Error('Terrain identity changed during bake')
  if (!Number.isFinite(ground.height) || !ground.sourceLevels.length
    || ground.sourceLevels.some(level => !Number.isInteger(level) || level < -1 || level > 20)
    || ground.ellipsoidZero !== ground.sourceLevels.includes(-1)) throw Error('Invalid canonical terrain sample')
  const footprints: Footprint[] = polygons.map((rings, component) => ({
    key: `${row.canonicalBuildingId}/${component}`, pnu: '', h: row.h, s, z: ground.height,
    ring: rings[0]!.map(point => [...point]),
    ...(rings.length > 1 ? { holes: rings.slice(1).map(ring => ring.map(point => [...point])) } : {}),
  }))
  return { canonicalBuildingId: row.canonicalBuildingId, sourceUFID: row.sourceUFID,
    footprints, ground, supportedGround: !ground.ellipsoidZero, heightSource: row.heightSource,
    provenance: row.provenance }
}
