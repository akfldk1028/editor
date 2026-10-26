import { expect, test } from 'bun:test'
import { ngiiMeshInput, type CanonicalBuilding } from './ngii-mesh-input'
import { TERRAIN_HEIGHT_CONTRACT } from '../features/world/lib/terrain-height-contract'

const ring = [[127, 37], [127.001, 37], [127.001, 37.001], [127, 37]]
const hole = [[127.0001, 37.0001], [127.0002, 37.0001], [127.0001, 37.0002], [127.0001, 37.0001]]
const archive = 'a'.repeat(64)
const row: CanonicalBuilding = {
  canonicalBuildingId: `ngii:${'b'.repeat(64)}`, sourceUFID: 'B001-example',
  geomWGS84: { type: 'MultiPolygon', coordinates: [[ring, hole], [ring.map(([x, y]) => [x! + .01, y!])]] },
  anchorWGS84: [127.0003, 37.0002], h: 17, heightSource: { kind: 'source-floors' },
  provenance: { family: 'NGII-B021', productCode: 'B021', productKind: 'continuous-topographic',
    layer: 'N3A_B0010000', crs: 'EPSG:5179', edition: '2024', sourceManifestSHA256: 'c'.repeat(64), productReceiptSHA256: 'd'.repeat(64) },
}
const sample = async () => ({ height: 68.123456789, sourceLevels: [15], ellipsoidZero: false,
  archiveSha256: archive, contract: TERRAIN_HEIGHT_CONTRACT })

test('one source building keeps all parts and holes with one pinned ground decision', async () => {
  const before = JSON.stringify(row), seen: number[][] = []
  const result = await ngiiMeshInput(row, archive, async (lon, lat) => { seen.push([lon, lat]); return sample() })
  expect(seen).toEqual([row.anchorWGS84])
  expect(result.footprints).toHaveLength(2)
  expect(new Set(result.footprints.map(f => f.key)).size).toBe(2)
  expect(result.footprints[0]!.holes).toEqual([hole])
  expect(result.footprints.every(f => f.z === 68.123456789 && f.h === 17 && f.s === 'e')).toBe(true)
  expect(result.canonicalBuildingId).toBe(row.canonicalBuildingId)
  expect(result.supportedGround).toBe(true)
  expect(JSON.stringify(row)).toBe(before)
})

test('confirmed all-ancestor NoData is retained for display and never counted as filled ground', async () => {
  const result = await ngiiMeshInput(row, archive, async () => ({ ...await sample(), height: 0, sourceLevels: [-1], ellipsoidZero: true }))
  expect(result.footprints).toHaveLength(2)
  expect(result.footprints[0]!.z).toBe(0)
  expect(result.supportedGround).toBe(false)
})

test('archive mismatch and read failures cannot publish substituted ground', async () => {
  await expect(ngiiMeshInput(row, archive, async () => ({ ...await sample(), archiveSha256: 'e'.repeat(64) }))).rejects.toThrow('Terrain identity')
  await expect(ngiiMeshInput(row, archive, async () => { throw Error('range unavailable') })).rejects.toThrow('range unavailable')
})

test('invalid geometry or a mixed source fails before terrain reads', async () => {
  let reads = 0
  const reader = async () => { reads++; return sample() }
  await expect(ngiiMeshInput({ ...row, provenance: { ...row.provenance, productKind: 'individual-sheet' } }, archive, reader)).rejects.toThrow('continuous')
  await expect(ngiiMeshInput({ ...row, geomWGS84: { type: 'Polygon', coordinates: [[[NaN, 37], ...ring]] } }, archive, reader)).rejects.toThrow('geometry')
  await expect(ngiiMeshInput({ ...row, h: 0 }, archive, reader)).rejects.toThrow('height')
  expect(reads).toBe(0)
})

test('positive tiny footprints and declared default heights remain in the candidate', async () => {
  const tiny = [[127,37],[127.00000001,37],[127.00000001,37.00000001],[127,37]]
  const result = await ngiiMeshInput({ ...row, geomWGS84: { type: 'Polygon', coordinates: [tiny] },
    h: 3.4, heightSource: { kind: 'declared-default' } }, archive, sample)
  expect(result.footprints).toHaveLength(1)
  expect(result.footprints[0]!.ring).toEqual(tiny)
  expect(result.footprints[0]!.s).toBe('u')
  expect(result.footprints[0]!.h).toBe(3.4)
})
