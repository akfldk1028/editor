import { expect, test } from 'bun:test'
import { loadLegacyBuildingRenderer, prepareWorldBuildingRenderer, selectWorldBuildingSource, verifyNationalBuildingCoverage, type RendererLoaders } from './world-building-renderer'

const national = () => ({
  schema: 'ace-map-release-v2', sourceFamily: 'NGII-B021', runtimeValidationRequired: true,
  terrain: { vrt_sha256: 'b'.repeat(64) },
  nationalBuildings: {
    schema: 'world-buildings/national-v1', url: 'national/version/tileset.json',
    sourceSha256: 'a'.repeat(64), terrainVrtSha256: 'b'.repeat(64), catalogRevision: 'c'.repeat(64), coverageSha256: '',
    materialRevision: 'neutral-opaque-v1', hierarchy: 'replace-coarse-ancestors-v1',
    coverage: { expectedRegions: 26248, completeRegions: 26248, missingRegions: 0, partialRegions: 0 },
  }, coverage: { schema: 'ngii-national-coverage-v1', sourcePlanSHA256: 'a'.repeat(64), catalogRevision: 'c'.repeat(64),
    regionCount: 26248, buildings: 20000000, components: 21000000,
    provinces: ['11','26','27','28','29','30','31','36','41','43','44','46','47','48','50','51','52'],
    supportedGroundBuildings: 19000000, unresolvedGroundBuildings: 1000000, unclassifiedProvinceBuildings: 0,
    missingRegions: 0, partialRegions: 0, runtimeValidated: false,
  },
})
const fixture = () => {
  const value = national()
  value.nationalBuildings.coverageSha256 = new Bun.CryptoHasher('sha256').update(JSON.stringify(value.coverage, Object.keys(value.coverage).sort())).digest('hex')
  return value
}
const loaders = (calls: string[]) => ({
  legacy: async () => { calls.push('legacy'); return () => { calls.push('create-legacy'); return {} } },
  national: async () => { calls.push('national'); return () => { calls.push('create-national'); return {} } },
}) as unknown as RendererLoaders

test('legacy renderer is created while preparation is pending and owns its rejection recovery', async () => {
  let reject!: (reason: Error) => void
  const resources = new Promise<never>((_, fail) => { reject = fail })
  let received: unknown, recovered: unknown
  class FakeBuildings {
    constructor(_viewer: unknown, _C: unknown, _changed: unknown, prepared: Promise<unknown>) {
      received = prepared
      void prepared.catch(error => { recovered = error })
    }
  }
  const load = async () => ({ BuildingTiles: FakeBuildings, prepareBuildingTiles: () => resources })
  const create = await loadLegacyBuildingRenderer(load as unknown as Parameters<typeof loadLegacyBuildingRenderer>[0])
  // No resolution of resources has occurred: construction must already be available.
  create({ viewer: {}, C: {}, changed: () => {} })
  expect(received).toBe(resources)
  const failure = new Error('transient archive failure'); reject(failure)
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(recovered).toBe(failure)
})

test('legacy preparation may reject before creation without losing its recoverable failure', async () => {
  const failure = new Error('early archive failure')
  const resources = Promise.reject(failure)
  let recovered: unknown
  class FakeBuildings {
    constructor(_viewer: unknown, _C: unknown, _changed: unknown, prepared: Promise<unknown>) {
      void prepared.catch(error => { recovered = error })
    }
  }
  const load = async () => ({ BuildingTiles: FakeBuildings, prepareBuildingTiles: () => resources })
  const create = await loadLegacyBuildingRenderer(load as unknown as Parameters<typeof loadLegacyBuildingRenderer>[0])
  await new Promise(resolve => setTimeout(resolve, 0))
  create({ viewer: {}, C: {}, changed: () => {} })
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(recovered).toBe(failure)
})

test('v1 and absent publication preserve the existing renderer', async () => {
  for (const release of [undefined, { schema: 'ace-map-release-v1' }]) {
    const calls: string[] = []
    const prepared = await prepareWorldBuildingRenderer(async () => release, loaders(calls))
    expect(prepared.kind).toBe('legacy-hybrid')
    expect(calls).toEqual(['legacy'])
  }
})

test('complete v2 loads only national code and creates exactly one renderer', async () => {
  const calls: string[] = []
  const prepared = await prepareWorldBuildingRenderer(async () => fixture(), loaders(calls))
  expect(prepared.kind).toBe('national-prebuilt')
  prepared.create({ viewer: {}, C: {}, changed: () => {} })
  expect(calls).toEqual(['national', 'create-national'])
  expect(() => prepared.create({ viewer: {}, C: {}, changed: () => {} })).toThrow('already created')
})

