import type { BuildingTiles } from './building-tiles'
import type { HeightCounts } from './context-masses'
import { validateNationalBuildingSource, type NationalBuildingSource } from './national-building-source'

export type WorldBuildingRenderer = Pick<BuildingTiles,
  'load' | 'setGround' | 'setSite' | 'setShow' | 'supplementNear' | 'heightAt' | 'dispose' | 'backgroundReady' | 'firstRenderedAt'>
export type NationalBuildingCoverage = {
  schema: 'ngii-national-coverage-v1'
  sourcePlanSHA256: string
  catalogRevision: string
  regionCount: number
  buildings: number
  components: number
  provinces: string[]
  supportedGroundBuildings: number
  unresolvedGroundBuildings: number
  unclassifiedProvinceBuildings: number
  missingRegions: 0
  partialRegions: 0
  runtimeValidated: boolean
}
type Selection = { kind: 'legacy-hybrid' } | { kind: 'national-prebuilt'; source: NationalBuildingSource; coverage: NationalBuildingCoverage }
const provinces = ['11','26','27','28','29','30','31','36','41','43','44','46','47','48','50','51','52']

/** Full national coverage is established by the sealed publisher's completed source and exact region audit. */
export function selectWorldBuildingSource(value: unknown): Selection {
  if (value === undefined) return { kind: 'legacy-hybrid' }
  const release = value as { schema?: string; sourceFamily?: string; nationalBuildings?: NationalBuildingSource;
    terrain?: { vrt_sha256?: string }; coverage?: NationalBuildingCoverage; runtimeValidationRequired?: boolean } | null
  if (release?.schema === 'ace-map-release-v1') {
    if (release.nationalBuildings !== undefined) throw new Error('v1 cannot select a national renderer')
    return { kind: 'legacy-hybrid' }
  }
  if (release?.schema !== 'ace-map-release-v2' || release.sourceFamily !== 'NGII-B021') {
    throw new Error('Invalid building renderer release')
  }
  const proof = release.coverage
  const source = validateNationalBuildingSource(release.nationalBuildings,
    release.terrain?.vrt_sha256 ?? '', proof?.catalogRevision ?? '')
  const count = (n: unknown) => typeof n === 'number' && Number.isSafeInteger(n) && n >= 0
  if (!source || !proof || proof.schema !== 'ngii-national-coverage-v1'
    || proof.sourcePlanSHA256 !== source.sourceSha256 || proof.catalogRevision !== source.catalogRevision
    || !count(proof.regionCount) || proof.regionCount !== source.coverage.expectedRegions
    || !count(proof.buildings) || proof.buildings === 0 || !count(proof.components) || proof.components < proof.buildings
    || !count(proof.supportedGroundBuildings) || !count(proof.unresolvedGroundBuildings)
    || proof.supportedGroundBuildings + proof.unresolvedGroundBuildings !== proof.buildings
    || !count(proof.unclassifiedProvinceBuildings) || proof.unclassifiedProvinceBuildings > proof.buildings
    || proof.missingRegions !== 0 || proof.partialRegions !== 0
    || typeof proof.runtimeValidated !== 'boolean' || release.runtimeValidationRequired !== true
    || !Array.isArray(proof.provinces) || proof.provinces.length !== provinces.length
    || [...proof.provinces].sort().some((code, i) => code !== provinces[i])) {
    throw new Error('National building coverage proof is missing or inconsistent')
  }
  return structuredClone({ kind: 'national-prebuilt', source, coverage: proof })
}

/** Matches Python release_store.encoded for the publisher's flat coverage schema. */
export async function verifyNationalBuildingCoverage(value: unknown): Promise<Selection> {
  const selected = selectWorldBuildingSource(value)
  if (selected.kind === 'national-prebuilt') {
    const canonical = JSON.stringify(selected.coverage, Object.keys(selected.coverage).sort())
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical))
    const sha = Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('')
    if (sha !== selected.source.coverageSha256) throw new Error('National building coverage SHA256 mismatch')
  }
  return selected
}

type CreateOptions = {
  viewer: ConstructorParameters<typeof BuildingTiles>[0]
  C: ConstructorParameters<typeof BuildingTiles>[1]
  changed: (counts: HeightCounts, pending: number, error: string) => void
  firstFrame?: () => void
}
type CreateRenderer = (options: CreateOptions) => WorldBuildingRenderer
export type RendererLoaders = {
  legacy: () => Promise<CreateRenderer>
  national: (source: NationalBuildingSource) => Promise<CreateRenderer>
}
export async function loadLegacyBuildingRenderer(loadModule = () => import('./building-tiles')): Promise<CreateRenderer> {
  const { BuildingTiles, prepareBuildingTiles } = await loadModule()
  const resources = prepareBuildingTiles()
  // Observe early rejection until construction; preserve the original promise for BuildingTiles.open's retry path.
  void resources.catch(() => {})
  return ({ viewer, C, changed, firstFrame }) => new BuildingTiles(viewer, C, changed, resources, firstFrame)
}
const loaders: RendererLoaders = {
  legacy: loadLegacyBuildingRenderer,
  national: async source => {
    const { NationalBuildings } = await import('./national-buildings')
    return ({ viewer, C, changed, firstFrame }) => new NationalBuildings(viewer, C, source, changed, firstFrame)
  },
}

export async function prepareWorldBuildingRenderer(readRelease: () => Promise<unknown>, modules: RendererLoaders = loaders) {
  const selection = await verifyNationalBuildingCoverage(await readRelease())
  // Resolve the release before importing either renderer: a national page must never warm the vector decoder.
  const create = await (selection.kind === 'legacy-hybrid' ? modules.legacy() : modules.national(selection.source))
  let created = false
  return {
    kind: selection.kind,
    create(options: CreateOptions): WorldBuildingRenderer {
      if (created) throw new Error('Building renderer already created')
      created = true
      return create(options)
    },
  }
}
