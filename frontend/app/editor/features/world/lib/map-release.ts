import { verifyNationalBuildingCoverage, type NationalBuildingCoverage } from './world-building-renderer'
import type { NationalBuildingSource } from './national-building-source'
type CatalogPointer = { schema: string; revision: string; source: string; index: string }
export type LegacyMapRelease = {
  schema: 'ace-map-release-v1'; releaseId: string
  buildings: { version: string; href: string }
  buildingCatalog: CatalogPointer
  terrain: { url: string; vrt_sha256: string; sha256: string; heightContract?: 'resolved-ancestor-grid-v1' }
  assetBases?: Partial<Record<'buildings' | 'world-buildings' | 'terrain', string>>
}

export type NationalMapRelease = {
  schema: 'ace-map-release-v2'; releaseId: string; sourceFamily: 'NGII-B021'
  terrain: LegacyMapRelease['terrain'] & { heightContract: 'resolved-ancestor-grid-v1' }
  nationalBuildings: NationalBuildingSource; coverage: NationalBuildingCoverage
  runtimeValidationRequired: true
  assetBases?: LegacyMapRelease['assetBases']
}
export type MapRelease = LegacyMapRelease | NationalMapRelease
export function requireLegacyMapRelease(value: MapRelease): LegacyMapRelease {
  if (value.schema !== 'ace-map-release-v1') throw Error('National prebuilt release has no legacy building source')
  return value
}

export function createMapReleaseReader(get: (url: string) => Promise<Response>, url: string) {
  let pending: Promise<MapRelease | undefined> | undefined
  return () => pending ??= (async () => {
    const response = await get(url)
    if (response.status === 404) return undefined
    if (!response.ok) throw new Error(`Map release ${response.status}`)
    const value = await response.json()
    if (!['ace-map-release-v1','ace-map-release-v2'].includes(value?.schema)
      || !/^[a-f0-9]{64}$/.test(value.releaseId ?? '')
      || !/^[a-f0-9]{64}$/.test(value.terrain?.vrt_sha256 ?? '')
      || !/^[a-f0-9]{64}$/.test(value.terrain?.sha256 ?? '')
      || typeof value.terrain?.url !== 'string') throw new Error('Invalid map release')
    if (value.schema === 'ace-map-release-v1') {
      if (!/^[a-f0-9]{64}$/.test(value.buildingCatalog?.revision ?? '')
        || !/^\d{8}-[a-f0-9]{8}$/.test(value.buildings?.version ?? '')
        || typeof value.buildings?.href !== 'string' || typeof value.buildingCatalog?.index !== 'string'
        || value.nationalBuildings !== undefined) throw new Error('Invalid map release')
    } else {
      if (value.terrain.heightContract !== 'resolved-ancestor-grid-v1' || value.buildings !== undefined
        || value.buildingCatalog !== undefined) throw new Error('Invalid national terrain/building contract')
      await verifyNationalBuildingCoverage(value)
    }
    if (value.terrain.heightContract !== undefined && value.terrain.heightContract !== 'resolved-ancestor-grid-v1') throw new Error('Invalid terrain height contract')
    for (const base of Object.values(value.assetBases ?? {})) {
      const parsed = new URL(String(base))
      if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) throw new Error('Invalid release asset base')
    }
    return value as MapRelease
  })().catch(error => { pending = undefined; throw error })
}

const remote = process.env.NEXT_PUBLIC_MAP_RELEASE_URL
const separateOverride = process.env.NEXT_PUBLIC_BUILDINGS_BASE_URL || process.env.NEXT_PUBLIC_WORLD_BUILDINGS_BASE_URL
  || process.env.NEXT_PUBLIC_TERRAIN_BASE_URL || process.env.NEXT_PUBLIC_TERRAIN_ARCHIVE_URL
const read = createMapReleaseReader(url => fetch(url, { cache:'no-store', signal:AbortSignal.timeout(5000) }),
  remote || `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/map-data/releases/current.json`)

// One snapshot per page keeps terrain and buildings consistent across independent
// async loaders. New publications are adopted together on the next page load.
let pinned: MapRelease | undefined
export const pinnedMapRelease = () => pinned
export const defaultMapReleaseReader: () => Promise<MapRelease | undefined> = async () => {
  if (typeof window === 'undefined' || (!remote && separateOverride)) return undefined
  pinned = await read()
  return pinned
}

export function releaseAssetUrl(value: string): string {
  if (/^https?:\/\//.test(value)) return value
  if (!value.startsWith('/api/map-data/')) throw new Error('Invalid release asset URL')
  return `${process.env.NEXT_PUBLIC_BASE_PATH || ''}${value}`
}