test('partial, sample, mismatched and unknown publications fail before loading either renderer', async () => {
  const changes = [
    (r: ReturnType<typeof national>) => { r.coverage.schema = 'sample' },
    (r: ReturnType<typeof national>) => { r.coverage.supportedGroundBuildings-- },
    (r: ReturnType<typeof national>) => { r.coverage.provinces.pop() },
    (r: ReturnType<typeof national>) => { r.coverage.provinces[0] = '26' },
    (r: ReturnType<typeof national>) => { r.coverage.buildings = 0 },
    (r: ReturnType<typeof national>) => { r.coverage.unclassifiedProvinceBuildings = -1 },
    (r: ReturnType<typeof national>) => { r.coverage.unclassifiedProvinceBuildings = r.coverage.buildings + 1 },
    (r: ReturnType<typeof national>) => { r.coverage.components = 1 },
    (r: ReturnType<typeof national>) => { r.coverage.sourcePlanSHA256 = 'e'.repeat(64) },
    (r: ReturnType<typeof national>) => { r.coverage.catalogRevision = 'e'.repeat(64) },
    (r: ReturnType<typeof national>) => { r.coverage.regionCount = 1 },
    (r: ReturnType<typeof national>) => { r.coverage.partialRegions = 1 },
    (r: ReturnType<typeof national>) => { r.nationalBuildings.coverage.partialRegions = 113 },
    (r: ReturnType<typeof national>) => { r.nationalBuildings.coverageSha256 = 'e'.repeat(64) },
    (r: ReturnType<typeof national>) => { r.terrain.vrt_sha256 = 'e'.repeat(64) },
    (r: ReturnType<typeof national>) => { r.schema = 'ace-map-release-v99' },
    (r: ReturnType<typeof national>) => { r.sourceFamily = 'legacy-gis' },
  ]
  for (const change of changes) {
    const release = fixture(); change(release); const calls: string[] = []
    await expect(prepareWorldBuildingRenderer(async () => release, loaders(calls))).rejects.toThrow()
    expect(calls).toEqual([])
  }
})

test('v1 cannot smuggle a second renderer through a candidate descriptor', () => {
  expect(() => selectWorldBuildingSource({ ...fixture(), schema: 'ace-map-release-v1' })).toThrow('v1 cannot')
})

test('national loading failure propagates without legacy fallback', async () => {
  const calls: string[] = []; const injected = loaders(calls)
  injected.national = async () => { throw new Error('unavailable') }
  await expect(prepareWorldBuildingRenderer(async () => fixture(), injected)).rejects.toThrow('unavailable')
  expect(calls).toEqual([])
})

test('selection captures descriptor values rather than mutable caller data', () => {
  const release = fixture(); const selected = selectWorldBuildingSource(release)
  release.nationalBuildings.url = 'changed/tileset.json'
  expect(selected.kind === 'national-prebuilt' && selected.source.url).toBe('national/version/tileset.json')
})

test('publisher Python canonical coverage digest agrees with browser verification', async () => {
  const release = national()
  // hashlib.sha256(release_store.encoded(coverage)), independently generated by Python.
  release.nationalBuildings.coverageSha256 = '61047b587927d03ad99ddbb73843e542461929dfc94f2a3ec58247cfd8b3b1c1'
  expect((await verifyNationalBuildingCoverage(release)).kind).toBe('national-prebuilt')
  release.coverage.supportedGroundBuildings--; release.coverage.unresolvedGroundBuildings++
  await expect(verifyNationalBuildingCoverage(release)).rejects.toThrow('SHA256 mismatch')
})


test('missing province attributes remain explicit without removing buildings or weakening province presence', async () => {
  const value = fixture()
  value.coverage.unclassifiedProvinceBuildings = 2100
  value.nationalBuildings.coverageSha256 = new Bun.CryptoHasher('sha256').update(JSON.stringify(value.coverage, Object.keys(value.coverage).sort())).digest('hex')
  const selected = await verifyNationalBuildingCoverage(value)
  expect(selected.kind === 'national-prebuilt' && selected.coverage.unclassifiedProvinceBuildings).toBe(2100)
  expect(selected.kind === 'national-prebuilt' && selected.coverage.buildings).toBe(value.coverage.buildings)
  const missing = fixture() as any; delete missing.coverage.unclassifiedProvinceBuildings
  expect(() => selectWorldBuildingSource(missing)).toThrow('coverage')
})
